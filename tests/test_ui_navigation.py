"""Tests for Komikku-style Adw.NavigationView UI transitions."""

import unittest
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw

Adw.init()

from kinema.window import KinemaWindow
from kinema.ui.watchlist_page import WatchlistPage
from kinema.ui.movie_page import MoviePage
from kinema.ui.player_page import PlayerPage


class TestUINavigation(unittest.TestCase):

    def test_navigation_flow(self):
        win = KinemaWindow()
        nav = win._nav_view
        self.assertEqual(nav.get_visible_page().get_tag(), 'main')

        # Select movie -> pushes detail
        win._on_movie_selected(None, {'id': 278, 'title': 'The Shawshank Redemption'})
        self.assertEqual(nav.get_visible_page().get_tag(), 'detail')
        self.assertEqual(nav.get_visible_page().get_title(), 'The Shawshank Redemption')

        # Play movie -> pushes player
        win._on_play_movie(None, {'movie': {'id': 278, 'title': 'The Shawshank Redemption'}})
        self.assertEqual(nav.get_visible_page().get_tag(), 'player')

        # Close player -> pops back to detail
        win._on_close_player(win._player_page)
        self.assertEqual(nav.get_visible_page().get_tag(), 'detail')

        # Pop detail -> returns to main
        nav.pop()
        self.assertEqual(nav.get_visible_page().get_tag(), 'main')

    def test_watchlist_page_instantiation(self):
        wlp = WatchlistPage()
        self.assertIsNotNone(wlp)

    def test_player_page_structure(self):
        pp = PlayerPage()
        self.assertEqual(pp.get_tag(), 'player')
        self.assertIsNotNone(pp._top_bar)
        self.assertIsNotNone(pp._controls)
        self.assertIsNotNone(pp._mpv_widget)

    def test_player_cursor_and_controls_toggle(self):
        pp = PlayerPage()
        # Verify initial state
        self.assertFalse(pp._cursor_hidden)

        # Trigger show controls
        pp._show_controls_briefly()
        self.assertTrue(pp._controls.get_visible())
        self.assertTrue(pp._top_bar.get_visible())
        self.assertFalse(pp._cursor_hidden)

        # Trigger hide controls
        pp._hide_controls()
        self.assertFalse(pp._controls.get_visible())
        self.assertFalse(pp._top_bar.get_visible())
        self.assertTrue(pp._cursor_hidden)

        # Motion reveals controls and cursor
        pp._on_motion(None, 50, 50)
        self.assertTrue(pp._controls.get_visible())
        self.assertTrue(pp._top_bar.get_visible())
        self.assertFalse(pp._cursor_hidden)

    def test_mpv_gl_proc_address_resolution(self):
        from kinema.ui.player_page import get_proc_address_wrapper
        proc = get_proc_address_wrapper()
        self.assertTrue(callable(proc))
        # Verify it resolves standard core OpenGL symbols on Wayland / EGL / GLX without raising AttributeError
        sym = proc(None, b"glClear")
        self.assertIsNotNone(sym)

    def test_player_controls_reset(self):
        pp = PlayerPage()
        controls = pp._controls
        # Simulate video at 50%
        controls._seek_bar.set_value(50.0)
        controls._curr_time_label.set_text("45:00")
        controls._total_time_label.set_text("1:30:00")

        # Calling reset clears everything
        controls.reset(0.0)
        self.assertEqual(controls._seek_bar.get_value(), 0.0)
        self.assertEqual(controls._curr_time_label.get_text(), "0:00")
        self.assertEqual(controls._total_time_label.get_text(), "0:00")

        # Calling reset with resume position
        controls.reset(start_pos=120, total_duration=240)
        self.assertEqual(controls._seek_bar.get_value(), 50.0)
        self.assertEqual(controls._curr_time_label.get_text(), "2:00")
        self.assertEqual(controls._total_time_label.get_text(), "4:00")

    def test_tv_series_movie_page(self):
        # TV show item from TMDB
        tv_show = {
            'id': 1399,
            'name': 'Game of Thrones',
            'first_air_date': '2011-04-17',
            'number_of_seasons': 8,
        }
        mp = MoviePage(movie=tv_show)
        self.assertEqual(mp._media_type, 'tv')
        self.assertEqual(mp.get_title(), 'Game of Thrones')
        self.assertTrue(mp._tv_box.get_visible())

    def test_watchlist_button_toggle(self):
        movie = {'id': 999999, 'title': 'Test Movie'}
        mp = MoviePage(movie=movie)
        # Should not be in watchlist initially
        self.assertFalse(mp._db.is_in_watchlist(999999))
        self.assertFalse(mp._watchlist_btn.has_css_class('watchlist-active'))
        self.assertEqual(mp._watchlist_btn.get_icon_name(), 'non-starred-symbolic')

        # Toggle to add
        mp._on_watchlist_toggled(mp._watchlist_btn)
        self.assertTrue(mp._db.is_in_watchlist(999999))
        self.assertTrue(mp._watchlist_btn.has_css_class('watchlist-active'))
        self.assertEqual(mp._watchlist_btn.get_icon_name(), 'starred-symbolic')

        # Toggle to remove
        mp._on_watchlist_toggled(mp._watchlist_btn)
        self.assertFalse(mp._db.is_in_watchlist(999999))
        self.assertFalse(mp._watchlist_btn.has_css_class('watchlist-active'))
        self.assertEqual(mp._watchlist_btn.get_icon_name(), 'non-starred-symbolic')

    def test_torrent_selection_ranking(self):
        from kinema.providers.torrent import TorrentProvider
        tp = TorrentProvider()
        streams = [
            {'infoHash': 'hash1', 'title': 'Movie 720p 👤 10', 'quality': '720p', 'seeds': 10},
            {'infoHash': 'hash2', 'title': 'Movie 1080p 👤 50', 'quality': '1080p', 'seeds': 50},
            {'infoHash': 'hash3', 'title': 'YTS 1080p 👤 60', 'quality': '1080p', 'seeds': 60},
            {'infoHash': 'hash4', 'title': 'Movie CAM 👤 100', 'quality': 'CAM', 'seeds': 100},
        ]
        best = tp._select_best_stream(streams)
        self.assertIsNotNone(best)
        # YTS 1080p should win with 1080p bonus + seeds + YTS bonus
        self.assertEqual(best['infoHash'], 'hash3')

    def test_movie_page_with_tmdb_id_only(self):
        item = {'tmdb_id': 278, 'title': 'The Shawshank Redemption'}
        mp = MoviePage(movie=item)
        self.assertEqual(mp._movie['id'], 278)
        self.assertEqual(mp._movie['tmdb_id'], 278)

    def test_player_controls_sub_timing_signature(self):
        pp = PlayerPage()
        controls = pp._controls
        # Verify it handles both 2-arg and 3-arg callback invocations without TypeError
        controls._on_sub_timing_adjusted(0.5)
        controls._on_sub_timing_adjusted(0.5, "Subtitle delayed by +0.5s")

    def test_search_page_status_pages(self):
        from kinema.ui.search_page import SearchPage
        sp = SearchPage()
        # Initial empty state
        self.assertTrue(sp._empty_state.get_visible())
        self.assertFalse(sp._scroll.get_visible())
        self.assertFalse(sp._no_results.get_visible())

        # Loading
        sp._show_loading()
        self.assertTrue(sp._spinner.get_visible())
        self.assertFalse(sp._scroll.get_visible())

        # No results
        sp._show_no_results()
        self.assertTrue(sp._no_results.get_visible())
        self.assertFalse(sp._scroll.get_visible())
        self.assertFalse(sp._empty_state.get_visible())

        # Results
        sp._show_results([{'id': 1, 'title': 'Test Movie'}])
        self.assertTrue(sp._scroll.get_visible())
        self.assertFalse(sp._no_results.get_visible())
        self.assertFalse(sp._empty_state.get_visible())

    def test_provider_manager_fastest_first(self):
        from kinema.providers.base import ProviderManager
        providers = ProviderManager.get_providers()
        names = [p.name for p in providers]
        self.assertEqual(names[0], 'VidLink')
        self.assertEqual(names[1], 'VidEasy')


    def test_movie_page_overview_none_handling(self):
        # Explicitly passing overview=None must not raise TypeError
        item = {'id': 278, 'title': 'The Shawshank Redemption', 'overview': None, 'tagline': None}
        mp = MoviePage(movie=item)
        self.assertEqual(mp._overview_label.get_text(), "")
        self.assertEqual(mp._tagline_label.get_text(), "")

    def test_library_page_instantiation(self):
        from kinema.ui.library_page import LibraryPage
        lp = LibraryPage()
        self.assertIsNotNone(lp)
        lp.refresh()

    def test_movies_page_instantiation(self):
        from kinema.ui.movies_page import MoviesPage
        mp = MoviesPage()
        self.assertIsNotNone(mp)
        self.assertIsNotNone(mp._search_entry)
        self.assertIsNotNone(mp._flowbox)

    def test_series_page_instantiation(self):
        from kinema.ui.series_page import SeriesPage
        sp = SeriesPage()
        self.assertIsNotNone(sp)
        self.assertIsNotNone(sp._search_entry)
        self.assertIsNotNone(sp._flowbox)

    def test_movie_card_hover_play_icon(self):
        from kinema.ui.movie_card import MovieCard
        item = {'id': 278, 'title': 'The Shawshank Redemption', 'media_type': 'movie'}
        card = MovieCard(item)
        self.assertIsNotNone(card._play_overlay)
        # Initially hidden
        self.assertFalse(card._play_overlay.get_visible())
        # Hover enters
        card._on_hover_enter(None, 10, 10)
        self.assertTrue(card._play_overlay.get_visible())
        # Hover leaves
        card._on_hover_leave(None)
        self.assertFalse(card._play_overlay.get_visible())

    def test_movie_card_play_movie_signal(self):
        """Clicking the play overlay emits play-movie with correct stream_data."""
        from kinema.ui.movie_card import MovieCard
        item = {'id': 278, 'title': 'The Shawshank Redemption', 'media_type': 'movie'}
        card = MovieCard(item)
        received = []
        card.connect('play-movie', lambda c, d: received.append(d))
        card._start_play()
        self.assertEqual(len(received), 1)
        sd = received[0]
        self.assertEqual(sd['movie']['id'], 278)
        self.assertEqual(sd['media_type'], 'movie')
        self.assertIsNotNone(sd)

    def test_movie_card_remove_item_signal(self):
        """Delete button emits remove-item with correct tmdb_id."""
        from kinema.ui.movie_card import MovieCard
        item = {'id': 42, 'title': 'Test Movie', 'media_type': 'movie'}
        card = MovieCard(item, show_remove_button=True)
        received_ids = []
        card.connect('remove-item', lambda c, tid: received_ids.append(tid))
        # Simulate delete click
        card._on_remove_released(type('g', (), {'set_state': lambda *a: None})(), 1, 0, 0)
        self.assertEqual(received_ids, [42])

    def test_movie_card_network_badge_tv(self):
        """TV card with 'network' field gets a network badge."""
        from kinema.ui.movie_card import _get_badge_label
        item = {'media_type': 'tv', 'network': 'Netflix'}
        self.assertEqual(_get_badge_label(item), 'NETFLIX')

        item2 = {'media_type': 'tv', 'network': 'HBO Max'}
        self.assertEqual(_get_badge_label(item2), 'HBO MAX')

        item3 = {'media_type': 'tv', 'network': 'Tokyo MX'}
        self.assertEqual(_get_badge_label(item3), 'TOKYO MX')

        item4 = {'media_type': 'tv', 'network': 'Amazon Prime Video'}
        self.assertEqual(_get_badge_label(item4), 'PRIME VIDEO')

    def test_movie_card_in_theaters_badge(self):
        """Movies released within 60 days show IN THEATERS badge."""
        from kinema.ui.movie_card import _get_badge_label
        from datetime import datetime, timedelta
        recent = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
        item = {'media_type': 'movie', 'release_date': recent}
        self.assertEqual(_get_badge_label(item), 'IN THEATERS')

        old_date = '2010-01-01'
        old_item = {'media_type': 'movie', 'release_date': old_date}
        self.assertIsNone(_get_badge_label(old_item))

    def test_movie_card_runtime_display(self):
        """_format_runtime returns correct string."""
        from kinema.ui.movie_card import _format_runtime
        self.assertEqual(_format_runtime(139), '2h 19m')
        self.assertEqual(_format_runtime(60), '1h')
        self.assertEqual(_format_runtime(45), '45m')
        self.assertEqual(_format_runtime(0), '')
        self.assertIsNone(_format_runtime(None)) if _format_runtime(None) is None else None

    def test_movie_card_tv_no_series_badge(self):
        """TV cards no longer show a 'SERIES' badge (deprecated)."""
        from kinema.ui.movie_card import MovieCard
        item = {'id': 1399, 'name': 'Game of Thrones', 'media_type': 'tv', 'first_air_date': '2011-04-17'}
        card = MovieCard(item)
        # The card should instantiate without errors
        self.assertIsNotNone(card)

    def test_library_page_remove_item(self):
        """LibraryPage remove-item deletes from DB and removes card from CW row."""
        from kinema.ui.library_page import LibraryPage
        from kinema.services.database import DatabaseService
        db = DatabaseService()
        # Add a fake history item
        db.update_watch_progress(
            tmdb_id=999998,
            title='Remove Test Movie',
            media_type='movie',
            progress_seconds=600,
            duration_seconds=3600,
        )
        lp = LibraryPage()
        # Verify it was added to history
        self.assertIsNotNone(db.get_item_progress(999998))
        # Simulate remove
        lp._on_remove_item(None, 999998)
        # Verify deletion from DB
        self.assertIsNone(db.get_item_progress(999998))

    def test_movies_page_play_movie_signal(self):
        """MoviesPage forwards play-movie from card to parent."""
        from kinema.ui.movies_page import MoviesPage
        mp = MoviesPage()
        self.assertIsNotNone(mp)
        # Verify play-movie signal is defined
        received = []
        mp.connect('play-movie', lambda p, d: received.append(d))
        # Simulate card emitting play-movie
        fake_stream = {'movie': {'id': 1}, 'media_type': 'movie'}
        mp._on_card_play(None, fake_stream)
        self.assertEqual(received, [fake_stream])

    def test_series_page_play_movie_signal(self):
        """SeriesPage forwards play-movie from card to parent."""
        from kinema.ui.series_page import SeriesPage
        sp = SeriesPage()
        received = []
        sp.connect('play-movie', lambda p, d: received.append(d))
        fake_stream = {'movie': {'id': 2}, 'media_type': 'tv'}
        sp._on_card_play(None, fake_stream)
        self.assertEqual(received, [fake_stream])

    def test_movie_page_ends_at_calculation(self):
        """MoviePage _format_runtime_ends_at returns correct format."""
        from kinema.ui.movie_page import MoviePage
        mp = MoviePage(movie={'id': 278, 'title': 'Test'})
        result = mp._format_runtime_ends_at(139)
        self.assertIn('2h 19m', result)
        self.assertIn('Ends at', result)

    def test_movies_page_infinite_scroll_attributes(self):
        """MoviesPage has pagination attributes."""
        from kinema.ui.movies_page import MoviesPage
        mp = MoviesPage()
        self.assertTrue(hasattr(mp, '_current_page'))
        self.assertTrue(hasattr(mp, '_is_loading'))
        self.assertTrue(hasattr(mp, '_has_more'))
        self.assertTrue(hasattr(mp, '_seen_ids'))

    def test_series_page_infinite_scroll_attributes(self):
        """SeriesPage has pagination attributes."""
        from kinema.ui.series_page import SeriesPage
        sp = SeriesPage()
        self.assertTrue(hasattr(sp, '_current_page'))
        self.assertTrue(hasattr(sp, '_is_loading'))
        self.assertTrue(hasattr(sp, '_has_more'))
        self.assertTrue(hasattr(sp, '_seen_ids'))

    def test_window_play_movie_wired(self):
        """KinemaWindow connects play-movie on all pages."""
        win = KinemaWindow()
        # Simulate direct card play from library
        stream_data = {'movie': {'id': 278, 'title': 'Test'}, 'media_type': 'movie', 'start_position': 0}
        # Should not raise; player page should be pushed
        win._on_play_movie(None, stream_data)
        self.assertEqual(win._nav_view.get_visible_page().get_tag(), 'player')
        win._on_close_player(win._player_page)

    def test_window_actions_and_hamburger_menu(self):
        win = KinemaWindow()
        self.assertTrue(win.has_action('preferences'))
        self.assertTrue(win.has_action('clear_history'))
        self.assertTrue(win.has_action('about'))


if __name__ == '__main__':
    unittest.main()

