"""Main application class for Showberry."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gio, Adw, Gdk, GLib
import logging
from pathlib import Path

from showberry.window import ShowberryWindow, KinemaWindow

logger = logging.getLogger(__name__)


class ShowberryApplication(Adw.Application):
    """The main application singleton."""

    def __init__(self):
        super().__init__(
            application_id='io.github.Dackerie.Showberry',
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.set_resource_base_path('/com/github/showberry/Showberry')

        schema_source = Gio.SettingsSchemaSource.get_default()
        schema = schema_source.lookup('io.github.Dackerie.Showberry', True) if schema_source else None
        if not schema:
            import sys
            candidate_schema_dirs = [
                Path(GLib.get_user_data_dir()) / 'glib-2.0' / 'schemas',
                Path(__file__).parent.parent / 'data',
                Path(__file__).parent / 'data',
            ]
            if getattr(sys, 'frozen', False):
                bundle_dir = getattr(sys, '_MEIPASS', Path(sys.executable).parent)
                candidate_schema_dirs.insert(0, Path(bundle_dir) / 'share' / 'glib-2.0' / 'schemas')
                candidate_schema_dirs.insert(0, Path(bundle_dir) / 'data')
                candidate_schema_dirs.insert(0, Path(sys.executable).parent / 'share' / 'glib-2.0' / 'schemas')
                candidate_schema_dirs.insert(0, Path(sys.executable).parent / 'data')

            for s_dir in candidate_schema_dirs:
                if (s_dir / 'gschemas.compiled').exists():
                    schema_source = Gio.SettingsSchemaSource.new_from_directory(
                        str(s_dir),
                        schema_source,
                        False
                    )
                    schema = schema_source.lookup('io.github.Dackerie.Showberry', True) if schema_source else None
                    if schema:
                        break

        if schema:
            self.settings = Gio.Settings.new_full(schema, None, None)
        else:
            self.settings = None
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._load_css()
        self._setup_icon_theme()
        self._setup_accelerators()

    def _setup_icon_theme(self):
        """Ensure bundled and system icon directories are registered with Gtk.IconTheme."""
        import sys
        try:
            display = Gdk.Display.get_default()
            if not display:
                return
            icon_theme = Gtk.IconTheme.get_for_display(display)
            search_paths = [
                Path(__file__).parent / 'data' / 'icons',
                Path(__file__).parent.parent / 'data' / 'icons',
                Path('/app/share/icons'),
                Path('/usr/share/icons'),
                Path('/usr/local/share/icons'),
                Path('/opt/homebrew/share/icons'),
                Path('/ucrt64/share/icons'),
            ]
            if getattr(sys, 'frozen', False):
                bundle_dir = getattr(sys, '_MEIPASS', Path(sys.executable).parent)
                exe_dir = Path(sys.executable).parent
                search_paths.insert(0, Path(bundle_dir) / 'share' / 'icons')
                search_paths.insert(0, Path(bundle_dir) / 'data' / 'icons')
                search_paths.insert(0, exe_dir / 'share' / 'icons')
                search_paths.insert(0, exe_dir / 'data' / 'icons')
                search_paths.insert(0, exe_dir.parent / 'Resources' / 'share' / 'icons')
                search_paths.insert(0, exe_dir.parent / 'Resources' / 'showberry' / 'share' / 'icons')

            for p in search_paths:
                if p.exists() and p.is_dir():
                    icon_theme.add_search_path(str(p))
        except Exception as e:
            logger.warning(f"Error configuring icon theme search paths: {e}")

    def _setup_accelerators(self):
        self.set_accels_for_action("win.shortcuts", ["<Ctrl>question", "<Ctrl>slash"])
        self.set_accels_for_action("win.preferences", ["<Ctrl>comma"])
        self.set_accels_for_action("win.fullscreen", ["F11"])
        self.set_accels_for_action("win.back", ["<Alt>Left"])
        self.set_accels_for_action("win.search", ["<Ctrl>f"])
        self.set_accels_for_action("win.tab_library", ["<Ctrl>1"])
        self.set_accels_for_action("win.tab_movies", ["<Ctrl>2"])
        self.set_accels_for_action("win.tab_series", ["<Ctrl>3"])
        self.set_accels_for_action("win.tab_next", ["<Ctrl>Page_Down", "<Ctrl>Tab"])
        self.set_accels_for_action("win.tab_prev", ["<Ctrl>Page_Up", "<Ctrl><Shift>Tab"])

    def _load_css(self):
        """Load application CSS stylesheet."""
        import sys
        candidate_paths = [
            Path(__file__).parent / 'data' / 'style.css',
            Path(__file__).parent / 'style.css',
            Path(__file__).parent.parent / 'data' / 'style.css',
            Path('/app/share/showberry/style.css'),
            Path(GLib.get_user_data_dir()) / 'showberry' / 'style.css',
            Path('/usr/share/showberry/style.css'),
            Path('/usr/local/share/showberry/style.css'),
        ]
        if getattr(sys, 'frozen', False):
            bundle_dir = getattr(sys, '_MEIPASS', Path(sys.executable).parent)
            candidate_paths.insert(0, Path(bundle_dir) / 'showberry' / 'data' / 'style.css')
            candidate_paths.insert(0, Path(bundle_dir) / 'data' / 'style.css')
            candidate_paths.insert(0, Path(sys.executable).parent / 'data' / 'style.css')
            candidate_paths.insert(0, Path(sys.executable).parent / 'showberry' / 'data' / 'style.css')

        provider = None
        for p in candidate_paths:
            if p.exists():
                provider = Gtk.CssProvider()
                provider.load_from_path(str(p))
                logger.info(f"Loaded CSS stylesheet from {p}")
                break

        if provider:
            display = Gdk.Display.get_default()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
        else:
            logger.warning("No CSS stylesheet found in any candidate path!")


    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = ShowberryWindow(application=self)
            self.window = win

        # Restore window state
        if self.settings:
            schema = self.settings.get_property('settings-schema')
            keys = schema.list_keys() if schema else []
            if 'window-width' in keys and 'window-height' in keys:
                width = self.settings.get_int('window-width')
                height = self.settings.get_int('window-height')
                win.set_default_size(width, height)
            if 'is-maximized' in keys and self.settings.get_boolean('is-maximized'):
                win.maximize()

        win.present()

    def get_settings(self):
        return self.settings

# Backwards compatibility alias
KinemaApplication = ShowberryApplication
