"""Settings service wrapper for GSettings with persistent fallback."""

import json
import logging
from pathlib import Path
from typing import Any

from gi.repository import Gio, GLib

logger = logging.getLogger(__name__)


class SettingsService:
    """Wrapper around GSettings for app preferences with JSON file fallback."""
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        schema_source = Gio.SettingsSchemaSource.get_default()
        schema = schema_source.lookup('io.github.Dackerie.Showberry', True) if schema_source else None
        if not schema:
            import sys
            candidate_schema_dirs = [
                Path(GLib.get_user_data_dir()) / 'glib-2.0' / 'schemas',
                Path(__file__).parent.parent.parent / 'data',
                Path(__file__).parent.parent / 'data',
            ]
            if getattr(sys, 'frozen', False):
                bundle_dir = getattr(sys, '_MEIPASS', Path(sys.executable).parent)
                candidate_schema_dirs.insert(0, Path(bundle_dir) / 'share' / 'glib-2.0' / 'schemas')
                candidate_schema_dirs.insert(0, Path(bundle_dir) / 'data')
                candidate_schema_dirs.insert(0, Path(sys.executable).parent / 'share' / 'glib-2.0' / 'schemas')
                candidate_schema_dirs.insert(0, Path(sys.executable).parent / 'data')

            for s_dir in candidate_schema_dirs:
                if (s_dir / 'gschemas.compiled').exists():
                    try:
                        schema_source = Gio.SettingsSchemaSource.new_from_directory(
                            str(s_dir),
                            schema_source,
                            False
                        )
                        schema = schema_source.lookup('io.github.Dackerie.Showberry', True) if schema_source else None
                        if schema:
                            break
                    except Exception as e:
                        logger.debug("Failed checking schema dir %s: %s", s_dir, e)

        if schema:
            try:
                self._settings = Gio.Settings.new_full(schema, None, None)
            except Exception as e:
                logger.warning("Failed initializing Gio.Settings with schema: %s", e)
                self._settings = None
        else:
            self._settings = None

        config_dir = Path(GLib.get_user_config_dir()) / 'showberry'
        self._config_file = config_dir / 'settings.json'
        self._fallback_store = self._load_fallback_store()

    def _load_fallback_store(self) -> dict:
        if self._config_file.is_file():
            try:
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.debug("Could not read fallback settings JSON: %s", e)
        return {}

    def _set_fallback(self, key: str, value: Any):
        self._fallback_store[key] = value
        try:
            self._config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self._fallback_store, f, indent=2)
        except Exception as e:
            logger.debug("Could not write fallback settings JSON: %s", e)


    def _has_schema_key(self, key: str) -> bool:
        if not self._settings:
            return False
        try:
            schema = getattr(self._settings.props, 'settings_schema', None)
            return schema.has_key(key) if schema else False
        except Exception:
            return False

    @property
    def tmdb_api_key(self):
        if self._has_schema_key('tmdb-api-key'):
            return self._settings.get_string('tmdb-api-key')
        return self._fallback_store.get('tmdb-api-key', '')

    @tmdb_api_key.setter
    def tmdb_api_key(self, value):
        if self._has_schema_key('tmdb-api-key'):
            self._settings.set_string('tmdb-api-key', value)
        else:
            self._set_fallback('tmdb-api-key', value)

    @property
    def default_provider(self):
        if self._has_schema_key('default-provider'):
            return self._settings.get_string('default-provider')
        return self._fallback_store.get('default-provider', 'vidy')

    @default_provider.setter
    def default_provider(self, value):
        if self._has_schema_key('default-provider'):
            self._settings.set_string('default-provider', value)
        else:
            self._set_fallback('default-provider', value)

    @property
    def theme_variant(self):
        if self._has_schema_key('theme-variant'):
            try:
                val = self._settings.get_string('theme-variant')
                if val:
                    return val
            except Exception:
                pass
        return self._fallback_store.get('theme-variant', 'dark')

    @theme_variant.setter
    def theme_variant(self, value):
        if self._has_schema_key('theme-variant'):
            try:
                self._settings.set_string('theme-variant', value)
            except Exception:
                pass
        self._set_fallback('theme-variant', value)

    @property
    def hwdec_mode(self) -> str:
        if self._has_schema_key('hwdec-mode'):
            try:
                return self._settings.get_string('hwdec-mode')
            except Exception:
                pass
        return self._fallback_store.get('hwdec-mode', 'auto')

    @hwdec_mode.setter
    def hwdec_mode(self, value: str):
        if self._has_schema_key('hwdec-mode'):
            try:
                self._settings.set_string('hwdec-mode', value)
            except Exception:
                pass
        self._set_fallback('hwdec-mode', value)


    @property
    def preferred_torrent_quality(self) -> str:
        if self._settings:
            return self._settings.get_string('preferred-torrent-quality')
        return self._fallback_store.get('preferred-torrent-quality', '1080p')

    @preferred_torrent_quality.setter
    def preferred_torrent_quality(self, value: str):
        if self._settings:
            self._settings.set_string('preferred-torrent-quality', value)
        else:
            self._set_fallback('preferred-torrent-quality', value)

    @property
    def max_torrent_size_gb(self) -> int:
        if self._settings:
            return self._settings.get_int('max-torrent-size-gb')
        return self._fallback_store.get('max-torrent-size-gb', 0)

    @max_torrent_size_gb.setter
    def max_torrent_size_gb(self, value: int):
        if self._settings:
            self._settings.set_int('max-torrent-size-gb', value)
        else:
            self._set_fallback('max-torrent-size-gb', value)

    @property
    def torrent_cache_size_gb(self) -> int:
        if self._settings:
            return self._settings.get_int('torrent-cache-size-gb')
        return self._fallback_store.get('torrent-cache-size-gb', 10)

    @torrent_cache_size_gb.setter
    def torrent_cache_size_gb(self, value: int):
        if self._settings:
            self._settings.set_int('torrent-cache-size-gb', value)
        else:
            self._set_fallback('torrent-cache-size-gb', value)


    @property
    def sub_pos(self) -> int:
        if self._has_schema_key('sub-pos'):
            return self._settings.get_int('sub-pos')
        return self._fallback_store.get('sub-pos', 94)

    @sub_pos.setter
    def sub_pos(self, value: int):
        if self._has_schema_key('sub-pos'):
            self._settings.set_int('sub-pos', value)
        else:
            self._set_fallback('sub-pos', value)

    @property
    def sub_scale(self) -> float:
        if self._has_schema_key('sub-scale'):
            return self._settings.get_double('sub-scale')
        return self._fallback_store.get('sub-scale', 1.0)

    @sub_scale.setter
    def sub_scale(self, value: float):
        if self._has_schema_key('sub-scale'):
            self._settings.set_double('sub-scale', value)
        else:
            self._set_fallback('sub-scale', value)

    @property
    def auto_skip_enabled(self) -> bool:
        if self._has_schema_key('auto-skip-enabled'):
            return self._settings.get_boolean('auto-skip-enabled')
        return self._fallback_store.get('auto-skip-enabled', True)

    @auto_skip_enabled.setter
    def auto_skip_enabled(self, value: bool):
        if self._has_schema_key('auto-skip-enabled'):
            self._settings.set_boolean('auto-skip-enabled', value)
        else:
            self._set_fallback('auto-skip-enabled', value)

    @property
    def auto_skip_countdown(self) -> int:
        if self._has_schema_key('auto-skip-countdown'):
            return self._settings.get_int('auto-skip-countdown')
        return self._fallback_store.get('auto-skip-countdown', 10)

    @auto_skip_countdown.setter
    def auto_skip_countdown(self, value: int):
        if self._has_schema_key('auto-skip-countdown'):
            self._settings.set_int('auto-skip-countdown', value)
        else:
            self._set_fallback('auto-skip-countdown', value)

    def get_settings(self):
        """Get the underlying GSettings object."""
        return self._settings
