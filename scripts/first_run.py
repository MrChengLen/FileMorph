#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Called by entrypoint.sh on first run.
Generates an API key and prints ONLY the key to stdout.
All other output must go to stderr to avoid corrupting the captured value.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import generate_api_key

if __name__ == "__main__":
    key = generate_api_key()
    print(key, end="")
