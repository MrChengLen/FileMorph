# SPDX-License-Identifier: AGPL-3.0-or-later
import re
import unicodedata


def safe_download_name(name: str, max_len: int = 200) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r"[^\w\s.\-]", "", name)
    name = name.strip(". ")
    return (name or "result")[:max_len]
