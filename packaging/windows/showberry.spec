# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

datas = [
    (os.path.join(repo_root, 'showberry', 'data', 'style.css'), 'showberry/data'),
    (os.path.join(repo_root, 'data', 'style.css'), 'data'),
    (os.path.join(repo_root, 'data', 'gschemas.compiled'), 'share/glib-2.0/schemas'),
    (os.path.join(repo_root, 'data', 'gschemas.compiled'), 'data'),
    (os.path.join(repo_root, 'data', 'icons'), 'share/icons'),
    (os.path.join(repo_root, 'data', 'icons'), 'data/icons'),
]

binaries = []
# On MSYS2 UCRT64, bundle libmpv-2.dll and potential companion dlls if available
for candidate in [
    '/ucrt64/bin/libmpv-2.dll',
    'C:/msys64/ucrt64/bin/libmpv-2.dll',
]:
    if os.path.exists(candidate):
        binaries.append((candidate, '.'))
        break

hiddenimports = [
    'showberry',
    'showberry.main',
    'showberry.application',
    'showberry.window',
    'showberry.providers',
    'showberry.providers.base',
    'showberry.providers.superstream',
    'showberry.providers.torrent',
    'showberry.providers.twoembed',
    'showberry.providers.vidsrcto',
    'showberry.providers.vidsrcxyz',
    'showberry.services',
    'showberry.services.database',
    'showberry.services.image_cache',
    'showberry.services.settings',
    'showberry.services.subtitles',
    'showberry.services.tmdb',
    'showberry.services.torrent',
    'showberry.ui',
    'showberry.ui.browse_page',
    'showberry.ui.details_page',
    'showberry.ui.home_page',
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
    'mpv',
    'OpenGL',
    'PIL',
    'requests',
    'sqlite3',
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
    icon=os.path.join(os.path.dirname(__file__), 'icon.ico'),
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
