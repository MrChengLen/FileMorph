# SPDX-License-Identifier: AGPL-3.0-or-later
"""The limits of an ffmpeg run (``app/converters/_ffmpeg.py``,
``app/converters/_limited_exec.py``).

The ffmpeg runs of a request share its time limit. On Linux ffmpeg starts
through ``_limited_exec.py``, which caps memory, CPU time and file size
first, and ffmpeg gets the environment without application secrets. Each
way a run stops comes back as an error whose message names the next step.
The tests that start real processes need Linux, those that convert need
ffmpeg on PATH; CI has both.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import ffmpeg
import pytest

from app.api.routes.auth import get_optional_user
from app.converters import _ffmpeg
from app.converters._limited_exec import PARENT_PID_ENV
from app.converters.base import InvalidInputError, OutputTooLargeError
from app.converters.registry import get_converter
from app.core.config import settings
from app.main import app
from tests.test_media_smoke import FFMPEG, _generate, _probe, requires_ffmpeg

linux_only = pytest.mark.skipif(sys.platform != "linux", reason="the limits apply on Linux")
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="signals end processes on POSIX")


class _Clock:
    """Stands in for the ``time`` module in ``_ffmpeg``."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(_ffmpeg, "time", fake)
    monkeypatch.setattr(settings, "media_subprocess_timeout_seconds", 85)
    return fake


@pytest.fixture
def ffmpeg_on_path(monkeypatch):
    monkeypatch.setattr(_ffmpeg.shutil, "which", lambda name: f"/usr/bin/{name}")


def _stream():
    return ffmpeg.input("in.mp4").output("out.mp4")


def _fake_run(returncode: int = 0, stderr: bytes = b"", seen: dict | None = None):
    def run(cmd, **kwargs):
        if seen is not None:
            seen.update(kwargs, cmd=cmd)
        return subprocess.CompletedProcess(cmd, returncode, b"", stderr)

    return run


# ── The command, the environment and the time limit ──────────────────────────


@pytest.mark.parametrize("cap", [None, 12345])
def test_on_linux_ffmpeg_starts_with_its_limits_and_without_secrets(
    monkeypatch, ffmpeg_on_path, clock, cap
):
    monkeypatch.setattr(_ffmpeg.sys, "platform", "linux")
    monkeypatch.setattr(_ffmpeg.os, "cpu_count", lambda: 4)
    monkeypatch.setenv("JWT_SECRET", "not-for-ffmpeg")
    seen: dict = {}
    monkeypatch.setattr(_ffmpeg.subprocess, "run", _fake_run(seen=seen))
    _ffmpeg.run_ffmpeg(_stream(), max_output_bytes=cap)
    cmd = seen["cmd"]
    file_bytes = _ffmpeg._FILE_LIMIT_BYTES if cap is None else cap
    assert cmd[:8] == [
        *(sys.executable, "-I", "-S", str(_ffmpeg._LIMITED_EXEC)),
        # memory, the time limit's CPU time for each of the 4 CPUs, file size
        *(str(_ffmpeg._MEMORY_LIMIT_BYTES), str(85 * 4 + 5), str(file_bytes)),
        "/usr/bin/ffmpeg",
    ]
    assert cmd[cmd.index("-filter_threads") + 1] == str(_ffmpeg.THREADS)
    assert cmd[cmd.index("-filter_complex_threads") + 1] == str(_ffmpeg.THREADS)
    assert cmd[cmd.index("-loglevel") + 1] == "error"  # no echo of the upload's tags
    assert "JWT_SECRET" not in seen["env"]
    assert seen["env"]["MALLOC_ARENA_MAX"] == "2"
    assert seen["env"][PARENT_PID_ENV] == str(os.getpid())
    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["timeout"] == 85


def test_elsewhere_ffmpeg_starts_directly_and_without_secrets(monkeypatch, ffmpeg_on_path, clock):
    monkeypatch.setattr(_ffmpeg.sys, "platform", "win32")
    monkeypatch.setenv("JWT_SECRET", "not-for-ffmpeg")
    seen: dict = {}
    monkeypatch.setattr(_ffmpeg.subprocess, "run", _fake_run(seen=seen))
    _ffmpeg.run_ffmpeg(_stream())
    assert seen["cmd"][0] == "/usr/bin/ffmpeg"
    assert "JWT_SECRET" not in seen["env"]


