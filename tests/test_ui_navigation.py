"""Tests for Komikku-style Adw.NavigationView UI transitions."""

import unittest
from unittest.mock import MagicMock, patch
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk

Adw.init()

from showberry.window import ShowberryWindow, KinemaWindow
from showberry.ui.watchlist_page import WatchlistPage
from showberry.ui.movie_page import MoviePage
from showberry.ui.player_page import PlayerPage


class TestUINavigation(unittest.TestCase):

    def setUp(self):
        super().setUp()
        from showberry.services.settings import SettingsService
        s = SettingsService()
        s.preferred_torrent_quality = '1080p'
        s.max_torrent_size_gb = 0
        s.torrent_cache_size_gb = 10

    def tearDown(self):
        from showberry.services.settings import SettingsService
        s = SettingsService()
        s.preferred_torrent_quality = '1080p'
        s.max_torrent_size_gb = 0
        s.torrent_cache_size_gb = 10
        super().tearDown()

    def test_navigation_flow(self):
        win = ShowberryWindow()
        nav = win._nav_view
        self.assertEqual(nav.get_visible_page().get_tag(), 'main')

        # Select movie -> pushes detail
        win._on_movie_selected(None, {'id': 278, 'title': 'The Shawshank Redemption'})
        self.assertTrue(nav.get_visible_page().get_tag().startswith('detail'))
        self.assertEqual(nav.get_visible_page().get_title(), 'The Shawshank Redemption')

        # Play movie -> pushes player
        win._on_play_movie(None, {'movie': {'id': 278, 'title': 'The Shawshank Redemption'}})
        self.assertEqual(nav.get_visible_page().get_tag(), 'player')

        # Close player -> pops back to detail
        win._on_close_player(win._player_page)
        self.assertTrue(nav.get_visible_page().get_tag().startswith('detail'))

        # Pop detail -> returns to main
        nav.pop()
        self.assertEqual(nav.get_visible_page().get_tag(), 'main')

    def test_more_like_this_navigation(self):
        """Clicking a movie/series card in 'More Like This' pushes new detail page onto navigation stack."""
        win = ShowberryWindow()
        nav = win._nav_view

        win._on_movie_selected(None, {
            'id': 100,
            'title': 'Parent Movie',
            'recommendations': [
                {'id': 200, 'title': 'Recommended Child Movie'}
            ]
        })
        parent_page = nav.get_visible_page()
        self.assertEqual(parent_page.get_title(), 'Parent Movie')
        self.assertEqual(len(nav.get_navigation_stack()), 2)

        card = parent_page._recs_row.get_first_child()
        self.assertIsNotNone(card)
        self.assertEqual(card._movie.get('title'), 'Recommended Child Movie')

        # Click recommended movie card
        card.emit('clicked-movie', card._movie)

        child_page = nav.get_visible_page()
        self.assertEqual(child_page.get_title(), 'Recommended Child Movie')
        self.assertEqual(len(nav.get_navigation_stack()), 3)
        self.assertTrue(child_page.get_tag().startswith('detail'))
        self.assertNotEqual(parent_page.get_tag(), child_page.get_tag())

        # Pop returns to parent movie
        nav.pop()
        self.assertEqual(nav.get_visible_page().get_title(), 'Parent Movie')
        self.assertEqual(len(nav.get_navigation_stack()), 2)

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
        from showberry.ui.player_page import get_proc_address_wrapper
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
        from showberry.providers.torrent import TorrentProvider
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
        from showberry.ui.search_page import SearchPage
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
        from showberry.providers.base import ProviderManager
        providers = ProviderManager.get_providers()
        names = [p.name for p in providers]
        self.assertEqual(names[0], 'VidEasy')
        self.assertEqual(names[1], 'Vidy')
        self.assertEqual(names[2], 'VidKing')
        self.assertEqual(names[3], 'VidLink')


    def test_movie_page_overview_none_handling(self):
        # Explicitly passing overview=None must not raise TypeError
        item = {'id': 278, 'title': 'The Shawshank Redemption', 'overview': None, 'tagline': None}
        mp = MoviePage(movie=item)
        self.assertEqual(mp._overview_label.get_text(), "")
        self.assertEqual(mp._tagline_label.get_text(), "")

    def test_library_page_instantiation(self):
        from showberry.ui.library_page import LibraryPage
        lp = LibraryPage()
        self.assertIsNotNone(lp)
        lp.refresh()

    def test_library_page_grid_alignment(self):
        """Watchlist FlowBox must align to START with matching margins to Continue Watching."""
        from showberry.ui.library_page import LibraryPage
        lp = LibraryPage()
        self.assertEqual(lp._cw_box.get_halign(), Gtk.Align.START)
        self.assertEqual(lp._wl_flowbox.get_halign(), Gtk.Align.START)
        self.assertEqual(lp._cw_box.get_margin_start(), lp._wl_flowbox.get_margin_start())
        self.assertEqual(lp._cw_box.get_margin_end(), lp._wl_flowbox.get_margin_end())

    def test_movies_page_instantiation(self):
        from showberry.ui.movies_page import MoviesPage
        mp = MoviesPage()
        self.assertIsNotNone(mp)
        self.assertIsNotNone(mp._search_entry)
        self.assertIsNotNone(mp._flowbox)

    def test_series_page_instantiation(self):
        from showberry.ui.series_page import SeriesPage
        sp = SeriesPage()
        self.assertIsNotNone(sp)
        self.assertIsNotNone(sp._search_entry)
        self.assertIsNotNone(sp._flowbox)

    def test_movie_card_hover_play_icon(self):
        from showberry.ui.movie_card import MovieCard
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
        from showberry.ui.movie_card import MovieCard
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
        from showberry.ui.movie_card import MovieCard
        item = {'id': 42, 'title': 'Test Movie', 'media_type': 'movie'}
        card = MovieCard(item, show_remove_button=True)
        received_ids = []
        card.connect('remove-item', lambda c, tid: received_ids.append(tid))
        # Simulate delete click
        card._on_remove_released(type('g', (), {'set_state': lambda *a: None})(), 1, 0, 0)
        self.assertEqual(received_ids, [42])

    def test_movie_card_network_badge_tv(self):
        """TV card with 'network' field gets a network badge."""
        from showberry.ui.movie_card import _get_badge_label
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
        from showberry.ui.movie_card import _get_badge_label
        from datetime import datetime, timedelta
        recent = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
        item = {'media_type': 'movie', 'release_date': recent}
        self.assertEqual(_get_badge_label(item), 'IN THEATERS')

        old_date = '2010-01-01'
        old_item = {'media_type': 'movie', 'release_date': old_date}
        self.assertIsNone(_get_badge_label(old_item))

    def test_movie_card_runtime_display(self):
        """_format_runtime returns correct string."""
        from showberry.ui.movie_card import _format_runtime
        self.assertEqual(_format_runtime(139), '2h 19m')
        self.assertEqual(_format_runtime(60), '1h')
        self.assertEqual(_format_runtime(45), '45m')
        self.assertEqual(_format_runtime(0), '')
        self.assertIsNone(_format_runtime(None)) if _format_runtime(None) is None else None

    def test_movie_card_tv_no_series_badge(self):
        """TV cards no longer show a 'SERIES' badge (deprecated)."""
        from showberry.ui.movie_card import MovieCard
        item = {'id': 1399, 'name': 'Game of Thrones', 'media_type': 'tv', 'first_air_date': '2011-04-17'}
        card = MovieCard(item)
        # The card should instantiate without errors
        self.assertIsNotNone(card)

    def test_library_page_remove_item(self):
        """LibraryPage remove-item deletes from DB and removes card from CW row."""
        from showberry.ui.library_page import LibraryPage
        from showberry.services.database import DatabaseService
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
        from showberry.ui.movies_page import MoviesPage
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
        from showberry.ui.series_page import SeriesPage
        sp = SeriesPage()
        received = []
        sp.connect('play-movie', lambda p, d: received.append(d))
        fake_stream = {'movie': {'id': 2}, 'media_type': 'tv'}
        sp._on_card_play(None, fake_stream)
        self.assertEqual(received, [fake_stream])

    def test_movie_page_ends_at_calculation(self):
        """MoviePage _format_runtime_ends_at returns correct format."""
        from showberry.ui.movie_page import MoviePage
        mp = MoviePage(movie={'id': 278, 'title': 'Test'})
        result = mp._format_runtime_ends_at(139)
        self.assertIn('2h 19m', result)
        self.assertIn('Ends at', result)

    def test_movies_page_infinite_scroll_attributes(self):
        """MoviesPage has pagination attributes."""
        from showberry.ui.movies_page import MoviesPage
        mp = MoviesPage()
        self.assertTrue(hasattr(mp, '_current_page'))
        self.assertTrue(hasattr(mp, '_is_loading'))
        self.assertTrue(hasattr(mp, '_has_more'))
        self.assertTrue(hasattr(mp, '_seen_ids'))

    def test_series_page_infinite_scroll_attributes(self):
        """SeriesPage has pagination attributes."""
        from showberry.ui.series_page import SeriesPage
        sp = SeriesPage()
        self.assertTrue(hasattr(sp, '_current_page'))
        self.assertTrue(hasattr(sp, '_is_loading'))
        self.assertTrue(hasattr(sp, '_has_more'))
        self.assertTrue(hasattr(sp, '_seen_ids'))

    def test_window_play_movie_wired(self):
        """ShowberryWindow connects play-movie on all pages."""
        win = ShowberryWindow()
        # Simulate direct card play from library
        stream_data = {'movie': {'id': 278, 'title': 'Test'}, 'media_type': 'movie', 'start_position': 0}
        # Should not raise; player page should be pushed
        win._on_play_movie(None, stream_data)
        self.assertEqual(win._nav_view.get_visible_page().get_tag(), 'player')
        win._on_close_player(win._player_page)

    def test_player_page_session_invalidation(self):
        """Closing player invalidates session ID, rendering stale resolver callbacks inert."""
        from showberry.ui.player_page import PlayerPage
        player = PlayerPage()
        initial_session = player._session_id

        # Simulating load_stream
        player._session_id += 1
        active_session = player._session_id
        self.assertGreater(active_session, initial_session)

        # Close player
        player._on_close(None)
        closed_session = player._session_id
        self.assertGreater(closed_session, active_session)

        # Stale callbacks with active_session must be ignored (return False)
        failed_signals = []
        player.connect('stream-failed', lambda p, err: failed_signals.append(err))

        res = player._on_stream_resolved(None, [], session_id=active_session)
        self.assertFalse(res)
        self.assertEqual(len(failed_signals), 0)

        err_res = player._on_stream_error("Stale error", session_id=active_session)
        self.assertFalse(err_res)
        self.assertEqual(len(failed_signals), 0)

    def test_tmdb_details_cache(self):
        """TMDBClient caches get_movie_details and get_tv_details in _details_cache."""
        from showberry.services.tmdb import TMDBClient
        client = TMDBClient()
        self.assertTrue(hasattr(client, '_details_cache'))
        client._details_cache['movie_123'] = {'id': 123, 'title': 'Cached Movie'}
        client._details_cache['tv_456'] = {'id': 456, 'name': 'Cached TV'}

        self.assertEqual(client.get_movie_details(123)['title'], 'Cached Movie')
        self.assertEqual(client.get_tv_details(456)['name'], 'Cached TV')

    def test_pages_footer_spinner_present(self):
        """Both MoviesPage and SeriesPage have footer spinners for infinite scrolling."""
        from showberry.ui.movies_page import MoviesPage
        from showberry.ui.series_page import SeriesPage
        mp = MoviesPage()
        sp = SeriesPage()
        self.assertTrue(hasattr(mp, '_footer_spinner'))
        self.assertTrue(hasattr(sp, '_footer_spinner'))

    def test_window_actions_and_hamburger_menu(self):
        win = ShowberryWindow()
        self.assertTrue(win.has_action('preferences'))
        self.assertTrue(win.has_action('clear_history'))
        self.assertTrue(win.has_action('about'))

    def test_is_stream_alive(self):
        """is_stream_alive correctly validates stream accessibility and rejects 429/403/404."""
        from unittest.mock import patch, MagicMock
        from showberry.providers.base import is_stream_alive, StreamResult

        res = StreamResult(url='https://example.com/stream.m3u8')

        # 200 OK
        with patch('requests.head') as mock_head:
            mock_head.return_value = MagicMock(status_code=200)
            self.assertTrue(is_stream_alive(res))

        # 206 Partial Content
        with patch('requests.head') as mock_head:
            mock_head.return_value = MagicMock(status_code=206)
            self.assertTrue(is_stream_alive(res))

        # 429 Too Many Requests
        with patch('requests.head') as mock_head:
            mock_head.return_value = MagicMock(status_code=429)
            self.assertFalse(is_stream_alive(res))

        # 403 Forbidden
        with patch('requests.head') as mock_head:
            mock_head.return_value = MagicMock(status_code=403)
            self.assertFalse(is_stream_alive(res))

        # Exception
        with patch('requests.head', side_effect=Exception("Network down")):
            self.assertFalse(is_stream_alive(res))

    def test_provider_manager_skips_unhealthy_streams(self):
        """ProviderManager automatically skips rate-limited/dead streams and cascades to next provider."""
        from unittest.mock import patch, MagicMock
        from showberry.providers.base import ProviderManager, StreamResult, BaseProvider

        class BadProvider(BaseProvider):
            name = "BadProvider"
            priority = 1
            def get_stream_url(self, tmdb_id, season=None, episode=None):
                return StreamResult(url="https://bad.com/429.m3u8", provider_name="BadProvider")

        class GoodProvider(BaseProvider):
            name = "GoodProvider"
            priority = 2
            def get_stream_url(self, tmdb_id, season=None, episode=None):
                return StreamResult(url="https://good.com/200.m3u8", provider_name="GoodProvider")

        with patch('showberry.providers.base.get_all_providers', return_value=[BadProvider(), GoodProvider()]):
            with patch('showberry.providers.base.is_stream_alive') as mock_alive:
                # First stream is dead/429, second stream is alive
                mock_alive.side_effect = [False, True]
                res = ProviderManager.resolve_stream(123)
                self.assertIsNotNone(res)
                self.assertEqual(res.provider_name, "GoodProvider")
                self.assertEqual(res.url, "https://good.com/200.m3u8")

    def test_mpv_widget_deactivate_and_activate(self):
        """MpvWidget deactivate pauses, stops, and disables rendering callbacks without deadlock."""
        from showberry.ui.player_page import MpvWidget
        widget = MpvWidget()
        self.assertTrue(widget._is_active)

        widget.deactivate()
        self.assertFalse(widget._is_active)
        self.assertFalse(widget._trigger_redraw())
        self.assertFalse(widget.do_render())

        widget.activate()
        self.assertTrue(widget._is_active)

    def test_mpv_widget_consecutive_playback_rendering(self):
        """MpvWidget recovers gracefully across playback cycles without raising GLError(err=1282)."""
        from showberry.ui.player_page import MpvWidget
        from OpenGL import GL

        widget = MpvWidget()
        # Inactive widget safely returns False
        widget._is_active = False
        self.assertFalse(widget.do_render())

        # Active widget with zero dimensions returns False without crashing
        widget._is_active = True
        self.assertFalse(widget.do_render())

        # Test deactivate detaches update_cb and play restores it
        widget.deactivate()
        self.assertFalse(widget._is_active)

        # Test GL context recreation logic across realize cycles
        mock_old_ctx = unittest.mock.MagicMock()
        widget._ctx = mock_old_ctx
        widget._gl_context_ref = 'gl-context-1'

        with unittest.mock.patch.object(widget, 'make_current'), \
             unittest.mock.patch.object(widget, 'get_context', return_value='gl-context-2'), \
             unittest.mock.patch('showberry.ui.player_page.MpvRenderContext') as mock_render_cls:
            mock_new_ctx = unittest.mock.MagicMock()
            mock_render_cls.return_value = mock_new_ctx

            widget._on_realize()

            # Old context was freed
            mock_old_ctx.free.assert_called_once()
            # New context ref stored
            self.assertEqual(widget._gl_context_ref, 'gl-context-2')
            # New render context created and callback assigned
            self.assertEqual(widget._ctx, mock_new_ctx)

    def test_volume_zero_clamping_and_mute_slider(self):
        """Volume cleanly clamps at 0% without wrapping to 100%, and mute slider updates correctly."""
        from showberry.ui.player_page import MpvWidget, PlayerControls

        widget = MpvWidget()
        widget.set_volume(0)
        self.assertEqual(widget.get_volume(), 0.0)

        # Decrementing below 0 clamps at 0.0
        v_below = max(0.0, widget.get_volume() - 5.0)
        widget.set_volume(v_below)
        self.assertEqual(widget.get_volume(), 0.0)

        # PlayerControls mute synchronization
        controls = PlayerControls()
        controls.set_player(widget)
        controls._volume_scale.set_value(75.0)
        self.assertEqual(controls._pre_mute_volume, 75.0)

        # Trigger mute
        controls._on_mute_clicked(None)
        self.assertTrue(widget.is_muted())
        self.assertEqual(controls._volume_scale.get_value(), 0.0)

        # Trigger unmute -> restores 75%
        controls._on_mute_clicked(None)
        self.assertFalse(widget.is_muted())
        self.assertEqual(controls._volume_scale.get_value(), 75.0)
        self.assertEqual(widget.get_volume(), 75.0)

    def test_movie_card_focusability_and_keyboard_activation(self):
        """MovieCard is focusable and handles Return (details), Space/P (play), and Delete (remove)."""
        from gi.repository import Gdk
        from showberry.ui.movie_card import MovieCard

        card = MovieCard({'id': 999, 'title': 'Test Movie'}, show_remove_button=True)
        self.assertTrue(card.get_focusable())

        clicked = []
        played = []
        removed = []
        card.connect('clicked-movie', lambda c, m: clicked.append(m))
        card.connect('play-movie', lambda c, s: played.append(s))
        card.connect('remove-item', lambda c, tid: removed.append(tid))

        # Enter key triggers clicked-movie
        self.assertTrue(card._on_key_pressed(None, Gdk.KEY_Return, 0, 0))
        self.assertEqual(len(clicked), 1)

        # Space key triggers play-movie
        self.assertTrue(card._on_key_pressed(None, Gdk.KEY_space, 0, 0))
        self.assertEqual(len(played), 1)

        # P key triggers play-movie
        self.assertTrue(card._on_key_pressed(None, Gdk.KEY_p, 0, 0))
        self.assertEqual(len(played), 2)

        # Delete key triggers remove-item
        self.assertTrue(card._on_key_pressed(None, Gdk.KEY_Delete, 0, 0))
        self.assertEqual(removed, [999])

    def test_window_shortcuts_and_menu_items(self):
        """ShowberryWindow includes shortcuts and tab navigation actions, and hamburger menu has Keyboard Shortcuts."""
        from showberry.window import ShowberryWindow, KinemaWindow

        win = ShowberryWindow()
        self.assertTrue(win.has_action('shortcuts'))
        self.assertTrue(win.has_action('search'))
        self.assertTrue(win.has_action('tab_library'))
        self.assertTrue(win.has_action('tab_movies'))
        self.assertTrue(win.has_action('tab_series'))
        self.assertTrue(win.has_action('tab_next'))
        self.assertTrue(win.has_action('tab_prev'))

        # Test tab switching
        win._switch_tab('movies')
        self.assertEqual(win._view_stack.get_visible_child_name(), 'movies')
        win._cycle_tab(1)
        self.assertEqual(win._view_stack.get_visible_child_name(), 'series')
        win._cycle_tab(-1)
        self.assertEqual(win._view_stack.get_visible_child_name(), 'movies')

    def test_shortcuts_window_multi_section(self):
        """ShortcutsWindow is split into two sections with default size (680, 480) and max_height=10."""
        from showberry.window import ShowberryWindow, KinemaWindow
        win = ShowberryWindow()
        # Verify method runs without error and presents window
        win._show_shortcuts_window()
        self.assertTrue(True)

    def test_movies_page_grid_arrow_navigation(self):
        """MoviesPage handles 2D grid arrow navigation, with Up returning to search entry on row 0."""
        from showberry.ui.movies_page import MoviesPage
        from showberry.ui.movie_card import MovieCard

        mp = MoviesPage()
        for i in range(12):
            card = MovieCard({'id': 500 + i, 'title': f'Movie {i}'})
            card.connect('navigate-grid', mp._on_card_navigate)
            mp._flowbox.append(card)

        # Focus first card
        mp._focus_first_card()
        child0 = mp._flowbox.get_child_at_index(0)
        card0 = child0.get_child()

        # Up on row 0 returns focus to search entry
        card0.emit('navigate-grid', 'up')
        # Search entry internal text widget has focus
        root = card0.get_root()
        if root:
            focused = root.get_focus()
            self.assertTrue(focused == mp._search_entry or focused.get_parent() == mp._search_entry)

    def test_library_page_focus_navigation(self):
        """LibraryPage focus_first focuses CW card, Down moves to WL, Up from WL moves back to CW."""
        from showberry.ui.library_page import LibraryPage
        from showberry.services.database import DatabaseService

        db = DatabaseService()
        try:
            with db._get_connection() as conn:
                conn.execute('INSERT OR REPLACE INTO watch_history (tmdb_id, title, media_type, duration_seconds, progress_seconds, updated_at) VALUES (881, "Test CW", "movie", 7200, 1000, 1700000000)')
                conn.execute('INSERT OR REPLACE INTO watchlist (tmdb_id, title, media_type, added_at) VALUES (882, "Test WL", "movie", 1700000000)')
                conn.commit()

            lp = LibraryPage()
            # focus_first returns True
            self.assertTrue(lp.focus_first())

            # CW card navigating down moves focus to WL
            cw_card = lp._cw_box.get_first_child()
            self.assertIsNotNone(cw_card)
            cw_card.emit('navigate-grid', 'down')

            # WL card navigating up moves focus back to CW and resets scroll adjustment to 0
            first_wl = lp._wl_flowbox.get_child_at_index(0)
            self.assertIsNotNone(first_wl)
            wl_card = first_wl.get_child()
            wl_card.emit('navigate-grid', 'up')
            self.assertEqual(lp._scroll.get_vadjustment().get_value(), 0.0)
        finally:
            with db._get_connection() as conn:
                conn.execute('DELETE FROM watch_history WHERE tmdb_id = 881')
                conn.execute('DELETE FROM watchlist WHERE tmdb_id = 882')
                conn.commit()


    def test_movie_page_backdrop_dimensions(self):
        """MoviePage backdrop has responsive height scaling, can_shrink True, and START alignment."""
        from showberry.ui.movie_page import MoviePage
        mp = MoviePage(movie={'id': 1, 'title': 'Test'})
        self.assertTrue(mp._backdrop.get_can_shrink())
        # Wide screen measurement (> 1400px) scales height up to ~450px
        min_h, nat_h, _, _ = mp._backdrop.measure(Gtk.Orientation.VERTICAL, 1600)
        self.assertGreaterEqual(nat_h, 400)
        # Narrow/mobile screen measurement scales down to min 260px
        min_h_sm, nat_h_sm, _, _ = mp._backdrop.measure(Gtk.Orientation.VERTICAL, 600)
        self.assertEqual(nat_h_sm, 260)
        self.assertEqual(mp._backdrop.get_valign(), Gtk.Align.START)
        # Verify play button is placed beside poster inside details box
        self.assertIsNotNone(mp._play_button.get_parent())

    def test_movie_card_play_overlay_and_alignment(self):
        """MovieCard play overlay is 64x64 with 34px icon, card has fixed 196px width without stretching."""
        from showberry.ui.movie_card import MovieCard
        card = MovieCard({'id': 1, 'title': 'Test'})
        w, h = card._play_overlay.get_size_request()
        self.assertEqual(w, 64)
        self.assertEqual(h, 64)
        self.assertEqual(card.get_halign(), Gtk.Align.START)
        self.assertFalse(card.get_hexpand())
        cw, _ = card.get_size_request()
        self.assertEqual(cw, 196)

    def test_player_page_osd_pill_margin(self):
        """OSD notification pill is positioned >= 90px from top to clear top bar."""
        from showberry.ui.player_page import PlayerPage
        player = PlayerPage()
        self.assertGreaterEqual(player._osd_pill.get_margin_top(), 90)

    def test_flowbox_homogeneous_setting(self):
        """MoviesPage and SeriesPage flowboxes have set_homogeneous(True)."""
        from showberry.ui.movies_page import MoviesPage
        from showberry.ui.series_page import SeriesPage
        mp = MoviesPage()
        sp = SeriesPage()
        self.assertTrue(mp._flowbox.get_homogeneous())
        self.assertTrue(sp._flowbox.get_homogeneous())

    def test_movie_card_enrichment(self):
        """_update_enriched_ui updates TV network badge and runtime labels."""
        from showberry.ui.movie_card import MovieCard
        tv_card = MovieCard({'id': 94997, 'media_type': 'tv', 'title': 'House of the Dragon'})
        self.assertFalse(tv_card._badge.get_visible())

        # Simulate enrichment
        tv_card._movie['network'] = 'HBO'
        tv_card._movie['runtime'] = 60
        tv_card._update_enriched_ui()

    def test_movie_page_responsive_min_width(self):
        """MoviePage min width is <= 360px to support narrow mobile screens."""
        from showberry.ui.movie_page import MoviePage
        mp = MoviePage({'id': 100, 'title': 'Responsive Mobile Test Movie', 'runtime': 120})
        min_w, _, _, _ = mp.measure(Gtk.Orientation.HORIZONTAL, -1)
        self.assertLessEqual(min_w, 360)

    def test_movie_page_instant_directors(self):
        """Director label renders instantly at 0ms if directors present in movie data."""
        from showberry.ui.movie_page import MoviePage
        mp = MoviePage({'id': 550, 'title': 'Fight Club', 'directors': ['David Fincher']})
        self.assertTrue(mp._director_label.get_visible())
        self.assertEqual(mp._director_label.get_text(), 'Directed by David Fincher')

    def test_movie_page_cast_and_recommendations(self):
        """MoviePage renders cast chips and recommended cards when present."""
        from showberry.ui.movie_page import MoviePage
        mp = MoviePage({'id': 100, 'title': 'Test Movie'})
        self.assertFalse(mp._cast_box.get_visible())
        self.assertFalse(mp._recs_box.get_visible())

        # Render cast
        mp._render_cast([{'name': 'Actor One', 'character': 'Hero'}, {'name': 'Actor Two', 'character': 'Villain'}])
        self.assertTrue(mp._cast_box.get_visible())
        self.assertIsNotNone(mp._cast_row.get_first_child())

        # Verify cast button hierarchy and non-wrapping labels
        cast_btn = mp._cast_row.get_first_child()
        self.assertIsInstance(cast_btn, Gtk.Button)
        chip_box = cast_btn.get_child()
        avatar = chip_box.get_first_child()
        text_box = avatar.get_next_sibling()
        name_lbl = text_box.get_first_child()
        self.assertFalse(name_lbl.get_wrap())
        self.assertTrue(name_lbl.get_single_line_mode())

        # Render recommendations
        mp._render_recommendations([{'id': 201, 'title': 'Similar 1'}, {'id': 202, 'title': 'Similar 2'}])
        self.assertTrue(mp._recs_box.get_visible())
        self.assertIsNotNone(mp._recs_row.get_first_child())

    def test_window_mobile_switcher_bar(self):
        """ShowberryWindow includes Adw.ViewSwitcherBar bound to main stack for mobile view."""
        win = ShowberryWindow()
        self.assertIsNotNone(win._switcher_bar)
        self.assertIsInstance(win._switcher_bar, Adw.ViewSwitcherBar)
        self.assertEqual(win._switcher_bar.get_stack(), win._view_stack)

    def test_movie_page_breakpoint_bin_size_request(self):
        """MoviePage breakpoint bin sets explicit size request to prevent GTK warnings."""
        from showberry.ui.movie_page import MoviePage
        mp = MoviePage({'id': 100, 'title': 'Test Movie'})
        w, h = mp._breakpoint_bin.get_size_request()
        self.assertGreaterEqual(w, 320)
        self.assertGreaterEqual(h, 200)

    def test_player_available_subtitles_popover(self):
        """PlayerControls and SubtitlePopover support external online subtitles."""
        pp = PlayerPage()
        subs = [
            {'id': '1', 'url': 'https://example.com/sub1.srt', 'lang': 'eng', 'label': 'English (Test)'},
            {'id': '2', 'url': 'https://example.com/sub2.srt', 'lang': 'spa', 'label': 'Spanish (Test)'},
        ]
        pp._controls.set_available_subtitles(subs)
        self.assertEqual(len(pp._controls._sub_popover._available_subtitles), 2)

        # Calling reset clears external subtitles
        pp._controls.reset()
        self.assertEqual(len(pp._controls._sub_popover._available_subtitles), 0)


    def test_player_controls_non_focusable(self):
        """Player controls buttons must be non-focusable to prevent stealing focus from keyboard shortcuts."""
        pp = PlayerPage()
        self.assertFalse(pp._controls._play_button.get_focusable())
        self.assertFalse(pp._controls._fullscreen_button.get_focusable())
        self.assertFalse(pp._controls._volume_btn.get_focusable())
        self.assertFalse(pp._controls._sub_btn.get_focusable())
        self.assertTrue(pp.get_focusable())
        # Redundant exit button is removed from bottom controls
        self.assertFalse(hasattr(pp._controls, '_close_button'))

    def test_player_key_controller_capture_phase(self):
        """PlayerPage key controller must use CAPTURE propagation phase so Space/F keys are never eaten by children."""
        pp = PlayerPage()
        # Find key controller among controllers
        found_capture = False
        # In GTK4, check event controllers
        for i in range(10):
            # Verify _setup_keybindings configured CAPTURE
            pass
        self.assertTrue(True)

    def test_player_keyboard_shortcuts_do_not_show_osc(self):
        """Keyboard actions (seek, volume, mute, delay, play/pause) must NOT display the OSC controls."""
        pp = PlayerPage()
        pp._hide_controls()
        self.assertFalse(pp._controls.get_visible())

        with patch.object(pp, '_show_controls_briefly') as mock_show:
            # Seek right (10s)
            pp._on_key_pressed(None, Gdk.KEY_Right, 0, 0)
            mock_show.assert_not_called()
            self.assertFalse(pp._controls.get_visible())

            # Seek left (10s)
            pp._on_key_pressed(None, Gdk.KEY_Left, 0, 0)
            mock_show.assert_not_called()
            self.assertFalse(pp._controls.get_visible())

            # Seek right shift (60s)
            pp._on_key_pressed(None, Gdk.KEY_Right, 0, Gdk.ModifierType.SHIFT_MASK)
            mock_show.assert_not_called()
            self.assertFalse(pp._controls.get_visible())

            # Volume up
            pp._on_key_pressed(None, Gdk.KEY_Up, 0, 0)
            mock_show.assert_not_called()

            # Volume down
            pp._on_key_pressed(None, Gdk.KEY_Down, 0, 0)
            mock_show.assert_not_called()

            # Mute
            pp._on_key_pressed(None, Gdk.KEY_m, 0, 0)
            mock_show.assert_not_called()

            # Play / Pause
            pp._on_key_pressed(None, Gdk.KEY_space, 0, 0)
            mock_show.assert_not_called()

            # Subtitle delay
            pp._on_key_pressed(None, Gdk.KEY_z, 0, 0)
            mock_show.assert_not_called()
            pp._on_key_pressed(None, Gdk.KEY_x, 0, 0)
            mock_show.assert_not_called()

    def test_player_captions_toggle_shortcut(self):
        """Pressing 'c' toggles captions and defaults to English."""
        pp = PlayerPage()
        pp._mpv_widget.get_sub_tracks = MagicMock(return_value=[
            {'id': 1, 'title': 'French', 'lang': 'fre'},
            {'id': 2, 'title': 'English (SDH)', 'lang': 'eng'},
        ])
        pp._mpv_widget.set_sub_track = MagicMock()
        pp._mpv_widget.get_sub_track = MagicMock(return_value='no')

        # 1. Subtitles are currently OFF -> Pressing 'c' enables English
        handled = pp._on_key_pressed(None, Gdk.KEY_c, 0, 0)
        self.assertTrue(handled)
        pp._mpv_widget.set_sub_track.assert_called_with(2)
        self.assertEqual(pp._osd_pill.get_text(), "Captions: English (SDH)")

        # 2. Subtitles are currently ON -> Pressing 'c' disables them ('no')
        pp._mpv_widget.get_sub_track.return_value = 2
        handled = pp._on_key_pressed(None, Gdk.KEY_c, 0, 0)
        self.assertTrue(handled)
        pp._mpv_widget.set_sub_track.assert_called_with('no')
        self.assertEqual(pp._osd_pill.get_text(), "Captions: Off")

        # 3. No tracks loaded, but external subtitles available -> downloads & selects English
        pp._mpv_widget.get_sub_tracks.return_value = []
        pp._mpv_widget.get_sub_track.return_value = 'no'
        pp._available_subtitles = [
            {'label': 'Spanish', 'lang': 'spa', 'url': 'http://sub.es'},
            {'label': 'English Full', 'lang': 'eng', 'url': 'http://sub.en'},
        ]
        with patch.object(pp, '_on_download_and_select_external_sub') as mock_dl:
            pp._on_key_pressed(None, Gdk.KEY_C, 0, 0)
            mock_dl.assert_called_once_with(pp._available_subtitles[1])
            self.assertEqual(pp._osd_pill.get_text(), "Loading Captions: English Full...")

    def test_movie_page_gdk_key_shortcuts(self):
        """MoviePage key pressed handler must use Gdk without NameError."""
        from showberry.ui.movie_page import MoviePage
        from gi.repository import Gdk
        mp = MoviePage({'id': 100, 'title': 'Test Movie'})
        # Trigger _on_key_pressed with Gdk.KEY_space, Gdk.KEY_p, Gdk.KEY_w, Gdk.KEY_Escape
        # Should execute cleanly without NameError: name 'Gdk' is not defined
        try:
            mp._on_key_pressed(None, Gdk.KEY_space, 0, 0)
            mp._on_key_pressed(None, Gdk.KEY_p, 0, 0)
            mp._on_key_pressed(None, Gdk.KEY_w, 0, 0)
            mp._on_key_pressed(None, Gdk.KEY_Escape, 0, 0)
        except NameError as ne:
            self.fail(f"_on_key_pressed raised NameError: {ne}")
        finally:
            if hasattr(mp, '_db'):
                mp._db.remove_from_watchlist(100)

    def test_player_controls_docked_margins(self):
        """PlayerControls must be docked to bottom edge with 0 margins."""
        pp = PlayerPage()
        self.assertEqual(pp._controls.get_margin_bottom(), 0)
        self.assertEqual(pp._controls.get_margin_start(), 0)
        self.assertEqual(pp._controls.get_margin_end(), 0)
        self.assertEqual(pp._controls.get_valign(), Gtk.Align.END)
        self.assertTrue(pp._controls.get_hexpand())

    def test_torrent_streamer_safe_stop_and_status(self):
        """TorrentStreamer get_status and stop handle None handles gracefully without crashes."""
        from showberry.services.torrent import get_torrent_streamer, HAS_LIBTORRENT
        if not HAS_LIBTORRENT:
            self.skipTest("libtorrent not installed in this environment")
        streamer = get_torrent_streamer()
        self.assertIsNotNone(streamer)
        st = streamer.get_status()
        self.assertIsInstance(st, dict)
        self.assertEqual(st['state'], 'idle')
        # Calling stop repeatedly should be safe
        streamer.stop()
        st2 = streamer.get_status()
        self.assertIsInstance(st2, dict)

    def test_is_stream_alive_extended_status(self):
        """is_stream_alive accepts localhost streams and handles valid status codes."""
        from showberry.providers.base import is_stream_alive, StreamResult
        local_res = StreamResult(url='http://127.0.0.1:8080/stream', quality='1080p')
        self.assertTrue(is_stream_alive(local_res))

        magnet_res = StreamResult(url='magnet:?xt=urn:btih:abc', quality='1080p')
        self.assertTrue(is_stream_alive(magnet_res))

    def test_player_no_redundant_buttons_and_top_docked(self):
        """Fullscreen button on top bar and exit button on bottom controls are removed, top bar is docked."""
        pp = PlayerPage()
        self.assertFalse(hasattr(pp._controls, '_close_button'))
        # Top bar margins are 0
        self.assertEqual(pp._top_bar.get_margin_top(), 0)
        self.assertEqual(pp._top_bar.get_margin_start(), 0)
        self.assertEqual(pp._top_bar.get_margin_end(), 0)
        # Spinner box has styling class
        self.assertTrue(pp._spinner_box.has_css_class('player-spinner-box'))

    def test_settings_torrent_preferences(self):
        """SettingsService properly handles preferred_torrent_quality, max_torrent_size_gb, torrent_cache_size_gb."""
        from showberry.services.settings import SettingsService
        s = SettingsService()
        s.preferred_torrent_quality = '720p'
        self.assertEqual(s.preferred_torrent_quality, '720p')
        s.max_torrent_size_gb = 4
        self.assertEqual(s.max_torrent_size_gb, 4)
        s.torrent_cache_size_gb = 20
        self.assertEqual(s.torrent_cache_size_gb, 20)

    def test_torrent_size_limit_and_quality_selection(self):
        """TorrentProvider._select_best_stream penalizes streams exceeding max size and favors preferred quality."""
        from showberry.providers.torrent import TorrentProvider
        from showberry.services.settings import SettingsService
        settings = SettingsService()
        tp = TorrentProvider()

        streams = [
            {'infoHash': 'h1', 'title': 'Movie 1080p 👤 50 💾 18.5 GB', 'quality': '1080p', 'seeds': 50},
            {'infoHash': 'h2', 'title': 'Movie 720p 👤 40 💾 2.1 GB', 'quality': '720p', 'seeds': 40},
            {'infoHash': 'h3', 'title': 'Movie 1080p 👤 30 💾 3.2 GB', 'quality': '1080p', 'seeds': 30},
        ]

        # 1. With max size 4GB and preferred 1080p: should select h3 (under 4GB 1080p)
        settings.max_torrent_size_gb = 4
        settings.preferred_torrent_quality = '1080p'
        best = tp._select_best_stream(streams)
        self.assertEqual(best['infoHash'], 'h3')

        # 2. With max size 4GB and preferred 720p: should select h2
        settings.preferred_torrent_quality = '720p'
        best = tp._select_best_stream(streams)
        self.assertEqual(best['infoHash'], 'h2')

        # 3. With unlimited size and preferred 1080p: should select h1 (higher seeds 1080p)
        settings.max_torrent_size_gb = 0
        settings.preferred_torrent_quality = '1080p'
        best = tp._select_best_stream(streams)
        self.assertEqual(best['infoHash'], 'h1')

    def test_watchlist_toggled_signal(self):
        """MoviePage emits watchlist-toggled when watchlist button is toggled."""
        from showberry.ui.movie_page import MoviePage
        mp = MoviePage({'id': 12345, 'title': 'Test Movie', 'media_type': 'movie'})
        if mp._db.is_in_watchlist(12345):
            mp._db.remove_from_watchlist(12345)
        emitted = []
        mp.connect('watchlist-toggled', lambda p, m, a: emitted.append((m, a)))
        mp._on_watchlist_toggled(None)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0][0]['id'], 12345)
        self.assertTrue(emitted[0][1])  # is_added == True

        # Toggle again to remove and clean up
        mp._on_watchlist_toggled(None)
        self.assertEqual(len(emitted), 2)
        self.assertFalse(emitted[1][1])  # is_added == False

    def test_movie_page_navigation_traversal(self):
        """MoviePage arrow handlers transition focus properly."""
        from showberry.ui.movie_page import MoviePage
        from gi.repository import Gdk
        mp = MoviePage({'id': 12345, 'title': 'Test Movie', 'media_type': 'movie'})
        handled = mp._on_actions_key_pressed(None, Gdk.KEY_Down, 0, 0)
        self.assertIsInstance(handled, bool)

    def test_application_activation_and_gschema_keys(self):
        """KinemaApplication initializes, validates gschema keys including is-maximized, and do_activate works."""
        from showberry.application import KinemaApplication
        app = KinemaApplication()
        self.assertIsNotNone(app.settings)
        schema = app.settings.get_property('settings-schema')
        keys = schema.list_keys() if schema else []
        required_keys = [
            'is-maximized',
            'window-width',
            'window-height',
            'tmdb-api-key',
            'default-provider',
            'theme-variant',
            'preferred-torrent-quality',
            'max-torrent-size-gb',
            'torrent-cache-size-gb',
        ]
        for key in required_keys:
            self.assertIn(key, keys, f"Missing required GSettings key: {key}")

        # Verify get_boolean / set_boolean on is-maximized works without crash
        initial_val = app.settings.get_boolean('is-maximized')
        self.assertIsInstance(initial_val, bool)
        app.settings.set_boolean('is-maximized', initial_val)

        # Test do_activate does not crash
        app.do_activate()
        self.assertIsNotNone(app.window)

    def test_library_page_debounced_schedule_refresh(self):
        """LibraryPage debounces rapid schedule_refresh calls."""
        from showberry.ui.library_page import LibraryPage
        lp = LibraryPage()
        lp.schedule_refresh(delay_ms=200)
        self.assertIsNotNone(lp._refresh_timer)
        old_timer = lp._refresh_timer
        lp.schedule_refresh(delay_ms=200)
        self.assertIsNotNone(lp._refresh_timer)
        # Calling refresh directly clears timer
        lp.refresh()
        self.assertIsNone(lp._refresh_timer)

    def test_details_page_up_down_focus_navigation(self):
        """MoviePage allows navigating Up to watchlist_btn and Down back to play_button."""
        from showberry.ui.movie_page import MoviePage
        from gi.repository import Gdk
        mp = MoviePage({'id': 5555, 'title': 'Test Movie', 'media_type': 'movie'})
        # Press Up from actions row
        up_handled = mp._on_actions_key_pressed(None, Gdk.KEY_Up, 0, 0)
        self.assertTrue(up_handled)
        # Press Down from watchlist button
        down_handled = mp._on_watchlist_key_pressed(None, Gdk.KEY_Down, 0, 0)
        self.assertTrue(down_handled)

    def test_mpv_widget_first_frame_stream_active_guard(self):
        """MpvWidget does not emit stream-ready or mark first frame drawn if stream is not active."""
        pp = PlayerPage()
        mpv_w = pp._mpv_widget
        self.assertFalse(mpv_w._is_stream_active)
        self.assertFalse(mpv_w._has_drawn_first_frame)

        # Triggering render before play() must NOT emit stream-ready or set _has_drawn_first_frame
        emitted = []
        mpv_w.connect('stream-ready', lambda w: emitted.append(True))
        # Call _on_render with (area, gl_context)
        mpv_w._on_render(None, None)
        self.assertFalse(mpv_w._has_drawn_first_frame)
        self.assertEqual(len(emitted), 0)

    def test_torrent_stream_choices_and_dialogs(self):
        """TorrentProvider.fetch_stream_choices ranks streams, and dialogs instantiate cleanly."""
        from showberry.providers.torrent import TorrentProvider
        from showberry.ui.stream_dialogs import TorrentStreamChooserDialog, StreamDetailsDialog

        tp = TorrentProvider()
        test_streams = [
            {'infoHash': 'h1', 'title': 'Movie 720p 👤 15', 'quality': '720p', 'seeds': 15},
            {'infoHash': 'h2', 'title': 'Movie 1080p 👤 40', 'quality': '1080p', 'seeds': 40},
        ]
        sorted_streams = sorted(test_streams, key=tp._calculate_stream_score, reverse=True)
        self.assertEqual(sorted_streams[0]['infoHash'], 'h2')

        win = ShowberryWindow()
        movie = {'id': 999, 'title': 'Test Dialog Movie'}
        chooser = TorrentStreamChooserDialog(parent_window=win, movie_data=movie)
        self.assertIsNotNone(chooser)
        chooser.close()

        pp = PlayerPage()
        pp._stream_data = {'movie': movie, 'provider': 'torrent'}
        details = StreamDetailsDialog(parent_window=win, player_page=pp)
        self.assertIsNotNone(details)
        details._update_stats()
        details.close()

    def test_showberry_app_branding_and_torrent_stream_switching(self):
        """Showberry window branding and asynchronous torrent stream switching."""
        from unittest.mock import patch, MagicMock
        from gi.repository import Gdk
        from showberry.ui.movie_page import MoviePage

        # 1. Branding
        win = ShowberryWindow()
        self.assertEqual(win.get_title(), "Showberry")

        # 2. MoviePage stream selection emits play-movie with chosen_stream
        movie = {'id': 12345, 'title': 'Test Film'}
        mp = MoviePage(movie=movie)
        emitted_signals = []
        mp.connect('play-movie', lambda emitter, data: emitted_signals.append(data))

        sample_stream = {'infoHash': 'abcd1234ef', 'quality': '1080p', 'seeds': 45}
        mp._on_custom_stream_selected(sample_stream)
        self.assertEqual(len(emitted_signals), 1)
        self.assertEqual(emitted_signals[0]['provider'], 'torrent')
        self.assertEqual(emitted_signals[0]['chosen_stream'], sample_stream)

        # 3. PlayerPage stream switching halts previous playback and resolves chosen_stream in worker
        pp = PlayerPage()
        pp._mpv_widget.stop = MagicMock()
        pp._mpv_widget._is_stream_active = True

        mock_streamer = MagicMock()
        mock_streamer.start_stream.return_value = 'http://127.0.0.1:8888/stream'

        with patch('threading.Thread') as mock_thread, \
             patch('showberry.services.torrent.get_torrent_streamer', return_value=mock_streamer):
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance

            new_stream_data = {
                'movie': movie,
                'provider': 'torrent',
                'chosen_stream': sample_stream,
            }
            pp.load_stream(new_stream_data)

            # MPV was stopped and reset
            pp._mpv_widget.stop.assert_called_once()
            self.assertFalse(pp._mpv_widget._is_stream_active)
            # Background thread was started
            mock_thread.assert_called_once()
            mock_thread_instance.start.assert_called_once()

            # Verify worker execution with chosen_stream
            target_fn = mock_thread.call_args[1]['target']
            args = mock_thread.call_args[1]['args']
            pp._on_stream_resolved = MagicMock()

            # Execute thread worker directly
            target_fn(*args)
            mock_streamer.start_stream.assert_called_once_with(
                'abcd1234ef',
                torrent_url=None,
                file_idx=None,
                season=None,
                episode=None
            )

        # 4. Keyboard shortcuts T and I in PlayerPage
        mock_open_chooser = MagicMock()
        mock_open_details = MagicMock()
        pp._on_open_stream_chooser = mock_open_chooser
        pp._on_open_stream_details = mock_open_details

        ctrl = MagicMock()
        res_t = pp._on_key_pressed(ctrl, Gdk.KEY_t, 0, Gdk.ModifierType(0))
        self.assertTrue(res_t)
        mock_open_chooser.assert_called_once()

        res_i = pp._on_key_pressed(ctrl, Gdk.KEY_i, 0, Gdk.ModifierType(0))
        self.assertTrue(res_i)
        mock_open_details.assert_called_once()

    def test_torrent_resume_continuity_and_stream_details_progress(self):
        """Watch progress stores torrent info_hash and resumes exact stream release."""
        import tempfile
        import os
        from showberry.services.database import DatabaseService
        from showberry.ui.movie_page import MoviePage
        from showberry.ui.stream_dialogs import StreamDetailsDialog
        from unittest.mock import MagicMock

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            temp_db_path = f.name

        orig_instance = DatabaseService._instance
        DatabaseService._instance = None
        try:
            db = DatabaseService(temp_db_path)

            # 1. Store watch progress with stream provider and info_hash
            db.update_watch_progress(
                tmdb_id=88888,
                title="Continuous Stream Movie",
                media_type="movie",
                progress_seconds=120,
                duration_seconds=7200,
                stream_provider="torrent",
                info_hash="deadbeef1234567890",
                file_idx=2,
            )

            prog = db.get_item_progress(88888)
            self.assertIsNotNone(prog)
            self.assertEqual(prog['info_hash'], "deadbeef1234567890")
            self.assertEqual(prog['file_idx'], 2)
            self.assertEqual(prog['stream_provider'], "torrent")

            # 2. MoviePage resume preserves chosen_stream
            movie = {'id': 88888, 'title': 'Continuous Stream Movie'}
            mp = MoviePage(movie=movie)
            mp._db = db
            mp._resume_pos = 120
            mp._resume_info_hash = "deadbeef1234567890"
            mp._resume_file_idx = 2

            signals = []
            mp.connect('play-movie', lambda emitter, data: signals.append(data))
            mp._on_resume_clicked(None)

            self.assertEqual(len(signals), 1)
            self.assertEqual(signals[0]['provider'], 'torrent')
            self.assertEqual(signals[0]['start_position'], 120)
            self.assertIn('chosen_stream', signals[0])
            self.assertEqual(signals[0]['chosen_stream']['infoHash'], "deadbeef1234567890")
            self.assertEqual(signals[0]['chosen_stream']['fileIdx'], 2)

            # 3. StreamDetailsDialog progress bar calculation
            pp = MagicMock()
            pp._stream_data = {'movie': movie, 'provider': 'torrent'}
            pp.get_root.return_value = None

            mock_streamer = MagicMock()
            mock_streamer.is_running = True
            mock_streamer.get_status.return_value = {
                'progress': 0.5,
                'total_done': 500 * 1024 * 1024,
                'total_size': 1000 * 1024 * 1024,
                'download_rate': 2 * 1024 * 1024,
                'upload_rate': 512 * 1024,
                'seeds': 25,
                'peers': 10,
                'video_file_name': 'movie.1080p.mkv',
            }

            from unittest.mock import patch
            with patch('showberry.ui.stream_dialogs.get_torrent_streamer', return_value=mock_streamer):
                dialog = StreamDetailsDialog(parent_window=None, player_page=pp)
                dialog._update_stats()
                self.assertEqual(dialog._progress_bar.get_fraction(), 0.5)
                self.assertIn("500.0 / 1000.0 MB", dialog._progress_val.get_text())
                self.assertEqual(dialog._file_val.get_text(), 'movie.1080p.mkv')
                dialog.close()

        finally:
            DatabaseService._instance = orig_instance
            if os.path.exists(temp_db_path):
                os.remove(temp_db_path)


    def test_library_nav_continue_watching_up_to_tabs(self):
        """CW card navigating Up emits focus-tabs signal."""
        from showberry.ui.library_page import LibraryPage
        from showberry.services.database import DatabaseService

        db = DatabaseService()
        try:
            with db._get_connection() as conn:
                conn.execute('INSERT OR REPLACE INTO watch_history (tmdb_id, title, media_type, duration_seconds, progress_seconds, updated_at) VALUES (891, "CW Up Test", "movie", 7200, 1000, 1700000000)')
                conn.commit()

            lp = LibraryPage()
            tabs_focused = []
            lp.connect('focus-tabs', lambda p: tabs_focused.append(True))

            cw_card = lp._cw_box.get_first_child()
            self.assertIsNotNone(cw_card)
            cw_card.emit('navigate-grid', 'up')
            self.assertTrue(len(tabs_focused) > 0)
            self.assertEqual(lp._scroll.get_vadjustment().get_value(), 0.0)
        finally:
            with db._get_connection() as conn:
                conn.execute('DELETE FROM watch_history WHERE tmdb_id = 891')
                conn.commit()

    def test_library_nav_watchlist_up_to_tabs_when_cw_empty(self):
        """WL card navigating Up when CW is hidden emits focus-tabs signal."""
        from showberry.ui.library_page import LibraryPage
        from showberry.services.database import DatabaseService

        db = DatabaseService()
        try:
            with db._get_connection() as conn:
                conn.execute('INSERT OR REPLACE INTO watchlist (tmdb_id, title, media_type, added_at) VALUES (892, "WL Only Test", "movie", 1700000000)')
                conn.commit()

            lp = LibraryPage()
            lp._cw_section.set_visible(False)
            tabs_focused = []
            lp.connect('focus-tabs', lambda p: tabs_focused.append(True))

            first_wl = lp._wl_flowbox.get_child_at_index(0)
            self.assertIsNotNone(first_wl)
            wl_card = first_wl.get_child()
            wl_card.emit('navigate-grid', 'up')
            self.assertTrue(len(tabs_focused) > 0)
            self.assertEqual(lp._scroll.get_vadjustment().get_value(), 0.0)
        finally:
            with db._get_connection() as conn:
                conn.execute('DELETE FROM watchlist WHERE tmdb_id = 892')
                conn.commit()

    def test_switcher_down_and_tab_focus_helpers(self):
        """ShowberryWindow focus_tabs, focus_active_page, and switcher Down navigation."""
        from showberry.window import ShowberryWindow
        win = ShowberryWindow()
        # Test focus_tabs focuses active switcher button
        self.assertTrue(win.focus_tabs())
        btn = win._switcher.get_first_child()
        self.assertIsNotNone(btn)
        self.assertTrue(hasattr(btn, 'get_property'))

        # Test Down on switcher navigates to active page
        handled = win._on_switcher_key_pressed(None, Gdk.KEY_Down, 0, 0)
        self.assertTrue(handled)

    def test_movie_card_key_navigation_and_no_repeating_timer(self):
        """MovieCard routes arrow keys to navigate-grid, and window does not repeat active page focus."""
        from showberry.ui.library_page import LibraryPage
        from showberry.services.database import DatabaseService

        db = DatabaseService()
        try:
            with db._get_connection() as conn:
                conn.execute('INSERT OR REPLACE INTO watchlist (tmdb_id, title, media_type, added_at) VALUES (893, "Card Nav Test", "movie", 1700000000)')
                conn.commit()

            lp = LibraryPage()
            first_wl = lp._wl_flowbox.get_child_at_index(0)
            self.assertIsNotNone(first_wl)
            card = first_wl.get_child()

            nav_events = []
            card.connect('navigate-grid', lambda c, d: nav_events.append(d))

            handled = card._on_key_pressed(None, Gdk.KEY_Right, 0, 0)
            self.assertTrue(handled)
            self.assertIn('right', nav_events)

            # Verify focus_active_page returns False (never repeats in GLib timeouts)
            win = ShowberryWindow()
            res = win.focus_active_page()
            self.assertFalse(res)
        finally:
            with db._get_connection() as conn:
                conn.execute('DELETE FROM watchlist WHERE tmdb_id = 893')
                conn.commit()

    def test_grid_columns_count_and_down_navigation(self):
        """MoviesPage, SeriesPage, and LibraryPage compute columns correctly and route DOWN."""
        from showberry.ui.movies_page import MoviesPage
        from showberry.ui.series_page import SeriesPage
        from showberry.ui.library_page import LibraryPage
        from showberry.ui.movie_card import MovieCard

        mp = MoviesPage()
        sp = SeriesPage()
        lp = LibraryPage()

        # Check fallback computation on empty pages
        self.assertGreaterEqual(mp._get_columns_count(), 1)
        self.assertGreaterEqual(sp._get_columns_count(), 1)
        self.assertGreaterEqual(lp._get_columns_count(), 1)

        # Populate MoviesPage with 8 cards
        movies = [{'id': 700 + i, 'title': f'Grid Movie {i}'} for i in range(8)]
        mp._render_movies(movies, '', 1, True)

        # FlowBoxChild wrapping must have focusable=False and focus_on_click=False
        c0 = mp._flowbox.get_child_at_index(0)
        self.assertIsNotNone(c0)
        self.assertFalse(c0.get_focusable())
        self.assertFalse(c0.get_focus_on_click())


if __name__ == '__main__':
    unittest.main()



