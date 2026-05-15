# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

import ffmpeg

_SUPPORTED_FORMATS = ["mp4", "avi", "mov", "mkv", "webm"]


def compress_video(input_path: Path, output_path: Path, quality: int = 70) -> Path:
    """Compress a video using ffmpeg CRF encoding.

    quality: 1 (worst/smallest) – 100 (best/largest).
    CRF scale for libx264: 0 (lossless) – 51 (worst). We map:
      quality 100 → CRF 18  (visually near-lossless)
      quality 1   → CRF 40  (very low quality, small file)
    """
    quality = max(1, min(100, quality))
    crf = round(18 + (100 - quality) * (40 - 18) / 99)

    (
        ffmpeg.input(str(input_path))
        .output(
            str(output_path),
            vcodec="libx264",
            crf=crf,
            acodec="aac",
            audio_bitrate="128k",
            format="mp4",
        )
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path
