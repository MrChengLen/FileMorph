# SPDX-License-Identifier: AGPL-3.0-or-later
from abc import ABC, abstractmethod
from pathlib import Path


class UnsupportedConversionError(Exception):
    def __init__(self, src: str, tgt: str):
        super().__init__(f"Conversion from '{src}' to '{tgt}' is not supported.")
        self.src = src
        self.tgt = tgt


class InvalidInputError(Exception):
    """A problem with the upload the user can fix; routes show ``str(exc)``.

    Raise it only with a message written for the user that names the fix.
    """


class EncryptedPdfError(InvalidInputError):
    """The PDF opens only with a password, and FileMorph never asks for one.

    pypdf raises ``FileNotDecryptedError`` on such a file, pikepdf
    ``PasswordError``. A PDF with only an owner password opens without one
    and never gets here. The routes send
    ``X-FileMorph-Error-Code: pdf_encrypted`` with it.
    """

    # ``*_args``: copy and pickle re-create an exception from its args; the
    # message stays fixed either way.
    def __init__(self, *_args: object) -> None:
        super().__init__(
            "This PDF is password-protected. Remove the password "
            "(e.g. open the file and print it to a new PDF) and try again."
        )


def read_utf8_text(path: Path) -> str:
    """Decode an uploaded text file as UTF-8, or tell the user how to fix it.

    Line endings are kept as-is (the CSV readers rely on that); a leading BOM,
    as in Excel's "CSV UTF-8", is dropped. A bare ``UnicodeDecodeError`` names
    codec, byte and offset — no help to a user.
    """
    try:
        return path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidInputError(
            "The file is not UTF-8 text. Re-save it as UTF-8 (in Excel: Save As → "
            "CSV UTF-8; in text editors: Save As → Encoding) and try again."
        ) from exc


class BaseConverter(ABC):
    """Abstract base class for all file converters."""

    @abstractmethod
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        """Convert input_path and write result to output_path. Returns output_path."""
        ...
