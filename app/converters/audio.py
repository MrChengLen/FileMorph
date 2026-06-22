# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

import ffmpeg  # ffmpeg-python

from app.converters._ffmpeg import audio_output_args, run_ffmpeg
from app.converters.base import BaseConverter
from app.converters.registry import register

_AUDIO_FORMATS = ["mp3", "wav", "flac", "ogg", "m4a", "aac", "wma", "opus"]

_AUDIO_PAIRS = [(src, tgt) for src in _AUDIO_FORMATS for tgt in _AUDIO_FORMATS if src != tgt]


class _AudioConverter(BaseConverter):
    """Convert audio between formats by invoking ffmpeg directly.

    Replaces the previous pydub path, which decoded the entire file to
    PCM in RAM (a 100 MB MP3 is >1 GB decoded) and passed the bare
    extension as the output format — ffmpeg has no muxer named
    ``m4a``/``aac``/``wma``. Direct invocation streams with constant
    memory; the extension→muxer/codec mapping and the quality→rate-
    control translation live in ``app/converters/_ffmpeg.py``.
    """

    def __init__(self, tgt_fmt: str):
        self._tgt_fmt = tgt_fmt

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        quality = int(kwargs.get("quality", 85))
        stream = ffmpeg.input(str(input_path)).output(
            str(output_path), **audio_output_args(self._tgt_fmt, quality)
        )
        run_ffmpeg(stream)
        return output_path


# Register all audio↔audio pairs
for _src, _tgt in _AUDIO_PAIRS:

    def _make(tgt: str) -> type[BaseConverter]:
        class _Converter(_AudioConverter):
            def __init__(self):
                super().__init__(tgt)

        _Converter.__name__ = f"AudioTo{tgt.upper()}Converter"
        return _Converter

    register((_src, _tgt))(_make(_tgt))
