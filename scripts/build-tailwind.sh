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

# SHA-256 pins from the release's sha256sums.txt. CI runs this script on every
# run (the Tailwind freshness gate), so the downloaded executable is verified
# before it ever runs. Bumping VERSION means replacing these values with the
# new release's sha256sums.txt.
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)       ASSET="tailwindcss-linux-x64";   BIN="$TOOLS/tailwindcss"
                      SHA256="7d24f7fa191d2193b78cd5f5a42a6093e14409521908529f42d80b11fde1f1d4" ;;
  Linux-aarch64)      ASSET="tailwindcss-linux-arm64"; BIN="$TOOLS/tailwindcss"
                      SHA256="69b1378b8133192d7d2feb12a116fa12d035594f58db3eff215879e4ad8cf39b" ;;
  Darwin-x86_64)      ASSET="tailwindcss-macos-x64";   BIN="$TOOLS/tailwindcss"
                      SHA256="6cbdad74be776c087ffa5e9a057512c54898f9fe8828d3362212dfe32fc933a3" ;;
  Darwin-arm64)       ASSET="tailwindcss-macos-arm64"; BIN="$TOOLS/tailwindcss"
                      SHA256="a1d0c7985759accca0bf12e51ac1dcbf0f6cf2fffb62e6e0f62d091c477a10a3" ;;
  MINGW*-*|MSYS*-*|CYGWIN*-*) ASSET="tailwindcss-windows-x64.exe"; BIN="$TOOLS/tailwindcss.exe"
                      SHA256="67f1c5e3f5a03406a7bf5badf5ada09b79f3ae78ec43450c15f7e983068da346" ;;
  *) echo "Unsupported host: $(uname -s) $(uname -m)"; exit 1 ;;
esac

# sha256sum on Linux/Git-Bash/MSYS, shasum -a 256 on macOS.
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# (Re-)download when the binary is missing or doesn't match its pin (truncated
# download, old VERSION). The download is verified before it replaces $BIN or
# becomes executable, so an unverified binary is never left in .tools/.
if [ ! -f "$BIN" ] || [ "$(sha256_of "$BIN")" != "$SHA256" ]; then
  URL="https://github.com/tailwindlabs/tailwindcss/releases/download/$VERSION/$ASSET"
  echo "Downloading Tailwind CLI $VERSION ($ASSET) -> $BIN"
  curl -fsSL --retry 3 -o "$BIN.part" "$URL"
  ACTUAL_SHA256="$(sha256_of "$BIN.part")"
  if [ "$ACTUAL_SHA256" != "$SHA256" ]; then
    rm -f "$BIN.part" "$BIN"
    echo "Checksum mismatch for the downloaded $ASSET" >&2
    echo "  expected $SHA256 (Tailwind CLI $VERSION)" >&2
    echo "  got      $ACTUAL_SHA256" >&2
    echo "If VERSION was bumped, update the SHA256 pins from its sha256sums.txt." >&2
    exit 1
  fi
  mv -f "$BIN.part" "$BIN"
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

# Content-hash the output.
HASH="$(sha256_of "$TMP_OUT" | cut -c1-8)"
FINAL="$CSS_DIR/tailwind.$HASH.css"

# Purge any previously-built hashed bundles so only the current one ships.
# The guard protects tailwind.input.css (the source file).
find "$CSS_DIR" -maxdepth 1 -type f -name 'tailwind.*.css' \
  ! -name 'tailwind.input.css' -delete

mv "$TMP_OUT" "$FINAL"

SIZE=$(wc -c < "$FINAL")
echo "Wrote $FINAL ($SIZE bytes)"
