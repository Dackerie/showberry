"""Unit tests for round 2 playback and library enhancements."""

import unittest
from unittest.mock import MagicMock, patch
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from showberry.window import ShowberryWindow
from showberry.ui.player_page import PlayerPage, PlayerControls, SubtitlePopover, ProviderPopover
from showberry.ui.movie_page import MoviePage
from showberry.ui.library_page import LibraryPage
from showberry.services.database import DatabaseService


class TestEnhancementsRound2(unittest.TestCase):

    def setUp(self):
        self.db = DatabaseService()

    def test_top_osc_bar_provider_menu_and_popover(self):
        """Verify provider switcher is on the top OSC bar and absent from bottom controls."""
        pp = PlayerPage()

        # Top OSC bar has provider menu button
        self.assertTrue(hasattr(pp, '_provider_menu_btn'))
        self.assertTrue(hasattr(pp, '_provider_badge_label'))
        self.assertTrue(hasattr(pp, '_provider_popover'))
        self.assertTrue(pp._provider_menu_btn.has_css_class('provider-pill-btn'))

        # Bottom controls do not have provider button
        controls = pp._controls
        self.assertFalse(hasattr(controls, '_provider_btn'))
        self.assertFalse(hasattr(controls, '_provider_popover'))

    def test_simplified_subtitle_popover(self):
        """Verify SubtitlePopover has only clean delay, position, size controls and no drift/autosync."""
        popover = SubtitlePopover()
        child = popover.get_child()
        self.assertIsNotNone(child)

        # Labels check
        self.assertTrue(hasattr(popover, '_delay_label'))
        self.assertTrue(hasattr(popover, '_pos_label'))
        self.assertTrue(hasattr(popover, '_scale_label'))

        # Check there is no auto-sync button or drift section in popover
        self.assertFalse(hasattr(popover, '_drift_label'))
        self.assertFalse(hasattr(popover, '_autosync_btn'))

    def test_episode_list_height_and_watched_refresh(self):
        """Verify TV details episode list has min_content_height and refresh_watch_state updates watched badges."""
        movie_data = {'id': 9999, 'title': 'Test Show', 'name': 'Test Show', 'media_type': 'tv'}
        mp = MoviePage(movie=movie_data)

        # Check min content height on episode scrolled window
        self.assertGreaterEqual(mp._episodes_scroll.get_min_content_height(), 380)

        # Render dummy episodes
        episodes = [
            {'episode_number': 1, 'name': 'Pilot', 'runtime': 45},
            {'episode_number': 2, 'name': 'Second', 'runtime': 45},
        ]
        mp._render_episodes(1, episodes)

        # Initially not completed
        row1 = mp._episodes_listbox.get_row_at_index(0)
        self.assertIsNotNone(row1)
        self.assertTrue(hasattr(row1, '_watched_pill'))
        self.assertFalse(row1._watched_pill.get_visible())

        # Mark episode 1 as completed in DB
        self.db.mark_completed(9999, 'tv', season=1, episode=1, title='Test Show')

        # Call refresh_watch_state() - must immediately update badge to visible without reload
        mp.refresh_watch_state()
        self.assertTrue(row1._watched_pill.get_visible())

        # Episode 2 should still not be watched
        row2 = mp._episodes_listbox.get_row_at_index(1)
        self.assertFalse(row2._watched_pill.get_visible())

        # Cleanup
        self.db.unmark_completed(9999, season=1, episode=1)

    def test_completed_items_excludes_single_tv_episodes(self):
        """Watching a single TV episode must not list the whole show in Completed."""
        test_id = 88888
        self.db.mark_completed(test_id, 'tv', season=1, episode=1, title='Solo Episode Show')

        completed_items = self.db.get_completed_items()
        matching = [i for i in completed_items if i.get('tmdb_id') == test_id]
        self.assertEqual(len(matching), 0, "Single TV episode must NOT show up in Library Completed items")

        # When the whole series is marked completed (season=0, episode=0)
        self.db.mark_completed(test_id, 'tv', season=0, episode=0, title='Solo Episode Show')
        completed_items_after = self.db.get_completed_items()
        matching_after = [i for i in completed_items_after if i.get('tmdb_id') == test_id]
        self.assertEqual(len(matching_after), 1, "Full TV show must appear in Completed once marked completed")

        # Cleanup
        self.db.unmark_completed(test_id, season=1, episode=1)
        self.db.unmark_completed(test_id, season=0, episode=0)

    def test_library_continue_watching_subsections(self):
        """Verify Continue Watching has TV Shows and Movies sub-sections."""
        lp = LibraryPage()

        # Check section structure
        self.assertTrue(hasattr(lp, '_cw_section'))
        self.assertTrue(hasattr(lp, '_cw_tv_wrapper'))
        self.assertTrue(hasattr(lp, '_cw_tv_box'))
        self.assertTrue(hasattr(lp, '_cw_movie_wrapper'))
        self.assertTrue(hasattr(lp, '_cw_movie_box'))

        # Insert dummy history items: 1 TV show, 1 movie
        self.db.update_watch_progress(
            tmdb_id=77771,
            title="Test Movie",
            media_type="movie",
            progress_seconds=120,
            duration_seconds=6000,
        )
        self.db.update_watch_progress(
            tmdb_id=77772,
            title="Test Series",
            media_type="tv",
            season=1,
            episode=1,
            progress_seconds=300,
            duration_seconds=3000,
        )

        lp.refresh(force=True)

        self.assertTrue(lp._cw_section.get_visible())
        self.assertTrue(lp._cw_tv_wrapper.get_visible())
        self.assertTrue(lp._cw_movie_wrapper.get_visible())

        self.assertGreaterEqual(len(list(_get_box_children(lp._cw_tv_box))), 1)
        self.assertGreaterEqual(len(list(_get_box_children(lp._cw_movie_box))), 1)

        # Cleanup
        self.db.delete_history_item(77771)
        self.db.delete_history_item(77772)


def _get_box_children(box):
    c = box.get_first_child()
    while c:
        yield c
        c = c.get_next_sibling()


if __name__ == '__main__':
    unittest.main()
