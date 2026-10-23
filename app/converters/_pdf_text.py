# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF → TXT text extraction, run as a child process.

``python -m app.converters._pdf_text <input.pdf> <output.txt> <max-pages>``

``PdfToTxtConverter`` (``app/converters/document.py``) starts this with a time
limit and stops it when it runs over: some PDFs take pypdf a long time, and
only a process can be stopped from outside. On Linux the address space, the
CPU time and the size of the text file are capped as well. The outcome is
printed as one word on stdout — ``ok``, ``too_many_pages``, ``encrypted``,
``unsupported_encryption``, ``too_large``, ``unreadable`` or ``failed`` — the
last two followed by the exception class (pypdf's messages can quote the
file). The parent discards stderr.
"""

from __future__ import annotations

import sys
from pathlib import Path

_MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
# A little over the parent's 30 s time limit (document.py).
_CPU_LIMIT_SECONDS = 35
# The text file it writes holds at most what fits in its memory.
_FILE_LIMIT_BYTES = 1024 * 1024 * 1024


def extract(input_path: Path, output_path: Path, max_pages: int) -> str:
    """Write the PDF's text to ``output_path``; return the outcome."""
    from pypdf.errors import FileNotDecryptedError, PyPdfError

    from app.converters.base import UnsupportedPdfEncryptionError, open_pypdf

    try:
        reader = open_pypdf(input_path)
        if len(reader.pages) > max_pages:
            return "too_many_pages"
        parts = [page.extract_text() or "" for page in reader.pages]
        # A broken font map can yield an unpaired surrogate, which UTF-8 can't
        # encode: write that character as "?" instead of failing.
        output_path.write_text("\n\n".join(parts), encoding="utf-8", errors="replace", newline="\n")
    except UnsupportedPdfEncryptionError:
        return "unsupported_encryption"
    except FileNotDecryptedError:
        return "encrypted"
    # PyPdfError covers LimitReachedError (a crafted file tripping one of
    # pypdf's resource limits); pypdf reads fonts and content streams lazily,
    # so a broken one only fails during extraction.
    except (PyPdfError, ValueError) as exc:
        return f"unreadable {type(exc).__name__}"
    except MemoryError:
        return "too_large"
    except Exception as exc:  # the parent logs the class and answers 500
        return f"failed {type(exc).__name__}"
    return "ok"


if __name__ == "__main__":
    import logging
    import warnings

    # pypdf logs each repair it makes; nobody reads them here.
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")
    from app.converters._isolated import limit_resources

    limit_resources(_MEMORY_LIMIT_BYTES, _CPU_LIMIT_SECONDS, _FILE_LIMIT_BYTES)
    print(extract(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])))
