# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared ffmpeg invocation layer for the media converters/compressors.

Why this module exists
----------------------
The video/audio converters and the video compressor all shell out to
ffmpeg. Before this module each call site built its own ``.run()`` with
three structural problems:

- **No timeout.** The LibreOffice (document.py) and ghostscript
  (_ghostscript.py) subprocesses are bounded; ffmpeg was not, so a
  crafted or merely very long media file could pin a worker thread
  forever.
- **One hardcoded codec pair for every container.** The WebM muxer only
  accepts VP8/VP9/AV1 + Vorbis/Opus, and ffmpeg has no muxers named
  ``mkv``/``wmv`` (the real names are ``matroska``/``asf``) — so a
  third of the registered video pairs failed at runtime with H.264/AAC
  forced everywhere.
- **pydub for audio.** It decoded the entire file to PCM in RAM (a
  100 MB MP3 is >1 GB decoded) and passed the bare target extension to
  ``-f``, which has no muxer for ``m4a``/``aac``/``wma``.

This module owns the container→codec matrix, the extension→muxer
mapping, the quality→CRF/qscale/bitrate translation, and a single
:func:`run_ffmpeg` that compiles an ffmpeg-python stream and executes
it via subprocess with a hard timeout (mirroring _ghostscript.py).
Uploads are opened through :func:`media_input`, never ``ffmpeg.input()``
directly. The output arguments copy no metadata from the source
(``_NO_SOURCE_METADATA``) except an audio file's music tags
(:func:`music_tags`). It also builds the two video → GIF passes and the
ffprobe checks around them (bottom of the file).
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import ffmpeg  # ffmpeg-python

from app.converters.base import InvalidInputError
from app.core.config import settings


class FFmpegError(RuntimeError):
    """Raised when an ffmpeg invocation fails, times out, or is unavailable."""


class FFmpegTimeoutError(FFmpegError):
    """Raised when an ffmpeg or ffprobe invocation runs past its timeout."""


# ffmpeg muxer names that differ from the user-facing file extension.
_MUXER_FOR_EXT = {"mkv": "matroska", "wmv": "asf"}

# The ffmpeg demuxers for the audio and video formats FileMorph accepts:
# mp3, wav, flac, ogg (also Opus), aac (ADTS), asf (WMA, WMV), mov (MP4,
# MOV, M4A), avi, matroska (MKV, WebM), flv and live_flv (FLV saved from a
# live stream). ffmpeg picks the demuxer from the file's content and
# refuses the upload if that demuxer is not listed. One list for audio and
# video, so a file whose container differs from its extension still
# converts if the container is listed.
INPUT_DEMUXERS = "mp3,wav,flac,ogg,aac,asf,mov,avi,matroska,flv,live_flv"

_NOT_A_SUPPORTED_MEDIA_FORMAT = (
    "Could not read this file: it is not in one of the audio or video formats "
    "FileMorph supports. Save it as MP4 (video) or MP3 (audio) and try again."
)


def _local_input(path: Path, demuxers: str, **options):
    """``ffmpeg.input`` for a local file, read only with ``demuxers``."""
    return ffmpeg.input(str(path), format_whitelist=demuxers, protocol_whitelist="file", **options)


def media_input(path: Path, **options):
    """``ffmpeg.input`` for an upload: only ``INPUT_DEMUXERS``, only local files.

    ``options`` are further input options, e.g. ``t=31`` to read at most 31 s.
    """
    return _local_input(path, INPUT_DEMUXERS, **options)


# Container → (video codec, audio codec). WebM *requires* VP8/VP9/AV1 +
# Vorbis/Opus; AVI gets the classic MPEG-4 Part 2 + MP3 combo because the
# point of requesting .avi output is legacy-player compatibility; WMV
# means ASF with Windows-Media codecs. Everything else is H.264 + AAC.
VIDEO_CODECS: dict[str, tuple[str, str]] = {
    "mp4": ("libx264", "aac"),
    "mov": ("libx264", "aac"),
    "mkv": ("libx264", "aac"),
    "flv": ("libx264", "aac"),
    "webm": ("libvpx-vp9", "libopus"),
    "avi": ("mpeg4", "libmp3lame"),
    "wmv": ("wmv2", "wmav2"),
}

