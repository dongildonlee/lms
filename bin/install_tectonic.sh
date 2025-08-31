#!/usr/bin/env bash
set -euo pipefail

# Always vendor a local binary for reproducibility.
# (Do NOT early-exit just because build env has tectonic.)
mkdir -p bin
cd bin

TT_VER="0.15.0"

UNAME="$(uname -s)"
ARCH="$(uname -m)"

case "$UNAME/$ARCH" in
  Darwin/x86_64)
    URL="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic-${TT_VER}/tectonic-${TT_VER}-x86_64-apple-darwin.tar.gz"
    ;;
  Darwin/arm64)
    URL="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic-${TT_VER}/tectonic-${TT_VER}-aarch64-apple-darwin.tar.gz"
    ;;
  Linux/x86_64)
    URL="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic-${TT_VER}/tectonic-${TT_VER}-x86_64-unknown-linux-gnu.tar.gz"
    ;;
  Linux/aarch64)
    URL="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic-${TT_VER}/tectonic-${TT_VER}-aarch64-unknown-linux-gnu.tar.gz"
    ;;
  *)
    echo "Unsupported platform: ${UNAME}/${ARCH}" >&2
    exit 1
    ;;
esac

echo "Downloading Tectonic ${TT_VER} from: ${URL}"
curl -fsSL -o tectonic.tgz "${URL}"
tar -xzf tectonic.tgz

# Find the unpacked binary
TT="$(find . -type f -name tectonic -perm -u+x | head -n1 || true)"
if [[ -z "${TT}" ]]; then
  echo "Could not find tectonic in archive" >&2
  exit 1
fi

# Place (or replace) the vendored binary
mv -f "${TT}" ./tectonic
chmod +x ./tectonic
rm -f tectonic.tgz

echo "Vendored Tectonic at: $(pwd)/tectonic"
./tectonic --version

