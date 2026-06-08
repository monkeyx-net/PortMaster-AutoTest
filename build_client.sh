#!/usr/bin/env bash
set -euo pipefail

# Build a standalone zip_client binary using PyInstaller.
# Usage: ./build_client.sh [--arch x86_64|aarch64]
#
# Optional: build the framebuffer screenshot .love file first:
#   ./build_fbshot.sh
# Then point the client at it:
#   --screenshot-cmd "love /path/to/fbshot.love {}"

ARCH="${1:-x86_64}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"

if [ "$ARCH" = "aarch64" ] && [ "$(uname -m)" != "aarch64" ]; then
    echo "Cross-build for aarch64 via Docker QEMU ..."
    docker run --rm --platform linux/arm64 \
        -v "$SCRIPT_DIR:/work" -w /work \
        python:3.11-slim \
        bash -c "
            pip install --quiet pyinstaller &&
            pyinstaller --onefile --name zip_client \
                --distpath /work/dist --workpath /work/build \
                --specpath /work /work/src/zip_client.py
        "
    echo "Done - binary at: $SCRIPT_DIR/dist/zip_client"
    exit 0
fi

"$PYTHON" -m pip install --quiet pyinstaller 2>/dev/null || {
    echo "pip install pyinstaller failed"
    exit 1
}

echo "Building zip_client with PyInstaller ..."
"$PYTHON" -m PyInstaller \
    --onefile \
    --name zip_client \
    --distpath "$SCRIPT_DIR/dist" \
    --workpath "$SCRIPT_DIR/build" \
    --specpath "$SCRIPT_DIR" \
    "$SCRIPT_DIR/src/zip_client.py"

echo "Done - binary at: $SCRIPT_DIR/dist/zip_client"
