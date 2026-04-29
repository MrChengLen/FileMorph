from pathlib import Path

import ffmpeg  # ffmpeg-python

from app.converters.base import BaseConverter
from app.converters.registry import register

_VIDEO_FORMATS = ["mp4", "avi", "mov", "mkv", "webm", "flv", "wmv"]

_VIDEO_PAIRS = [(src, tgt) for src in _VIDEO_FORMATS for tgt in _VIDEO_FORMATS if src != tgt]


class _VideoConverter(BaseConverter):
    """Re-encode video to a target container format using ffmpeg."""

    def __init__(self, tgt_fmt: str):
        self._tgt_fmt = tgt_fmt

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        (
            ffmpeg.input(str(input_path))
            .output(str(output_path), format=self._tgt_fmt, vcodec="libx264", acodec="aac")
            .overwrite_output()
            .run(quiet=True)
        )
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
