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

echo "==> Bundling PyGObject (gi)..."
GI_DIR="$(python3 -c 'import gi, os; print(os.path.dirname(gi.__file__))' 2>/dev/null || true)"
if [ -n "$GI_DIR" ] && [ -d "$GI_DIR" ]; then
    echo "Found gi at ${GI_DIR}, copying into AppDir..."
    cp -r "$GI_DIR" "${APP_DIR}/usr/lib/python3/dist-packages/" 2>/dev/null || true
fi

echo "==> Installing desktop, icons, and metadata..."
cp data/io.github.Dackerie.Showberry.desktop "${APP_DIR}/usr/share/applications/"
cp data/io.github.Dackerie.Showberry.desktop "${APP_DIR}/"
cp data/io.github.Dackerie.Showberry.metainfo.xml "${APP_DIR}/usr/share/metainfo/"
cp data/io.github.Dackerie.Showberry.gschema.xml "${APP_DIR}/usr/share/glib-2.0/schemas/"
glib-compile-schemas "${APP_DIR}/usr/share/glib-2.0/schemas/"

cp -r data/icons/* "${APP_DIR}/usr/share/icons/"
cp data/icons/hicolor/512x512/apps/io.github.Dackerie.Showberry.png "${APP_DIR}/io.github.Dackerie.Showberry.png"
cp data/icons/hicolor/512x512/apps/io.github.Dackerie.Showberry.png "${APP_DIR}/.DirIcon"

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

# Recursively copy media dependencies (FFmpeg, libass, libplacebo, etc.) needed by libmpv
echo "==> Bundling libmpv media dependencies..."
for pass in 1 2; do
    for sofile in "${APP_DIR}/usr/lib/"*.so*; do
        if [ -f "$sofile" ]; then
            for dep in $(ldd "$sofile" 2>/dev/null | grep '=> /' | awk '{print $3}'); do
                dep_name="$(basename "$dep")"
                case "$dep_name" in
                    libc.so*|libm.so*|libpthread.so*|libdl.so*|librt.so*|ld-linux*|libGL.so*|libEGL.so*|libwayland*|libX11*|libxcb*|libresolv.so*|libgcc_s.so*)
                        # Exclude low-level system, glibc and graphics display libraries
                        ;;
                    *)
                        if [ -f "$dep" ] && [ ! -e "${APP_DIR}/usr/lib/${dep_name}" ]; then
                            cp -L "$dep" "${APP_DIR}/usr/lib/" 2>/dev/null || true
                        fi
                        ;;
                esac
            done
        fi
    done
done

echo "==> Generating AppRun launcher..."
cat << 'LAUNCHER' > "${APP_DIR}/AppRun"
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib:${HERE}/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="${HERE}/usr/lib/python3/dist-packages:${HERE}/usr/lib/python3/site-packages:${PYTHONPATH:-}"
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

ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run -n "${APP_DIR}" Showberry-x86_64.AppImage
echo "==> Successfully created Showberry-x86_64.AppImage"
