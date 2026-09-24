"""Pytest configuration and global fixtures."""

import os
import sys
import ctypes
import tempfile
import pytest

# Ensure data directory and renderer settings are active for tests
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
data_dir = os.path.join(repo_root, 'data')
os.environ.setdefault('GSETTINGS_SCHEMA_DIR', data_dir)
os.environ.setdefault('GSK_RENDERER', 'cairo')

if sys.platform == 'darwin':
    # Pre-load core GLib / GObject / GTK4 / Libadwaita libraries into global namespace
    for lib_name in [
        'libglib-2.0.0.dylib',
        'libglib-2.0.dylib',
        'libgobject-2.0.0.dylib',
        'libgobject-2.0.dylib',
        'libgio-2.0.0.dylib',
        'libgirepository-1.0.1.dylib',
        'libgirepository-2.0.0.dylib',
        'libgtk-4.1.dylib',
        'libgtk-4.dylib',
        'libadwaita-1.0.dylib',
        'libadwaita-1.dylib',
    ]:
        for d in ['/opt/homebrew/lib', '/usr/local/lib']:
            cand = os.path.join(d, lib_name)
            if os.path.exists(cand):
                try:
                    ctypes.CDLL(cand, mode=ctypes.RTLD_GLOBAL)
                    break
                except Exception:
                    pass

from showberry.services.database import DatabaseService


@pytest.fixture(autouse=True)
def isolate_test_database(monkeypatch):
    """Ensure all tests run with an isolated temporary SQLite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = os.path.join(tmpdir, 'test_showberry.db')
        # Reset singleton instance so it binds to the temporary DB
        DatabaseService._instance = None
        db = DatabaseService(db_path=test_db_path)
        yield db
        DatabaseService._instance = None


@pytest.fixture(autouse=True)
def isolate_test_settings(monkeypatch):
    """Ensure all tests run with an isolated SettingsService instance."""
    from showberry.services.settings import SettingsService
    SettingsService._instance = None
    settings = SettingsService()
    yield settings
    SettingsService._instance = None

