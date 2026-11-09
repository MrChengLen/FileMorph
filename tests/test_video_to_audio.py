# SPDX-License-Identifier: AGPL-3.0-or-later
"""Video → audio: ``VideoToAudioConverter`` (app/converters/video.py) and the
``has_audio`` probe in app/converters/_ffmpeg.py.

Two layers, as in tests/test_video_to_gif.py:

1. Unit tests with ffmpeg and ffprobe replaced — the registered pairs, the
   compiled command (the first audio track only, no picture, no metadata,
   the upload opened like every other), the probe that tells a video without
   sound apart once ffmpeg failed, the routes' error code and output-cap tip,
   the web UI and the docs. They run everywhere.
2. Functional tests that make clips with ffmpeg's ``lavfi`` sources and run
   them through the real converter. Skipped when ffmpeg/ffprobe are not on
   PATH (local Windows dev); the CI runner installs ffmpeg, so they always
   run there.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import ffmpeg
import pytest

import app.converters._ffmpeg as ffmpeg_mod
import app.converters.video as video_mod
from app.converters._ffmpeg import (
    AUDIO_TARGETS,
    INPUT_DECODERS,
    INPUT_DEMUXERS,
    MAX_PIXELS,
    THREADS,
    FFmpegError,
    has_audio,
)
from app.converters.audio import _AUDIO_FORMATS
from app.converters.base import InvalidInputError, NoAudioTrackError, OutputTooLargeError
from app.converters.registry import get_converter, get_supported_conversions
from app.converters.video import _AUDIO_TARGETS, _VIDEO_FORMATS, VideoToAudioConverter
from app.core.config import settings
from tests.test_media_smoke import (
    _AUDIO_EXPECT,
    _PHONE_MARKERS,
    _PHONE_TAGS,
    _chapter_file,
    _generate,
    _metadata_traces,
    _probe_json,
    _tag_args,
    requires_ffmpeg,
)

ROOT = Path(__file__).resolve().parents[1]

# Any bytes the magic-byte check lets through; the converter is replaced.
_MP4_UPLOAD = {"file": ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")}


# ---------------------------------------------------------------------------
# Unit layer — no ffmpeg binary required
# ---------------------------------------------------------------------------


def test_every_video_format_converts_to_the_audio_targets():
    conversions = get_supported_conversions()
    for src in _VIDEO_FORMATS:
        for tgt in _AUDIO_TARGETS:
            converter = get_converter(src, tgt)
            assert isinstance(converter, VideoToAudioConverter), (src, tgt)
            assert converter._tgt_fmt == tgt
        # Every audio format, Opus and WMA included — their encoders take
        # surround sound as stereo (_SURROUND_SAFE_AF), so nothing is left out.
        assert set(_AUDIO_FORMATS) <= set(conversions[src]), src
    assert set(_AUDIO_TARGETS) == set(_AUDIO_FORMATS)
    # Audio → audio keeps its own converter.
    assert type(get_converter("wav", "mp3")).__module__ == "app.converters.audio"


def _capture(monkeypatch, *, fails: Exception | None = None, sound: bool = True) -> dict:
    """Replace ffmpeg (failing with ``fails``, if given) and the probe in
    app/converters/video.py; return the ffmpeg runs and the probes."""
    calls: dict = {"runs": [], "probes": []}

    def fake_run(stream, **kwargs):
        calls["runs"].append({"cmd": ffmpeg.compile(stream), **kwargs})
        if fails is not None:
            raise fails

    def fake_probe(path):
        calls["probes"].append(path)
        return sound

    monkeypatch.setattr(video_mod, "has_audio", fake_probe)
    monkeypatch.setattr(video_mod, "run_ffmpeg", fake_run)
    return calls


def _contains(cmd: list[str], part: list[str]) -> bool:
    return any(cmd[i : i + len(part)] == part for i in range(len(cmd)))


def test_the_command_keeps_the_first_audio_track_and_nothing_else(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    runs = calls["runs"]
    out = tmp_path / "out.mp3"
    get_converter("mov", "mp3").convert(tmp_path / "in.mov", out, max_output_bytes=1000)
    assert len(runs) == 1
    assert calls["probes"] == []  # a run that works needs no probe
    cmd = runs[0]["cmd"]
    # The upload is opened as every other one is (media_input).
    assert cmd[1 : cmd.index("-i")] == [
        *("-codec_whitelist", INPUT_DECODERS, "-format_whitelist", INPUT_DEMUXERS),
        *("-max_pixels", str(MAX_PIXELS), "-protocol_whitelist", "file"),
        *("-threads", str(THREADS)),
    ]
    # One stream: the first audio track — no picture, cover, subtitles or
    # further tracks.
    assert cmd.count("-map") == 1 and _contains(cmd, ["-map", "0:a:0"])
    assert "-vn" in cmd
    # Nothing of the video's metadata, not even a title.
    assert _contains(cmd, ["-map_metadata", "-1"]) and _contains(cmd, ["-map_chapters", "-1"])
    assert not [arg for arg in cmd if arg.startswith("-metadata")]
    assert cmd[-1] == str(out)
    # ffmpeg stops writing at the caller's output cap.
    assert runs[0]["max_output_bytes"] == 1000


@pytest.mark.parametrize("tgt", _AUDIO_TARGETS)
def test_each_target_gets_its_muxer_and_codec(tmp_path, monkeypatch, tgt):
    runs = _capture(monkeypatch)["runs"]
    get_converter("mp4", tgt).convert(tmp_path / "in.mp4", tmp_path / f"out.{tgt}")
    muxer, codec = AUDIO_TARGETS[tgt]
    cmd = runs[0]["cmd"]
    assert _contains(cmd, ["-f", muxer]) and _contains(cmd, ["-acodec", codec])


def test_quality_drives_the_rate_control_as_for_audio(tmp_path, monkeypatch):
    runs = _capture(monkeypatch)["runs"]
    for quality in (1, 100):
        get_converter("mp4", "mp3").convert(
            tmp_path / "in.mp4", tmp_path / "out.mp3", quality=quality
        )
    assert _contains(runs[0]["cmd"], ["-q:a", "9"])  # LAME V9, the smallest
    assert _contains(runs[1]["cmd"], ["-q:a", "0"])  # LAME V0, the best


def test_a_failed_run_on_a_video_without_sound_is_no_audio_track(tmp_path, monkeypatch):
    source = tmp_path / "in.mp4"
    calls = _capture(monkeypatch, fails=FFmpegError("ffmpeg exit 1"), sound=False)
    with pytest.raises(NoAudioTrackError) as exc:
        get_converter("mp4", "mp3").convert(source, tmp_path / "out.mp3")
    assert calls["probes"] == [source]
    # A problem the user can fix: the routes answer it with a 400 and its code.
    assert isinstance(exc.value, InvalidInputError)
    assert exc.value.error_code == "no_audio_track"
    assert str(exc.value) == NoAudioTrackError.message
    assert "Choose a video with sound" in NoAudioTrackError.message


def test_a_failed_run_on_a_video_with_sound_stays_a_failure(tmp_path, monkeypatch):
    # A damaged file, say: the route's generic 500, not "no sound".
    calls = _capture(monkeypatch, fails=FFmpegError("ffmpeg exit 1"), sound=True)
    with pytest.raises(FFmpegError):
        get_converter("mp4", "mp3").convert(tmp_path / "in.mp4", tmp_path / "out.mp3")
    assert len(calls["probes"]) == 1


@pytest.mark.parametrize(
    "error", [InvalidInputError("not a supported format"), OutputTooLargeError()]
)
def test_a_run_stopped_for_a_named_reason_is_not_probed(tmp_path, monkeypatch, error):
    # Refused, out of time or over the cap: ffmpeg's own reason stands.
    calls = _capture(monkeypatch, fails=error)
    with pytest.raises(type(error)):
        get_converter("mp4", "mp3").convert(tmp_path / "in.mp4", tmp_path / "out.mp3")
    assert calls["probes"] == []


# ── the probe ────────────────────────────────────────────────────────────────


def _fake_ffprobe(monkeypatch, payload: dict, *, returncode=0, stderr=b"") -> list[dict]:
    calls: list[dict] = []

    class _Result:
        def __init__(self):
            self.returncode = returncode
            self.stdout = json.dumps(payload).encode()
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        # On Linux the program follows _limited_exec.py and its limits.
        calls.append({"cmd": cmd[cmd.index("ffprobe") :], "timeout": kwargs.get("timeout")})
        return _Result()

    monkeypatch.setattr(ffmpeg_mod.shutil, "which", lambda _: "ffprobe")
    monkeypatch.setattr(ffmpeg_mod, "_exec", fake_run)
    return calls


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"streams": [{"index": 1}]}, True),
        ({"programs": [], "streams": []}, False),  # a video without sound
        ({}, False),
    ],
)
def test_the_probe_looks_for_an_audio_stream(tmp_path, monkeypatch, payload, expected):
    calls = _fake_ffprobe(monkeypatch, payload)
    assert has_audio(tmp_path / "in.mp4") is expected
    cmd = calls[0]["cmd"]
    # Read as media_input reads an upload: the listed demuxers and decoders
    # only, frames up to 4K.
    assert cmd[cmd.index("-format_whitelist") + 1] == INPUT_DEMUXERS
    assert cmd[cmd.index("-codec_whitelist") + 1] == INPUT_DECODERS
    assert cmd[cmd.index("-protocol_whitelist") + 1] == "file"
    assert cmd[cmd.index("-max_pixels") + 1] == str(MAX_PIXELS)
    assert cmd[cmd.index("-select_streams") + 1] == "a:0"
    # The stream's index only: the probe never prints the upload's tags.
    assert cmd[cmd.index("-show_entries") + 1] == "stream=index"
    assert "-show_streams" not in cmd and "-show_format" not in cmd
    # Headers only, as the music-tag dump: within its time, never past the media limit.
    assert calls[0]["timeout"] <= min(60, settings.media_subprocess_timeout_seconds)


def test_the_probe_refuses_a_container_ffmpeg_would_refuse(tmp_path, monkeypatch):
    _fake_ffprobe(monkeypatch, {}, returncode=1, stderr=b"Format au not on whitelist 'mp3,wav'")
    with pytest.raises(InvalidInputError, match="not in one of the audio or video formats"):
        has_audio(tmp_path / "in.mp4")


# ── the routes ───────────────────────────────────────────────────────────────


def _raising(error: Exception):
    def convert(self, input_path, output_path, **kwargs):
        raise error

    return convert


def test_the_convert_route_answers_with_the_sound(client, monkeypatch):
    runs = []

    def fake_run(stream, **kwargs):
        cmd = ffmpeg.compile(stream)
        runs.append({"cmd": cmd, **kwargs})
        Path(cmd[-1]).write_bytes(b"ID3 the sound")

    monkeypatch.setattr(video_mod, "has_audio", lambda path: True)
    monkeypatch.setattr(video_mod, "run_ffmpeg", fake_run)
    res = client.post("/api/v1/convert", files=_MP4_UPLOAD, data={"target_format": "mp3"})
    assert res.status_code == 200, res.text
    assert res.content == b"ID3 the sound"
    assert "clip.mp3" in res.headers["content-disposition"]
    # The route hands the tier's output cap down, as for every conversion.
    assert runs[0]["max_output_bytes"] > 0


def test_the_convert_route_sends_no_audio_track(client, monkeypatch):
    monkeypatch.setattr(VideoToAudioConverter, "convert", _raising(NoAudioTrackError()))
    res = client.post("/api/v1/convert", files=_MP4_UPLOAD, data={"target_format": "mp3"})
    assert res.status_code == 400, res.text
    assert res.headers["X-FileMorph-Error-Code"] == "no_audio_track"
    assert res.json()["detail"] == NoAudioTrackError.message


def test_a_batch_names_the_missing_sound_of_the_file(client, monkeypatch):
    monkeypatch.setattr(VideoToAudioConverter, "convert", _raising(NoAudioTrackError()))
    files = [("files", _MP4_UPLOAD["file"])]
    res = client.post("/api/v1/convert/batch", files=files, data={"target_formats": ["m4a"]})
    assert res.status_code == 422, res.text
    assert NoAudioTrackError.message in res.json()["files"][0]["error_message"]


@pytest.mark.parametrize(
    ("tgt", "tip"),
    [
        # A long video as WAV is the usual way to the cap: a smaller format helps.
        ("wav", "Choose MP3 or M4A, a fraction of the size of WAV or FLAC"),
        ("flac", "Choose MP3 or M4A, a fraction of the size of WAV or FLAC"),
        # Already compressed: only a shorter video makes it smaller.
        ("mp3", "Use a shorter video for a smaller audio file"),
        ("m4a", "Use a shorter video for a smaller audio file"),
    ],
)
def test_an_audio_file_over_the_cap_names_what_makes_it_smaller(client, monkeypatch, tgt, tip):
    assert get_converter("mp4", tgt).output_cap_tip == tip
    monkeypatch.setattr(VideoToAudioConverter, "convert", _raising(OutputTooLargeError()))
    res = client.post("/api/v1/convert", files=_MP4_UPLOAD, data={"target_format": tgt})
    assert res.status_code == 413, res.text
    assert res.headers["X-FileMorph-Error-Code"] == "output_cap_exceeded"
    assert tip in res.json()["detail"]
    files = [("files", _MP4_UPLOAD["file"])]
    res = client.post("/api/v1/convert/batch", files=files, data={"target_formats": [tgt]})
    assert res.status_code == 422, res.text
    assert tip in res.json()["files"][0]["error_message"]


# ── the web UI and the docs ──────────────────────────────────────────────────


def _js_strings(client, locale: str) -> dict[str, str]:
    html = client.get(f"/{locale}/").text
    blob = re.search(
        r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', html, re.S
    )
    assert blob, "FM_I18N block missing"
    return json.loads(blob.group(1))


@pytest.mark.parametrize("locale", ["en", "de"])
def test_the_ui_names_the_missing_sound_in_the_page_language(client, locale):
    text = _js_strings(client, locale)["errorNoAudioTrack"]
    if locale == "en":  # the server's own message
        assert text == NoAudioTrackError.message
    else:  # translated, not the English fallback
        assert text != NoAudioTrackError.message and "keinen Ton" in text


def test_app_js_knows_the_audio_formats_and_the_code():
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
    match = re.search(r"const AUDIO_TYPES = \[([^\]]*)\];", js)
    assert match, "AUDIO_TYPES not found in app.js"
    assert sorted(re.findall(r"'([a-z0-9]+)'", match.group(1))) == sorted(_AUDIO_FORMATS)
    assert "errCode === 'no_audio_track'" in js and "i18n.errorNoAudioTrack" in js
    # No quality slider for an audio target, as for audio → audio — and a
    # hidden slider sends nothing, so the server's default applies, not a
    # value left from an earlier file.
    assert "if (AUDIO_TYPES.includes(target)) return false;" in js
    send = "} else if (!document.getElementById('quality-section').classList.contains('hidden')) {"
    assert f"{send}\n" in js and js.count("formData.append('quality'") == 1


def test_the_api_reference_lists_the_code():
    reference = (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")
    assert "| `no_audio_track` | `400` |" in reference


# ---------------------------------------------------------------------------
# Functional layer — needs ffmpeg/ffprobe on PATH
# ---------------------------------------------------------------------------

# Target → (token expected in ffprobe's format_name, the audio codec).
_EXPECT = {**_AUDIO_EXPECT, "wav": ("wav", "pcm_s16le")}


def _streams(path: Path) -> list[tuple[str, str]]:
    return [(s["codec_type"], s["codec_name"]) for s in _probe_json(path)["streams"]]


@pytest.fixture(scope="module")
def clip_with_sound(tmp_path_factory):
    path = tmp_path_factory.mktemp("sound") / "clip.mp4"
    _generate(
        "-f", "lavfi", "-i", "testsrc2=duration=0.6:size=128x72:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(path),
    )  # fmt: skip
    return path


@requires_ffmpeg
@pytest.mark.parametrize("tgt", _AUDIO_TARGETS)
def test_the_sound_becomes_each_audio_format(clip_with_sound, tmp_path, tgt):
    out = tmp_path / f"out.{tgt}"
    get_converter("mp4", tgt).convert(clip_with_sound, out, quality=85)
    token, codec = _EXPECT[tgt]
    assert token in _probe_json(out)["format"]["format_name"]
    assert _streams(out) == [("audio", codec)]  # the sound only: no picture


@requires_ffmpeg
@pytest.mark.parametrize("fmt", _VIDEO_FORMATS)
def test_every_video_format_gives_its_sound(clip_with_sound, tmp_path, fmt):
    source = clip_with_sound
    if fmt != "mp4":
        source = tmp_path / f"in.{fmt}"
        get_converter("mp4", fmt).convert(clip_with_sound, source, quality=70)
    out = tmp_path / "out.mp3"
    get_converter(fmt, "mp3").convert(source, out, quality=85)
    assert _streams(out) == [("audio", "mp3")]


@requires_ffmpeg
def test_a_real_video_without_sound_is_no_audio_track(clip_with_sound, tmp_path):
    silent = tmp_path / "silent.mp4"
    _generate(
        "-f", "lavfi", "-i", "testsrc2=duration=0.4:size=128x72:rate=10",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(silent),
    )  # fmt: skip
    assert has_audio(clip_with_sound) is True
    assert has_audio(silent) is False
    # ffmpeg finds no audio track to map; the probe then names the reason.
    with pytest.raises(NoAudioTrackError):
        get_converter("mp4", "mp3").convert(silent, tmp_path / "out.mp3", quality=85)
    assert not (tmp_path / "out.mp3").exists()


@requires_ffmpeg
def test_a_picture_in_a_codec_filemorph_does_not_read_still_gives_its_sound(tmp_path):
    # Cinepak isn't among the decoders an upload may use. A probe up front,
    # which opens a decoder for every stream, would refuse this file; the run
    # decodes only the first audio track and so gives the sound.
    assert "cinepak" not in INPUT_DECODERS.split(",")
    source = tmp_path / "old.avi"
    _generate(
        "-f", "lavfi", "-i", "testsrc2=duration=0.6:size=128x72:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
        "-c:v", "cinepak", "-c:a", "pcm_s16le", "-shortest",
        str(source),
    )  # fmt: skip
    out = tmp_path / "out.mp3"
    get_converter("avi", "mp3").convert(source, out, quality=85)
    assert _streams(out) == [("audio", "mp3")]


@requires_ffmpeg
def test_only_the_first_audio_track_is_kept(tmp_path):
    # The first track mono, the second stereo: on its own, ffmpeg would pick
    # the one with more channels.
    source = tmp_path / "two_tracks.mkv"
    _generate(
        "-f", "lavfi", "-i", "testsrc2=duration=0.6:size=128x72:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
        "-f", "lavfi", "-i", "sine=frequency=880:duration=0.6",
        "-map", "0:v", "-map", "1:a", "-map", "2:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac:a:1", "2",
        "-shortest", str(source),
    )  # fmt: skip
    assert [s.get("channels") for s in _probe_json(source)["streams"][1:]] == [1, 2]
    out = tmp_path / "out.wav"
    get_converter("mkv", "wav").convert(source, out, quality=85)
    streams = _probe_json(out)["streams"]
    assert len(streams) == 1 and streams[0]["channels"] == 1


@pytest.fixture(scope="module")
def sample_surround_mkv(tmp_path_factory):
    # 5.1 sound as a film carries it: AC-3, whose decoder gives the "5.1(side)" layout.
    path = tmp_path_factory.mktemp("sound") / "surround.mkv"
    _generate(
        "-f", "lavfi", "-i", "testsrc2=duration=0.6:size=128x72:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "ac3", "-af", "pan=5.1(side)|c0=c0|c1=c0|c2=c0|c3=c0|c4=c0|c5=c0",
        "-shortest", str(path),
    )  # fmt: skip
    return path


# MP3, Opus and WMA take surround as stereo (_SURROUND_SAFE_AF downmixes it);
# AAC/M4A, Vorbis (OGG), FLAC and WAV keep all six channels.
_SURROUND_DOWNMIXED = {"mp3", "opus", "wma"}


@requires_ffmpeg
@pytest.mark.parametrize("tgt", _AUDIO_TARGETS)
def test_surround_sound_converts_to_every_target(sample_surround_mkv, tmp_path, tgt):
    assert _probe_json(sample_surround_mkv)["streams"][1]["channels"] == 6
    out = tmp_path / f"out.{tgt}"
    get_converter("mkv", tgt).convert(sample_surround_mkv, out, quality=85)
    streams = _probe_json(out)["streams"]
    assert len(streams) == 1 and streams[0]["codec_type"] == "audio"
    assert streams[0]["channels"] == (2 if tgt in _SURROUND_DOWNMIXED else 6)


@requires_ffmpeg
@pytest.mark.parametrize("tgt", ["webm", "wmv"])
def test_surround_video_conversions_downmix_the_audio(sample_surround_mkv, tmp_path, tgt):
    # The regression this PR fixes: libopus (WebM) and wmav2 (WMV) fail on a
    # 5.1(side) source. The audio is downmixed to stereo, the picture stays.
    out = tmp_path / f"out.{tgt}"
    get_converter("mkv", tgt).convert(sample_surround_mkv, out, quality=70)
    kinds = {s["codec_type"] for s in _probe_json(out)["streams"]}
    assert {"video", "audio"} <= kinds
    audio = next(s for s in _probe_json(out)["streams"] if s["codec_type"] == "audio")
    assert audio["channels"] == 2


# What a phone writes into a clip (tests/test_media_smoke.py), plus a title,
# which audio → audio would keep as a music tag.
_TITLE = "Hafenrundfahrt"


@pytest.fixture(scope="module")
def sample_phone_mov(tmp_path_factory):
    folder = tmp_path_factory.mktemp("sound")
    path = folder / "phone.mov"
    _generate(
        "-f", "lavfi", "-i", "testsrc2=duration=0.6:size=128x72:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
        "-f", "ffmetadata", "-i", str(_chapter_file(folder)),
        "-map", "0:v", "-map", "1:a", "-map_chapters", "2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        *_tag_args({**_PHONE_TAGS, "title": _TITLE}), "-movflags", "use_metadata_tags",
        str(path),
    )  # fmt: skip
    return path


@requires_ffmpeg
def test_the_phone_clip_carries_every_marker(sample_phone_mov):
    # Guards the test below against passing on a clip with nothing to strip.
    assert _metadata_traces(sample_phone_mov) == {*_PHONE_MARKERS, "chapters"}
    assert _TITLE.encode() in sample_phone_mov.read_bytes()


@requires_ffmpeg
@pytest.mark.parametrize("tgt", _AUDIO_TARGETS)
def test_the_sound_carries_no_metadata_from_the_video(sample_phone_mov, tmp_path, tgt):
    out = tmp_path / f"out.{tgt}"
    get_converter("mov", tgt).convert(sample_phone_mov, out, quality=85)
    assert _metadata_traces(out) == set()
    raw = out.read_bytes()
    assert _TITLE.encode() not in raw and _TITLE.encode("utf-16-le") not in raw
    assert _TITLE not in json.dumps(_probe_json(out))
