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
    mingw-w64-ucrt-x86_64-adwaita-icon-theme \
    mingw-w64-ucrt-x86_64-python-pillow \
    mingw-w64-ucrt-x86_64-python-gobject \
    mingw-w64-ucrt-x86_64-python-pip \
    mingw-w64-ucrt-x86_64-python-cryptography \
    mingw-w64-ucrt-x86_64-pyinstaller \
    mingw-w64-ucrt-x86_64-mpv \
    mingw-w64-ucrt-x86_64-gcc \
    mingw-w64-ucrt-x86_64-glib2 \
    mingw-w64-ucrt-x86_64-openssl \
    mingw-w64-ucrt-x86_64-cmake \
    mingw-w64-ucrt-x86_64-ninja \
    mingw-w64-ucrt-x86_64-git \
    mingw-w64-ucrt-x86_64-boost \
    mingw-w64-ucrt-x86_64-boost-libs \
    mingw-w64-ucrt-x86_64-ntldd \
    mingw-w64-ucrt-x86_64-angleproject

echo "==> [2/5] Installing Python PIP packages..."
pip install --break-system-packages \
    requests \
    pillow \
    curl_cffi \
    pycryptodome \
    cryptography \
    PyOpenGL \
    python-mpv

echo "==> [2b/5] Checking Libtorrent Python bindings..."
if python -c "import libtorrent" 2>/dev/null; then
    echo "==> Libtorrent is already installed and functional. Skipping source compilation!"
else
    echo "==> Building and installing Libtorrent from source..."
    (
        git clone --recursive "https://github.com/arvidn/libtorrent"
        cd libtorrent
        git switch --detach 578e06824c3546f3371ab43967ab288a7e253eca
        mkdir build && cd build
        cmake .. -G Ninja -DCMAKE_BUILD_TYPE=Release -Dpython-bindings=ON -DBUILD_SHARED_LIBS=OFF -Dstatic_runtime=ON -DPython3_EXECUTABLE="$(which python)"
        cmake --build .
        cmake --install . --prefix /ucrt64
        cd ../..
        rm -rf libtorrent
        echo "==> Libtorrent built and installed into /ucrt64 successfully!"
    ) || {
        echo "==> Warning: Libtorrent build failed or skipped. Continuing build without torrent streaming..."
        rm -rf libtorrent 2>/dev/null || true
    }
fi

mkdir -p output
echo "==> [3/5] Compiling GSettings schemas..."
glib-compile-schemas data/

echo "==> [4/5] Running PyInstaller..."
rm -rf build/ dist/showberry
pyinstaller packaging/windows/showberry.spec --noconfirm

echo "==> [5/5] Finalizing distribution bundle and collecting DLL dependencies..."
python "${SCRIPT_DIR}/collect_dlls.py"
cp "${SCRIPT_DIR}/icon.ico" dist/showberry/
if [ -d "dist/showberry/_internal" ]; then
    cp "${SCRIPT_DIR}/icon.ico" dist/showberry/_internal/
fi

echo "==> Ensuring bundled symbolic icons are in Windows distribution..."
mkdir -p dist/showberry/share/icons dist/showberry/data/icons
cp -a data/icons/* dist/showberry/share/icons/ 2>/dev/null || true
cp -a data/icons/* dist/showberry/data/icons/ 2>/dev/null || true
if [ -d "dist/showberry/_internal" ]; then
    mkdir -p dist/showberry/_internal/share/icons dist/showberry/_internal/data/icons
    cp -a data/icons/* dist/showberry/_internal/share/icons/ 2>/dev/null || true
    cp -a data/icons/* dist/showberry/_internal/data/icons/ 2>/dev/null || true
fi

echo "==> Showberry Windows binary bundle created at: ${REPO_ROOT}/dist/showberry"
