"""Unit tests for round 3 fixes and enhancements."""

import tempfile
import unittest
from unittest.mock import MagicMock, patch
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from showberry.services.database import DatabaseService
from showberry.ui.player_page import PlayerPage
from showberry.ui.movie_card import MovieCard
from showberry.ui.library_page import LibraryPage


class TestEnhancementsRound3(unittest.TestCase):

    def setUp(self):
        # Use an isolated temporary database for tests
        self.temp_db_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db = DatabaseService(db_path=self.temp_db_file.name)

    def tearDown(self):
        try:
            self.temp_db_file.close()
        except Exception:
            pass

    def test_provider_pill_flat_class(self):
        """Verify the top OSC provider pill menu button has 'flat' and 'provider-pill-btn' classes."""
        pp = PlayerPage()
        self.assertTrue(pp._provider_menu_btn.has_css_class('flat'))
        self.assertTrue(pp._provider_menu_btn.has_css_class('provider-pill-btn'))

    def test_get_next_unwatched_episode_no_history(self):
        """Verify defaults to S1E1 when show has no history."""
        s, ep, pos = self.db.get_next_unwatched_episode(1001)
        self.assertEqual(s, 1)
        self.assertEqual(ep, 1)
        self.assertEqual(pos, 0)

    def test_get_next_unwatched_episode_active_in_progress(self):
        """Verify returns active episode and position when episode is in-progress (>15s) and not completed."""
        self.db.update_watch_progress(
            tmdb_id=1002,
            title="Show 2",
            media_type='tv',
            season=1,
            episode=3,
            progress_seconds=450.0,
            duration_seconds=1200.0,
        )
        s, ep, pos = self.db.get_next_unwatched_episode(1002)
        self.assertEqual(s, 1)
        self.assertEqual(ep, 3)
        self.assertEqual(pos, 450)

    def test_get_next_unwatched_episode_queued_after_completion(self):
        """Verify returns queued episode S1E4 with pos 0 when S1E3 ended and S1E4 was queued at 0.0s."""
        self.db.mark_completed(
            tmdb_id=1003,
            media_type='tv',
            season=1,
            episode=3,
            title="Show 3"
        )
        self.db.update_watch_progress(
            tmdb_id=1003,
            title="Show 3",
            media_type='tv',
            season=1,
            episode=4,
            progress_seconds=0.0,
            duration_seconds=1200.0,
        )
        s, ep, pos = self.db.get_next_unwatched_episode(1003)
        self.assertEqual(s, 1)
        self.assertEqual(ep, 4)
        self.assertEqual(pos, 0)

    def test_get_next_unwatched_episode_current_completed_advances(self):
        """Verify advances to S1E4 if progress still points to S1E3 but S1E3 is marked completed."""
        self.db.mark_completed(
            tmdb_id=1004,
            media_type='tv',
            season=1,
            episode=3,
            title="Show 4"
        )
        self.db.update_watch_progress(
            tmdb_id=1004,
            title="Show 4",
            media_type='tv',
            season=1,
            episode=3,
            progress_seconds=1150.0,
            duration_seconds=1200.0,
        )
        s, ep, pos = self.db.get_next_unwatched_episode(1004)
        self.assertEqual(s, 1)
        self.assertEqual(ep, 4)
        self.assertEqual(pos, 0)

    def test_get_next_unwatched_episode_from_completed_table(self):
        """Verify determines next episode from completed_media history when no active progress exists."""
        self.db.mark_completed(1005, 'tv', 1, 1, "Show 5")
        self.db.mark_completed(1005, 'tv', 1, 2, "Show 5")
        self.db.mark_completed(1005, 'tv', 1, 3, "Show 5")
        s, ep, pos = self.db.get_next_unwatched_episode(1005)
        self.assertEqual(s, 1)
        self.assertEqual(ep, 4)
        self.assertEqual(pos, 0)

    def test_movie_completed_deduplication(self):
        """Verify completed movies are deleted from watch_history and never shown in get_watch_history."""
        # 1. Add movie in progress
        self.db.update_watch_progress(
            tmdb_id=2001,
            title="Movie 1",
            media_type='movie',
            progress_seconds=3000.0,
            duration_seconds=5000.0,
        )
        history = self.db.get_watch_history()
        self.assertTrue(any(item['id'] == 2001 for item in history))

        # 2. Mark movie completed
        self.db.mark_completed(
            tmdb_id=2001,
            media_type='movie',
            title="Movie 1"
        )

        # 3. Verify watch_history no longer returns it
        history = self.db.get_watch_history()
        self.assertFalse(any(item['id'] == 2001 for item in history))

        # 4. Verify completed_items returns it
        completed = self.db.get_completed_items()
        self.assertTrue(any(item['id'] == 2001 for item in completed))

    def test_movie_rewatch_unmarks_completed(self):
        """Verify starting to rewatch a movie removes it from completed_media and puts it back in watch_history."""
        # Completed movie
        self.db.mark_completed(tmdb_id=2002, media_type='movie', title="Movie 2")
        self.assertTrue(self.db.is_completed(2002))

        # User starts rewatching: progress at 500s of 6000s
        self.db.update_watch_progress(
            tmdb_id=2002,
            title="Movie 2",
            media_type='movie',
            progress_seconds=500.0,
            duration_seconds=6000.0
        )
        self.assertFalse(self.db.is_completed(2002))
        history = self.db.get_watch_history()
        self.assertTrue(any(item['id'] == 2002 for item in history))

    def test_movie_card_starts_next_unwatched_episode(self):
        """Verify MovieCard._start_play emits S1E4 when S1E3 was completed and S1E4 queued at 0s."""
        self.db.mark_completed(3001, 'tv', 1, 3, "Show 3001")
        self.db.update_watch_progress(
            tmdb_id=3001,
            title="Show 3001",
            media_type='tv',
            season=1,
            episode=4,
            progress_seconds=0.0,
            duration_seconds=1200.0
        )
        card = MovieCard({'id': 3001, 'title': 'Show 3001', 'media_type': 'tv'})

        emitted_data = []
        card.connect('play-movie', lambda c, data: emitted_data.append(data))
        card._start_play()

        self.assertEqual(len(emitted_data), 1)
        self.assertEqual(emitted_data[0]['season'], 1)
        self.assertEqual(emitted_data[0]['episode'], 4)
        self.assertEqual(emitted_data[0]['start_position'], 0)

    def test_library_instant_movie_removal(self):
        """Verify removing a movie from Continue Watching removes it immediately from _cw_movie_box."""
        lp = LibraryPage()
        # Clear existing children to test isolation
        while lp._cw_movie_box.get_first_child():
            lp._cw_movie_box.remove(lp._cw_movie_box.get_first_child())
        while lp._cw_tv_box.get_first_child():
            lp._cw_tv_box.remove(lp._cw_tv_box.get_first_child())

        movie_item = {'id': 4001, 'title': 'Test Movie', 'media_type': 'movie'}
        movie_card = MovieCard(movie_item, show_remove_button=True)
        lp._cw_movie_box.append(movie_card)
        lp._cw_movie_wrapper.set_visible(True)
        lp._cw_section.set_visible(True)

        self.assertIsNotNone(movie_card.get_parent())
        lp._on_remove_item(movie_card, 4001)

        # Card must have been removed immediately from the DOM
        self.assertIsNone(movie_card.get_parent())
        self.assertFalse(lp._cw_movie_wrapper.get_visible())

    def test_library_subtitles_alignment_class(self):
        """Verify TV Shows and Movies headers have title-subsection class."""
        lp = LibraryPage()
        tv_hdr = lp._cw_tv_wrapper.get_first_child()
        movie_hdr = lp._cw_movie_wrapper.get_first_child()

        self.assertTrue(tv_hdr.has_css_class('title-subsection'))
        self.assertTrue(movie_hdr.has_css_class('title-subsection'))

    def test_library_completed_item_removal(self):
        """Verify removing an item from Completed removes it from DB and DOM immediately."""
        self.db.mark_completed(5001, 'movie', 0, 0, "Completed Movie 1")
        self.assertTrue(self.db.is_completed(5001))

        lp = LibraryPage()
        lp.refresh(force=True)
        c0 = lp._completed_flowbox.get_child_at_index(0)
        self.assertIsNotNone(c0)
        card = c0.get_child()
        self.assertIsNotNone(card)

        # Trigger removal
        lp._on_remove_completed_item(card, 5001)

        # Verified removed from DB
        self.assertFalse(self.db.is_completed(5001))
        # Verified removed from DOM
        self.assertIsNone(card.get_parent())


if __name__ == '__main__':
    unittest.main()