def test_the_runs_of_a_request_share_its_time_limit(monkeypatch, ffmpeg_on_path, clock):
    seen: dict = {}
    monkeypatch.setattr(_ffmpeg.subprocess, "run", _fake_run(seen=seen))
    with _ffmpeg.media_time_limit():
        clock.now += 30
        _ffmpeg.run_ffmpeg(_stream())
        assert seen["timeout"] == 55
        clock.now += 55
        seen.clear()
        with pytest.raises(InvalidInputError, match="ran out before this file was done"):
            _ffmpeg.run_ffmpeg(_stream())
        assert not seen  # ffmpeg didn't start
    _ffmpeg.run_ffmpeg(_stream())  # outside a request: the whole limit
    assert seen["timeout"] == 85


@pytest.mark.parametrize(
    ("used", "message"),
    [
        # It had (nearly) all of the request's time: too long on its own.
        (0, "takes longer to convert than the 85 seconds a request may take here"),
        # The files before it took a good part: on its own it may convert.
        (30, "ran out before this file was done. Send it again on its own."),
    ],
)
def test_a_run_out_of_time_names_the_next_step(monkeypatch, ffmpeg_on_path, clock, used, message):
    def time_out(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(_ffmpeg.subprocess, "run", time_out)
    with _ffmpeg.media_time_limit():
        clock.now += used
        with pytest.raises(InvalidInputError, match=message):
            _ffmpeg.run_ffmpeg(_stream())


# A whitelist in ffmpeg's message pushes it out of the last 500 characters.
_LONG_REFUSAL = (
    f"[avi @ 0x1] Codec (cinepak) not on whitelist '{_ffmpeg.INPUT_DECODERS}'\n".encode()
    + b"Error opening input file in.avi.\n" * 20
)


# The status of a process ended by a signal is minus the signal's number:
# 9 SIGKILL, 11 SIGSEGV and 25 SIGXFSZ on Linux and macOS.
@pytest.mark.parametrize(
    ("returncode", "stderr", "error", "message"),
    [
        (1, _LONG_REFUSAL, InvalidInputError, "Save it as MP4 (video) or MP3 (audio)"),
        (
            1,
            b"[h264 @ 0x1] Picture size 8192x4320 exceeds specified max pixel count 8847360",
            InvalidInputError,
            "larger than 4K (more than 4096 × 2160 pixels per frame)",
        ),
        # libdav1d (AV1) checks the frame size itself.
        (1, b"[libdav1d @ 0x1] Frame size 7680x4320 exceeds limit 8912896", InvalidInputError, "larger than 4K"),
        (1, b"Error while decoding stream #0:0: Cannot allocate memory", InvalidInputError, "too large or complex"),
        (1, b"x264 [error]: malloc of size 12441600 failed", InvalidInputError, "too large or complex"),
        pytest.param(-9, b"", InvalidInputError, "too large or complex", marks=posix_only),
        pytest.param(-25, b"", OutputTooLargeError, "", marks=posix_only),
        # The signal decides: ffmpeg logs the pixel limit for cover art it only probes.
        pytest.param(
            -25,
            b"[mjpeg @ 0x1] Picture size 3008x3000 exceeds specified max pixel count 8912896",
            OutputTooLargeError,
            "",
            marks=posix_only,
        ),
        pytest.param(-11, b"", _ffmpeg.FFmpegError, "exit -11", marks=posix_only),
        (1, b"boom", _ffmpeg.FFmpegError, "exit 1"),
    ],
)  # fmt: skip
def test_each_way_ffmpeg_stops_comes_back_as_its_error(
    monkeypatch, ffmpeg_on_path, clock, returncode, stderr, error, message
):
    monkeypatch.setattr(_ffmpeg.subprocess, "run", _fake_run(returncode, stderr))
    with pytest.raises(error) as excinfo:
        _ffmpeg.run_ffmpeg(_stream())
    assert type(excinfo.value) is error
    assert message in str(excinfo.value)


# ── The routes ───────────────────────────────────────────────────────────────


@pytest.fixture
def free_user():
    user = MagicMock()
    user.tier.value = "free"  # sends batches of up to 10 files
    app.dependency_overrides[get_optional_user] = lambda: user
    yield
    app.dependency_overrides.pop(get_optional_user, None)


@pytest.mark.parametrize(
    ("route", "names", "data"),
    [
        ("/api/v1/convert/batch", ("a.wav", "b.wav"), {"target_formats": ["mp3", "mp3"]}),
        ("/api/v1/compress/batch", ("a.mp4", "b.mp4"), {}),
    ],
)
def test_the_files_of_a_batch_share_its_time_limit(
    client, auth_headers, monkeypatch, ffmpeg_on_path, clock, free_user, route, names, data
):
    started = []

    def run_out_of_time(cmd, **kwargs):
        started.append(kwargs["timeout"])
        clock.now += kwargs["timeout"]
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(_ffmpeg.subprocess, "run", run_out_of_time)
    files = [("files", (name, b"\x00" * 64, "application/octet-stream")) for name in names]
    res = client.post(route, headers=auth_headers, files=files, data=data)
    assert res.status_code == 422, res.text  # no file converted
    first, second = (f["error_message"] for f in res.json()["files"])
    assert "takes longer to convert than the 85 seconds" in first
    assert "ran out before this file was done. Send it again on its own." in second
    assert started == [85]  # the second file never started


@pytest.mark.parametrize(
    ("route", "name", "data"),
    [
        ("/api/v1/convert", "a.wav", {"target_format": "mp3"}),
        ("/api/v1/compress", "a.mp4", {}),
    ],
)
def test_a_file_out_of_time_gets_a_400_with_the_next_step(
    client, auth_headers, monkeypatch, ffmpeg_on_path, clock, route, name, data
):
    def time_out(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(_ffmpeg.subprocess, "run", time_out)
    files = {"file": (name, b"\x00" * 64, "application/octet-stream")}
    res = client.post(route, headers=auth_headers, files=files, data=data)
    assert res.status_code == 400
    assert res.headers["X-FileMorph-Error-Code"] == "invalid_input"
    assert "Convert a shorter part of it" in res.json()["detail"]


@posix_only
def test_a_compressed_video_past_the_output_cap_is_a_413(
    client, auth_headers, monkeypatch, ffmpeg_on_path, clock, free_user
):
    seen: dict = {}
    monkeypatch.setattr(_ffmpeg.subprocess, "run", _fake_run(-25, seen=seen))  # SIGXFSZ
    monkeypatch.setattr(_ffmpeg.sys, "platform", "linux")
    upload = ("a.mp4", b"\x00" * 64, "video/mp4")
    res = client.post("/api/v1/compress", headers=auth_headers, files={"file": upload})
    assert res.status_code == 413
    assert res.headers["X-FileMorph-Error-Code"] == "output_cap_exceeded"
    assert "Output too large (over the 300 MB cap). Lower the quality." in res.json()["detail"]
    assert seen["cmd"][6] == str(300 * 1024 * 1024)  # the free plan's output cap
    files = [("files", ("a.mp4", b"\x00" * 64, "video/mp4"))] * 2
    res = client.post("/api/v1/compress/batch", headers=auth_headers, files=files)
    assert res.status_code == 422
    assert "Output too large (over the 300 MB cap)" in res.json()["files"][0]["error_message"]


def test_a_gif_after_the_time_of_a_batch_is_sent_again_on_its_own(
    client, auth_headers, monkeypatch, ffmpeg_on_path, clock, free_user
):
    from app.converters import video as video_mod

    def probe(path, *, timeout):
        clock.now += 30  # the first file takes 30 of the 85 seconds
        return _ffmpeg.VideoProbe(640, 360, 5.0)

    def run_out_of_time(stream, **kwargs):
        raise _ffmpeg.FFmpegTimeoutError("stopped")

    monkeypatch.setattr(video_mod, "probe_video", probe)
    monkeypatch.setattr(video_mod, "run_ffmpeg", run_out_of_time)
    files = [("files", (name, b"\x00" * 64, "video/mp4")) for name in ("a.mp4", "b.mp4")]
    data = {"target_formats": ["gif", "gif"]}
    res = client.post("/api/v1/convert/batch", headers=auth_headers, files=files, data=data)
    assert res.status_code == 422, res.text
    first, second = (f["error_message"] for f in res.json()["files"])
    assert "too large to turn into a GIF in time" in first  # it had the request's time
    assert "Send it again on its own." in second


# ── _limited_exec.py, started for real (Linux) ───────────────────────────────

_MEMORY, _CPU, _FILE = 2**30, 95, 2**20


def _limited(*program: str, **kwargs) -> subprocess.CompletedProcess:
    limits = (str(_MEMORY), str(_CPU), str(_FILE))
    return subprocess.run(
        [sys.executable, "-I", "-S", str(_ffmpeg._LIMITED_EXEC), *limits, *program],
        capture_output=True,
        encoding="utf-8",
        timeout=30,
        **kwargs,
    )


def _limit(report: str, name: str) -> tuple[str, str]:
    """Soft and hard value of ``name`` in a ``/proc/<pid>/limits`` report."""
    match = re.search(rf"^{name}\s+(\S+)\s+(\S+)", report, re.M)
    assert match, f"{name} not in the report"
    return match.group(1), match.group(2)


@linux_only
def test_the_program_runs_with_the_limits():
    report = _limited(
        "/bin/cat", "/proc/self/limits", "/proc/self/status", "/proc/self/oom_score_adj", check=True
    ).stdout
    # Soft and hard limit alike, so the program can't raise them again.
    assert _limit(report, "Max address space") == (str(_MEMORY), str(_MEMORY))
    assert _limit(report, "Max cpu time") == (str(_CPU), str(_CPU))
    assert _limit(report, "Max file size") == (str(_FILE), str(_FILE))
    assert _limit(report, "Max core file size") == ("0", "0")
    assert re.search(r"^NoNewPrivs:\s+1$", report, re.M)
    # SIGPIPE and SIGXFSZ have their default action again: a write past the
    # file size limit ends the program.
    ignored = int(re.search(r"^SigIgn:\s+([0-9a-f]+)$", report, re.M).group(1), 16)
    assert not ignored & (1 << (signal.SIGPIPE - 1) | 1 << (signal.SIGXFSZ - 1))
    assert report.split()[-1] == "1000"  # first in line for the OOM killer


@linux_only
def test_a_lower_hard_limit_of_the_host_stays():
    run = (
        "import os, resource, sys; resource.setrlimit(resource.RLIMIT_CPU, (80, 80)); "
        f"os.execv(sys.executable, [sys.executable, '-I', '-S', {str(_ffmpeg._LIMITED_EXEC)!r}, "
        f"'{_MEMORY}', '{_CPU}', '{_FILE}', '/bin/cat', '/proc/self/limits'])"
    )
    res = subprocess.run(
        [sys.executable, "-c", run], capture_output=True, encoding="utf-8", timeout=30, check=True
    )
    assert _limit(res.stdout, "Max cpu time") == ("80", "80")


@linux_only
def test_the_program_may_start_threads():
    run = "import threading; t = threading.Thread(target=print, args=('ran',)); t.start(); t.join()"
    assert _limited(sys.executable, "-I", "-S", "-c", run, check=True).stdout.strip() == "ran"


def _state(proc: Path) -> str | None:
    """The process state letter (``Z`` for a zombie), None once it is gone."""
    try:
        return (proc / "stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return None


@linux_only
def test_the_program_ends_with_the_process_that_started_it():
    start = (
        "import subprocess, sys; "
        f"p = subprocess.Popen([sys.executable, '-I', '-S', {str(_ffmpeg._LIMITED_EXEC)!r}, "
        f"'{_MEMORY}', '{_CPU}', '{_FILE}', '/bin/sleep', '60']); "
        "print(p.pid, flush=True); sys.stdin.read()"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", start],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        encoding="utf-8",
    )
    try:
        proc = Path(f"/proc/{int(parent.stdout.readline())}")
        # Once sleep runs, the limits and the parent-death signal are set.
        deadline = time.monotonic() + 10
        while (proc / "comm").read_text(encoding="utf-8").strip() != "sleep":
            assert time.monotonic() < deadline, "the program did not start"
            time.sleep(0.02)
        parent.kill()
        parent.wait(timeout=10)
        deadline = time.monotonic() + 10
        while _state(proc) not in (None, "Z"):
            assert time.monotonic() < deadline, "the program outlived its parent"
            time.sleep(0.02)
    finally:
        parent.kill()


@linux_only
def test_the_program_does_not_start_when_its_parent_has_changed():
    res = _limited("/bin/echo", "started", env={**os.environ, PARENT_PID_ENV: "1"})
    assert (res.returncode, res.stdout) == (1, "")


# ── With a real ffmpeg: decoders, frame size, output cap ─────────────────────


def _ffmpeg_lists(what: str) -> str:
    return subprocess.run(
        [FFMPEG, "-hide_banner", f"-{what}"],
        capture_output=True,
        encoding="utf-8",
        check=True,
        timeout=30,
    ).stdout


@requires_ffmpeg
def test_every_listed_decoder_is_in_this_ffmpeg():
    names = set(re.findall(r"^ [VAS][A-Z.]{5} (\S+)", _ffmpeg_lists("decoders"), re.M))
    missing = set(_ffmpeg.INPUT_DECODERS.split(",")) - names
    assert not missing, sorted(missing)


@requires_ffmpeg
def test_a_listed_codec_is_read_by_a_listed_decoder():
    # ffmpeg opens a codec's default decoder: the first one `ffmpeg -codecs`
    # names, or the codec's own name when it names none.
    listed = set(_ffmpeg.INPUT_DECODERS.split(","))
    wrong = []
    for line in re.findall(r"^ D[A-Z.]{5} \S+.*$", _ffmpeg_lists("codecs"), re.M):
        codec = line.split()[1]
        decoders = re.search(r"\(decoders: ([^)]*)\)", line)
        names = decoders.group(1).split() if decoders else [codec]
        if listed & set(names) and names[0] not in listed:
            wrong.append(f"{codec}: {names[0]}")
    assert not wrong, wrong


@requires_ffmpeg
def test_a_codec_off_the_list_is_refused_with_the_next_step(tmp_path):
    source = tmp_path / "in.avi"
    _generate(
        "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=5:duration=0.4",
        "-c:v", "huffyuv",
        str(source),
    )  # fmt: skip
    with pytest.raises(InvalidInputError, match="Save it as MP4"):
        get_converter("avi", "mp4").convert(source, tmp_path / "out.mp4", quality=70)


@requires_ffmpeg
def test_a_4k_video_converts(tmp_path):
    # More frames than x264 looks ahead (40), so the encoder takes the most
    # memory it takes for this size, within the address-space limit on Linux.
    source = tmp_path / "in.mp4"
    _generate(
        "-f", "lavfi", "-i", f"testsrc2=size={_ffmpeg._MAX_WIDTH}x{_ffmpeg._MAX_HEIGHT}:rate=30:duration=1.6",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(source),
    )  # fmt: skip
    out = tmp_path / "out.mkv"
    get_converter("mp4", "mkv").convert(source, out, quality=85)
    fmt_name, codecs = _probe(out)
    assert "matroska" in fmt_name
    assert "h264" in codecs


@requires_ffmpeg
def test_a_video_larger_than_4k_is_refused_with_the_next_step(tmp_path):
    source = tmp_path / "in.mp4"
    _generate(
        "-f", "lavfi", "-i", f"color=c=black:size={_ffmpeg._MAX_WIDTH + 16}x{_ffmpeg._MAX_HEIGHT}:rate=5:duration=0.4",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(source),
    )  # fmt: skip
    with pytest.raises(InvalidInputError, match="larger than 4K"):
        get_converter("mp4", "mkv").convert(source, tmp_path / "out.mkv", quality=70)


@requires_ffmpeg
@pytest.mark.skipif(sys.platform != "linux", reason="the file size limit applies on Linux")
def test_ffmpeg_stops_writing_at_the_output_cap(tmp_path):
    source = tmp_path / "in.mp3"
    _generate("-f", "lavfi", "-i", "sine=frequency=440:duration=5", str(source))
    with pytest.raises(OutputTooLargeError):  # 5 s of WAV are about 440 KB
        get_converter("mp3", "wav").convert(
            source, tmp_path / "out.wav", quality=85, max_output_bytes=100_000
        )


@requires_ffmpeg
@pytest.mark.skipif(sys.platform != "linux", reason="the file size limit applies on Linux")
def test_cover_art_over_the_pixel_limit_does_not_hide_the_output_cap(tmp_path):
    # ffmpeg probes the 3000 × 3000 cover, logs that it is over MAX_PIXELS and
    # converts the sound, up to the output cap.
    source = tmp_path / "in.mp3"
    _generate(
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
        "-f", "lavfi", "-i", "color=c=red:size=3000x3000:duration=0.04",
        "-map", "0:a", "-map", "1:v", "-frames:v", "1", "-c:v", "mjpeg",
        "-disposition:v", "attached_pic", "-id3v2_version", "3",
        str(source),
    )  # fmt: skip
    with pytest.raises(OutputTooLargeError):
        get_converter("mp3", "wav").convert(
            source, tmp_path / "out.wav", quality=85, max_output_bytes=100_000
        )
    out = tmp_path / "small.wav"  # and within the cap the cover doesn't matter
    get_converter("mp3", "wav").convert(source, out, quality=85, max_output_bytes=10**7)
    assert out.stat().st_size > 400_000
