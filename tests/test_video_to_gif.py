# SPDX-License-Identifier: AGPL-3.0-or-later
"""Video → GIF: ``VideoToGifConverter`` (app/converters/video.py) and the
``gif_*`` builders and ffprobe checks in app/converters/_ffmpeg.py.

Two layers, as in tests/test_media_smoke.py:

1. Unit tests with ffmpeg and ffprobe replaced — the compiled commands, the
   probe parsing, the converter's refusals and time budget, the route's
   error codes and the web UI's texts. They run everywhere.
2. Functional tests that make clips with ffmpeg's ``lavfi`` sources and run
   them through the real converter. Skipped when ffmpeg/ffprobe are not on
   PATH (local Windows dev); the CI runner installs ffmpeg, so they always
   run there.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import ffmpeg
import pytest

import app.converters._ffmpeg as ffmpeg_mod
import app.converters.video as video_mod
from app.converters._ffmpeg import (
    GIF_FPS,
    GIF_MAX_SECONDS,
    GIF_MAX_SIDE,
    GIF_TIME_BUDGET_SECONDS,
    INPUT_DECODERS,
    INPUT_DEMUXERS,
    MAX_PIXELS,
    THREADS,
    FFmpegError,
    FFmpegTimeoutError,
    VideoProbe,
    count_gif_frames,
    gif_palette_stream,
    gif_stream,
    probe_video,
    run_ffmpeg,
)
from app.converters.base import (
    InvalidInputError,
    OutputTooLargeError,
    VideoTooComplexError,
    VideoTooLongError,
)
from app.converters.registry import get_converter
from app.converters.video import _VIDEO_FORMATS, VideoToGifConverter

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

requires_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None,
    reason="ffmpeg/ffprobe not on PATH (installed in CI; optional for local dev)",
)

# Any bytes the magic-byte check lets through; the converter is replaced.
_MP4_UPLOAD = {"file": ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")}


# ---------------------------------------------------------------------------
# Unit layer — no ffmpeg binary required
# ---------------------------------------------------------------------------


def test_every_video_format_converts_to_gif_and_images_keep_pillow():
    for src in _VIDEO_FORMATS:
        assert isinstance(get_converter(src, "gif"), VideoToGifConverter), src
    assert type(get_converter("png", "gif")).__module__ == "app.converters.image"


def _options_before_each_input(cmd: list[str]) -> list[list[str]]:
    groups, start = [], 1  # cmd[0] is the program
    for i, arg in enumerate(cmd):
        if arg == "-i":
            groups.append(cmd[start:i])
            start = i + 2
    return groups


def _contains(cmd: list[str], part: list[str]) -> bool:
    return any(cmd[i : i + len(part)] == part for i in range(len(cmd)))


def _passes(tmp_path, max_output_bytes=1000) -> tuple[list[str], list[str]]:
    src, palette, out = tmp_path / "in.mp4", tmp_path / "p.png", tmp_path / "o.gif"
    pass1 = ffmpeg.compile(gif_palette_stream(src, palette, seconds=31))
    pass2 = ffmpeg.compile(
        gif_stream(src, palette, out, seconds=31, max_output_bytes=max_output_bytes)
    )
    return pass1, pass2


def test_both_passes_read_the_upload_with_the_listed_demuxers_and_a_time_cap(tmp_path):
    pass1, pass2 = _passes(tmp_path)
    upload = [
        *("-codec_whitelist", INPUT_DECODERS, "-format_whitelist", INPUT_DEMUXERS),
        *("-max_pixels", str(MAX_PIXELS), "-protocol_whitelist", "file"),
        *("-t", "31", "-threads", str(THREADS)),
    ]
    assert _options_before_each_input(pass1) == [upload]
    # The palette is the file pass 1 wrote, read as a PNG only.
    palette = ["-format_whitelist", "image2,png_pipe", "-protocol_whitelist", "file"]
    assert _options_before_each_input(pass2) == [upload, palette]


def test_the_filter_graphs(tmp_path):
    pass1, pass2 = _passes(tmp_path)
    graph1 = pass1[pass1.index("-filter_complex") + 1]
    graph2 = pass2[pass2.index("-filter_complex") + 1]
    for graph in (graph1, graph2):
        # The first video stream that isn't cover art, GIF_FPS, the box, no alpha.
        assert graph.startswith(f"[0:V:0]fps=fps={GIF_FPS}["), graph
        assert f"min({GIF_MAX_SIDE}\\,iw)" in graph and f"min({GIF_MAX_SIDE}\\,ih)" in graph
        assert "force_original_aspect_ratio=decrease" in graph
        assert "format=rgb24" in graph
    assert "palettegen=stats_mode=full" in graph1
    # 6 bits per channel with the top bits repeated: 255 stays 255, so white stays white.
    assert graph1.count("bitor(bitand(val\\,252)\\,bitand(val\\,192)/64)") == 3
    assert "paletteuse=" in graph2 and "dither=bayer" in graph2 and "lutrgb" not in graph2


def test_the_gif_loops_carries_no_metadata_and_stops_at_the_cap(tmp_path):
    _, capped = _passes(tmp_path, max_output_bytes=1000)
    for option in (
        ["-f", "gif"],
        ["-loop", "0"],
        ["-map_metadata", "-1"],
        ["-map_chapters", "-1"],
        ["-fs", "1000"],
    ):
        assert _contains(capped, option), (option, capped)
    _, uncapped = _passes(tmp_path, max_output_bytes=None)
    assert "-fs" not in uncapped


class _FakeMedia:
    """Stands in for ffprobe and the ffmpeg passes of VideoToGifConverter:
    records each step and its timeout, writes ``gif_bytes`` bytes to each
    pass's output and reports ``frames`` frames."""

    def __init__(self, monkeypatch, probe, *, gif_bytes=100, frames=20, run_error=None):
        self.steps: list[str] = []
        self.timeouts: list[float] = []
        self.commands: list[list[str]] = []

        def fake_probe(path, *, timeout):
            self.steps.append("probe")
            self.timeouts.append(timeout)
            return probe

        def fake_run(stream, *, timeout, max_output_bytes=None):
            self.steps.append("ffmpeg")
            self.timeouts.append(timeout)
            if run_error is not None:
                raise run_error
            cmd = ffmpeg.compile(stream)
            self.commands.append(cmd)
            Path(cmd[-1]).write_bytes(b"x" * gif_bytes)  # the output path is last

        def fake_count(path, *, timeout):
            self.steps.append("count")
            self.timeouts.append(timeout)
            return frames

        monkeypatch.setattr(video_mod, "probe_video", fake_probe)
        monkeypatch.setattr(video_mod, "run_ffmpeg", fake_run)
        monkeypatch.setattr(video_mod, "count_gif_frames", fake_count)


