#!/usr/bin/env bash
set -euo pipefail
mkdir -p bin
cd bin
curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh
chmod +x ./tectonic
./tectonic --version
echo "Vendored tectonic at: $(pwd)/tectonic"
