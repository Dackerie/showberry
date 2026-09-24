# -*- mode: python ; coding: utf-8 -*-
import os
import sys
spec_dir = SPECPATH if 'SPECPATH' in globals() else (os.path.dirname(__file__) if '__file__' in globals() else os.getcwd())
repo_root = os.path.abspath(os.path.join(spec_dir, '..', '..'))

datas = [
    (os.path.join(repo_root, 'showberry', 'data', 'style.css'), 'showberry/data'),
    (os.path.join(repo_root, 'data', 'style.css'), 'data'),
    (os.path.join(repo_root, 'data', 'gschemas.compiled'), 'share/glib-2.0/schemas'),
    (os.path.join(repo_root, 'data', 'gschemas.compiled'), 'data'),
    (os.path.join(repo_root, 'data', 'icons'), 'share/icons'),
    (os.path.join(repo_root, 'data', 'icons'), 'data/icons'),
]

for icon_base in ['/opt/homebrew/share/icons', '/usr/local/share/icons']:
    if os.path.isdir(icon_base):
        for theme in ['Adwaita', 'hicolor']:
            theme_path = os.path.join(icon_base, theme)
            if os.path.isdir(theme_path):
                datas.append((theme_path, f'share/icons/{theme}'))
        break

binaries = []

hiddenimports = [
    'showberry',
    'showberry.main',
    'showberry.application',
    'showberry.window',
    'showberry.providers',
    'showberry.providers.base',
    'showberry.providers.cinejoy',
    'showberry.providers.cinesrc',
    'showberry.providers.movy',
    'showberry.providers.primewire',
    'showberry.providers.superembed',
    'showberry.providers.torrent',
    'showberry.providers.vidfast',
    'showberry.providers.vidlink',
    'showberry.providers.vidnest',
    'showberry.providers.vidrift',
    'showberry.providers.vidsrc',
    'showberry.providers.vidy',
    'showberry.providers.vidzee',
    'showberry.providers.vixsrc',
    'showberry.services',
    'showberry.services.database',
    'showberry.services.image_cache',
    'showberry.services.settings',
    'showberry.services.subtitles',
    'showberry.services.tmdb',
    'showberry.services.torrent',
    'showberry.ui',
    'showberry.ui.browse_page',
    'showberry.ui.library_page',
    'showberry.ui.movie_card',
    'showberry.ui.movie_page',
    'showberry.ui.movies_page',
    'showberry.ui.person_page',
    'showberry.ui.player_page',
    'showberry.ui.search_page',
    'showberry.ui.series_page',
    'showberry.ui.settings_page',
    'showberry.ui.stream_dialogs',
    'showberry.ui.watchlist_page',
    'curl_cffi',
    'Crypto',
    'cryptography',
    'cryptography.hazmat.primitives.asymmetric.ec',
    'cryptography.hazmat.primitives.serialization',
    'cryptography.hazmat.primitives.kdf.hkdf',
    'cryptography.hazmat.primitives.hashes',
    'cryptography.hazmat.primitives.ciphers.aead',
    'cryptography.hazmat.backends.openssl',
    'cryptography.hazmat.backends.default_backend',
    'mpv',
    'OpenGL',
    'PIL',
    'requests',
    'sqlite3',
    'libtorrent',
]

a = Analysis(
    [os.path.join(repo_root, 'showberry', 'main.py')],
    pathex=[repo_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={
        'gi': {
            'icons': ['Adwaita'],
            'themes': ['Adwaita'],
            'module-versions': {
                'Gtk': '4.0',
                'Adw': '1'
            }
        }
    },
    runtime_hooks=[],
    excludes=['tkinter', 'unittest'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='showberry',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='showberry',
)