def _convert(tmp_path, **kwargs) -> Path:
    src = tmp_path / "in.mp4"
    src.write_bytes(b"")
    out = tmp_path / "out.gif"
    VideoToGifConverter().convert(src, out, **kwargs)
    return out


def test_a_short_clip_runs_the_probe_both_passes_and_the_count(tmp_path, monkeypatch):
    media = _FakeMedia(monkeypatch, VideoProbe(1920, 1080, 12.0))
    out = _convert(tmp_path, max_output_bytes=1000)
    assert media.steps == ["probe", "ffmpeg", "ffmpeg", "count"]
    assert out.exists()
    assert not list(tmp_path.glob("*_palette.png")), "the palette file was left behind"


def test_the_steps_share_one_time_budget(tmp_path, monkeypatch):
    media = _FakeMedia(monkeypatch, VideoProbe(640, 360, 5.0))
    _convert(tmp_path)
    assert media.timeouts[0] <= GIF_TIME_BUDGET_SECONDS
    assert media.timeouts == sorted(media.timeouts, reverse=True)


def test_the_budget_is_never_above_the_media_timeout(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "media_subprocess_timeout_seconds", 0)
    media = _FakeMedia(monkeypatch, VideoProbe(640, 360, 5.0))
    with pytest.raises(VideoTooComplexError):
        _convert(tmp_path)
    assert media.steps == []  # no time left, not even for the probe