# Audio extension → (muxer, codec). The muxer column is the reason this
# table exists: ffmpeg has no output formats named m4a/aac/wma — the
# correct muxers are ipod/adts/asf, and feeding the bare extension to
# ``-f`` is a hard runtime error.
AUDIO_TARGETS: dict[str, tuple[str, str]] = {
    "mp3": ("mp3", "libmp3lame"),
    "wav": ("wav", "pcm_s16le"),
    "flac": ("flac", "flac"),
    "ogg": ("ogg", "libvorbis"),
    "m4a": ("ipod", "aac"),
    "aac": ("adts", "aac"),
    "wma": ("asf", "wmav2"),
    "opus": ("opus", "libopus"),
}


def _scale(quality: int, at_q1: float, at_q100: float) -> int:
    """Map quality 1-100 linearly onto an encoder parameter range."""
    quality = max(1, min(100, quality))
    return round(at_q1 + (quality - 1) * (at_q100 - at_q1) / 99)


# NEU-C.2 for media, as for images (app/converters/_metadata.py): ffmpeg
# copies the source's global and per-stream tags and its chapters into the
# output by default — on a phone clip that is where it was filmed, the
# device and the capture time. A negative input index maps none of it; the
# muxer still writes its own technical tags (encoder, handler, language
# "und"). Rotation is display-matrix side data, not metadata, and
# autorotate turns the frames upright before encoding either way.
_NO_SOURCE_METADATA = {"map_metadata": -1, "map_chapters": -1}


def video_output_args(container: str, quality: int, *, audio_bitrate: str) -> dict:
    """Build ffmpeg output kwargs for a video container at a quality level.

    quality 1 (smallest) – 100 (best) maps onto each encoder's native
    rate control: CRF 40→18 for libx264, CRF 45→18 for VP9 (its scale
    runs 0-63), qscale 31→2 for the legacy qscale-driven codecs. No tags
    or chapters are copied from the source (``_NO_SOURCE_METADATA``).
    """
    try:
        vcodec, acodec = VIDEO_CODECS[container]
    except KeyError:
        raise ValueError(f"unsupported video container: {container!r}") from None

    args: dict = {
        "format": _MUXER_FOR_EXT.get(container, container),
        "vcodec": vcodec,
        "acodec": acodec,
        "audio_bitrate": audio_bitrate,
        # yuv420p is the only pixel format every mainstream player
        # decodes; without it x264 happily emits yuv444 for RGB sources.
        "pix_fmt": "yuv420p",
        # yuv420p requires even dimensions — round odd sources down one
        # pixel instead of failing (e.g. an 855×479 screen recording).
        "vf": "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        **_NO_SOURCE_METADATA,
    }
    if vcodec == "libx264":
        args["crf"] = _scale(quality, 40, 18)
    elif vcodec == "libvpx-vp9":
        # VP9 constant-quality mode needs an explicit bitrate of 0 — CRF
        # alone means "constrained quality" and ignores most of the range.
        args["crf"] = _scale(quality, 45, 18)
        args["video_bitrate"] = 0
        # libvpx defaults (cpu-used 0, single-threaded rows) are far too
        # slow for a request/response service; cpu-used 3 + row-mt is the
        # standard VOD speed/quality compromise.
        args["cpu-used"] = 3
        args["row-mt"] = 1
    else:  # qscale-driven legacy encoders (mpeg4, wmv2)
        args["q:v"] = _scale(quality, 31, 2)
    return args


