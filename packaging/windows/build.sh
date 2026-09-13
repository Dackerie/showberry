#!/usr/bin/env bash
set -euo pipefail

echo "========================================"
echo " Building Showberry for Windows (MSYS2) "
echo "========================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

echo "==> [1/5] Installing MSYS2 UCRT64 dependencies..."
pacman -S --noconfirm --needed \
    mingw-w64-ucrt-x86_64-python \
    mingw-w64-ucrt-x86_64-gtk4 \
    mingw-w64-ucrt-x86_64-libadwaita \
    mingw-w64-ucrt-x86_64-python-pillow \
    mingw-w64-ucrt-x86_64-python-gobject \
    mingw-w64-ucrt-x86_64-python-pip \
    mingw-w64-ucrt-x86_64-pyinstaller \
    mingw-w64-ucrt-x86_64-mpv \
    mingw-w64-ucrt-x86_64-gcc \
    mingw-w64-ucrt-x86_64-glib2

echo "==> [2/5] Installing Python PIP packages..."
pip install --break-system-packages \
    requests \
    pillow \
    curl_cffi \
    pycryptodome \
    PyOpenGL \
    python-mpv \
    libtorrent

echo "==> [3/5] Compiling GSettings schemas..."
glib-compile-schemas data/

echo "==> [4/5] Running PyInstaller..."
rm -rf build/ dist/showberry
pyinstaller packaging/windows/showberry.spec --noconfirm

echo "==> [5/5] Finalizing distribution bundle..."
# Ensure libmpv-2.dll is located alongside showberry.exe
if [ -f "/ucrt64/bin/libmpv-2.dll" ]; then
    cp "/ucrt64/bin/libmpv-2.dll" dist/showberry/
fi
cp "${SCRIPT_DIR}/icon.ico" dist/showberry/

echo "==> Showberry Windows binary bundle created at: ${REPO_ROOT}/dist/showberry"
