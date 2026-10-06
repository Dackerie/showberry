#!/usr/bin/env bash
set -euo pipefail

echo "==> Building Zero-Dependency Showberry AppImage..."

APP_DIR="AppDir"
rm -rf "${APP_DIR}"
mkdir -p "${APP_DIR}/usr/bin" \
         "${APP_DIR}/usr/lib" \
         "${APP_DIR}/usr/share/applications" \
         "${APP_DIR}/usr/share/icons" \
         "${APP_DIR}/usr/share/glib-2.0/schemas" \
         "${APP_DIR}/usr/share/metainfo" \
         "${APP_DIR}/usr/lib/girepository-1.0"

# 1. Standalone Portable Python (x86_64 CPython 3.12)
PYTHON_VERSION="3.12.15"
PYTHON_TAG="20261003"
PYTHON_TAR="/tmp/cpython-${PYTHON_VERSION}-${PYTHON_TAG}-x86_64.tar.gz"
PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_TAG}/cpython-${PYTHON_VERSION}%2B${PYTHON_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz"

if [ ! -f "${PYTHON_TAR}" ]; then
    echo "==> Downloading standalone Python ${PYTHON_VERSION} runtime..."
    curl -fSL -o "${PYTHON_TAR}" "${PYTHON_URL}"
fi

echo "==> Unpacking standalone Python into AppDir..."
tar -xzf "${PYTHON_TAR}" -C "${APP_DIR}/usr/"
PY="${APP_DIR}/usr/python/bin/python3"

echo "==> Upgrading pip in bundled Python..."
"$PY" -m pip install --no-cache-dir --upgrade pip setuptools wheel

echo "==> Bundling PyGObject and Cairo..."
BUNDLED_GI=false
for d in /usr/lib/python3/dist-packages /usr/lib/python3.12/dist-packages /usr/local/lib/python3/dist-packages; do
    if [ -d "$d/gi" ]; then
        echo "    Copying pre-compiled PyGObject from $d..."
        cp -r "$d/gi" "${APP_DIR}/usr/python/lib/python3.12/site-packages/" 2>/dev/null || true
        cp -a "$d"/_gi*.so "${APP_DIR}/usr/python/lib/python3.12/site-packages/" 2>/dev/null || true
        if [ -d "$d/cairo" ]; then
            cp -r "$d/cairo" "${APP_DIR}/usr/python/lib/python3.12/site-packages/" 2>/dev/null || true
            cp -a "$d"/_cairo*.so "${APP_DIR}/usr/python/lib/python3.12/site-packages/" 2>/dev/null || true
        fi
        BUNDLED_GI=true
        break
    fi
done

echo "==> Installing Python dependencies into bundled Python..."
"$PY" -m pip install --no-cache-dir \
    pycairo \
    python-mpv \
    requests \
    pillow \
    curl_cffi \
    pycryptodome \
    cryptography \
    PyOpenGL

if ! "$PY" -c "import gi" &>/dev/null; then
    echo "    Installing PyGObject<3.50 via pip..."
    "$PY" -m pip install --no-cache-dir "PyGObject<3.50"
fi

"$PY" -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); from gi.repository import Gtk, Adw"
echo "    PyGObject verified successfully in bundled Python!"

echo "==> Installing Showberry package into bundled Python..."
"$PY" -m pip install --no-cache-dir --no-deps .

# 2. Bundle Native Libraries (libmpv, codecs, libadwaita)
echo "==> Bundling media & desktop shared libraries..."

bundle_lib() {
    local lib_path="$1"
    [ -f "$lib_path" ] || return 0
    local base
    base="$(basename "$lib_path")"
    if [ ! -f "${APP_DIR}/usr/lib/${base}" ]; then
        cp -L "$lib_path" "${APP_DIR}/usr/lib/${base}" 2>/dev/null || true
    fi
}

bundle_dependencies_of() {
    local target_so="$1"
    [ -f "$target_so" ] || return 0
    ldd "$target_so" 2>/dev/null | awk '{print $3}' | grep -E '^/' | while read -r dep; do
        local b
        b="$(basename "$dep")"
        case "$b" in
            # Exclude core glibc, dynamic linker, and direct GPU driver libraries
            libc.so*|libm.so*|libpthread.so*|libdl.so*|librt.so*|ld-linux*|\
            libGL.so*|libGLX.so*|libEGL.so*|libGLdispatch.so*|libdrm.so*|\
            libX11.so*|libxcb.so*|libwayland-client.so*)
                continue
                ;;
            *)
                bundle_lib "$dep"
                ;;
        esac
    done
}

# Locate libmpv
MPV_SO="$(ldconfig -p 2>/dev/null | grep 'libmpv.so' | head -n 1 | awk '{print $NF}' || true)"
if [ -z "$MPV_SO" ]; then
    for candidate in /usr/lib/x86_64-linux-gnu/libmpv.so* /usr/lib64/libmpv.so* /usr/lib/libmpv.so*; do
        if [ -f "$candidate" ]; then
            MPV_SO="$candidate"
            break
        fi
    done
fi

if [ -n "$MPV_SO" ] && [ -f "$MPV_SO" ]; then
    echo "    Found libmpv: $MPV_SO"
    bundle_lib "$MPV_SO"
    bundle_dependencies_of "$MPV_SO"
    # Ensure libmpv.so symlink exists
    MPV_BASE="$(basename "$MPV_SO")"
    (cd "${APP_DIR}/usr/lib" && ln -sf "$MPV_BASE" libmpv.so && ln -sf "$MPV_BASE" libmpv.so.2)