def test_too_little_time_left_for_pass_two_is_too_complex(tmp_path, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(video_mod, "time", SimpleNamespace(monotonic=lambda: now[0]))
    media = _FakeMedia(monkeypatch, VideoProbe(3840, 2160, 25.0))
    fake_run = video_mod.run_ffmpeg

    def slow_pass(stream, *, timeout):
        fake_run(stream, timeout=timeout)
        now[0] += 50  # pass 1 used 50 of the 85 s: pass 2 can't finish in the 35 left

    monkeypatch.setattr(video_mod, "run_ffmpeg", slow_pass)
    with pytest.raises(VideoTooComplexError):
        _convert(tmp_path)
    assert media.steps == ["probe", "ffmpeg"]


def test_quality_does_not_change_what_ffmpeg_runs(tmp_path, monkeypatch):
    media = _FakeMedia(monkeypatch, VideoProbe(640, 360, 5.0))
    for quality in (1, 100):
        _convert(tmp_path, quality=quality)
    assert len(media.commands) == 4
    assert media.commands[:2] == media.commands[2:]


def test_a_video_over_the_limit_is_refused_before_any_pass(tmp_path, monkeypatch):
    media = _FakeMedia(monkeypatch, VideoProbe(640, 360, GIF_MAX_SECONDS + 1.0))
    with pytest.raises(VideoTooLongError) as exc:
        _convert(tmp_path)
    assert exc.value.error_code == "video_too_long"
    assert media.steps == ["probe"]


def test_a_phone_clip_of_a_little_over_30_seconds_still_converts(tmp_path, monkeypatch):
    media = _FakeMedia(monkeypatch, VideoProbe(1080, 1920, GIF_MAX_SECONDS + 0.03))
    _convert(tmp_path)
    assert media.steps == ["probe", "ffmpeg", "ffmpeg", "count"]


def test_frames_past_the_limit_refuse_a_video_of_unknown_length(tmp_path, monkeypatch):
    # The passes read GIF_MAX_SECONDS + 1 s, so a longer video yields that many frames.
    _FakeMedia(monkeypatch, VideoProbe(640, 360, None), frames=(GIF_MAX_SECONDS + 1) * GIF_FPS)
    with pytest.raises(VideoTooLongError):
        _convert(tmp_path)


def test_a_video_of_unknown_length_within_the_limit_converts(tmp_path, monkeypatch):
    _FakeMedia(monkeypatch, VideoProbe(640, 360, None), frames=GIF_MAX_SECONDS * GIF_FPS)
    assert _convert(tmp_path).exists()


def test_more_pixels_than_4k_is_too_complex(tmp_path, monkeypatch):
    media = _FakeMedia(monkeypatch, VideoProbe(7680, 4320, 5.0))
    with pytest.raises(VideoTooComplexError) as exc:
        _convert(tmp_path)
    assert exc.value.error_code == "video_too_complex"
    assert media.steps == ["probe"]


def test_a_file_without_a_video_picture_is_plain_invalid_input(tmp_path, monkeypatch):
    _FakeMedia(monkeypatch, None)
    with pytest.raises(InvalidInputError) as exc:
        _convert(tmp_path)
    assert not hasattr(exc.value, "error_code")
    assert "no video picture" in str(exc.value)


def test_a_gif_over_the_cap_is_output_too_large(tmp_path, monkeypatch):
    media = _FakeMedia(monkeypatch, VideoProbe(640, 360, 5.0), gif_bytes=2000)
    with pytest.raises(OutputTooLargeError):
        _convert(tmp_path, max_output_bytes=1000)
    assert "count" not in media.steps
    assert not list(tmp_path.glob("*_palette.png")), "the palette file was left behind"


def test_a_timeout_is_too_complex(tmp_path, monkeypatch):
    _FakeMedia(monkeypatch, VideoProbe(640, 360, 5.0), run_error=FFmpegTimeoutError("timed out"))
    with pytest.raises(VideoTooComplexError):
        _convert(tmp_path)


def test_the_messages_name_the_limit():
    assert f"longer than {GIF_MAX_SECONDS} seconds" in VideoTooLongError.message
    assert f"{GIF_MAX_SECONDS} seconds or less" in VideoTooLongError.message


# ── ffprobe ──────────────────────────────────────────────────────────────────


def _fake_ffprobe(monkeypatch, payload: dict, *, returncode=0, stderr=b"") -> list[list[str]]:
    calls: list[list[str]] = []

    class _Result:
        def __init__(self):
            self.returncode = returncode
            self.stdout = json.dumps(payload).encode()
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        calls.append(cmd[cmd.index("ffprobe") :])  # on Linux after _limited_exec.py's limits
        return _Result()

    monkeypatch.setattr(ffmpeg_mod.shutil, "which", lambda _: "ffprobe")
    monkeypatch.setattr(ffmpeg_mod.subprocess, "run", fake_run)
    return calls


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"streams": [{"width": 1920, "height": 1080, "duration": "12.5"}], "format": {}},
            VideoProbe(1920, 1080, 12.5),
        ),
        # Matroska and WebM: no stream duration, the container's instead.
        (
            {"streams": [{"width": 640, "height": 360}], "format": {"duration": "8.0"}},
            VideoProbe(640, 360, 8.0),
        ),
        # A WebM recorded in the browser says nothing about its length.
        (
            {"streams": [{"width": 640, "height": 360, "duration": "N/A"}], "format": {}},
            VideoProbe(640, 360, None),
        ),
        ({"streams": [], "format": {"duration": "3.0"}}, None),  # sound only
        ({"streams": [{"height": 360}], "format": {}}, None),
    ],
)
def test_the_probe_reads_size_and_duration(tmp_path, monkeypatch, payload, expected):
    calls = _fake_ffprobe(monkeypatch, payload)
    assert probe_video(tmp_path / "in.mp4", timeout=5) == expected
    cmd = calls[0]
    assert cmd[:7] == [
        "ffprobe",
        "-v",
        "error",
        "-format_whitelist",
        INPUT_DEMUXERS,
        "-protocol_whitelist",
        "file",
    ]
    assert cmd[cmd.index("-codec_whitelist") + 1] == INPUT_DECODERS  # as media_input
    assert cmd[cmd.index("-select_streams") + 1] == "V:0"
    # Numeric fields only: the probe never prints the upload's tags.
    assert "tags" not in cmd[cmd.index("-show_entries") + 1]
    assert "-show_streams" not in cmd and "-show_format" not in cmd


