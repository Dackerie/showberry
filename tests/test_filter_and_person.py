"""Tests for Filter & Sort features, TMDB discover, and PersonPage filmography view."""

import unittest
from unittest.mock import MagicMock, patch
from datetime import date, datetime, timedelta
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk

from showberry.services.tmdb import (
    TMDBClient,
    MOVIE_GENRES,
    TV_GENRES,
    LANGUAGES,
    YEAR_OPTIONS,
    SORT_OPTIONS,
)
from showberry.ui.filter_popover import FilterSortPopover
from showberry.ui.person_page import PersonPage
from showberry.ui.movie_page import MoviePage
from showberry.ui.movie_card import MovieCard, _get_badge_label
from showberry.window import ShowberryWindow


class TestTMDBDiscoverAndPerson(unittest.TestCase):
    """Test discover_movies, discover_tv, get_person_details, and get_person_credits."""

    def setUp(self):
        self.tmdb = TMDBClient()

    @patch.object(TMDBClient, '_request')
    def test_discover_movies_params(self, mock_request):
        mock_request.return_value = {'results': [{'id': 1, 'title': 'Filtered Movie', 'vote_average': 8.0}]}

        res = self.tmdb.discover_movies(
            page=1,
            sort_by='vote_average.desc',
            genre_id=28,  # Action
            year='2023',
            language='en',
            only_released=True,
        )

        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['title'], 'Filtered Movie')
        self.assertEqual(res[0]['media_type'], 'movie')

        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], '/discover/movie')
        params = args[1]
        self.assertEqual(params.get('sort_by'), 'vote_average.desc')
        self.assertEqual(params.get('with_genres'), '28')
        self.assertEqual(params.get('primary_release_year'), 2023)
        self.assertEqual(params.get('with_original_language'), 'en')
        # High vote threshold for movies (300)
        self.assertEqual(params.get('vote_count.gte'), 300)
        # only_released filter active
        self.assertEqual(params.get('primary_release_date.lte'), date.today().isoformat())

    @patch.object(TMDBClient, '_request')
    def test_discover_movies_vintage_threshold(self, mock_request):
        mock_request.return_value = {'results': []}

        self.tmdb.discover_movies(sort_by='vote_average.desc', year='1980s')
        args, _ = mock_request.call_args
        params = args[1]
        self.assertEqual(params.get('vote_count.gte'), 100)

    @patch.object(TMDBClient, '_request')
    def test_discover_tv_decade_filter(self, mock_request):
        mock_request.return_value = {'results': [{'id': 2, 'name': 'Decade Series', 'vote_average': 7.5}]}

        res = self.tmdb.discover_tv(
            page=1,
            sort_by='vote_average.desc',
            genre_id=18,  # Drama
            year='2010s',
            language='ja',
            only_released=True,
        )

        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['title'], 'Decade Series')
        self.assertEqual(res[0]['media_type'], 'tv')

        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], '/discover/tv')
        params = args[1]
        self.assertEqual(params.get('vote_count.gte'), 150)
        self.assertEqual(params.get('first_air_date.gte'), '2010-01-01')
        self.assertEqual(params.get('first_air_date.lte'), '2019-12-31')
        self.assertEqual(params.get('with_original_language'), 'ja')

    @patch.object(TMDBClient, '_request')
    def test_get_person_details(self, mock_request):
        mock_request.return_value = {
            'id': 12345,
            'name': 'Cillian Murphy',
            'biography': 'Irish actor born in Douglas, Cork.',
            'profile_path': '/path.jpg',
            'known_for_department': 'Acting',
            'place_of_birth': 'Douglas, Cork, Ireland',
        }

        details = self.tmdb.get_person_details(12345)
        self.assertIsNotNone(details)
        self.assertEqual(details['name'], 'Cillian Murphy')
        self.assertEqual(details['known_for_department'], 'Acting')
        mock_request.assert_called_once_with('/person/12345')

    @patch.object(TMDBClient, '_request')
    def test_get_person_credits(self, mock_request):
        mock_request.return_value = {
            'cast': [
                {'id': 10, 'title': 'Oppenheimer', 'media_type': 'movie', 'popularity': 90.0},
                {'id': 20, 'name': 'Peaky Blinders', 'media_type': 'tv', 'popularity': 80.0},
                {'id': 10, 'title': 'Oppenheimer Duplicate', 'media_type': 'movie', 'popularity': 50.0},
            ]
        }

        credits = self.tmdb.get_person_credits(12345)
        self.assertEqual(len(credits), 2)  # Duplicates deduplicated
        self.assertEqual(credits[0]['id'], 10)
        self.assertEqual(credits[0]['title'], 'Oppenheimer')
        self.assertEqual(credits[1]['id'], 20)
        self.assertEqual(credits[1]['title'], 'Peaky Blinders')

    @patch.object(TMDBClient, '_request')
    def test_get_person_credits_crew_and_directing(self, mock_request):
        """Verify directing credits are parsed, marked is_director=True, and sorted first."""
        mock_request.return_value = {
            'crew': [
                {'id': 100, 'title': 'Oppenheimer', 'media_type': 'movie', 'job': 'Director', 'department': 'Directing', 'popularity': 95.0},
                {'id': 101, 'title': 'Tenet', 'media_type': 'movie', 'job': 'Director', 'department': 'Directing', 'popularity': 75.0},
            ],
            'cast': [
                {'id': 102, 'title': 'Cameo Appearance', 'media_type': 'movie', 'character': 'Man in crowd', 'popularity': 120.0},
            ]
        }

        credits = self.tmdb.get_person_credits(525)
        self.assertEqual(len(credits), 3)
        # Directing credits should come first even if acting cameo has higher popularity
        self.assertTrue(credits[0]['is_director'])
        self.assertTrue(credits[1]['is_director'])
        self.assertFalse(credits[2]['is_director'])
        self.assertEqual(credits[0]['title'], 'Oppenheimer')
        self.assertEqual(credits[1]['title'], 'Tenet')
        self.assertEqual(credits[2]['title'], 'Cameo Appearance')

    @patch.object(TMDBClient, '_request')
    def test_search_person(self, mock_request):
        """Verify search_person queries TMDB person search endpoint."""
        mock_request.return_value = {'results': [{'id': 525, 'name': 'Christopher Nolan'}]}
        results = self.tmdb.search_person('Christopher Nolan')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], 525)
        mock_request.assert_called_once_with('/search/person', {'query': 'Christopher Nolan'})


