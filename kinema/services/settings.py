"""Settings service wrapper for GSettings."""

import gi
gi.require_version('Gtk', '4.0')

from pathlib import Path
from gi.repository import Gio


class SettingsService:
    """Wrapper around GSettings for app preferences."""

    def __init__(self):
        schema_source = Gio.SettingsSchemaSource.get_default()
        schema = schema_source.lookup('com.github.kinema.Kinema', True) if schema_source else None
        if not schema:
            local_data = Path(__file__).parent.parent.parent / 'data'
            if (local_data / 'gschemas.compiled').exists():
                schema_source = Gio.SettingsSchemaSource.new_from_directory(
                    str(local_data),
                    schema_source,
                    False
                )
                schema = schema_source.lookup('com.github.kinema.Kinema', True) if schema_source else None

        if schema:
            self._settings = Gio.Settings.new_full(schema, None, None)
        else:
            self._settings = None
        self._fallback_store = {}

    @property
    def tmdb_api_key(self):
        if self._settings:
            return self._settings.get_string('tmdb-api-key')
        return self._fallback_store.get('tmdb-api-key', '')

    @tmdb_api_key.setter
    def tmdb_api_key(self, value):
        if self._settings:
            self._settings.set_string('tmdb-api-key', value)
        else:
            self._fallback_store['tmdb-api-key'] = value

    @property
    def default_provider(self):
        if self._settings:
            return self._settings.get_string('default-provider')
        return self._fallback_store.get('default-provider', 'VidEasy')

    @default_provider.setter
    def default_provider(self, value):
        if self._settings:
            self._settings.set_string('default-provider', value)
        else:
            self._fallback_store['default-provider'] = value

    @property
    def theme_variant(self):
        if self._settings:
            return self._settings.get_string('theme-variant')
        return self._fallback_store.get('theme-variant', 'dark')

    @theme_variant.setter
    def theme_variant(self, value):
        if self._settings:
            self._settings.set_string('theme-variant', value)
        else:
            self._fallback_store['theme-variant'] = value

    def get_settings(self):
        """Get the underlying GSettings object."""
        return self._settings