def test_the_probe_refuses_a_container_ffmpeg_would_refuse(tmp_path, monkeypatch):
    _fake_ffprobe(monkeypatch, {}, returncode=1, stderr=b"Format au not on whitelist 'mp3,wav'")
    with pytest.raises(InvalidInputError, match="not in one of the audio or video formats"):
        probe_video(tmp_path / "in.mp4", timeout=5)


def test_a_failing_probe_is_an_ffmpeg_error(tmp_path, monkeypatch):
    _fake_ffprobe(monkeypatch, {}, returncode=1, stderr=b"moov atom not found")
    with pytest.raises(FFmpegError, match="ffprobe exit 1"):
        probe_video(tmp_path / "in.mp4", timeout=5)


def _timing_out(monkeypatch, program: str) -> None:
    monkeypatch.setattr(ffmpeg_mod.shutil, "which", lambda _: program)

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(ffmpeg_mod.subprocess, "run", fake_run)


def test_timeouts_are_ffmpeg_timeout_errors(tmp_path, monkeypatch):
    _timing_out(monkeypatch, "ffprobe")
    with pytest.raises(FFmpegTimeoutError):
        probe_video(tmp_path / "in.mp4", timeout=1)
    _timing_out(monkeypatch, "ffmpeg")
    with pytest.raises(FFmpegTimeoutError, match="takes longer to convert"):
        run_ffmpeg(ffmpeg.input("in.mp4").output("out.gif"), timeout=1)
    # Outside the GIF converter, which answers it itself, the routes answer
    # a run out of time with a 400 that names the next step.
    assert issubclass(FFmpegTimeoutError, InvalidInputError)