def audio_output_args(target_ext: str, quality: int, *, tags: dict[str, str] | None = None) -> dict:
    """Build ffmpeg output kwargs for an audio target format.

    Lossy targets honour quality 1-100 via each codec's preferred rate
    control (LAME/Vorbis VBR scales, bitrate for AAC/Opus); lossless
    targets (wav/flac) ignore it. ``-vn`` drops embedded cover-art
    streams — raw-stream muxers like ADTS cannot carry them. Of the
    source's metadata the output carries only ``tags``, the music tags
    :func:`music_tags` read (NEU-C.2).
    """
    try:
        muxer, codec = AUDIO_TARGETS[target_ext]
    except KeyError:
        raise ValueError(f"unsupported audio target: {target_ext!r}") from None

    args: dict = {"format": muxer, "acodec": codec, "vn": None, **_NO_SOURCE_METADATA}
    # ffmpeg-python 0.2.0 cannot repeat an option, so each tag gets its own
    # "-metadata:g:<key>": ffmpeg reads a specifier starting with "g" as the
    # file's global metadata and ignores the rest.
    args.update({f"metadata:g:{key}": f"{key}={value}" for key, value in (tags or {}).items()})
    if codec == "libmp3lame":
        args["q:a"] = _scale(quality, 9, 0)  # LAME VBR: 9 ≈ 65 kbps … 0 ≈ 245 kbps
    elif codec == "libvorbis":
        args["q:a"] = _scale(quality, 0, 10)  # Vorbis quality scale (sane floor at 0)
    elif codec == "aac":
        args["audio_bitrate"] = f"{_scale(quality, 64, 256)}k"
    elif codec == "libopus":
        args["audio_bitrate"] = f"{_scale(quality, 32, 192)}k"
    elif codec == "wmav2":
        # wmav2 only accepts a narrow bitrate table; 128k is the safe,
        # universally decodable point — quality does not scale it.
        args["audio_bitrate"] = "128k"
    return args


# The music tags an audio output keeps: title, artist and album artist,
# album, track number and genre, plus the year — from the first of
# _YEAR_TAGS that starts with one (WMA keeps it as "WM/Year", APE and some
# Vorbis taggers as "YEAR"). Only the year: a recorder may store the
# recording time in the date. Everything else the source carries — the
# recording time, the device, comments, chapters — is dropped, as for video.
_MUSIC_TAGS = ("title", "artist", "album_artist", "album", "track", "genre")
_YEAR_TAGS = ("date", "year", "wm/year")
# What a crafted upload's tags may cost: how much of the dump is read into
# memory, the length of each value kept from it (Linux refuses an argument
# over 128 KiB), and the time for the dump, which needs only the headers.
_MAX_TAGS_READ = 1_000_000
_MAX_TAG_LENGTH = 1_000
_TAGS_TIMEOUT_SECONDS = 60


def music_tags(path: Path, dump: Path) -> dict[str, str]:
    """The music tags and the year of an upload, for :func:`audio_output_args`.

    ffmpeg writes the upload's global tags and those of its first audio
    stream (where Ogg keeps them) to ``dump`` as ffmetadata — opened with
    :func:`media_input` and run by :func:`run_ffmpeg`, like a conversion.
    A file rather than ffprobe's output, so at most ``_MAX_TAGS_READ`` of it
    is read. No chapters (``map_chapters=-1``): :func:`_read_ffmetadata`
    reads one section, and a chapter's ``title=`` would replace the song's.
    """
    try:
        run_ffmpeg(
            media_input(path).output(
                str(dump),
                format="ffmetadata",
                map_chapters=-1,
                map_metadata="0",
                **{"map_metadata:g": "0:s:a:0"},
            ),
            timeout=min(_TAGS_TIMEOUT_SECONDS, settings.media_subprocess_timeout_seconds),
        )
        with dump.open(encoding="utf-8", errors="replace", newline="") as f:
            text = f.read(_MAX_TAGS_READ)
    finally:
        dump.unlink(missing_ok=True)
    found = {key.lower(): value for key, value in _read_ffmetadata(text).items()}
    tags = {key: found[key] for key in _MUSIC_TAGS if found.get(key)}
    for key in _YEAR_TAGS:
        year = re.match(r"[0-9]{4}", found.get(key, ""))
        if year:
            tags["date"] = year.group()
            break
    return tags


