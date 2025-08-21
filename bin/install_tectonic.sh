#!/usr/bin/env bash
set -euo pipefail

if command -v tectonic >/dev/null 2>&1; then
  echo "Tectonic already on PATH"
  exit 0
fi

mkdir -p bin
cd bin

UNAME="$(uname -s)"
ARCH="$(uname -m)"

if [[ "$UNAME" == "Darwin" && "$ARCH" == "x86_64" ]]; then
  URL="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic-0.15.0/tectonic-0.15.0-x86_64-apple-darwin.tar.gz"
elif [[ "$UNAME" == "Darwin" && "$ARCH" == "arm64" ]]; then
  URL="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic-0.15.0/tectonic-0.15.0-aarch64-apple-darwin.tar.gz"
elif [[ "$UNAME" == "Linux" && "$ARCH" == "x86_64" ]]; then
  URL="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic-0.15.0/tectonic-0.15.0-x86_64-unknown-linux-gnu.tar.gz"
else
  echo "Unsupported platform: $UNAME/$ARCH"
  exit 1
fi

echo "Downloading Tectonic from: $URL"
curl -L "$URL" -o tectonic.tgz
tar -xzf tectonic.tgz
TT="$(find . -type f -name tectonic -perm -u+x | head -n1)"
if [[ -z "$TT" ]]; then
  echo "Could not find tectonic in archive"
  exit 1
fi
mv "$TT" ./tectonic
chmod +x ./tectonic
echo "Installed ./bin/tectonic"
