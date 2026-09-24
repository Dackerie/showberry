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

echo "==> [1/6] Ensuring build and runtime dependencies..."
if command -v brew &>/dev/null; then
    brew install gtk4 libadwaita adwaita-icon-theme python3 pygobject3 mpv create-dmg libtorrent-rasterbar dylibbundler 2>/dev/null || true
fi

echo "==> [2/6] Installing Python dependencies..."
python3 -m pip install --break-system-packages \
    requests \
    pillow \
    curl_cffi \
    pycryptodome \
    cryptography \
    PyOpenGL \
    python-mpv \
    pyinstaller 2>/dev/null || true

echo "==> [3/6] Compiling local GSettings schemas..."
glib-compile-schemas data/ 2>/dev/null || true

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
PYINSTALLER_CMD="pyinstaller"
if ! command -v pyinstaller &>/dev/null; then
    for cand in /tmp/showberry-venv/bin/pyinstaller ~/.local/bin/pyinstaller /opt/homebrew/bin/pyinstaller; do
        if [ -x "$cand" ]; then
            PYINSTALLER_CMD="$cand"
            break
        fi
    done
fi
"$PYINSTALLER_CMD" packaging/macos/showberry.spec --noconfirm
mv dist/showberry "${APP_DIR}/Contents/Resources/showberry"
chmod -R u+w "${APP_DIR}"

echo "==> Bundling libmpv and libtorrent into macOS App bundle..."
mkdir -p "${APP_DIR}/Contents/Resources/showberry/_internal"
for lib_pattern in "libmpv*.dylib" "libtorrent-rasterbar*.dylib"; do
    for cand in /opt/homebrew/lib/${lib_pattern} /usr/local/lib/${lib_pattern}; do
        if [ -f "$cand" ]; then
            cp -L "$cand" "${APP_DIR}/Contents/Resources/showberry/" 2>/dev/null || true
            cp -L "$cand" "${APP_DIR}/Contents/Resources/showberry/_internal/" 2>/dev/null || true
        fi
    done
done

echo "==> Running dylibbundler to rewrite Mach-O load paths and bundle all transitive dependencies..."
DYLIBBUNDLER_ARGS=(
    -b
    -d "${APP_DIR}/Contents/Resources/showberry/_internal"
    -p "@loader_path/_internal"
    -of
)

for d in /opt/homebrew/lib /usr/local/lib; do
    if [ -d "$d" ]; then
        DYLIBBUNDLER_ARGS+=(-s "$d")
    fi
done

for f in "${APP_DIR}/Contents/Resources/showberry"/libmpv*.dylib "${APP_DIR}/Contents/Resources/showberry"/libtorrent-rasterbar*.dylib; do
    if [ -f "$f" ]; then
        DYLIBBUNDLER_ARGS+=(-x "$f")
    fi
done

while IFS= read -r so_file; do
    if [ -f "$so_file" ]; then
        DYLIBBUNDLER_ARGS+=(-x "$so_file")
    fi
done < <(find "${APP_DIR}/Contents/Resources/showberry/_internal" -name "*libtorrent*.so" 2>/dev/null)

if command -v dylibbundler &>/dev/null; then
    dylibbundler "${DYLIBBUNDLER_ARGS[@]}" || {
        echo "==> Warning: dylibbundler encountered warnings or non-zero exit; continuing..."
    }
else
    echo "==> Warning: dylibbundler not found in PATH, skipping automatic Mach-O bundling"
fi

# Ensure fallback symlinks exist at top-level pointing to _internal if needed
cd "${APP_DIR}/Contents/Resources/showberry"
if [ -f "_internal/libmpv.dylib" ] && [ ! -f "libmpv.dylib" ]; then
    ln -sf "_internal/libmpv.dylib" "libmpv.dylib"
fi
if [ -f "_internal/libmpv.2.dylib" ] && [ ! -f "libmpv.2.dylib" ]; then
    ln -sf "_internal/libmpv.2.dylib" "libmpv.2.dylib"
elif [ -f "_internal/libmpv.dylib" ] && [ ! -f "libmpv.2.dylib" ]; then
    ln -sf "_internal/libmpv.dylib" "libmpv.2.dylib"
fi
for lt_lib in _internal/libtorrent-rasterbar*.dylib; do
    if [ -f "$lt_lib" ] && [ ! -f "libtorrent-rasterbar.dylib" ]; then
        ln -sf "$lt_lib" "libtorrent-rasterbar.dylib"
    fi
done
cd "${REPO_ROOT}"