def test_the_frame_count_reads_the_gif_as_a_gif_only(tmp_path, monkeypatch):
    calls = _fake_ffprobe(monkeypatch, {"streams": [{"nb_read_packets": "300"}]})
    assert count_gif_frames(tmp_path / "o.gif", timeout=5) == 300
    assert calls[0][3:5] == ["-format_whitelist", "gif"]
    assert "-count_packets" in calls[0]


def test_a_missing_frame_count_is_an_error(tmp_path, monkeypatch):
    _fake_ffprobe(monkeypatch, {"streams": []})
    with pytest.raises(FFmpegError):
        count_gif_frames(tmp_path / "o.gif", timeout=5)


# ── the routes ───────────────────────────────────────────────────────────────


def _raising(error: Exception):
    def convert(self, input_path, output_path, **kwargs):
        raise error

    return convert


@pytest.mark.parametrize(
    ("error", "code"),
    [(VideoTooLongError(), "video_too_long"), (VideoTooComplexError(), "video_too_complex")],
)
def test_the_convert_route_sends_the_gif_codes(client, monkeypatch, error, code):
    monkeypatch.setattr(VideoToGifConverter, "convert", _raising(error))
    res = client.post("/api/v1/convert", files=_MP4_UPLOAD, data={"target_format": "gif"})
    assert res.status_code == 400, res.text
    assert res.headers["X-FileMorph-Error-Code"] == code
    assert res.json()["detail"] == error.message


def test_a_gif_over_the_cap_names_a_shorter_clip(client, monkeypatch):
    monkeypatch.setattr(VideoToGifConverter, "convert", _raising(OutputTooLargeError()))
    res = client.post("/api/v1/convert", files=_MP4_UPLOAD, data={"target_format": "gif"})
    assert res.status_code == 413, res.text
    assert res.headers["X-FileMorph-Error-Code"] == "output_cap_exceeded"
    assert "Use a shorter clip for a smaller GIF" in res.json()["detail"]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (VideoTooLongError(), VideoTooLongError.message),
        (OutputTooLargeError(), "Use a shorter clip for a smaller GIF"),
    ],
)
def test_a_batch_names_the_gif_problem_of_the_file(client, monkeypatch, error, expected):
    monkeypatch.setattr(VideoToGifConverter, "convert", _raising(error))
    files = [("files", _MP4_UPLOAD["file"])]
    res = client.post("/api/v1/convert/batch", files=files, data={"target_formats": ["gif"]})
    assert res.status_code == 422, res.text
    assert expected in res.json()["files"][0]["error_message"]


# ── the web UI ───────────────────────────────────────────────────────────────


def _js_strings(client, locale: str) -> dict[str, str]:
    html = client.get(f"/{locale}/").text
    blob = re.search(
        r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', html, re.S
    )
    assert blob, "FM_I18N block missing"
    return json.loads(blob.group(1))


@pytest.mark.parametrize(
    ("locale", "seconds", "pixels"),
    [
        ("en", f"up to {GIF_MAX_SECONDS} seconds", f"{GIF_MAX_SIDE} pixels"),
        ("de", f"bis {GIF_MAX_SECONDS} Sekunden", f"{GIF_MAX_SIDE} Pixel"),
    ],
)
def test_the_gif_note_names_the_limits(client, locale, seconds, pixels):
    html = client.get(f"/{locale}/").text
    note = re.search(r'<p id="gif-notice"[^>]*>(.*?)</p>', html, re.S)
    assert note, "the GIF note is missing from the convert tool"
    text = " ".join(note.group(1).split())
    assert seconds in text and pixels in text, text


