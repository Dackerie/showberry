"""Tests for SQLite DatabaseService."""

import os
import tempfile
import unittest
from kinema.services.database import DatabaseService


class TestDatabaseService(unittest.TestCase):

    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp_db.close()
        # Create fresh instance with temporary database path
        DatabaseService._instance = None
        self.db = DatabaseService(db_path=self.tmp_db.name)

    def tearDown(self):
        if os.path.exists(self.tmp_db.name):
            os.unlink(self.tmp_db.name)
        DatabaseService._instance = None

    def test_watch_history(self):
        self.db.update_watch_progress(
            tmdb_id=550,
            title="Fight Club",
            media_type="movie",
            progress_seconds=120.5,
            duration_seconds=8340.0,
            overview="An insomniac office worker...",
            backdrop_url="https://image.tmdb.org/t/p/w1280/backdrop.jpg",
            poster_url="https://image.tmdb.org/t/p/w500/poster.jpg"
        )

        item = self.db.get_item_progress(550)
        self.assertIsNotNone(item)
        self.assertEqual(item['title'], "Fight Club")
        self.assertEqual(item['id'], 550)
        self.assertEqual(item['poster_url_small'], "https://image.tmdb.org/t/p/w500/poster.jpg")
        self.assertEqual(item['poster_path'], "https://image.tmdb.org/t/p/w500/poster.jpg")
        self.assertEqual(item['backdrop_path'], "https://image.tmdb.org/t/p/w1280/backdrop.jpg")
        self.assertEqual(item['overview'], "An insomniac office worker...")
        self.assertAlmostEqual(item['progress_seconds'], 120.5)

        history = self.db.get_watch_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['tmdb_id'], 550)
        self.assertEqual(history[0]['id'], 550)
        self.assertEqual(history[0]['overview'], "An insomniac office worker...")

        self.db.delete_history_item(550)
        self.assertIsNone(self.db.get_item_progress(550))

    def test_watchlist(self):
        self.assertFalse(self.db.is_in_watchlist(1396))

        self.db.add_to_watchlist(
            tmdb_id=1396,
            title="Breaking Bad",
            media_type="tv",
            vote_average=9.5,
            overview="A chemistry teacher diagnosed with cancer...",
            poster_url="https://image.tmdb.org/t/p/w500/bb.jpg",
            backdrop_url="https://image.tmdb.org/t/p/w1280/bb_back.jpg"
        )
        self.assertTrue(self.db.is_in_watchlist(1396))

        watchlist = self.db.get_watchlist()
        self.assertEqual(len(watchlist), 1)
        self.assertEqual(watchlist[0]['title'], "Breaking Bad")
        self.assertEqual(watchlist[0]['id'], 1396)
        self.assertEqual(watchlist[0]['poster_url_small'], "https://image.tmdb.org/t/p/w500/bb.jpg")
        self.assertEqual(watchlist[0]['poster_path'], "https://image.tmdb.org/t/p/w500/bb.jpg")
        self.assertEqual(watchlist[0]['backdrop_path'], "https://image.tmdb.org/t/p/w1280/bb_back.jpg")
        self.assertEqual(watchlist[0]['overview'], "A chemistry teacher diagnosed with cancer...")

        self.db.remove_from_watchlist(1396)
        self.assertFalse(self.db.is_in_watchlist(1396))


if __name__ == '__main__':
    unittest.main()
