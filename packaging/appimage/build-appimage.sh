#!/usr/bin/env bash
set -euo pipefail

echo "==> Building Showberry AppImage..."

APP_DIR="AppDir"
rm -rf "${APP_DIR}"
mkdir -p "${APP_DIR}/usr/bin" \
         "${APP_DIR}/usr/lib" \
         "${APP_DIR}/usr/share/applications" \
         "${APP_DIR}/usr/share/icons" \
         "${APP_DIR}/usr/share/glib-2.0/schemas" \
         "${APP_DIR}/usr/share/metainfo" \
         "${APP_DIR}/usr/lib/python3/dist-packages"

echo "==> Installing Python dependencies into AppDir..."
python3 -m pip install --break-system-packages --target "${APP_DIR}/usr/lib/python3/dist-packages" \
    requests pillow curl_cffi pycryptodome PyOpenGL python-mpv

echo "==> Installing Showberry package into AppDir..."
python3 -m pip install --break-system-packages --target "${APP_DIR}/usr/lib/python3/dist-packages" --no-deps .

for gid in /usr/lib/python3/dist-packages/gi /usr/lib64/python3*/site-packages/gi /usr/lib/python3*/site-packages/gi; do
    if [ -d "$gid" ]; then
        cp -r "$gid" "${APP_DIR}/usr/lib/python3/dist-packages/" 2>/dev/null || true
        break
    fi
done

echo "==> Installing desktop, icons, and metadata..."
cp data/io.github.Dackerie.Showberry.desktop "${APP_DIR}/usr/share/applications/"
cp data/io.github.Dackerie.Showberry.desktop "${APP_DIR}/"
cp data/io.github.Dackerie.Showberry.metainfo.xml "${APP_DIR}/usr/share/metainfo/"
cp data/io.github.Dackerie.Showberry.gschema.xml "${APP_DIR}/usr/share/glib-2.0/schemas/"
glib-compile-schemas "${APP_DIR}/usr/share/glib-2.0/schemas/"

cp -r data/icons/* "${APP_DIR}/usr/share/icons/"
cp data/icons/hicolor/scalable/apps/io.github.Dackerie.Showberry.svg "${APP_DIR}/io.github.Dackerie.Showberry.svg"
cp data/icons/hicolor/scalable/apps/io.github.Dackerie.Showberry.svg "${APP_DIR}/.DirIcon"

echo "==> Bundling system typelibs and media libraries..."
mkdir -p "${APP_DIR}/usr/lib/girepository-1.0"
for d in /usr/lib/x86_64-linux-gnu/girepository-1.0 /usr/lib64/girepository-1.0 /usr/lib/girepository-1.0; do
    if [ -d "$d" ]; then
        cp -r "$d"/* "${APP_DIR}/usr/lib/girepository-1.0/" 2>/dev/null || true
    fi
done

for lib in /usr/lib/x86_64-linux-gnu/libmpv.so* /usr/lib/libmpv.so* /usr/lib64/libmpv.so*; do
    if [ -f "$lib" ] || [ -L "$lib" ]; then
        cp -d "$lib" "${APP_DIR}/usr/lib/" 2>/dev/null || true
    fi
done

echo "==> Generating AppRun launcher..."
cat << 'LAUNCHER' > "${APP_DIR}/AppRun"
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib:${HERE}/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="${HERE}/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
export GI_TYPELIB_PATH="${HERE}/usr/lib/girepository-1.0:${HERE}/usr/lib/x86_64-linux-gnu/girepository-1.0:${GI_TYPELIB_PATH:-}"
export GSETTINGS_SCHEMA_DIR="${HERE}/usr/share/glib-2.0/schemas:${GSETTINGS_SCHEMA_DIR:-}"
export XDG_DATA_DIRS="${HERE}/usr/share:${XDG_DATA_DIRS:-}"
exec python3 -m showberry.main "$@"
LAUNCHER
chmod +x "${APP_DIR}/AppRun"

echo "==> Packing AppImage with appimagetool..."
if ! command -v appimagetool &> /dev/null; then
    echo "Downloading appimagetool..."
    wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" -O ./appimagetool
    chmod +x ./appimagetool
    APPIMAGETOOL="./appimagetool"
else
    APPIMAGETOOL="appimagetool"
fi

ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run "${APP_DIR}" Showberry-x86_64.AppImage
echo "==> Successfully created Showberry-x86_64.AppImage"