class TestFilterSortPopover(unittest.TestCase):
    """Test FilterSortPopover UI, leave timer, only_released switch, and filter state handling."""

    def test_popover_initial_state(self):
        popover = FilterSortPopover(is_tv=False)
        self.assertFalse(popover.is_active())

        filters = popover.get_filter_params()
        self.assertEqual(filters['sort_by'], 'popularity.desc')
        self.assertEqual(filters['genre_id'], 0)
        self.assertEqual(filters['year'], 'All Years')
        self.assertEqual(filters['language'], '')
        self.assertFalse(filters['only_released'])

    def test_popover_tv_genres(self):
        popover_tv = FilterSortPopover(is_tv=True)
        self.assertEqual(popover_tv._genres, TV_GENRES)

    def test_popover_selection_and_reset(self):
        popover = FilterSortPopover(is_tv=False)
        signals = []
        popover.connect('filter-changed', lambda p, f: signals.append(f))

        # Change sort to top_rated (index 1 in SORT_OPTIONS)
        popover._sort_dropdown.set_selected(1)
        self.assertTrue(popover.is_active())
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['sort_by'], 'vote_average.desc')

        # Change genre to index 1 (Action)
        popover._genre_dropdown.set_selected(1)
        self.assertEqual(len(signals), 2)
        self.assertNotEqual(signals[1]['genre_id'], 0)

        # Toggle only_released
        popover._released_switch.set_active(True)
        self.assertEqual(len(signals), 3)
        self.assertTrue(signals[2]['only_released'])

        # Reset filters
        popover.reset()
        self.assertFalse(popover.is_active())
        self.assertEqual(popover.get_filter_params()['sort_by'], 'popularity.desc')
        self.assertEqual(popover.get_filter_params()['genre_id'], 0)
        self.assertFalse(popover.get_filter_params()['only_released'])

    def test_update_button_style(self):
        popover = FilterSortPopover(is_tv=False)
        btn = Gtk.MenuButton()

        popover.update_button_style(btn)
        self.assertFalse(btn.has_css_class('suggested-action'))

        # Set active filter
        popover._year_dropdown.set_selected(1)
        self.assertTrue(popover.is_active())
        popover.update_button_style(btn)
        self.assertTrue(btn.has_css_class('suggested-action'))

        # Reset
        popover.reset()
        popover.update_button_style(btn)
        self.assertFalse(btn.has_css_class('suggested-action'))

    def test_motion_leave_timer(self):
        popover = FilterSortPopover(is_tv=False)
        self.assertFalse(popover._is_any_dropdown_open())

        # Trigger motion leave
        popover._on_motion_leave(None)
        self.assertIsNotNone(popover._leave_timer_id)

        # Re-entering cancels timer
        popover._on_motion_enter(None, 0, 0)
        self.assertIsNone(popover._leave_timer_id)