fi

# Locate and bundle libadwaita-1
ADW_SO="$(ldconfig -p 2>/dev/null | grep 'libadwaita-1.so' | head -n 1 | awk '{print $NF}' || true)"
if [ -z "$ADW_SO" ]; then
    for candidate in /usr/lib/x86_64-linux-gnu/libadwaita-1.so* /usr/lib64/libadwaita-1.so* /usr/lib/libadwaita-1.so*; do
        if [ -f "$candidate" ]; then
            ADW_SO="$candidate"
            break
        fi
    done
fi

if [ -n "$ADW_SO" ] && [ -f "$ADW_SO" ]; then
    echo "    Found libadwaita: $ADW_SO"
    bundle_lib "$ADW_SO"
    bundle_dependencies_of "$ADW_SO"
    ADW_BASE="$(basename "$ADW_SO")"
    (cd "${APP_DIR}/usr/lib" && ln -sf "$ADW_BASE" libadwaita-1.so && ln -sf "$ADW_BASE" libadwaita-1.so.0)
fi

# 3. Bundle Typelibs for PyGObject
echo "==> Bundling system typelibs..."
for dir in /usr/lib/x86_64-linux-gnu/girepository-1.0 /usr/lib64/girepository-1.0 /usr/lib/girepository-1.0; do
    if [ -d "$dir" ]; then
        cp -a "$dir"/*.typelib "${APP_DIR}/usr/lib/girepository-1.0/" 2>/dev/null || true
    fi
done

# 4. GSettings Schemas
echo "==> Installing and compiling GSettings schemas..."
cp data/io.github.Dackerie.Showberry.gschema.xml "${APP_DIR}/usr/share/glib-2.0/schemas/"
for schema_dir in /usr/share/glib-2.0/schemas; do
    if [ -d "$schema_dir" ]; then
        cp -n "$schema_dir"/org.gtk.*.xml "${APP_DIR}/usr/share/glib-2.0/schemas/" 2>/dev/null || true
        cp -n "$schema_dir"/org.gnome.desktop.*.xml "${APP_DIR}/usr/share/glib-2.0/schemas/" 2>/dev/null || true
    fi
done
glib-compile-schemas "${APP_DIR}/usr/share/glib-2.0/schemas/"

# 5. Desktop, Icons, Styles, Metadata
echo "==> Installing desktop, icons, styles, and metadata..."
cp data/io.github.Dackerie.Showberry.desktop "${APP_DIR}/usr/share/applications/"
cp data/io.github.Dackerie.Showberry.desktop "${APP_DIR}/"
cp data/io.github.Dackerie.Showberry.metainfo.xml "${APP_DIR}/usr/share/metainfo/"

mkdir -p "${APP_DIR}/usr/share/showberry"
cp data/style.css "${APP_DIR}/usr/share/showberry/style.css"

cp -r data/icons/* "${APP_DIR}/usr/share/icons/"
cp data/icons/hicolor/512x512/apps/io.github.Dackerie.Showberry.png "${APP_DIR}/io.github.Dackerie.Showberry.png"
cp data/icons/hicolor/512x512/apps/io.github.Dackerie.Showberry.png "${APP_DIR}/.DirIcon"

# 6. Generate Standalone AppRun Launcher
echo "==> Generating standalone AppRun launcher..."
cat << 'LAUNCHER' > "${APP_DIR}/AppRun"
#!/usr/bin/env bash
set -e

HERE="$(dirname "$(readlink -f "${0}")")"

export APPDIR="${HERE}"
export PATH="${HERE}/usr/python/bin:${HERE}/usr/bin:${PATH}"
export PYTHONHOME="${HERE}/usr/python"
export PYTHONPATH="${HERE}/usr/python/lib/python3.12/site-packages:${PYTHONPATH:-}"

# Bundled libraries first, host fallback second (for GPU drivers)
export LD_LIBRARY_PATH="${HERE}/usr/lib:${HERE}/usr/python/lib:${HERE}/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export GI_TYPELIB_PATH="${HERE}/usr/lib/girepository-1.0:${HERE}/usr/lib/x86_64-linux-gnu/girepository-1.0:${GI_TYPELIB_PATH:-}"
export GSETTINGS_SCHEMA_DIR="${HERE}/usr/share/glib-2.0/schemas:${GSETTINGS_SCHEMA_DIR:-}"
export XDG_DATA_DIRS="${HERE}/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export GSK_RENDERER="${GSK_RENDERER:-gl}"

# Execute Showberry using bundled portable Python
exec "${HERE}/usr/python/bin/python3" -m showberry.main "$@"
LAUNCHER
chmod +x "${APP_DIR}/AppRun"

# 7. Package AppImage with appimagetool
echo "==> Packing AppImage with appimagetool..."
if [ -x "./appimagetool" ]; then
    APPIMAGETOOL="./appimagetool"
elif command -v appimagetool &> /dev/null; then
    APPIMAGETOOL="appimagetool"
else
    echo "Downloading appimagetool..."
    wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" -O ./appimagetool
    chmod +x ./appimagetool
    APPIMAGETOOL="./appimagetool"
fi

ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run -n "${APP_DIR}" Showberry-x86_64.AppImage
echo "==> Successfully created standalone Showberry-x86_64.AppImage"
