"""Browse page - discover trending and popular movies."""

import threading
from typing import List, Dict, Any

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, GObject, Gdk, Pango

from kinema.services.tmdb import TMDBClient, genre_id_to_name
from kinema.services.image_cache import ImageCache
from kinema.services.database import DatabaseService


from kinema.ui.movie_card import MovieCard


class MovieRow(Gtk.Box):
    """A horizontal row of movie cards with a title."""

    __gsignals__ = {
        'movie-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, title, movies):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(16)
        self.set_margin_end(16)

        # Section title
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        label = Gtk.Label(label=title)
        label.add_css_class('title-section')
        label.set_xalign(0)
        header.append(label)
        self.append(header)

        # Scrolled movie list with smooth horizontal layout
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroll.set_min_content_height(350)

        card_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        card_box.set_margin_start(4)
        card_box.set_margin_end(4)
        card_box.set_margin_top(4)
        card_box.set_margin_bottom(8)

        for movie in movies:
            card = MovieCard(movie)
            card.connect('clicked-movie', self._on_movie_clicked)
            card_box.append(card)

        scroll.set_child(card_box)
        self.append(scroll)

    def _on_movie_clicked(self, card, movie_data):
        self.emit('movie-selected', movie_data)


class BrowsePage(Gtk.Box):
    """Browse page showing continue watching, watchlist, trending and popular movies."""

    __gsignals__ = {
        'movie-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._tmdb = TMDBClient()
        self._db = DatabaseService()
        self._setup_ui()
        self._load_movies()

    def _setup_ui(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Loading indicator
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(48, 48)
        self._spinner.set_halign(Gtk.Align.CENTER)
        self._spinner.set_valign(Gtk.Align.CENTER)
        self._spinner.set_vexpand(True)
        self._spinner.start()

        # Error label
        self._error_label = Gtk.Label()
        self._error_label.set_visible(False)
        self._error_label.set_halign(Gtk.Align.CENTER)
        self._error_label.set_valign(Gtk.Align.CENTER)
        self._error_label.add_css_class('dim-label')
        self._error_label.add_css_class('title-4')

        # Clamp for content
        self._clamp = Adw.Clamp()
        self._clamp.set_maximum_size(1400)
        self._clamp.set_tightening_threshold(800)

        self._rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._clamp.set_child(self._rows_box)

        self._content_box.append(self._clamp)
        self._content_box.append(self._spinner)
        self._content_box.append(self._error_label)

        scroll.set_child(self._content_box)
        self.append(scroll)

    def _load_movies(self):
        """Load movies from TMDB and local DB in background thread."""
        self._spinner.set_visible(True)
        self._spinner.start()
        self._error_label.set_visible(False)

        # Clear existing rows
        while True:
            child = self._rows_box.get_first_child()
            if child is None:
                break
            self._rows_box.remove(child)

        threading.Thread(target=self._fetch_movies_worker, daemon=True).start()

    def _fetch_movies_worker(self):
        """Background worker fetching metadata."""
        from kinema.services.settings import SettingsService
        settings = SettingsService()
        api_key = settings.tmdb_api_key

        # Local watch history & watchlist
        history = self._db.get_watch_history(limit=15)
        watchlist = self._db.get_watchlist(limit=15)

        self._tmdb.set_api_key(api_key)

        trending = self._tmdb.get_trending()
        trending_tv = self._tmdb.get_trending_tv()
        popular = self._tmdb.get_popular()
        top_rated = self._tmdb.get_top_rated()
        now_playing = self._tmdb.get_now_playing()

        GLib.idle_add(
            self._render_rows,
            history,
            watchlist,
            trending,
            trending_tv,
            popular,
            top_rated,
            now_playing
        )

    def _render_rows(self, history, watchlist, trending, trending_tv, popular, top_rated, now_playing):
        """Populate movie rows on main UI thread."""
        self._spinner.stop()
        self._spinner.set_visible(False)

        # 1. Continue Watching row
        if history:
            row = MovieRow('Continue Watching', history)
            row.connect('movie-selected', self._on_movie_selected)
            self._rows_box.append(row)

        # 2. Watchlist row
        if watchlist:
            row = MovieRow('Your Watchlist', watchlist)
            row.connect('movie-selected', self._on_movie_selected)
            self._rows_box.append(row)

        # 3. Trending Movies
        if trending:
            row = MovieRow('Trending Movies', trending)
            row.connect('movie-selected', self._on_movie_selected)
            self._rows_box.append(row)

        # 4. Trending Series
        if trending_tv:
            row = MovieRow('Popular TV Series', trending_tv)
            row.connect('movie-selected', self._on_movie_selected)
            self._rows_box.append(row)

        # 5. Popular Movies
        if popular:
            row = MovieRow('Popular Movies', popular)
            row.connect('movie-selected', self._on_movie_selected)
            self._rows_box.append(row)

        # 6. Top Rated
        if top_rated:
            row = MovieRow('Top Rated', top_rated)
            row.connect('movie-selected', self._on_movie_selected)
            self._rows_box.append(row)

        # 7. Now Playing
        if now_playing:
            row = MovieRow('Now Playing in Theaters', now_playing)
            row.connect('movie-selected', self._on_movie_selected)
            self._rows_box.append(row)

        if not trending and not popular and not history and not watchlist:
            self._show_error('Failed to load movies. Please check your API key and connection.')

    def _show_error(self, message):
        self._spinner.stop()
        self._spinner.set_visible(False)
        self._error_label.set_text(message)
        self._error_label.set_visible(True)

    def _on_movie_selected(self, row, movie_data):
        self.emit('movie-selected', movie_data)

    def refresh(self):
        """Refresh browse content."""
        self._load_movies()