class TestUpcomingBadges(unittest.TestCase):
    """Test upcoming badges on cards and movie detail pages."""

    def setUp(self):
        self._details_patcher = patch.object(MoviePage, '_load_details_async')
        self._details_patcher.start()
        self._card_data_patcher = patch.object(MovieCard, '_load_card_data')
        self._card_data_patcher.start()

    def tearDown(self):
        self._details_patcher.stop()
        self._card_data_patcher.stop()

    def test_get_badge_label_upcoming(self):
        future_date = (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d')
        past_date_in_theaters = (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d')
        old_date = '2015-05-15'

        # Future movie
        self.assertEqual(_get_badge_label({'media_type': 'movie', 'release_date': future_date}), 'UPCOMING')
        # In theaters
        self.assertEqual(_get_badge_label({'media_type': 'movie', 'release_date': past_date_in_theaters}), 'IN THEATERS')
        # Old movie
        self.assertIsNone(_get_badge_label({'media_type': 'movie', 'release_date': old_date}))
        # Future TV show
        self.assertEqual(_get_badge_label({'media_type': 'tv', 'first_air_date': future_date}), 'UPCOMING')

    def test_movie_card_upcoming_styling(self):
        future_date = (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d')
        card = MovieCard({'id': 888, 'title': 'Future Movie', 'release_date': future_date})
        self.assertTrue(card._badge.get_visible())
        self.assertEqual(card._badge.get_text(), 'UPCOMING')
        self.assertTrue(card._badge.has_css_class('badge-upcoming'))

    def test_movie_card_director_badge(self):
        """Verify cards for directed titles show DIRECTOR badge with badge-director styling."""
        card = MovieCard({'id': 888, 'title': 'Directed Masterpiece', 'is_director': True})
        self.assertTrue(card._badge.get_visible())
        self.assertEqual(card._badge.get_text(), 'DIRECTOR')
        self.assertTrue(card._badge.has_css_class('badge-director'))
        self.assertFalse(card._badge.has_css_class('badge-upcoming'))

    def test_movie_page_upcoming_indicator(self):
        future_date = (datetime.now() + timedelta(days=120)).strftime('%Y-%m-%d')
        year = future_date[:4]
        mp = MoviePage({'id': 889, 'title': 'Future Release', 'release_date': future_date})
        self.assertEqual(mp._year_label.get_text(), f"Upcoming ({year})")
        self.assertIsNotNone(mp._play_button.get_tooltip_text())


class TestPersonPage(unittest.TestCase):
    """Test PersonPage filmography UI, tabs, and interactions."""

    def setUp(self):
        self._load_patcher = patch.object(PersonPage, '_load_person_info')
        self._load_patcher.start()
        self._avatar_patcher = patch.object(PersonPage, '_load_avatar')
        self._avatar_patcher.start()
        self.person_data = {
            'id': 999,
            'name': 'Florence Pugh',
            'profile_path': '/florence.jpg',
            'character': 'Yelena Belova',
        }
        self.page = PersonPage(self.person_data)

    def tearDown(self):
        self._load_patcher.stop()
        self._avatar_patcher.stop()

    def test_page_structure(self):
        self.assertEqual(self.page.get_title(), 'Florence Pugh')
        self.assertEqual(self.page._name_label.get_text(), 'Florence Pugh')
        self.assertEqual(self.page._bio_label.get_lines(), 4)

    def test_bio_clamp_toggle(self):
        long_bio = "A" * 400
        self.page._apply_data({'biography': long_bio, 'name': 'Florence Pugh'}, [])
        self.assertTrue(self.page._bio_label.get_visible())
        self.assertTrue(self.page._bio_expand_btn.get_visible())
        self.assertEqual(self.page._bio_expand_btn.get_label(), "Read More")

        # Click Read More
        self.page._on_expand_bio_clicked(self.page._bio_expand_btn)
        self.assertEqual(self.page._bio_label.get_lines(), 0)
        self.assertEqual(self.page._bio_expand_btn.get_label(), "Show Less")

        # Click Show Less
        self.page._on_expand_bio_clicked(self.page._bio_expand_btn)
        self.assertEqual(self.page._bio_label.get_lines(), 4)
        self.assertEqual(self.page._bio_expand_btn.get_label(), "Read More")

    def test_bio_multi_paragraph_clamping(self):
        multi_para = "Paragraph 1 is here.\n\nParagraph 2 is here.\n\nParagraph 3 is here.\n\nParagraph 4 is here."
        self.page._apply_data({'biography': multi_para, 'name': 'Florence Pugh'}, [])
        # Initially clamped to normalized 4-line representation without raw paragraph blowout
        self.assertEqual(self.page._bio_label.get_lines(), 4)
        self.assertNotIn('\n', self.page._bio_label.get_text())
        self.assertTrue(self.page._bio_expand_btn.get_visible())

        # Expand restores full multi-paragraph text
        self.page._on_expand_bio_clicked(self.page._bio_expand_btn)
        self.assertEqual(self.page._bio_label.get_lines(), 0)
        self.assertIn('\n\n', self.page._bio_label.get_text())
        self.assertEqual(self.page._bio_label.get_text(), multi_para)

        # Collapse returns to normalized 4-line representation
        self.page._on_expand_bio_clicked(self.page._bio_expand_btn)
        self.assertEqual(self.page._bio_label.get_lines(), 4)
        self.assertNotIn('\n', self.page._bio_label.get_text())

    def test_filmography_filtering_tabs(self):
        credits = [
            {'id': 1, 'title': 'Movie 1', 'media_type': 'movie', 'popularity': 50.0},
            {'id': 2, 'title': 'Movie 2', 'media_type': 'movie', 'popularity': 40.0},
            {'id': 3, 'title': 'Series 1', 'name': 'Series 1', 'media_type': 'tv', 'popularity': 60.0},
        ]
        self.page._apply_data(None, credits)

        # Default filter: 'all'
        self.assertIsNotNone(self.page._flowbox.get_child_at_index(0))
        self.assertIsNotNone(self.page._flowbox.get_child_at_index(1))
        self.assertIsNotNone(self.page._flowbox.get_child_at_index(2))
        self.assertIsNone(self.page._flowbox.get_child_at_index(3))

        # Filter: 'movie'
        self.page._btn_movies.set_active(True)
        self.assertEqual(self.page._filter_type, 'movie')
        self.assertIsNotNone(self.page._flowbox.get_child_at_index(0))
        self.assertIsNotNone(self.page._flowbox.get_child_at_index(1))
        self.assertIsNone(self.page._flowbox.get_child_at_index(2))

        # Filter: 'tv'
        self.page._btn_tv.set_active(True)
        self.assertEqual(self.page._filter_type, 'tv')
        self.assertIsNotNone(self.page._flowbox.get_child_at_index(0))
        self.assertIsNone(self.page._flowbox.get_child_at_index(1))

    def test_movie_selected_signal(self):
        credits = [{'id': 1, 'title': 'Movie 1', 'media_type': 'movie', 'popularity': 50.0}]
        self.page._apply_data(None, credits)

        selected_items = []
        self.page.connect('movie-selected', lambda p, m: selected_items.append(m))

        # Click card
        child = self.page._flowbox.get_child_at_index(0)
        card = child.get_child()
        card.emit('clicked-movie', card._movie)

        self.assertEqual(len(selected_items), 1)
        self.assertEqual(selected_items[0]['id'], 1)
        self.assertEqual(selected_items[0]['title'], 'Movie 1')


class TestCastClickToPersonIntegration(unittest.TestCase):
    """Test clicking cast member chips in MoviePage and navigation in ShowberryWindow."""

    def setUp(self):
        self._details_patcher = patch.object(MoviePage, '_load_details_async')
        self._details_patcher.start()
        self._load_patcher = patch.object(PersonPage, '_load_person_info')
        self._load_patcher.start()

    def tearDown(self):
        self._details_patcher.stop()
        self._load_patcher.stop()

    def test_movie_page_cast_click_emits_person_selected(self):
        mp = MoviePage({'id': 500, 'title': 'Interstellar'})
        cast = [{'id': 102, 'name': 'Matthew McConaughey', 'character': 'Cooper'}]
        mp._render_cast(cast)

        person_emitted = []
        mp.connect('person-selected', lambda p, person: person_emitted.append(person))

        cast_btn = mp._cast_row.get_first_child()
        self.assertIsInstance(cast_btn, Gtk.Button)
        cast_btn.emit('clicked')

        self.assertEqual(len(person_emitted), 1)
        self.assertEqual(person_emitted[0]['id'], 102)
        self.assertEqual(person_emitted[0]['name'], 'Matthew McConaughey')

    def test_window_on_person_selected_pushes_page(self):
        win = ShowberryWindow()
        person_data = {'id': 102, 'name': 'Matthew McConaughey'}
        win._on_person_selected(None, person_data)

        visible = win._nav_view.get_visible_page()
        self.assertIsInstance(visible, PersonPage)
        self.assertEqual(visible.get_title(), 'Matthew McConaughey')


class TestMoviePageDirectorChips(unittest.TestCase):
    """Test MoviePage clickable director & creator chips."""

    def setUp(self):
        self._details_patcher = patch.object(MoviePage, '_load_details_async')
        self._details_patcher.start()

    def tearDown(self):
        self._details_patcher.stop()

    def test_movie_page_single_director_chip(self):
        mp = MoviePage({
            'id': 500,
            'title': 'Oppenheimer',
            'directors': ['Christopher Nolan'],
            'directors_data': [{'id': 525, 'name': 'Christopher Nolan', 'job': 'Director'}],
        })
        self.assertTrue(mp._director_box.get_visible())
        self.assertTrue(mp._director_label.get_visible())
        self.assertEqual(mp._director_label.get_text(), 'Directed by Christopher Nolan')

        # Check chip button
        chip = mp._director_chips_box.get_first_child()
        self.assertIsInstance(chip, Gtk.Button)
        self.assertTrue(chip.has_css_class('director-chip'))

        # Clicking chip emits person-selected
        selected = []
        mp.connect('person-selected', lambda p, data: selected.append(data))
        chip.emit('clicked')
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]['id'], 525)
        self.assertEqual(selected[0]['name'], 'Christopher Nolan')

    def test_movie_page_tv_creator_chip(self):
        mp = MoviePage({
            'id': 1396,
            'title': 'Breaking Bad',
            'media_type': 'tv',
            'directors_data': [{'id': 666, 'name': 'Vince Gilligan', 'job': 'Creator'}],
        })
        self.assertTrue(mp._director_box.get_visible())
        self.assertEqual(mp._director_label.get_text(), 'Created by Vince Gilligan')

    def test_movie_page_multiple_directors(self):
        mp = MoviePage({
            'id': 100,
            'title': 'Fargo',
            'directors': ['Joel Coen', 'Ethan Coen'],
        })
        self.assertTrue(mp._director_box.get_visible())
        chip1 = mp._director_chips_box.get_first_child()
        self.assertIsNotNone(chip1)
        chip2 = chip1.get_next_sibling()
        self.assertIsNotNone(chip2)

        selected = []
        mp.connect('person-selected', lambda p, data: selected.append(data))
        chip2.emit('clicked')
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]['name'], 'Ethan Coen')


