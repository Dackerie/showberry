"""Watchlist / Library page showing saved movies and TV shows."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject

from showberry.ui.browse_page import MovieCard
from showberry.services.database import DatabaseService


class WatchlistPage(Gtk.Box):
    """Library page showing user's saved watchlist."""

    __gsignals__ = {
        'movie-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._db = DatabaseService()
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self._clamp = Adw.Clamp()
        self._clamp.set_maximum_size(1400)
        self._clamp.set_tightening_threshold(800)

        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self._content_box.set_margin_top(16)
        self._content_box.set_margin_bottom(24)
        self._content_box.set_margin_start(16)
        self._content_box.set_margin_end(16)

        # Empty state status page
        self._empty_status = Adw.StatusPage()
        self._empty_status.set_icon_name('emblem-favorite-symbolic')
        self._empty_status.set_title("Your Watchlist is Empty")
        self._empty_status.set_description("Bookmark movies and TV series to save them for later.")
        self._empty_status.set_vexpand(True)
        self._empty_status.set_visible(False)
        self._content_box.append(self._empty_status)

        # FlowBox for responsive movie cards grid
        self._flowbox = Gtk.FlowBox()
        self._flowbox.set_valign(Gtk.Align.START)
        self._flowbox.set_max_children_per_line(8)
        self._flowbox.set_min_children_per_line(2)
        self._flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flowbox.set_column_spacing(16)
        self._flowbox.set_row_spacing(16)
        self._content_box.append(self._flowbox)

        self._clamp.set_child(self._content_box)
        scroll.set_child(self._clamp)
        self.append(scroll)

    def refresh(self):
        """Reload watchlist items from database."""
        # Clear existing flowbox children
        while True:
            child = self._flowbox.get_first_child()
            if child is None:
                break
            self._flowbox.remove(child)

        items = self._db.get_watchlist()
        if not items:
            self._empty_status.set_visible(True)
            self._flowbox.set_visible(False)
            return

        self._empty_status.set_visible(False)
        self._flowbox.set_visible(True)

        for item in items:
            # Reconstruct movie data dict for MovieCard
            poster = item.get('poster_url')
            movie_data = {
                'id': item.get('tmdb_id') or item.get('id'),
                'tmdb_id': item.get('tmdb_id') or item.get('id'),
                'title': item.get('title', ''),
                'media_type': item.get('media_type', 'movie'),
                'poster_url': poster,
                'poster_url_small': poster,
                'poster_path': poster,
                'backdrop_url': item.get('backdrop_url'),
                'backdrop_path': item.get('backdrop_url'),
                'vote_average': item.get('vote_average', 0.0),
                'release_date': item.get('release_date', ''),
                'overview': item.get('overview', ''),
            }
            card = MovieCard(movie_data)
            card.connect('clicked-movie', lambda c, m: self.emit('movie-selected', m))
            self._flowbox.append(card)
