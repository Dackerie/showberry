#!/usr/bin/env python3
"""Showberry - A movie browser and player for GNOME."""

import os
import sys
import locale

# Force modern OpenGL renderer to eliminate Vulkan swapchain stalls with GLArea
os.environ.setdefault('GSK_RENDERER', 'gl')

# Preload libcurl-impersonate with RTLD_GLOBAL on Linux to avoid symbol collision with libmpv's libcurl
if sys.platform.startswith('linux'):
    try:
        import ctypes
        for _lib in ('/usr/lib/libcurl-impersonate.so.4', '/usr/lib64/libcurl-impersonate.so.4', '/usr/local/lib/libcurl-impersonate.so.4'):
            if os.path.exists(_lib):
                ctypes.CDLL(_lib, mode=ctypes.RTLD_GLOBAL)
                break
    except Exception:
        pass
elif sys.platform == 'win32':
    # Ensure current directory and exe directory are in PATH and Windows DLL search path (Python 3.8+)
    import ctypes
    import ctypes.util

    exe_dir = os.path.dirname(sys.executable)
    bundle_dir = getattr(sys, '_MEIPASS', exe_dir)
    internal_dir = os.path.join(exe_dir, '_internal')

    # Add directories to PATH and Windows DLL search path (Python 3.8+)
    search_dirs = [exe_dir, internal_dir, bundle_dir, os.getcwd()]
    for p in search_dirs:
        if p and os.path.isdir(p):
            abs_p = os.path.abspath(p)
            if hasattr(os, 'add_dll_directory'):
                try:
                    os.add_dll_directory(abs_p)
                except Exception:
                    pass
            if abs_p not in os.environ.get('PATH', ''):
                os.environ['PATH'] = abs_p + os.pathsep + os.environ.get('PATH', '')

    # Hook ctypes.util.find_library so python-mpv receives the exact absolute path to libmpv-2.dll
    _orig_find_library = ctypes.util.find_library
    def _win_find_library(name):
        if 'mpv' in name.lower():
            for d in (exe_dir, internal_dir, bundle_dir):
                if not d or not os.path.isdir(d):
                    continue
                for candidate in ('libmpv-2.dll', 'mpv-2.dll', 'mpv-1.dll', 'mpv.dll'):
                    cand_path = os.path.join(d, candidate)
                    if os.path.isfile(cand_path):
                        return os.path.abspath(cand_path)
        return _orig_find_library(name)
    ctypes.util.find_library = _win_find_library

elif sys.platform == 'darwin':
    import ctypes
    import ctypes.util

    # On macOS, search Homebrew and bundle paths for libmpv.dylib
    mac_paths = ['/opt/homebrew/lib', '/usr/local/lib']
    if getattr(sys, 'frozen', False):
        exe_parent = os.path.dirname(sys.executable)
        mac_paths.insert(0, exe_parent)
        mac_paths.insert(0, os.path.abspath(os.path.join(exe_parent, '..')))
        mac_paths.insert(0, os.path.abspath(os.path.join(exe_parent, '..', 'Resources')))
        mac_paths.insert(0, os.path.abspath(os.path.join(exe_parent, '..', 'Resources', 'showberry')))
        mac_paths.insert(0, os.path.abspath(os.path.join(exe_parent, '..', 'Frameworks')))
    existing_dyld = os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')
    for p in mac_paths:
        if os.path.exists(p) and p not in existing_dyld:
            existing_dyld = (p + os.pathsep + existing_dyld) if existing_dyld else p
    os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = existing_dyld
    os.environ['DYLD_LIBRARY_PATH'] = existing_dyld

    # Hook ctypes.util.find_library so python-mpv finds bundled or Homebrew libmpv.dylib
    _orig_find_library = ctypes.util.find_library
    def _mac_find_library(name):
        if 'mpv' in name.lower():
            for d in mac_paths:
                if not d or not os.path.isdir(d):
                    continue
                for candidate in ('libmpv.2.dylib', 'libmpv.dylib', 'mpv.dylib'):
                    cand_path = os.path.join(d, candidate)
                    if os.path.isfile(cand_path):
                        return os.path.abspath(cand_path)
        return _orig_find_library(name)
    ctypes.util.find_library = _mac_find_library

# GTK stomps over locale settings needed by libmpv
locale.setlocale(locale.LC_NUMERIC, 'C')

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gio, GLib
from showberry.application import ShowberryApplication


def main():
    app = ShowberryApplication()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
