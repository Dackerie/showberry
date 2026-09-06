"""Dedicated Series page with integrated search, responsive TV series grid, and infinite scrolling."""

import logging
import threading
from typing import Dict, Any, List

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, GObject

from kinema.services.tmdb import TMDBClient
from kinema.services.settings import SettingsService
from kinema.ui.movie_card import MovieCard

logger = logging.getLogger(__name__)


class SeriesPage(Gtk.Box):
    """Browse and search TV series in a responsive grid with infinite scrolling."""

    __gsignals__ = {
        'movie-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'play-movie':     (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._tmdb = TMDBClient()
        self._search_timeout = None
        self._current_query = ""

        # Pagination state
        self._current_page = 1
        self._is_loading = False
        self._has_more = True
        self._seen_ids: set = set()

        # ── Search Bar ─────────────────────────────────────────────────────
        search_clamp = Adw.Clamp()
        search_clamp.set_maximum_size(680)
        search_clamp.set_tightening_threshold(400)
        search_clamp.set_margin_top(12)
        search_clamp.set_margin_bottom(10)
        search_clamp.set_margin_start(16)
        search_clamp.set_margin_end(16)

        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Search TV series by title...")
        self._search_entry.connect('search-changed', self._on_search_changed)
        self._search_entry.connect('activate', self._on_search_activate)
        search_clamp.set_child(self._search_entry)
        self.append(search_clamp)

        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Main Container ─────────────────────────────────────────────────
        self._content_overlay = Gtk.Overlay()
        self._content_overlay.set_vexpand(True)

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_vexpand(True)

        grid_clamp = Adw.Clamp()
        grid_clamp.set_maximum_size(1400)
        grid_clamp.set_tightening_threshold(800)

        self._flowbox = Gtk.FlowBox()
        self._flowbox.set_homogeneous(True)
        self._flowbox.set_column_spacing(14)
        self._flowbox.set_row_spacing(14)
        self._flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flowbox.set_margin_start(16)
        self._flowbox.set_margin_end(16)
        self._flowbox.set_margin_top(14)
        self._flowbox.set_margin_bottom(24)

        grid_clamp.set_child(self._flowbox)
        self._scroll.set_child(grid_clamp)
        self._content_overlay.set_child(self._scroll)

        # ── Overlay Spinner (initial load) ──────────────────────────────────
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(48, 48)
        self._spinner.set_halign(Gtk.Align.CENTER)
        self._spinner.set_valign(Gtk.Align.CENTER)
        self._spinner.set_visible(False)
        self._content_overlay.add_overlay(self._spinner)

        # ── No Results ─────────────────────────────────────────────────────
        self._no_results = Adw.StatusPage()
        self._no_results.set_icon_name('system-search-symbolic')
        self._no_results.set_title("No TV Series Found")
        self._no_results.set_description("Try searching with different keywords.")
        self._no_results.set_vexpand(True)
        self._no_results.set_visible(False)
        self._content_overlay.add_overlay(self._no_results)

        self.append(self._content_overlay)

        # ── Connect infinite scroll ─────────────────────────────────────────
        vadj = self._scroll.get_vadjustment()
        vadj.connect('value-changed', self._on_scroll_changed)

        self._load_series(reset=True)

    # ── Search ─────────────────────────────────────────────────────────────

    def _on_search_changed(self, entry):
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
        self._search_timeout = GLib.timeout_add(300, self._do_search)

    def _on_search_activate(self, entry):
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
        self._do_search()

    def _do_search(self):
        self._search_timeout = None
        query = self._search_entry.get_text().strip()
        self._current_query = query
        self._load_series(reset=True)
        return False

    # ── Loading ────────────────────────────────────────────────────────────

    def _load_series(self, reset: bool = False):
        if self._is_loading:
            return
        if not self._has_more and not reset:
            return

        if reset:
            self._current_page = 1
            self._has_more = True
            self._seen_ids.clear()
            self._show_loading()

        self._is_loading = True
        query = self._current_query
        page = self._current_page
        threading.Thread(
            target=self._fetch_series_worker,
            args=(query, page, reset),
            daemon=True
        ).start()

    def _fetch_series_worker(self, query: str, page: int, reset: bool):
        settings = SettingsService()
        self._tmdb.set_api_key(settings.tmdb_api_key)

        if not query:
            trending = self._tmdb.get_trending_tv(page=page) or []
            popular = self._tmdb.get_popular_tv(page=page) or []
            seen = set()
            series = []
            for s in trending + popular:
                sid = s.get('id')
                if sid and sid not in seen:
                    seen.add(sid)
                    s['media_type'] = 'tv'
                    series.append(s)
        else:
            series = self._tmdb.search_tv(query, page=page) or []
            for s in series:
                s['media_type'] = 'tv'

        GLib.idle_add(self._render_series, series, query, page, reset)

    def _render_series(self, series: List[Dict[str, Any]], query: str, page: int, reset: bool):
        if query != self._current_query:
            self._is_loading = False
            return False

        self._spinner.stop()
        self._spinner.set_visible(False)
        self._is_loading = False

        # Deduplicate
        new_series = []
        for s in series:
            sid = s.get('id')
            if sid and sid not in self._seen_ids:
                self._seen_ids.add(sid)
                new_series.append(s)

        if page == 1 and reset:
            while True:
                child = self._flowbox.get_first_child()
                if child is None:
                    break
                self._flowbox.remove(child)

        if not new_series and page == 1:
            self._scroll.set_visible(False)
            self._no_results.set_visible(True)
            self._has_more = False
            return False

        if not new_series:
            self._has_more = False
            return False

        self._no_results.set_visible(False)
        self._scroll.set_visible(True)
        self._has_more = len(series) > 0

        for s in new_series:
            card = MovieCard(s)
            card.connect('clicked-movie', self._on_card_clicked)
            card.connect('play-movie', self._on_card_play)
            self._flowbox.append(card)

        self._current_page = page + 1
        return False

    def _show_loading(self):
        self._no_results.set_visible(False)
        self._spinner.set_visible(True)
        self._spinner.start()

    # ── Infinite Scroll ────────────────────────────────────────────────────

    def _on_scroll_changed(self, vadj):
        value = vadj.get_value()
        upper = vadj.get_upper()
        page_size = vadj.get_page_size()
        if upper - (value + page_size) < 600:
            if not self._is_loading and self._has_more:
                self._load_series(reset=False)

    # ── Signal forwarding ──────────────────────────────────────────────────

    def _on_card_clicked(self, card, movie_data):
        self.emit('movie-selected', movie_data)

    def _on_card_play(self, card, stream_data):
        self.emit('play-movie', stream_data)

    def refresh(self):
        self._load_series(reset=True)
