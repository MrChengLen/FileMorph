# SPDX-License-Identifier: AGPL-3.0-or-later
"""Functional smoke matrix for the ffmpeg-backed media stack.

Two layers:

1. Pure unit tests for the codec matrix / quality mapping in
   ``app/converters/_ffmpeg.py`` — run everywhere, no ffmpeg needed.
2. A functional smoke matrix that generates sub-second clips via
   ffmpeg's ``lavfi`` test sources, runs every registered video/audio
   target through the real converters, and verifies container + codecs
   with ffprobe. Skipped when ffmpeg/ffprobe are not on PATH (local
   Windows dev); the CI runner installs ffmpeg, so the matrix always
   runs there.

Regression context: before the codec matrix, ``*→webm/mkv/wmv`` video
pairs and ``m4a/aac/wma`` audio targets failed at runtime (codecs the
container forbids, or muxer names ffmpeg does not know), and /compress
remuxed every video into MP4 while keeping the original extension.
"""

import json
import shutil
import subprocess

import pytest

from app.compressors.video import compress_video
from app.converters._ffmpeg import (
    AUDIO_TARGETS,
    VIDEO_CODECS,
    FFmpegError,
    audio_output_args,
    run_ffmpeg,
    video_output_args,
)
from app.converters.audio import _AUDIO_FORMATS
from app.converters.registry import get_converter
from app.converters.video import _VIDEO_FORMATS

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

requires_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None,
    reason="ffmpeg/ffprobe not on PATH (installed in CI; optional for local dev)",
)


# ---------------------------------------------------------------------------
# Unit layer — no ffmpeg binary required
# ---------------------------------------------------------------------------


def test_video_codec_matrix_covers_registered_formats():
    assert set(_VIDEO_FORMATS) == set(VIDEO_CODECS)


def test_audio_matrix_covers_registered_formats():
    assert set(_AUDIO_FORMATS) == set(AUDIO_TARGETS)


def test_webm_gets_webm_legal_codecs():
    # The WebM muxer rejects H.264/AAC outright — VP9/Opus is the fix.
    args = video_output_args("webm", 70, audio_bitrate="128k")
    assert args["vcodec"] == "libvpx-vp9"
    assert args["acodec"] == "libopus"
    assert args["video_bitrate"] == 0  # VP9 constant-quality mode


def test_mkv_and_wmv_use_real_muxer_names():
    # ffmpeg has no muxers named "mkv"/"wmv".
    assert video_output_args("mkv", 70, audio_bitrate="128k")["format"] == "matroska"
    assert video_output_args("wmv", 70, audio_bitrate="128k")["format"] == "asf"


def test_video_args_round_odd_dimensions():
    # yuv420p requires even dimensions — without the scale filter an
    # 855×479 source fails with "width/height not divisible by 2".
    args = video_output_args("mp4", 70, audio_bitrate="128k")
    assert args["vf"] == "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def test_x264_crf_mapping_endpoints_unchanged():
    # Same mapping the compressor always documented: quality 100→CRF 18, 1→40.
    assert video_output_args("mp4", 100, audio_bitrate="128k")["crf"] == 18
    assert video_output_args("mp4", 1, audio_bitrate="128k")["crf"] == 40
    crf70 = video_output_args("mp4", 70, audio_bitrate="128k")["crf"]
    crf90 = video_output_args("mp4", 90, audio_bitrate="128k")["crf"]
    assert crf90 < crf70  # better quality → lower CRF


def test_audio_muxer_names_are_real():
    # ffmpeg has no muxers named m4a/aac/wma — these mappings are the fix.
    assert audio_output_args("m4a", 85)["format"] == "ipod"
    assert audio_output_args("aac", 85)["format"] == "adts"
    assert audio_output_args("wma", 85)["format"] == "asf"


def test_audio_quality_drives_rate_control():
    assert audio_output_args("mp3", 100)["q:a"] == 0  # LAME V0
    assert audio_output_args("mp3", 1)["q:a"] == 9
    assert audio_output_args("opus", 85)["audio_bitrate"].endswith("k")
    assert "q:a" not in audio_output_args("wav", 85)  # lossless ignores quality


def test_unknown_targets_raise():
    with pytest.raises(ValueError):
        video_output_args("3gp", 70, audio_bitrate="128k")
    with pytest.raises(ValueError):
        audio_output_args("ra", 70)


def _fake_stream():
    import ffmpeg

    return ffmpeg.input("in.mp4").output("out.mp4")


def test_run_ffmpeg_missing_binary(monkeypatch):
    import app.converters._ffmpeg as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _: None)
    with pytest.raises(FFmpegError, match="not found"):
        run_ffmpeg(_fake_stream())


def test_run_ffmpeg_timeout_translated(monkeypatch):
    import app.converters._ffmpeg as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _: "ffmpeg")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    with pytest.raises(FFmpegError, match="timed out"):
        run_ffmpeg(_fake_stream(), timeout=1)


def test_run_ffmpeg_failure_translated(monkeypatch):
    import app.converters._ffmpeg as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _: "ffmpeg")

    class _Result:
        returncode = 1
        stderr = b"boom: invalid argument"

    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: _Result())
    with pytest.raises(FFmpegError, match="exit 1"):
        run_ffmpeg(_fake_stream(), timeout=5)


# ---------------------------------------------------------------------------
# Functional smoke matrix — needs ffmpeg/ffprobe on PATH
# ---------------------------------------------------------------------------