@pytest.mark.parametrize("locale", ["en", "de"])
def test_the_ui_error_texts(client, locale):
    strings = _js_strings(client, locale)
    assert str(GIF_MAX_SECONDS) in strings["errorVideoTooLong"]
    if locale == "en":  # the server's own messages
        assert strings["errorVideoTooLong"] == VideoTooLongError.message
        assert strings["errorVideoTooComplex"] == VideoTooComplexError.message
    else:  # translated, not the English fallback
        assert strings["errorVideoTooLong"] != VideoTooLongError.message
        assert strings["errorVideoTooComplex"] != VideoTooComplexError.message


def test_llms_txt_names_gif_and_its_limit(client):
    body = client.get("/llms.txt").text
    assert f"(up to {GIF_MAX_SECONDS} seconds) into animated GIFs" in body


def test_app_js_knows_the_video_formats_and_the_gif_codes():
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
    match = re.search(r"const VIDEO_TYPES = \[([^\]]*)\];", js)
    assert match, "VIDEO_TYPES not found in app.js"
    assert sorted(re.findall(r"'([a-z0-9]+)'", match.group(1))) == sorted(_VIDEO_FORMATS)
    for code, key in (
        ("video_too_long", "errorVideoTooLong"),
        ("video_too_complex", "errorVideoTooComplex"),
    ):
        assert f"errCode === '{code}'" in js and f"i18n.{key}" in js, code
    assert "i18n.errorOutputCapGif" in js
    # The quality slider hides for a GIF target.
    assert "if (target === 'gif') return false;" in js


# ---------------------------------------------------------------------------
# Functional layer — needs ffmpeg/ffprobe on PATH
# ---------------------------------------------------------------------------


def _make_clip(path: Path, *, seconds: float = 1, size: str = "320x180", rate: int = 25, extra=()):
    subprocess.run(
        [
            FFMPEG, "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=duration={seconds}:size={size}:rate={rate}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            *extra, str(path),
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )  # fmt: skip
    return path


def _gif_info(path: Path) -> tuple[int, int, int]:
    """Width, height and number of frames of a GIF."""
    out = subprocess.run(
        [
            FFPROBE, "-v", "error", "-count_packets", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,nb_read_packets", "-of", "json", str(path),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )  # fmt: skip
    stream = json.loads(out.stdout)["streams"][0]
    return stream["width"], stream["height"], int(stream["nb_read_packets"])


@pytest.fixture(scope="module")
def clip_mp4(tmp_path_factory):
    if FFMPEG is None:
        pytest.skip("ffmpeg not on PATH")
    return _make_clip(tmp_path_factory.mktemp("gif") / "clip.mp4")


@requires_ffmpeg
@pytest.mark.parametrize("fmt", _VIDEO_FORMATS)
def test_every_video_format_becomes_a_looping_gif(clip_mp4, tmp_path, fmt):
    source = clip_mp4
    if fmt != "mp4":
        source = tmp_path / f"in.{fmt}"
        get_converter("mp4", fmt).convert(clip_mp4, source, quality=70)
    out = tmp_path / "out.gif"
    get_converter(fmt, "gif").convert(source, out, max_output_bytes=10**7)
    data = out.read_bytes()
    assert data[:6] == b"GIF89a"
    assert b"NETSCAPE2.0" in data  # the loop extension
    width, height, frames = _gif_info(out)
    assert (width, height) == (320, 180)  # inside the box: not upscaled
    assert 9 <= frames <= 11  # 1 s at 10 frames a second


@requires_ffmpeg
def test_the_probe_reads_a_real_clip(clip_mp4):
    video = probe_video(clip_mp4, timeout=30)
    assert (video.width, video.height) == (320, 180)
    assert video.duration == pytest.approx(1.0, abs=0.1)


@requires_ffmpeg
@pytest.mark.parametrize(("size", "expected"), [("1280x720", (480, 270)), ("720x1280", (270, 480))])
def test_frames_fit_the_box(tmp_path, size, expected):
    source = _make_clip(tmp_path / "in.mp4", seconds=0.5, size=size)
    out = tmp_path / "out.gif"
    VideoToGifConverter().convert(source, out)
    assert _gif_info(out)[:2] == expected


@requires_ffmpeg
def test_a_phone_clip_stays_upright(clip_mp4, tmp_path):
    """Phones store a portrait clip landscape plus a rotation; ffmpeg turns it
    before the filters see it."""
    rotated = tmp_path / "rotated.mp4"
    made = subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-display_rotation:v:0", "90", "-i", str(clip_mp4),
         "-c", "copy", str(rotated)],
        capture_output=True,
        timeout=60,
    )  # fmt: skip
    if made.returncode != 0:
        pytest.skip("this ffmpeg can't write a rotation (-display_rotation)")
    out = tmp_path / "out.gif"
    VideoToGifConverter().convert(rotated, out)
    assert _gif_info(out)[:2] == (180, 320)


@requires_ffmpeg
def test_the_gif_carries_no_metadata_from_the_video(tmp_path):
    source = _make_clip(
        tmp_path / "in.mov",
        extra=(
            "-metadata", "title=FMMARKER-TITLE",
            "-metadata", "make=FMMARKER-MAKE",
            "-metadata", "location=+52.5163+013.3777/",
        ),
    )  # fmt: skip
    assert b"FMMARKER-TITLE" in source.read_bytes(), "the test clip lacks its markers"
    out = tmp_path / "out.gif"
    VideoToGifConverter().convert(source, out)
    data = out.read_bytes()
    assert b"FMMARKER" not in data
    assert b"52.5163" not in data


@requires_ffmpeg
def test_a_clip_with_an_alpha_channel_becomes_a_gif(tmp_path):
    source = tmp_path / "in.mov"  # PNG frames with half-transparent pixels
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=duration=0.5:size=128x72:rate=10,format=rgba,colorchannelmixer=aa=0.5",
         "-c:v", "png", str(source)],
        capture_output=True,
        check=True,
        timeout=60,
    )  # fmt: skip
    out = tmp_path / "out.gif"
    VideoToGifConverter().convert(source, out)
    assert _gif_info(out)[:2] == (128, 72)


