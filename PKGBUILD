# Maintainer: Dackerie <dackerie@showberry.dev>
pkgname=showberry
pkgver=0.3.0
pkgrel=1
pkgdesc="An elegant, modern movie and TV series streaming application for GNOME"
arch=('any')
url="https://github.com/Dackerie/showberry"
license=('GPL-3.0-or-later')
depends=(
    'gtk4'
    'libadwaita'
    'python-gobject'
    'mpv'
    'python-requests'
    'python-pillow'
    'python-pycryptodome'
    'libtorrent-rasterbar'
)
optdepends=(
    'python-curl-cffi: Enhanced TLS anti-bot evasion for streaming providers'
    'python-opengl: Fast OpenGL display widget'
    'python-mpv: Direct libmpv Python API bindings'
)
makedepends=(
    'python-build'
    'python-installer'
    'python-setuptools'
    'python-wheel'
)

build() {
    cd "$startdir"
    python -m build --wheel --no-isolation
}

package() {
    cd "$startdir"
    python -m installer --destdir="$pkgdir" dist/*.whl

    # Desktop entry
    install -Dm644 data/io.github.Dackerie.Showberry.desktop "$pkgdir/usr/share/applications/io.github.Dackerie.Showberry.desktop"

    # AppStream Metainfo
    install -Dm644 data/io.github.Dackerie.Showberry.metainfo.xml "$pkgdir/usr/share/metainfo/io.github.Dackerie.Showberry.metainfo.xml"

    # GSettings Schema
    install -Dm644 data/io.github.Dackerie.Showberry.gschema.xml "$pkgdir/usr/share/glib-2.0/schemas/io.github.Dackerie.Showberry.gschema.xml"

    # Style CSS
    install -Dm644 data/style.css "$pkgdir/usr/share/showberry/style.css"

    # Icons
    if [ -d data/icons ]; then
        mkdir -p "$pkgdir/usr/share/icons"
        cp -r data/icons/* "$pkgdir/usr/share/icons/" 2>/dev/null || true
    fi
}