def _generate(*args: str) -> None:
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", *args],
        capture_output=True,
        check=True,
        timeout=60,
    )


def _probe(path) -> tuple[str, set[str]]:
    out = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    data = json.loads(out.stdout)
    return data["format"]["format_name"], {s["codec_name"] for s in data["streams"]}


@pytest.fixture(scope="module")
def sample_mp4(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    _generate(
        "-f", "lavfi", "-i", "testsrc2=duration=0.6:size=128x72:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(path),
    )  # fmt: skip
    return path


@pytest.fixture(scope="module")
def sample_wav(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "sample.wav"
    _generate("-f", "lavfi", "-i", "sine=frequency=440:duration=0.6", str(path))
    return path


@pytest.fixture(scope="module")
def sample_webm(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "sample.webm"
    _generate(
        "-f", "lavfi", "-i", "testsrc2=duration=0.6:size=128x72:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
        "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
        "-c:a", "libopus", "-shortest",
        str(path),
    )  # fmt: skip
    return path


# Target → (token expected in ffprobe format_name, codecs expected in streams).
# webm/mkv share the probe format_name "matroska,webm" — the codec set is
# what distinguishes a real WebM (VP9/Opus) from generic Matroska.
_VIDEO_EXPECT = {
    "mp4": ("mp4", {"h264", "aac"}),
    "mov": ("mov", {"h264", "aac"}),
    "mkv": ("matroska", {"h264", "aac"}),
    "webm": ("webm", {"vp9", "opus"}),
    "avi": ("avi", {"mpeg4", "mp3"}),
    "flv": ("flv", {"h264", "aac"}),
    "wmv": ("asf", {"wmv2", "wmav2"}),
}

_AUDIO_EXPECT = {
    "mp3": ("mp3", "mp3"),
    "flac": ("flac", "flac"),
    "ogg": ("ogg", "vorbis"),
    "m4a": ("m4a", "aac"),
    "aac": ("aac", "aac"),
    "wma": ("asf", "wmav2"),
    "opus": ("ogg", "opus"),
}


@requires_ffmpeg
@pytest.mark.parametrize("tgt", sorted(set(_VIDEO_FORMATS) - {"mp4"}))
def test_video_convert_matrix(sample_mp4, tmp_path, tgt):
    out = tmp_path / f"out.{tgt}"
    get_converter("mp4", tgt).convert(sample_mp4, out, quality=70)
    assert out.stat().st_size > 0
    fmt_name, codecs = _probe(out)
    expected_token, expected_codecs = _VIDEO_EXPECT[tgt]
    assert expected_token in fmt_name
    assert expected_codecs <= codecs


@requires_ffmpeg
@pytest.mark.parametrize("tgt", sorted(set(_AUDIO_FORMATS) - {"wav"}))
def test_audio_convert_matrix(sample_wav, tmp_path, tgt):
    out = tmp_path / f"out.{tgt}"
    get_converter("wav", tgt).convert(sample_wav, out, quality=85)
    assert out.stat().st_size > 0
    fmt_name, codecs = _probe(out)
    expected_token, expected_codec = _AUDIO_EXPECT[tgt]
    assert expected_token in fmt_name
    assert expected_codec in codecs


@pytest.fixture(scope="module")
def sample_odd_mkv(tmp_path_factory):
    # ffv1 (lossless) accepts odd dimensions, unlike the delivery codecs —
    # video-only on purpose, so this also covers inputs without audio.
    path = tmp_path_factory.mktemp("media") / "sample_odd.mkv"
    _generate(
        "-f", "lavfi", "-i", "testsrc2=duration=0.4:size=127x71:rate=10",
        "-c:v", "ffv1",
        str(path),
    )  # fmt: skip
    return path


@requires_ffmpeg
def test_video_odd_dimensions_are_rounded_not_rejected(sample_odd_mkv, tmp_path):
    """Regression guard for the yuv420p even-dimension requirement: odd
    sources are rounded down one pixel by the scale filter, not failed."""
    out = tmp_path / "out.mp4"
    get_converter("mkv", "mp4").convert(sample_odd_mkv, out, quality=70)
    fmt_name, codecs = _probe(out)
    assert "mp4" in fmt_name
    assert "h264" in codecs


@requires_ffmpeg
def test_audio_lossy_input_decodes(sample_wav, tmp_path):
    mp3 = tmp_path / "in.mp3"
    get_converter("wav", "mp3").convert(sample_wav, mp3, quality=85)
    out = tmp_path / "out.ogg"
    get_converter("mp3", "ogg").convert(mp3, out, quality=85)
    fmt_name, codecs = _probe(out)
    assert "ogg" in fmt_name
    assert "vorbis" in codecs


@requires_ffmpeg
def test_compress_video_keeps_mp4(sample_mp4, tmp_path):
    out = tmp_path / "compressed.mp4"
    compress_video(sample_mp4, out, quality=60)
    fmt_name, codecs = _probe(out)
    assert "mp4" in fmt_name
    assert {"h264", "aac"} <= codecs


@requires_ffmpeg
def test_compress_video_preserves_webm_container(sample_webm, tmp_path):
    """Regression: /compress used to remux everything into MP4 while keeping
    the original extension — a compressed .webm was a mislabelled MP4."""
    out = tmp_path / "compressed.webm"
    compress_video(sample_webm, out, quality=60)
    fmt_name, codecs = _probe(out)
    assert "webm" in fmt_name
    assert {"vp9", "opus"} <= codecs