@requires_ffmpeg
def test_a_clip_over_the_limit_is_refused(tmp_path):
    source = _make_clip(tmp_path / "in.mp4", seconds=GIF_MAX_SECONDS + 2, size="64x36", rate=10)
    out = tmp_path / "out.gif"
    with pytest.raises(VideoTooLongError):
        VideoToGifConverter().convert(source, out)
    assert not out.exists()  # refused before any pass


@requires_ffmpeg
def test_frames_past_the_limit_refuse_a_clip_of_unknown_length(tmp_path, monkeypatch):
    source = _make_clip(tmp_path / "in.mp4", seconds=GIF_MAX_SECONDS + 5, size="64x36", rate=10)
    # As for a WebM recorded in the browser: the container doesn't say how long it is.
    monkeypatch.setattr(video_mod, "probe_video", lambda path, *, timeout: VideoProbe(64, 36, None))
    with pytest.raises(VideoTooLongError):
        VideoToGifConverter().convert(source, tmp_path / "out.gif")


@requires_ffmpeg
def test_a_gif_over_the_cap_is_refused(clip_mp4, tmp_path):
    with pytest.raises(OutputTooLargeError):
        VideoToGifConverter().convert(clip_mp4, tmp_path / "out.gif", max_output_bytes=2000)
    assert not list(tmp_path.glob("*_palette.png"))


@requires_ffmpeg
def test_a_file_with_only_sound_has_no_picture(tmp_path):
    source = tmp_path / "in.mp4"
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "aac", str(source)],
        capture_output=True,
        check=True,
        timeout=60,
    )  # fmt: skip
    with pytest.raises(InvalidInputError, match="no video picture"):
        VideoToGifConverter().convert(source, tmp_path / "out.gif")


@requires_ffmpeg
def test_an_upload_in_another_format_is_refused_by_the_probe(tmp_path):
    source = tmp_path / "in.mp4"  # Sun AU audio under an .mp4 name
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
         "-f", "au", str(source)],
        capture_output=True,
        check=True,
        timeout=60,
    )  # fmt: skip
    with pytest.raises(InvalidInputError, match="not in one of the audio or video formats"):
        VideoToGifConverter().convert(source, tmp_path / "out.gif")
