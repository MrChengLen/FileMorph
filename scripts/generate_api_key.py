#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""CLI tool to generate a new FileMorph API key.

Usage:
    python scripts/generate_api_key.py

The generated key is printed once — save it securely.
The hashed version is stored in data/api_keys.json.
"""

import sys
from pathlib import Path

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import generate_api_key

if __name__ == "__main__":
    key = generate_api_key()
    print()
    print("=" * 56)
    print("  New API Key Generated")
    print("=" * 56)
    print(f"  {key}")
    print("=" * 56)
    print("  Store this key securely — it will not be shown again.")
    print("  Use it as: X-API-Key: <key>")
    print()
