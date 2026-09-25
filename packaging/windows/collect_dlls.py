#!/usr/bin/env python3
"""
Recursively collect and copy all MSYS2 DLL dependencies into the PyInstaller distribution.
Ensures libmpv-2.dll and all its transitive dependencies (FFmpeg, libass, libplacebo, etc.)
are bundled alongside showberry.exe and inside _internal.
"""

import os
import sys
import re
import shutil
import subprocess
from pathlib import Path


def get_dll_deps(dll_path):
    """Extract imported DLL names using objdump."""
    try:
        out = subprocess.check_output(
            ['objdump', '-p', str(dll_path)],
            stderr=subprocess.DEVNULL
        ).decode('utf-8', errors='ignore')
        return [m.group(1) for m in re.finditer(r'DLL Name:\s*(\S+)', out)]
    except Exception:
        return []


def main():
    repo_root = Path(__file__).resolve().parent.parent.parent
    dist_dir = repo_root / 'dist' / 'showberry'
    internal_dir = dist_dir / '_internal'

    if not dist_dir.is_dir():
        print(f"Error: dist directory not found: {dist_dir}")
        sys.exit(1)

    # Detect MSYS2 / UCRT64 bin directory
    bin_candidates = [
        Path('/ucrt64/bin'),
        Path(sys.prefix) / 'bin',
        Path('C:/msys64/ucrt64/bin'),
        Path('D:/a/_temp/msys64/ucrt64/bin'),
    ]
    bin_dir = None
    for cand in bin_candidates:
        if (cand / 'libmpv-2.dll').exists():
            bin_dir = cand
            break

    if not bin_dir:
        mingw_prefix = os.environ.get('MINGW_PREFIX')
        if mingw_prefix and (Path(mingw_prefix) / 'bin' / 'libmpv-2.dll').exists():
            bin_dir = Path(mingw_prefix) / 'bin'

    if not bin_dir:
        print("WARNING: Could not locate MSYS2 bin directory with libmpv-2.dll.")
        return

    print(f"==> MSYS2 bin directory found: {bin_dir}")

    # Step 1: Ensure libmpv-2.dll is copied to both dist_dir and _internal
    mpv_src = bin_dir / 'libmpv-2.dll'
    print(f"==> Copying root {mpv_src.name} to bundle...")
    shutil.copy2(mpv_src, dist_dir)
    if internal_dir.is_dir():
        shutil.copy2(mpv_src, internal_dir)

    # Step 2: Queue all binaries in dist_dir to find their transitive dependencies
    queue = [mpv_src]
    for p in dist_dir.rglob('*'):
        if p.is_file() and p.suffix.lower() in ('.dll', '.exe', '.pyd'):
            queue.append(p)

    visited_paths = set()
    copied_dlls = set()

    print("==> Recursively scanning and collecting DLL dependencies...")
    while queue:
        curr = queue.pop(0)
        norm_key = str(curr).lower()
        if norm_key in visited_paths:
            continue
        visited_paths.add(norm_key)

        for dep_name in get_dll_deps(curr):
            dep_key = dep_name.lower()
            dep_src = bin_dir / dep_name

            # If dependency exists in MSYS2 bin and hasn't been bundled yet
            if dep_src.is_file() and dep_key not in copied_dlls:
                copied_dlls.add(dep_key)

                # Copy to dist_dir root
                shutil.copy2(dep_src, dist_dir)
                # Also copy to _internal if it exists
                if internal_dir.is_dir():
                    shutil.copy2(dep_src, internal_dir)

                # Queue the newly found DLL to discover its dependencies
                queue.append(dep_src)

    print(f"==> Successfully bundled {len(copied_dlls)} additional MSYS2 DLL dependencies!")

    # Step 2b: Ensure ANGLE / EGL DLLs are bundled (required by GTK4 GLArea on Windows)
    egl_dlls = ['libEGL.dll', 'libGLESv2.dll', 'd3dcompiler_47.dll']
    windir = Path(os.environ.get('WINDIR', 'C:/Windows'))
    angle_search_dirs = [
        bin_dir,
        Path('C:/Windows/System32/Microsoft-Edge-WebView'),
        windir / 'System32' / 'Microsoft-Edge-WebView',
        windir / 'System32',
    ]
    for dll_name in egl_dlls:
        for sdir in angle_search_dirs:
            candidate = sdir / dll_name
            if candidate.is_file():
                print(f"==> Bundling EGL/ANGLE component: {candidate}")
                shutil.copy2(candidate, dist_dir)
                if internal_dir.is_dir():
                    shutil.copy2(candidate, internal_dir)
                break

    # Step 3: Ensure GSettings schemas and style.css are present in distribution
    schemas_src = repo_root / 'data'
    target_schema_dirs = [
        dist_dir / 'share' / 'glib-2.0' / 'schemas',
        dist_dir / 'data',
    ]
    if internal_dir.is_dir():
        target_schema_dirs.extend([
            internal_dir / 'share' / 'glib-2.0' / 'schemas',
            internal_dir / 'data',
        ])
    for target in target_schema_dirs:
        target.mkdir(parents=True, exist_ok=True)
        for fname in ('io.github.Dackerie.Showberry.gschema.xml', 'gschemas.compiled', 'style.css'):
            src_f = schemas_src / fname
            if src_f.is_file():
                shutil.copy2(src_f, target)

    print("==> Successfully bundled GSettings schemas and style files into Windows distribution!")

    # Step 4: Ensure gdk-pixbuf loaders and loaders.cache are present at root and internal
    msys_lib = bin_dir.parent / 'lib'
    msys_loaders_dir = msys_lib / 'gdk-pixbuf-2.0' / '2.10.0' / 'loaders'
    msys_cache = msys_lib / 'gdk-pixbuf-2.0' / '2.10.0' / 'loaders.cache'

    target_lib_dirs = [dist_dir / 'lib' / 'gdk-pixbuf' / 'loaders']
    if internal_dir.is_dir():
        target_lib_dirs.append(internal_dir / 'lib' / 'gdk-pixbuf' / 'loaders')

    for t_loaders in target_lib_dirs:
        t_loaders.mkdir(parents=True, exist_ok=True)
        if msys_loaders_dir.is_dir():
            for f in msys_loaders_dir.glob('*.dll'):
                shutil.copy2(f, t_loaders)
        if msys_cache.is_file():
            shutil.copy2(msys_cache, t_loaders.parent / 'loaders.cache')

    if internal_dir.is_dir() and (internal_dir / 'lib').is_dir():
        shutil.copytree(internal_dir / 'lib', dist_dir / 'lib', dirs_exist_ok=True)

    # Step 5: Ensure Adwaita, AdwaitaLegacy, and hicolor icon themes are mirrored
    msys_icons = bin_dir.parent / 'share' / 'icons'
    if msys_icons.is_dir():
        for theme in ('Adwaita', 'AdwaitaLegacy', 'hicolor'):
            theme_src = msys_icons / theme
            if theme_src.is_dir():
                for target_share in [dist_dir / 'share' / 'icons', internal_dir / 'share' / 'icons']:
                    target_theme = target_share / theme
                    if not target_theme.is_dir():
                        shutil.copytree(theme_src, target_theme, dirs_exist_ok=True)

    print("==> Successfully bundled gdk-pixbuf loaders and icon themes into Windows distribution!")


if __name__ == '__main__':
    main()
