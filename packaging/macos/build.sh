#!/usr/bin/env bash
set -euo pipefail

echo "========================================"
echo "    Building Showberry for macOS DMG    "
echo "========================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ARCH="${ARCH:-$(uname -m)}"
echo "==> Target Architecture: ${ARCH}"

cd "${REPO_ROOT}"

if ! command -v pyinstaller &>/dev/null; then
    echo "==> [1/6] Installing Homebrew dependencies..."
    if command -v brew &>/dev/null; then
        brew install gtk4 libadwaita adwaita-icon-theme python3 pygobject3 mpv create-dmg libtorrent-rasterbar || true
    fi

    echo "==> [2/6] Installing Python dependencies..."
    python3 -m pip install --break-system-packages \
        requests \
        pillow \
        curl_cffi \
        pycryptodome \
        PyOpenGL \
        python-mpv \
        pyinstaller
else
    echo "==> [1/6 & 2/6] Dependencies already installed, skipping..."
fi

echo "==> [3/6] Compiling GSettings schemas..."
glib-compile-schemas data/ || true

echo "==> [4/6] Creating macOS App Bundle..."
APP_DIR="${REPO_ROOT}/Showberry.app"
rm -rf "${APP_DIR}"
mkdir -p "${APP_DIR}/Contents/MacOS"
mkdir -p "${APP_DIR}/Contents/Resources"

cp "${SCRIPT_DIR}/Info.plist" "${APP_DIR}/Contents/"
cp "${SCRIPT_DIR}/showberry.icns" "${APP_DIR}/Contents/Resources/"

echo "==> Compiling native Swift launcher..."
swiftc "${SCRIPT_DIR}/launcher.swift" -O -o "${APP_DIR}/Contents/MacOS/Showberry"
chmod +x "${APP_DIR}/Contents/MacOS/Showberry"

echo "==> [5/6] Building PyInstaller bundle..."
rm -rf build/ dist/showberry
pyinstaller packaging/macos/showberry.spec --noconfirm
mv dist/showberry "${APP_DIR}/Contents/Resources/showberry"

echo "==> Bundling libmpv into macOS App bundle..."
for mpv_cand in /opt/homebrew/lib/libmpv*.dylib /usr/local/lib/libmpv*.dylib; do
    if [ -f "$mpv_cand" ]; then
        cp -a "$mpv_cand" "${APP_DIR}/Contents/Resources/showberry/" 2>/dev/null || true
    fi
done

echo "==> Bundling icons into macOS App bundle..."
for icon_base in /opt/homebrew/share/icons /usr/local/share/icons; do
    if [ -d "$icon_base/Adwaita" ]; then
        mkdir -p "${APP_DIR}/Contents/Resources/share/icons"
        cp -a "$icon_base/Adwaita" "${APP_DIR}/Contents/Resources/share/icons/" 2>/dev/null || true
        cp -a "$icon_base/hicolor" "${APP_DIR}/Contents/Resources/share/icons/" 2>/dev/null || true
        mkdir -p "${APP_DIR}/Contents/Resources/showberry/share/icons"
        cp -a "$icon_base/Adwaita" "${APP_DIR}/Contents/Resources/showberry/share/icons/" 2>/dev/null || true
        cp -a "$icon_base/hicolor" "${APP_DIR}/Contents/Resources/showberry/share/icons/" 2>/dev/null || true
        break
    fi
done

echo "==> Ad-hoc signing application bundle..."
find "${APP_DIR}" -type f | while read -r file; do
    if file "$file" | grep -q "Mach-O"; then
        codesign -f -s - "$file" 2>/dev/null || true
    fi
done
codesign -f -s - --deep "${APP_DIR}" 2>/dev/null || true

echo "==> [6/6] Generating Drag-and-Drop DMG..."
DMG_NAME="Showberry-macOS-${ARCH}.dmg"
rm -f "${DMG_NAME}"

create-dmg \
    --volname "Showberry" \
    --volicon "${SCRIPT_DIR}/showberry.icns" \
    --window-pos 200 120 \
    --window-size 660 400 \
    --icon-size 128 \
    --icon "Showberry.app" 180 170 \
    --hide-extension "Showberry.app" \
    --app-drop-link 480 170 \
    "${DMG_NAME}" \
    "${APP_DIR}"

echo "==> Successfully created ${DMG_NAME}!"
