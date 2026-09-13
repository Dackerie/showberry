"""Pytest configuration and global fixtures."""

import os
import tempfile
import pytest
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
