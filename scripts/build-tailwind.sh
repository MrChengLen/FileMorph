#!/usr/bin/env bash
# Build the self-hosted Tailwind bundle under app/static/css/.
#
# Output filename is content-hashed (tailwind.<sha256-prefix>.css) so the
# CachingStaticFiles regex in app/main.py can serve it with a far-future
# `immutable` Cache-Control. The app resolves the current filename at
# startup by scanning the directory, so nothing else needs updating when
# the hash rotates.
#
# Re-run after editing templates, JS class names, or tailwind.config.js.
# No Node.js toolchain — we fetch the standalone, statically-linked
# Tailwind CLI binary on first run and drop it under .tools/ (gitignored).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="$ROOT/.tools"
VERSION="v3.4.17"
CSS_DIR="$ROOT/app/static/css"

mkdir -p "$TOOLS"

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)       ASSET="tailwindcss-linux-x64";   BIN="$TOOLS/tailwindcss" ;;
  Linux-aarch64)      ASSET="tailwindcss-linux-arm64"; BIN="$TOOLS/tailwindcss" ;;
  Darwin-x86_64)      ASSET="tailwindcss-macos-x64";   BIN="$TOOLS/tailwindcss" ;;
  Darwin-arm64)       ASSET="tailwindcss-macos-arm64"; BIN="$TOOLS/tailwindcss" ;;
  MINGW*-*|MSYS*-*|CYGWIN*-*) ASSET="tailwindcss-windows-x64.exe"; BIN="$TOOLS/tailwindcss.exe" ;;
  *) echo "Unsupported host: $(uname -s) $(uname -m)"; exit 1 ;;
esac

if [ ! -x "$BIN" ]; then
  URL="https://github.com/tailwindlabs/tailwindcss/releases/download/$VERSION/$ASSET"
  echo "Downloading Tailwind CLI $VERSION ($ASSET) -> $BIN"
  curl -sSL -o "$BIN" "$URL"
  chmod +x "$BIN"
fi

cd "$ROOT"

# Build to an intermediate path first; we'll hash and rename.
TMP_OUT="$CSS_DIR/.tailwind.build.css"
"$BIN" \
  -c tailwind.config.js \
  -i app/static/css/tailwind.input.css \
  -o "$TMP_OUT" \
  --minify

# Content-hash the output. Use sha256sum if available (Linux/Git-Bash/MSYS),
# fall back to shasum -a 256 (macOS default).
if command -v sha256sum >/dev/null 2>&1; then
  HASH="$(sha256sum "$TMP_OUT" | cut -c1-8)"
else
  HASH="$(shasum -a 256 "$TMP_OUT" | cut -c1-8)"
fi
FINAL="$CSS_DIR/tailwind.$HASH.css"

# Purge any previously-built hashed bundles so only the current one ships.
# The guard protects tailwind.input.css (the source file).
find "$CSS_DIR" -maxdepth 1 -type f -name 'tailwind.*.css' \
  ! -name 'tailwind.input.css' -delete

mv "$TMP_OUT" "$FINAL"

SIZE=$(wc -c < "$FINAL")
echo "Wrote $FINAL ($SIZE bytes)"
