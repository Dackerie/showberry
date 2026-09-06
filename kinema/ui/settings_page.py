"""Settings page - configure app preferences."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio

from kinema.services.settings import SettingsService
from kinema.providers import get_all_providers


class SettingsPage(Gtk.Box):
    """Settings page with preferences."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._settings = SettingsService()

        # Scrollable content
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        # Preferences page
        self._prefs_page = Adw.PreferencesPage()
        self._prefs_page.set_title('Settings')
        self._prefs_page.set_icon_name('emblem-system-symbolic')

        self._setup_general_group()
        self._setup_player_group()
        self._setup_about_group()

        scroll.set_child(self._prefs_page)
        self.append(scroll)

    def _setup_general_group(self):
        """Setup general settings group."""
        group = Adw.PreferencesGroup()
        group.set_title('General')
        group.set_description('General app settings')

        # TMDB API Key
        api_key_row = Adw.EntryRow()
        api_key_row.set_title('TMDB API Key')
        api_key_row.set_text(self._settings.tmdb_api_key)
        api_key_row.connect('notify::text', self._on_api_key_changed)
        group.add(api_key_row)

        # Theme variant
        theme_row = Adw.ComboRow()
        theme_row.set_title('Theme')
        theme_row.set_model(Gtk.StringList.new(['Default', 'Light', 'Dark']))
        theme_row.set_selected(self._get_theme_index())
        theme_row.connect('notify::selected', self._on_theme_changed)
        group.add(theme_row)

        self._prefs_page.add(group)

    def _setup_player_group(self):
        """Setup player settings group."""
        group = Adw.PreferencesGroup()
        group.set_title('Player')
        group.set_description('Video player settings')

        # Default provider
        providers = get_all_providers()
        provider_names = [p.name for p in providers]

        provider_row = Adw.ComboRow()
        provider_row.set_title('Default Provider')
        provider_row.set_model(Gtk.StringList.new(provider_names))

        # Find current provider index
        current_provider = self._settings.default_provider
        for i, p in enumerate(providers):
            if p.name.lower() == current_provider.lower():
                provider_row.set_selected(i)
                break

        provider_row.connect('notify::selected', self._on_provider_changed)
        group.add(provider_row)

        self._prefs_page.add(group)

    def _setup_about_group(self):
        """Setup about group."""
        group = Adw.PreferencesGroup()
        group.set_title('About')

        # App name
        app_row = Adw.ActionRow()
        app_row.set_title('Kinema')
        app_row.set_subtitle('A movie browser and player for GNOME')
        group.add(app_row)

        # Version
        version_row = Adw.ActionRow()
        version_row.set_title('Version')
        version_row.set_subtitle('0.1.0')
        group.add(version_row)

        # Help row with API key link
        help_row = Adw.ActionRow()
        help_row.set_title('Get TMDB API Key')
        help_row.set_subtitle('Register at themoviedb.org to get a free API key')
        help_row.set_activatable(True)
        help_row.connect('activated', self._on_help_clicked)
        group.add(help_row)

        self._prefs_page.add(group)

    def _get_theme_index(self):
        theme = self._settings.theme_variant
        return {'default': 0, 'light': 1, 'dark': 2}.get(theme, 0)

    def _on_api_key_changed(self, entry, pspec):
        self._settings.tmdb_api_key = entry.get_text()

    def _on_theme_changed(self, row, pspec):
        themes = ['default', 'light', 'dark']
        theme = themes[row.get_selected()]
        self._settings.theme_variant = theme
        self._apply_theme(theme)

    def _on_provider_changed(self, row, pspec):
        providers = get_all_providers()
        index = row.get_selected()
        if index < len(providers):
            self._settings.default_provider = providers[index].name

    def _apply_theme(self, theme):
        """Apply the selected theme."""
        app = Gtk.Application.get_default()
        if not app:
            return

        style_manager = Adw.StyleManager.get_default()
        if theme == 'light':
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        elif theme == 'dark':
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.DEFAULT)

    def _on_help_clicked(self, row):
        import subprocess
        subprocess.Popen(['xdg-open', 'https://www.themoviedb.org/settings/api'])
