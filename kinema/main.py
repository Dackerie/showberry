#!/usr/bin/env python3
"""Kinema - A movie browser and player for GNOME."""

import os
import sys
import locale

# Force modern OpenGL renderer to eliminate Vulkan swapchain stalls with GLArea
os.environ.setdefault('GSK_RENDERER', 'gl')

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
