from pathlib import Path

from app.converters.base import BaseConverter
from app.converters.registry import register

_AUDIO_FORMATS = ["mp3", "wav", "flac", "ogg", "m4a", "aac", "wma", "opus"]

_AUDIO_PAIRS = [(src, tgt) for src in _AUDIO_FORMATS for tgt in _AUDIO_FORMATS if src != tgt]


class _AudioConverter(BaseConverter):
    """Convert audio between formats via pydub (uses ffmpeg under the hood)."""

    def __init__(self, tgt_fmt: str):
        self._tgt_fmt = tgt_fmt

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(str(input_path))
        export_fmt = self._tgt_fmt
        # pydub uses "mp3" not "mp3", "ogg" not "vorbis", etc.
        audio.export(str(output_path), format=export_fmt)
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