def _read_ffmetadata(text: str) -> dict[str, str]:
    """The ``key=value`` lines of an ffmetadata dump, which puts a backslash
    before ``=``, ``;``, ``#``, a backslash and a line break. A value is cut
    at ``_MAX_TAG_LENGTH`` characters while it is read."""
    tags: dict[str, str] = {}
    key, field, escaped = None, [], False
    for char in text:
        if escaped:
            escaped = False
            if len(field) < _MAX_TAG_LENGTH:
                field.append(char)
        elif char == "\\":
            escaped = True
        elif char == "=" and key is None:
            key, field = "".join(field), []
        elif char == "\n":
            if key is not None:
                tags[key] = "".join(field)
            key, field = None, []
        elif len(field) < _MAX_TAG_LENGTH:
            field.append(char)
    return tags


def run_ffmpeg(stream, *, timeout: float | None = None) -> None:
    """Compile an ffmpeg-python stream and run it with a hard timeout.

    Raises :class:`FFmpegError` on every failure mode (binary missing,
    non-zero exit, timeout — then :class:`FFmpegTimeoutError`). ffmpeg's
    stderr echoes the upload's metadata, so its tail lands in the exception
    message only with APP_DEBUG; the routes catch broadly and return a
    generic message to the client (A-3).
    """
    if shutil.which("ffmpeg") is None:
        raise FFmpegError("ffmpeg binary not found on PATH")
    if timeout is None:
        timeout = settings.media_subprocess_timeout_seconds

    cmd = ffmpeg.compile(stream, overwrite_output=True)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise FFmpegTimeoutError(f"ffmpeg timed out after {timeout:.0f}s") from exc
    _raise_on_failure("ffmpeg", result)


def _raise_on_failure(tool: str, result: subprocess.CompletedProcess) -> None:
    """Translate a non-zero exit of ffmpeg or ffprobe into an exception."""
    if result.returncode != 0:
        tail = result.stderr.decode("utf-8", errors="replace")[-500:].strip()
        if "not on whitelist" in tail:  # a container media_input doesn't accept
            raise InvalidInputError(_NOT_A_SUPPORTED_MEDIA_FORMAT)
        detail = f": {tail or '<no stderr>'}" if settings.app_debug else ""
        raise FFmpegError(f"{tool} exit {result.returncode}{detail}")


# ---------------------------------------------------------------------------
# Video → GIF (app/converters/video.py)
# ---------------------------------------------------------------------------

# A GIF is for short clips. GIF counts frame delays in hundredths of a
# second, so 10 fps gives every frame exactly the same delay. Frames fit a
# GIF_MAX_SIDE square, so portrait clips are capped too, and are never
# upscaled.
GIF_MAX_SECONDS = 30
GIF_FPS = 10
GIF_MAX_SIDE = 480
# Phones save a "30-second" clip as e.g. 30.03 s; this much more still converts.
GIF_SLACK_SECONDS = 0.5
# A larger source (8K) can't be decoded within the time budget.
GIF_MAX_SOURCE_PIXELS = 4096 * 2160
# One budget for the probe, both passes and the frame count — under the 100 s
# a CDN in front of the app may wait for an answer (as in _isolated.py), so
# the caller gets the 400 that names the next step, not a gateway timeout.
GIF_TIME_BUDGET_SECONDS = 85


class VideoProbe(NamedTuple):
    width: int
    height: int
    duration: float | None  # seconds; None when the container doesn't say


def _ffprobe(path: Path, *args: str, demuxers: str, timeout: float) -> dict:
    """Run ffprobe on a local file, read only with ``demuxers``, and return
    its JSON output. Fails like :func:`run_ffmpeg`."""
    if shutil.which("ffprobe") is None:
        raise FFmpegError("ffprobe binary not found on PATH")
    cmd = [
        "ffprobe", "-v", "error",
        "-format_whitelist", demuxers, "-protocol_whitelist", "file",
        *args, "-of", "json", str(path),
    ]  # fmt: skip
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise FFmpegTimeoutError(f"ffprobe timed out after {timeout:.0f}s") from exc
    _raise_on_failure("ffprobe", result)
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise FFmpegError("ffprobe printed no JSON") from exc


