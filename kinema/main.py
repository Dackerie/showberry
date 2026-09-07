#!/usr/bin/env python3
"""Kinema - A movie browser and player for GNOME."""

import os
import sys
import locale

# Force modern OpenGL renderer to eliminate Vulkan swapchain stalls with GLArea
os.environ.setdefault('GSK_RENDERER', 'gl')

# Preload libcurl-impersonate with RTLD_GLOBAL to avoid symbol collision with libmpv's libcurl
try:
    import ctypes
    for _lib in ('/usr/lib/libcurl-impersonate.so.4', '/usr/lib64/libcurl-impersonate.so.4', '/usr/local/lib/libcurl-impersonate.so.4'):
        if os.path.exists(_lib):
            ctypes.CDLL(_lib, mode=ctypes.RTLD_GLOBAL)
            break
except Exception:
    pass

# GTK stomps over locale settings needed by libmpv
locale.setlocale(locale.LC_NUMERIC, 'C')

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gio, GLib
from kinema.application import KinemaApplication


def main():
    app = KinemaApplication()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
