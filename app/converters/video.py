# SPDX-License-Identifier: AGPL-3.0-or-later
import time
from pathlib import Path

from app.converters._ffmpeg import (
    GIF_FPS,
    GIF_MAX_SECONDS,
    GIF_MAX_SOURCE_PIXELS,
    GIF_SLACK_SECONDS,
    GIF_TIME_BUDGET_SECONDS,
    FFmpegTimeoutError,
    count_gif_frames,
    gif_palette_stream,
    gif_stream,
    media_input,
    probe_video,
    run_ffmpeg,
    video_output_args,
)
from app.converters.base import (
    BaseConverter,
    InvalidInputError,
    OutputTooLargeError,
    VideoTooComplexError,
    VideoTooLongError,
)
from app.converters.registry import register
from app.core.config import settings

_VIDEO_FORMATS = ["mp4", "avi", "mov", "mkv", "webm", "flv", "wmv"]

_VIDEO_PAIRS = [(src, tgt) for src in _VIDEO_FORMATS for tgt in _VIDEO_FORMATS if src != tgt]


class _VideoConverter(BaseConverter):
    """Re-encode video into a target container using ffmpeg.

    Codecs come from the per-container matrix in
    ``app/converters/_ffmpeg.py`` — WebM only accepts VP9/Opus, AVI and
    WMV carry their legacy codecs, everything else is H.264/AAC. The
    ``quality`` kwarg (1-100, route default 85) drives the encoder's
    rate control; the invocation runs under the media subprocess
    timeout.
    """

    def __init__(self, tgt_fmt: str):
        self._tgt_fmt = tgt_fmt

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        quality = int(kwargs.get("quality", 85))
        stream = media_input(input_path).output(
            str(output_path),
            **video_output_args(self._tgt_fmt, quality, audio_bitrate="192k"),
        )
        run_ffmpeg(stream)
        return output_path


# Register all video↔video pairs
for _src, _tgt in _VIDEO_PAIRS:

    def _make(tgt: str) -> type[BaseConverter]:
        class _Converter(_VideoConverter):
            def __init__(self):
                super().__init__(tgt)

        _Converter.__name__ = f"VideoTo{tgt.upper()}Converter"
        return _Converter

    register((_src, _tgt))(_make(_tgt))


_NO_VIDEO_PICTURE = (
    "This file has no video picture, so it can't become a GIF. Choose a video file and try again."
)


class VideoToGifConverter(BaseConverter):
    """Turn a short video into an animated GIF.

    Up to ``GIF_MAX_SECONDS``: a longer video is refused, never cut short.
    Frame rate and size are fixed (``GIF_*`` in ``app/converters/_ffmpeg.py``),
    so ``quality`` doesn't apply. Two ffmpeg passes — a palette for the whole
    clip, then the frames mapped onto it — because in one pass ffmpeg would
    hold every frame in memory until the palette is known. The probe, both
    passes and the frame count share one time budget.
    """

    # The routes' tip when the GIF passes the output cap (read via getattr).
    output_cap_tip = "Use a shorter clip for a smaller GIF, or convert to MP4 or WebM"

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        max_output_bytes = kwargs.get("max_output_bytes")
        budget = min(GIF_TIME_BUDGET_SECONDS, settings.media_subprocess_timeout_seconds)
        deadline = time.monotonic() + budget
        limit = GIF_MAX_SECONDS + GIF_SLACK_SECONDS
        # One second past the limit is read: frames from beyond it prove the
        # video too long even when its duration is missing (a WebM recorded
        # in the browser) or wrong.
        seconds = GIF_MAX_SECONDS + 1
        palette_path = output_path.with_name(f"{output_path.stem}_palette.png")
        try:
            video = probe_video(input_path, timeout=_time_left(deadline))
            if video is None:
                raise InvalidInputError(_NO_VIDEO_PICTURE)
            if video.width * video.height > GIF_MAX_SOURCE_PIXELS:
                raise VideoTooComplexError()
            if video.duration is not None and video.duration > limit:
                raise VideoTooLongError()
            started = time.monotonic()
            run_ffmpeg(
                gif_palette_stream(input_path, palette_path, seconds=seconds),
                timeout=_time_left(deadline),
            )
            # Pass 2 decodes the clip again and does more per frame: with less
            # time left than pass 1 took, it would only run into the budget.
            if time.monotonic() - started > _time_left(deadline):
                raise VideoTooComplexError()
            run_ffmpeg(
                gif_stream(
                    input_path,
                    palette_path,
                    output_path,
                    seconds=seconds,
                    max_output_bytes=max_output_bytes,
                ),
                timeout=_time_left(deadline),
            )
            if max_output_bytes is not None and output_path.stat().st_size > max_output_bytes:
                raise OutputTooLargeError()
            if count_gif_frames(output_path, timeout=_time_left(deadline)) > limit * GIF_FPS:
                raise VideoTooLongError()
        except FFmpegTimeoutError as exc:
            raise VideoTooComplexError() from exc
        finally:
            palette_path.unlink(missing_ok=True)
        return output_path


def _time_left(deadline: float) -> float:
    """Seconds until ``deadline``; FFmpegTimeoutError once there are none."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise FFmpegTimeoutError("GIF time budget used up")
    return left


register(*((src, "gif") for src in _VIDEO_FORMATS))(VideoToGifConverter)