def _seconds(value) -> float | None:
    """An ffprobe duration in seconds; None for "N/A", junk or ≤ 0."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def probe_video(path: Path, *, timeout: float) -> VideoProbe | None:
    """Frame size and duration of an upload's first video stream — cover art
    doesn't count — or None if it has none. Same demuxers as
    :func:`media_input`; only numeric fields are read, so none of the
    upload's tags are echoed."""
    data = _ffprobe(
        path,
        "-select_streams", "V:0",
        "-show_entries", "stream=width,height,duration:format=duration",
        demuxers=INPUT_DEMUXERS,
        timeout=timeout,
    )  # fmt: skip
    streams = data.get("streams") or []
    if not streams:
        return None
    width, height = streams[0].get("width"), streams[0].get("height")
    if not (isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0):
        return None
    duration = _seconds(streams[0].get("duration"))
    if duration is None:
        duration = _seconds((data.get("format") or {}).get("duration"))
    return VideoProbe(width, height, duration)


def count_gif_frames(path: Path, *, timeout: float) -> int:
    """The number of frames in a GIF written by :func:`gif_stream` — counted, not decoded."""
    data = _ffprobe(
        path,
        "-select_streams", "v:0", "-count_packets",
        "-show_entries", "stream=nb_read_packets",
        demuxers="gif",
        timeout=timeout,
    )  # fmt: skip
    try:
        return int(data["streams"][0]["nb_read_packets"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise FFmpegError("ffprobe reported no frame count") from exc


def _gif_frames(input_path: Path, seconds: float):
    """At most ``seconds`` of the upload's first video stream (no cover art),
    at GIF_FPS, fitted into the GIF_MAX_SIDE square, as opaque RGB."""
    return (
        media_input(input_path, t=seconds)["V:0"]
        .filter("fps", fps=GIF_FPS)
        .filter(
            "scale",
            w=f"min({GIF_MAX_SIDE},iw)",
            h=f"min({GIF_MAX_SIDE},ih)",
            force_original_aspect_ratio="decrease",
            flags="lanczos",
        )
        # No alpha: the GIF stays opaque, and both passes' colour tables
        # count at most one entry per RGB colour.
        .filter("format", "rgb24")
    )


# 6 bits per channel, the top two bits repeated below them, so white stays white.
_SIX_BITS = "bitor(bitand(val,252),bitand(val,192)/64)"


def gif_palette_stream(input_path: Path, palette_path: Path, *, seconds: float):
    """Pass 1: one 256-colour palette for the whole clip, written to ``palette_path``."""
    return (
        _gif_frames(input_path, seconds)
        # Colours are counted at 6 bits per channel, which keeps palettegen's
        # colour statistics small; the palette still has 256 colours.
        .filter("lutrgb", r=_SIX_BITS, g=_SIX_BITS, b=_SIX_BITS)
        .filter("palettegen", stats_mode="full")
        .output(str(palette_path), update=1)
    )


def gif_stream(
    input_path: Path,
    palette_path: Path,
    output_path: Path,
    *,
    seconds: float,
    max_output_bytes: int | None,
):
    """Pass 2: the clip mapped onto the pass-1 palette, as a looping GIF
    without metadata. ``-fs`` stops writing once ``max_output_bytes`` is
    passed; ffmpeg still exits 0 then, so the caller checks the file size."""
    palette = _local_input(palette_path, "image2,png_pipe")
    frames = ffmpeg.filter(
        [_gif_frames(input_path, seconds), palette],
        "paletteuse",
        # Ordered dithering is the same in every frame, so a pixel that
        # doesn't change keeps its colour, and the GIF encoder stores only
        # the rectangle that did change.
        dither="bayer",
        bayer_scale=4,
        diff_mode="rectangle",
    )
    options = {"format": "gif", "loop": 0, "map_metadata": -1, "map_chapters": -1}
    if max_output_bytes is not None:
        options["fs"] = max_output_bytes
    return frames.output(str(output_path), **options)
