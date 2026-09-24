"""Showberry background services."""

import sys
from typing import Any

__all__ = [
    'TMDBClient',
    'DatabaseService',
    'ImageCache',
    'SettingsService',
    'SubtitleService',
    'setup_logging',
    'get_log_dir',
    'get_log_file',
    'open_log_folder',
]


def __getattr__(name: str) -> Any:
    if name == 'TMDBClient':
        from showberry.services.tmdb import TMDBClient
        return TMDBClient
    elif name == 'DatabaseService':
        from showberry.services.database import DatabaseService
        return DatabaseService
    elif name == 'ImageCache':
        from showberry.services.image_cache import ImageCache
        return ImageCache
    elif name == 'SettingsService':
        from showberry.services.settings import SettingsService
        return SettingsService
    elif name == 'SubtitleService':
        from showberry.services.subtitles import SubtitleService
        return SubtitleService
    elif name in ('setup_logging', 'get_log_dir', 'get_log_file', 'open_log_folder'):
        import showberry.services.logger as _logger
        return getattr(_logger, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

