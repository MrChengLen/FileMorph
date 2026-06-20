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
"""

from __future__ import annotations

import shutil
import subprocess

import ffmpeg  # ffmpeg-python

from app.core.config import settings


class FFmpegError(RuntimeError):
    """Raised when an ffmpeg invocation fails, times out, or is unavailable."""


# ffmpeg muxer names that differ from the user-facing file extension.
_MUXER_FOR_EXT = {"mkv": "matroska", "wmv": "asf"}

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


def video_output_args(container: str, quality: int, *, audio_bitrate: str) -> dict:
    """Build ffmpeg output kwargs for a video container at a quality level.

    quality 1 (smallest) – 100 (best) maps onto each encoder's native
    rate control: CRF 40→18 for libx264, CRF 45→18 for VP9 (its scale
    runs 0-63), qscale 31→2 for the legacy qscale-driven codecs.
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


def audio_output_args(target_ext: str, quality: int) -> dict:
    """Build ffmpeg output kwargs for an audio target format.

    Lossy targets honour quality 1-100 via each codec's preferred rate
    control (LAME/Vorbis VBR scales, bitrate for AAC/Opus); lossless
    targets (wav/flac) ignore it. ``-vn`` drops embedded cover-art
    streams — raw-stream muxers like ADTS cannot carry them, and
    dropping them matches the strip-metadata default the image pipeline
    already applies (NEU-C.2).
    """
    try:
        muxer, codec = AUDIO_TARGETS[target_ext]
    except KeyError:
        raise ValueError(f"unsupported audio target: {target_ext!r}") from None

    args: dict = {"format": muxer, "acodec": codec, "vn": None}
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


def run_ffmpeg(stream, *, timeout: int | None = None) -> None:
    """Compile an ffmpeg-python stream and run it with a hard timeout.

    Raises :class:`FFmpegError` on every failure mode (binary missing,
    non-zero exit, timeout). The stderr tail lands in the exception
    message for the server-side log only — the routes catch broadly and
    return a generic message to the client (A-3).
    """
    if shutil.which("ffmpeg") is None:
        raise FFmpegError("ffmpeg binary not found on PATH")
    if timeout is None:
        timeout = settings.media_subprocess_timeout_seconds

    cmd = ffmpeg.compile(stream, overwrite_output=True)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"ffmpeg timed out after {timeout}s") from exc

    if result.returncode != 0:
        tail = result.stderr.decode("utf-8", errors="replace")[-500:].strip()
        raise FFmpegError(f"ffmpeg exit {result.returncode}: {tail or '<no stderr>'}")
