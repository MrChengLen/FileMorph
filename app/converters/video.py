# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

import ffmpeg  # ffmpeg-python

from app.converters._ffmpeg import run_ffmpeg, video_output_args
from app.converters.base import BaseConverter
from app.converters.registry import register

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
        stream = ffmpeg.input(str(input_path)).output(
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
