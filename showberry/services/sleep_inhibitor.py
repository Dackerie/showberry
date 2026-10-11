"""Cross-platform service to prevent screen and system sleep during media playback."""

from __future__ import annotations

import atexit
import logging
import subprocess
import sys
import threading
from typing import Callable, Optional

try:
    import gi
    try:
        gi.require_version('Gtk', '4.0')
    except Exception:
        pass
    from gi.repository import Gio, GLib, Gtk
except Exception:
    Gio = None
    GLib = None
    Gtk = None

logger = logging.getLogger(__name__)

# Windows Win32 Execution State Flags
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


class SleepInhibitor:
    """Manages display and system sleep inhibition across Linux, Windows, and macOS."""

    def __init__(self, window_getter: Optional[Callable[[], Optional[Any]]] = None):
        """
        Args:
            window_getter: Optional callable returning the active top-level Gtk.Window
                           for platforms/APIs that attach inhibition to a specific window.
        """
        self._window_getter = window_getter
        self._is_inhibited = False
        self._lock = threading.Lock()

        # Linux (GTK Application Inhibit)
        self._inhibit_cookie: Optional[int] = None

        # Windows
        self._win_heartbeat_id: Optional[int] = None

        # macOS (caffeinate process)
        self._caffeinate_proc: Optional[subprocess.Popen] = None

        # Ensure cleanup on abnormal process termination
        atexit.register(self.uninhibit)

    @property
    def is_inhibited(self) -> bool:
        """Return True if display sleep is currently prevented."""
        return self._is_inhibited

    def inhibit(self) -> None:
        """Prevent display and system sleep (called when video playback starts or resumes)."""
        with self._lock:
            if self._is_inhibited:
                return

            if sys.platform == 'win32':
                self._inhibit_windows()
            elif sys.platform == 'darwin':
                self._inhibit_macos()
            else:
                self._inhibit_linux()

            self._is_inhibited = True
            logger.info("Display sleep inhibited for playback")

    def uninhibit(self) -> None:
        """Restore normal display sleep behavior (called on pause, stop, or exit)."""
        with self._lock:
            if not self._is_inhibited:
                return

            if sys.platform == 'win32':
                self._uninhibit_windows()
            elif sys.platform == 'darwin':
                self._uninhibit_macos()
            else:
                self._uninhibit_linux()

            self._is_inhibited = False
            logger.info("Display sleep restored to system defaults")

    # -------------------------------------------------------------------------
    # Windows implementation (Win32 SetThreadExecutionState)
    # -------------------------------------------------------------------------
    def _inhibit_windows(self) -> None:
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(
                _ES_CONTINUOUS | _ES_DISPLAY_REQUIRED | _ES_SYSTEM_REQUIRED
            )
            # Periodic heartbeat (every 30 seconds) to ensure long movies are never interrupted
            if GLib and hasattr(GLib, 'timeout_add_seconds'):
                self._win_heartbeat_id = GLib.timeout_add_seconds(30, self._on_win_heartbeat)
            logger.debug("Windows display sleep inhibited via SetThreadExecutionState")
        except Exception as e:
            logger.warning("Failed to inhibit Windows display sleep: %s", e)

    def _on_win_heartbeat(self) -> bool:
        """Reinforce the display required state periodically on Windows."""
        if not self._is_inhibited:
            self._win_heartbeat_id = None
            return False
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(
                _ES_CONTINUOUS | _ES_DISPLAY_REQUIRED | _ES_SYSTEM_REQUIRED
            )
        except Exception:
            pass
        return True

    def _uninhibit_windows(self) -> None:
        if self._win_heartbeat_id is not None:
            if GLib and hasattr(GLib, 'source_remove'):
                GLib.source_remove(self._win_heartbeat_id)
            self._win_heartbeat_id = None
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
            logger.debug("Windows display sleep uninhibited")
        except Exception as e:
            logger.warning("Failed to uninhibit Windows display sleep: %s", e)

    # -------------------------------------------------------------------------
    # macOS implementation (caffeinate subprocess)
    # -------------------------------------------------------------------------
    def _inhibit_macos(self) -> None:
        try:
            # -d: prevent display sleep
            # -u: declare user activity assertion
            self._caffeinate_proc = subprocess.Popen(
                ['caffeinate', '-d', '-u'],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.debug("macOS display sleep inhibited via caffeinate (pid=%s)", self._caffeinate_proc.pid)
        except Exception as e:
            logger.warning("Failed to inhibit macOS sleep via caffeinate: %s", e)
            self._caffeinate_proc = None

    def _uninhibit_macos(self) -> None:
        if self._caffeinate_proc is not None:
            try:
                self._caffeinate_proc.terminate()
                self._caffeinate_proc.wait(timeout=0.5)
            except Exception:
                try:
                    self._caffeinate_proc.kill()
                except Exception:
                    pass
            self._caffeinate_proc = None
            logger.debug("macOS caffeinate terminated")

    # -------------------------------------------------------------------------
    # Linux implementation (Gtk.Application inhibit + FreeDesktop fallback)
    # -------------------------------------------------------------------------
    def _inhibit_linux(self) -> None:
        app = None
        if Gio:
            try:
                app = Gio.Application.get_default()
            except Exception:
                pass
        if not app and Gtk:
            try:
                app = Gtk.Application.get_default()
            except Exception:
                pass

        if app and hasattr(app, 'inhibit') and hasattr(app, 'get_is_registered') and app.get_is_registered():
            try:
                window = self._window_getter() if self._window_getter else None
                flags = Gtk.ApplicationInhibitFlags.IDLE | Gtk.ApplicationInhibitFlags.SUSPEND
                self._inhibit_cookie = app.inhibit(window, flags, "Showberry video playback")
                logger.debug("Linux display sleep inhibited via Gtk.Application (cookie=%s)", self._inhibit_cookie)
                return
            except Exception as e:
                logger.warning("Failed to inhibit sleep via Gtk.Application: %s", e)

        # Fallback: DBus call to org.freedesktop.ScreenSaver if available
        if Gio and hasattr(Gio, 'DBusProxy'):
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                res = bus.call_sync(
                    "org.freedesktop.ScreenSaver",
                    "/org/freedesktop/ScreenSaver",
                    "org.freedesktop.ScreenSaver",
                    "Inhibit",
                    GLib.Variant("(ss)", ("Showberry", "Showberry video playback")),
                    GLib.VariantType("(u)"),
                    Gio.DBusCallFlags.NONE,
                    1000,
                    None,
                )
                if res:
                    self._inhibit_cookie = res.unpack()[0]
                    logger.debug("Linux display sleep inhibited via ScreenSaver DBus (cookie=%s)", self._inhibit_cookie)
            except Exception as e:
                logger.debug("DBus ScreenSaver inhibit fallback unavailable: %s", e)

    def _uninhibit_linux(self) -> None:
        if self._inhibit_cookie is not None:
            app = None
            if Gio:
                try:
                    app = Gio.Application.get_default()
                except Exception:
                    pass
            if not app and Gtk:
                try:
                    app = Gtk.Application.get_default()
                except Exception:
                    pass

            if app and hasattr(app, 'uninhibit') and (not hasattr(app, 'get_is_registered') or app.get_is_registered()):
                try:
                    app.uninhibit(self._inhibit_cookie)
                    logger.debug("Linux display sleep uninhibited via Gtk.Application (cookie=%s)", self._inhibit_cookie)
                    self._inhibit_cookie = None
                    return
                except Exception as e:
                    logger.warning("Failed to uninhibit via Gtk.Application: %s", e)

            # DBus UnInhibit fallback
            if Gio and hasattr(Gio, 'DBusProxy'):
                try:
                    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                    bus.call_sync(
                        "org.freedesktop.ScreenSaver",
                        "/org/freedesktop/ScreenSaver",
                        "org.freedesktop.ScreenSaver",
                        "UnInhibit",
                        GLib.Variant("(u)", (self._inhibit_cookie,)),
                        None,
                        Gio.DBusCallFlags.NONE,
                        1000,
                        None,
                    )
                    logger.debug("Linux display sleep uninhibited via ScreenSaver DBus")
                except Exception as e:
                    logger.debug("DBus ScreenSaver uninhibit fallback unavailable: %s", e)

            self._inhibit_cookie = None
