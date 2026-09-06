"""Main application class for Kinema."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gio, Adw, Gdk
from pathlib import Path

from kinema.window import KinemaWindow


class KinemaApplication(Adw.Application):
    """The main application singleton."""

    def __init__(self):
        super().__init__(
            application_id='com.github.kinema.Kinema',
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.set_resource_base_path('/com/github/kinema/Kinema')

        schema_source = Gio.SettingsSchemaSource.get_default()
        schema = schema_source.lookup('com.github.kinema.Kinema', True) if schema_source else None
        if not schema:
            local_data = Path(__file__).parent.parent / 'data'
            if (local_data / 'gschemas.compiled').exists():
                schema_source = Gio.SettingsSchemaSource.new_from_directory(
                    str(local_data),
                    schema_source,
                    False
                )
                schema = schema_source.lookup('com.github.kinema.Kinema', True) if schema_source else None

        if schema:
            self.settings = Gio.Settings.new_full(schema, None, None)
        else:
            self.settings = None
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._load_css()

    def _load_css(self):
        """Load application CSS stylesheet."""
        candidate_paths = [
            Path(__file__).parent.parent / 'data' / 'style.css',
            Path('/app/share/kinema/style.css'),
            Path('/usr/share/kinema/style.css'),
            Path('/usr/local/share/kinema/style.css'),
        ]
        provider = None
        for p in candidate_paths:
            if p.exists():
                provider = Gtk.CssProvider()
                provider.load_from_path(str(p))
                break

        if provider:
            display = Gdk.Display.get_default()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )


    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = KinemaWindow(application=self)
            self.window = win

        # Restore window state
        if self.settings:
            width = self.settings.get_int('window-width')
            height = self.settings.get_int('window-height')
            maximized = self.settings.get_boolean('is-maximized')

            win.set_default_size(width, height)
            if maximized:
                win.maximize()

        win.present()

    def get_settings(self):
        return self.settings
