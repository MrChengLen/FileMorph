# SPDX-License-Identifier: AGPL-3.0-or-later
from abc import ABC, abstractmethod
from pathlib import Path


class UnsupportedConversionError(Exception):
    def __init__(self, src: str, tgt: str):
        super().__init__(f"Conversion from '{src}' to '{tgt}' is not supported.")
        self.src = src
        self.tgt = tgt


class BaseConverter(ABC):
    """Abstract base class for all file converters."""

    @abstractmethod
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        """Convert input_path and write result to output_path. Returns output_path."""
        ...
