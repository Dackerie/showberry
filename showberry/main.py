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
    # Ensure current directory and exe directory are in PATH so libmpv-2.dll and dependencies can be found
    exe_dir = os.path.dirname(sys.executable)
    bundle_dir = getattr(sys, '_MEIPASS', exe_dir)
    for p in (bundle_dir, exe_dir):
        if p and os.path.exists(p) and p not in os.environ.get('PATH', ''):
            os.environ['PATH'] = p + os.pathsep + os.environ.get('PATH', '')
elif sys.platform == 'darwin':
    # On macOS, search Homebrew and bundle paths for libmpv.dylib
    mac_paths = ['/opt/homebrew/lib', '/usr/local/lib']
    if getattr(sys, 'frozen', False):
        mac_paths.insert(0, os.path.join(os.path.dirname(sys.executable), '..', 'Resources'))
    existing_dyld = os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')
    for p in mac_paths:
        if os.path.exists(p) and p not in existing_dyld:
            existing_dyld = (p + os.pathsep + existing_dyld) if existing_dyld else p
    os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = existing_dyld

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
