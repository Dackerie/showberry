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


if __name__ == '__main__':
    main()