echo "==> Bundling icons into macOS App bundle..."
for icon_base in /opt/homebrew/share/icons /usr/local/share/icons; do
    if [ -d "$icon_base/Adwaita" ]; then
        mkdir -p "${APP_DIR}/Contents/Resources/share/icons"
        cp -RL "$icon_base/Adwaita" "${APP_DIR}/Contents/Resources/share/icons/" 2>/dev/null || true
        cp -RL "$icon_base/hicolor" "${APP_DIR}/Contents/Resources/share/icons/" 2>/dev/null || true
        mkdir -p "${APP_DIR}/Contents/Resources/showberry/share/icons"
        cp -RL "$icon_base/Adwaita" "${APP_DIR}/Contents/Resources/showberry/share/icons/" 2>/dev/null || true
        cp -RL "$icon_base/hicolor" "${APP_DIR}/Contents/Resources/showberry/share/icons/" 2>/dev/null || true
        break
    fi
done

echo "==> Ensuring bundled symbolic icons are in macOS App bundle..."
mkdir -p "${APP_DIR}/Contents/Resources/share/icons" \
         "${APP_DIR}/Contents/Resources/showberry/share/icons" \
         "${APP_DIR}/Contents/Resources/showberry/data/icons"
cp -RL "${REPO_ROOT}/data/icons/"* "${APP_DIR}/Contents/Resources/share/icons/" 2>/dev/null || true
cp -RL "${REPO_ROOT}/data/icons/"* "${APP_DIR}/Contents/Resources/showberry/share/icons/" 2>/dev/null || true
cp -RL "${REPO_ROOT}/data/icons/"* "${APP_DIR}/Contents/Resources/showberry/data/icons/" 2>/dev/null || true

echo "==> Bundling GSettings schemas into macOS App bundle..."
mkdir -p "${APP_DIR}/Contents/Resources/share/glib-2.0/schemas" \
         "${APP_DIR}/Contents/Resources/showberry/share/glib-2.0/schemas" \
         "${APP_DIR}/Contents/Resources/showberry/data"
cp -RL "${REPO_ROOT}/data/io.github.Dackerie.Showberry.gschema.xml" "${APP_DIR}/Contents/Resources/share/glib-2.0/schemas/" 2>/dev/null || true
cp -RL "${REPO_ROOT}/data/io.github.Dackerie.Showberry.gschema.xml" "${APP_DIR}/Contents/Resources/showberry/share/glib-2.0/schemas/" 2>/dev/null || true
cp -RL "${REPO_ROOT}/data/io.github.Dackerie.Showberry.gschema.xml" "${APP_DIR}/Contents/Resources/showberry/data/" 2>/dev/null || true
if [ -f "${REPO_ROOT}/data/gschemas.compiled" ]; then
    cp -RL "${REPO_ROOT}/data/gschemas.compiled" "${APP_DIR}/Contents/Resources/share/glib-2.0/schemas/" 2>/dev/null || true
    cp -RL "${REPO_ROOT}/data/gschemas.compiled" "${APP_DIR}/Contents/Resources/showberry/share/glib-2.0/schemas/" 2>/dev/null || true
    cp -RL "${REPO_ROOT}/data/gschemas.compiled" "${APP_DIR}/Contents/Resources/showberry/data/" 2>/dev/null || true
fi
glib-compile-schemas "${APP_DIR}/Contents/Resources/share/glib-2.0/schemas" 2>/dev/null || true
glib-compile-schemas "${APP_DIR}/Contents/Resources/showberry/share/glib-2.0/schemas" 2>/dev/null || true

echo "==> Bundling GObject typelibs into macOS App bundle..."
mkdir -p "${APP_DIR}/Contents/Resources/share/girepository-1.0" \
         "${APP_DIR}/Contents/Resources/showberry/share/girepository-1.0"
for cand in /opt/homebrew/lib/girepository-1.0 /usr/local/lib/girepository-1.0; do
    if [ -d "$cand" ]; then
        cp -RL "$cand"/* "${APP_DIR}/Contents/Resources/share/girepository-1.0/" 2>/dev/null || true
        cp -RL "$cand"/* "${APP_DIR}/Contents/Resources/showberry/share/girepository-1.0/" 2>/dev/null || true
        break
    fi
done

echo "==> Bundling CSS styles into macOS App bundle..."
mkdir -p "${APP_DIR}/Contents/Resources/showberry/data" \
         "${APP_DIR}/Contents/Resources/data"
cp -RL "${REPO_ROOT}/data/style.css" "${APP_DIR}/Contents/Resources/showberry/data/" 2>/dev/null || true
cp -RL "${REPO_ROOT}/data/style.css" "${APP_DIR}/Contents/Resources/data/" 2>/dev/null || true

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

if command -v create-dmg &>/dev/null; then
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
else
    echo "==> create-dmg not found, generating DMG via native hdiutil..."
    DMG_TMP="${REPO_ROOT}/dmg_staging"
    rm -rf "${DMG_TMP}"
    mkdir -p "${DMG_TMP}"
    cp -R "${APP_DIR}" "${DMG_TMP}/"
    ln -s /Applications "${DMG_TMP}/Applications"
    hdiutil create -volname "Showberry" -srcfolder "${DMG_TMP}" -ov -format UDZO "${DMG_NAME}"
    rm -rf "${DMG_TMP}"
fi

echo "==> Successfully created ${DMG_NAME}!"