class TestPersonPageKeyboardNav(unittest.TestCase):
    """Test PersonPage tab counts, keyboard navigation, and search fallback."""

    def setUp(self):
        self._load_patcher = patch.object(PersonPage, '_load_person_info')
        self._load_patcher.start()

    def tearDown(self):
        self._load_patcher.stop()

    def test_load_person_info_spawns_thread(self):
        with patch('threading.Thread') as mock_thread:
            page = PersonPage({'id': 525, 'name': 'Christopher Nolan'})
            self._load_patcher.stop()
            try:
                page._load_person_info(525)
                mock_thread.assert_called_once()
            finally:
                self._load_patcher.start()

    def test_tab_counts_update(self):
        page = PersonPage({'id': 525, 'name': 'Christopher Nolan'})
        credits = [
            {'id': 1, 'title': 'Oppenheimer', 'media_type': 'movie', 'is_director': True},
            {'id': 2, 'title': 'Inception', 'media_type': 'movie', 'is_director': True},
            {'id': 3, 'title': 'TV Special', 'media_type': 'tv', 'is_director': False},
        ]
        page._apply_data({'name': 'Christopher Nolan', 'known_for_department': 'Directing'}, credits)
        self.assertEqual(page._btn_all.get_label(), 'All (3)')
        self.assertEqual(page._btn_movies.get_label(), 'Movies (2)')
        self.assertEqual(page._btn_tv.get_label(), 'TV Series (1)')

    def test_focus_active_filter_btn_and_first_card(self):
        page = PersonPage({'id': 525, 'name': 'Christopher Nolan'})
        credits = [{'id': 1, 'title': 'Oppenheimer', 'media_type': 'movie'}]
        page._apply_data(None, credits)

        # Active filter button selection
        page._btn_movies.set_active(True)
        page._focus_active_filter_btn()
        # Should focus first card
        ok = page._focus_first_card()
        self.assertTrue(ok)

    def test_on_card_navigate_up_focuses_filter_btn(self):
        page = PersonPage({'id': 525, 'name': 'Christopher Nolan'})
        credits = [
            {'id': 1, 'title': 'Oppenheimer', 'media_type': 'movie'},
            {'id': 2, 'title': 'Inception', 'media_type': 'movie'},
        ]
        page._apply_data(None, credits)

        child = page._flowbox.get_child_at_index(0)
        card = child.get_child()
        # Navigate up from first row
        page._on_card_navigate(card, 'up')
        self.assertEqual(page._scroll.get_vadjustment().get_value(), 0.0)

    def test_person_page_escape_pop(self):
        page = PersonPage({'id': 525, 'name': 'Christopher Nolan'})
        nav_view = Adw.NavigationView()
        nav_view.push(page)
        self.assertEqual(nav_view.get_visible_page(), page)

        # Send Escape
        handled = page._on_key_pressed(None, Gdk.KEY_Escape, 0, 0)
        self.assertTrue(handled)

    @patch.object(TMDBClient, 'search_person')
    @patch.object(TMDBClient, 'get_person_details')
    @patch.object(TMDBClient, 'get_person_credits')
    def test_search_fallback_when_id_none(self, mock_credits, mock_details, mock_search):
        mock_search.return_value = [{'id': 525, 'name': 'Christopher Nolan'}]
        mock_details.return_value = {'name': 'Christopher Nolan', 'known_for_department': 'Directing'}
        mock_credits.return_value = [{'id': 1, 'title': 'Inception', 'media_type': 'movie'}]

        page = PersonPage({'id': None, 'name': 'Christopher Nolan'})
        page._fetch_data_worker(0)
        mock_search.assert_called_once_with('Christopher Nolan')
        mock_details.assert_called_once_with(525)
        mock_credits.assert_called_once_with(525)


if __name__ == '__main__':
    unittest.main()
