"""SQLite Database service for watch history and watchlist persistence."""

import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from gi.repository import GLib

logger = logging.getLogger(__name__)


class DatabaseService:
    """Local SQLite database for watch progress, history, and watchlist."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        if hasattr(self, '_initialized') and self._initialized:
            return

        if db_path is None:
            data_dir = Path(GLib.get_user_data_dir()) / 'showberry'
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / 'showberry.db')

            # Migrate legacy database if it exists
            legacy_db = Path(GLib.get_user_data_dir()) / 'kinema' / 'kinema.db'
            if not Path(db_path).exists() and legacy_db.exists():
                try:
                    import shutil
                    shutil.copy2(legacy_db, db_path)
                    logger.info("Migrated legacy database from %s to %s", legacy_db, db_path)
                except Exception as e:
                    logger.warning("Failed to migrate legacy database: %s", e)

        self._db_path = db_path
        self._init_db()
        self._initialized = True

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        """Create database tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watch_history (
                    tmdb_id INTEGER PRIMARY KEY,
                    media_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    poster_path TEXT,
                    poster_url TEXT,
                    backdrop_url TEXT,
                    season INTEGER,
                    episode INTEGER,
                    progress_seconds REAL DEFAULT 0,
                    duration_seconds REAL DEFAULT 0,
                    updated_at REAL NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    tmdb_id INTEGER PRIMARY KEY,
                    media_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    poster_path TEXT,
                    poster_url TEXT,
                    backdrop_url TEXT,
                    overview TEXT,
                    release_date TEXT,
                    vote_average REAL DEFAULT 0,
                    added_at REAL NOT NULL
                )
            """)

            # Safe migrations for existing databases
            for migration in [
                "ALTER TABLE watchlist ADD COLUMN overview TEXT",
                "ALTER TABLE watchlist ADD COLUMN backdrop_url TEXT",
                "ALTER TABLE watch_history ADD COLUMN overview TEXT",
                "ALTER TABLE watch_history ADD COLUMN stream_provider TEXT",
                "ALTER TABLE watch_history ADD COLUMN info_hash TEXT",
                "ALTER TABLE watch_history ADD COLUMN file_idx INTEGER",
            ]:
                try:
                    cursor.execute(migration)
                except Exception:
                    pass

            conn.commit()

    # --- Watch History Methods ---

    def update_watch_progress(
        self,
        tmdb_id: int,
        title: str,
        media_type: str = 'movie',
        poster_url: Optional[str] = None,
        backdrop_url: Optional[str] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        progress_seconds: float = 0,
        duration_seconds: float = 0,
        overview: Optional[str] = None,
        stream_provider: Optional[str] = None,
        info_hash: Optional[str] = None,
        file_idx: Optional[int] = None,
    ):
        """Record or update watch progress."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO watch_history (
                    tmdb_id, media_type, title, poster_url, backdrop_url,
                    season, episode, progress_seconds, duration_seconds, updated_at, overview,
                    stream_provider, info_hash, file_idx
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tmdb_id) DO UPDATE SET
                    media_type = excluded.media_type,
                    title = excluded.title,
                    poster_url = COALESCE(excluded.poster_url, watch_history.poster_url),
                    backdrop_url = COALESCE(excluded.backdrop_url, watch_history.backdrop_url),
                    season = excluded.season,
                    episode = excluded.episode,
                    progress_seconds = excluded.progress_seconds,
                    duration_seconds = excluded.duration_seconds,
                    updated_at = excluded.updated_at,
                    overview = COALESCE(excluded.overview, watch_history.overview),
                    stream_provider = COALESCE(excluded.stream_provider, watch_history.stream_provider),
                    info_hash = COALESCE(excluded.info_hash, watch_history.info_hash),
                    file_idx = COALESCE(excluded.file_idx, watch_history.file_idx)
            """, (
                tmdb_id, media_type, title, poster_url, backdrop_url,
                season, episode, progress_seconds, duration_seconds, time.time(), overview,
                stream_provider, info_hash, file_idx
            ))
            conn.commit()

    def get_watch_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent watch history, most recent first."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM watch_history
                WHERE progress_seconds > 10 AND (duration_seconds == 0 OR progress_seconds < duration_seconds * 0.95)
                ORDER BY updated_at DESC LIMIT ?
            """, (limit,))
            rows = []
            for r in cursor.fetchall():
                d = dict(r)
                d['id'] = d['tmdb_id']
                if d.get('poster_url'):
                    d['poster_url_small'] = d['poster_url']
                    d['poster_path'] = d['poster_url']
                if d.get('backdrop_url'):
                    d['backdrop_path'] = d['backdrop_url']
                rows.append(d)
            return rows

    def get_item_progress(self, tmdb_id: int) -> Optional[Dict[str, Any]]:
        """Get progress for a single title."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM watch_history WHERE tmdb_id = ?", (tmdb_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d['id'] = d['tmdb_id']
                if d.get('poster_url'):
                    d['poster_url_small'] = d['poster_url']
                    d['poster_path'] = d['poster_url']
                if d.get('backdrop_url'):
                    d['backdrop_path'] = d['backdrop_url']
                return d
            return None

    def delete_history_item(self, tmdb_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM watch_history WHERE tmdb_id = ?", (tmdb_id,))
            conn.commit()

    # --- Watchlist Methods ---

    def add_to_watchlist(
        self,
        tmdb_id: int,
        title: str,
        media_type: str = 'movie',
        poster_url: Optional[str] = None,
        release_date: Optional[str] = None,
        vote_average: float = 0.0,
        overview: Optional[str] = None,
        backdrop_url: Optional[str] = None,
    ):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO watchlist (
                    tmdb_id, media_type, title, poster_url, release_date, vote_average, added_at, overview, backdrop_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (tmdb_id, media_type, title, poster_url, release_date, vote_average, time.time(), overview, backdrop_url))
            conn.commit()

    def remove_from_watchlist(self, tmdb_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM watchlist WHERE tmdb_id = ?", (tmdb_id,))
            conn.commit()

    def is_in_watchlist(self, tmdb_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM watchlist WHERE tmdb_id = ?", (tmdb_id,))
            return cursor.fetchone() is not None

    def get_watchlist(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM watchlist ORDER BY added_at DESC LIMIT ?", (limit,))
            rows = []
            for r in cursor.fetchall():
                d = dict(r)
                d['id'] = d['tmdb_id']
                if d.get('poster_url'):
                    d['poster_url_small'] = d['poster_url']
                    d['poster_path'] = d['poster_url']
                if d.get('backdrop_url'):
                    d['backdrop_path'] = d['backdrop_url']
                rows.append(d)
            return rows
