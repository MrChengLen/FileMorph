# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

import ffmpeg

from app.converters._ffmpeg import run_ffmpeg, video_output_args

_SUPPORTED_FORMATS = ["mp4", "avi", "mov", "mkv", "webm"]


def compress_video(input_path: Path, output_path: Path, quality: int = 70) -> Path:
    """Compress a video by re-encoding it, keeping its container.

    quality: 1 (worst/smallest) – 100 (best/largest), mapped onto each
    encoder's rate control in ``app/converters/_ffmpeg.py`` (libx264:
    quality 100 → CRF 18, quality 1 → CRF 40 — unchanged from the
    previous hardcoded mapping).

    The container follows the output path's extension. The /compress
    route names the output after the input, so a .webm stays WebM
    (VP9/Opus) and a .mkv stays Matroska — previously every input was
    silently muxed into MP4 while keeping the original extension,
    producing mislabelled files.
    """
    container = output_path.suffix.lstrip(".").lower() or "mp4"
    stream = ffmpeg.input(str(input_path)).output(
        str(output_path),
        **video_output_args(container, quality, audio_bitrate="128k"),
    )
    run_ffmpeg(stream)
    return output_path
