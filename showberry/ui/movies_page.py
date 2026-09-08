"""Dedicated Movies page with integrated search, responsive grid, and infinite scrolling."""

import logging
import threading
from typing import Dict, Any, List

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, GObject, Gdk

from showberry.services.tmdb import TMDBClient
from showberry.services.settings import SettingsService
from showberry.ui.movie_card import MovieCard

logger = logging.getLogger(__name__)


class MoviesPage(Gtk.Box):
    """Browse and search movies in a responsive grid with infinite scrolling."""

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
        self._search_entry.set_placeholder_text("Search movies by title...")
        self._search_entry.connect('search-changed', self._on_search_changed)
        self._search_entry.connect('activate', self._on_search_activate)

        search_key_ctrl = Gtk.EventControllerKey.new()
        search_key_ctrl.connect('key-pressed', self._on_search_key_pressed)
        self._search_entry.add_controller(search_key_ctrl)

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
        self._flowbox.set_halign(Gtk.Align.CENTER)
        self._flowbox.set_margin_start(16)
        self._flowbox.set_margin_end(16)
        self._flowbox.set_margin_top(14)
        self._flowbox.set_margin_bottom(24)


        # ── Infinite-scroll footer spinner ─────────────────────────────────
        self._footer_spinner = Gtk.Spinner()
        self._footer_spinner.set_size_request(32, 32)
        self._footer_spinner.set_halign(Gtk.Align.CENTER)
        self._footer_spinner.set_margin_bottom(24)
        self._footer_spinner.set_visible(False)

        scroll_content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroll_content_box.append(self._flowbox)
        scroll_content_box.append(self._footer_spinner)

        grid_clamp.set_child(scroll_content_box)
        self._scroll.set_child(grid_clamp)
        self._content_overlay.set_child(self._scroll)

        # ── Overlay spinner (initial load) ─────────────────────────────────
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(48, 48)
        self._spinner.set_halign(Gtk.Align.CENTER)
        self._spinner.set_valign(Gtk.Align.CENTER)
        self._spinner.set_visible(False)
        self._content_overlay.add_overlay(self._spinner)

        # ── No Results ─────────────────────────────────────────────────────
        self._no_results = Adw.StatusPage()
        self._no_results.set_icon_name('system-search-symbolic')
        self._no_results.set_title("No Movies Found")
        self._no_results.set_description("Try searching with different keywords.")
        self._no_results.set_vexpand(True)
        self._no_results.set_visible(False)
        self._content_overlay.add_overlay(self._no_results)

        self.append(self._content_overlay)

        # ── Connect infinite scroll ─────────────────────────────────────────
        vadj = self._scroll.get_vadjustment()
        vadj.connect('value-changed', self._on_scroll_changed)

        # Load initial trending movies
        self._load_movies(reset=True)

    # ── Search ─────────────────────────────────────────────────────────────

    def _on_search_changed(self, entry):
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
        self._search_timeout = GLib.timeout_add(300, self._do_search)

    def _focus_first_card(self):
        first_child = self._flowbox.get_child_at_index(0)
        if first_child:
            card = first_child.get_child()
            if card and hasattr(card, 'grab_focus'):
                card.grab_focus()
            else:
                first_child.grab_focus()

    def _get_columns_count(self) -> int:
        fb = self._flowbox
        c0 = fb.get_child_at_index(0)
        c1 = fb.get_child_at_index(1)
        if c0 and c1:
            ok0, r0 = c0.compute_bounds(fb)
            ok1, r1 = c1.compute_bounds(fb)
            if ok0 and ok1 and r0.get_width() > 50 and r1.get_x() > r0.get_x():
                y0 = r0.get_y()
                prev_x = r0.get_x()
                cols = 1
                while True:
                    c = fb.get_child_at_index(cols)
                    if not c:
                        break
                    ok, r = c.compute_bounds(fb)
                    if not ok or r.get_x() <= prev_x or r.get_y() > y0 + 10:
                        break
                    prev_x = r.get_x()
                    cols += 1
                return max(1, cols)
        width = self._flowbox.get_width()
        if width <= 1:
            scroll_w = self._scroll.get_width()
            if scroll_w <= 1:
                scroll_w = 1200
            clamped_w = min(1400, 800 + (scroll_w - 800) * 0.5) if scroll_w > 800 else scroll_w
            width = max(100, clamped_w - 32)
        return max(1, int((width + 14) // 224))

    def _on_card_navigate(self, card, direction: str):
        parent = card.get_parent()
        if not parent or not hasattr(parent, 'get_index'):
            return
        idx = parent.get_index()
        cols = self._get_columns_count()

        target_idx = None
        if direction == 'up':
            if idx < cols:
                self._search_entry.grab_focus()
                return
            target_idx = max(0, idx - cols)
        elif direction == 'down':
            target_idx = idx + cols
            if not self._flowbox.get_child_at_index(target_idx):
                # If column below doesn't exist, land on the last available item in the grid
                last_idx = idx
                while self._flowbox.get_child_at_index(last_idx + 1):
                    last_idx += 1
                if last_idx > idx:
                    target_idx = last_idx
                else:
                    return
        elif direction == 'left':
            if idx > 0:
                target_idx = idx - 1
        elif direction == 'right':
            target_idx = idx + 1

        if target_idx is not None:
            target_child = self._flowbox.get_child_at_index(target_idx)
            if target_child:
                target_card = target_child.get_child()
                if target_card and hasattr(target_card, 'grab_focus'):
                    target_card.grab_focus()
                else:
                    target_child.grab_focus()

    def _on_search_key_pressed(self, controller, keyval, keycode, state):
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            return False
        if keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            self._focus_first_card()
            return True
        elif keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            root = self.get_root()
            if root and hasattr(root, 'focus_tabs'):
                root.focus_tabs()
                return True
        elif keyval == Gdk.KEY_Escape:
            self._search_entry.set_text("")
            self._focus_first_card()
            return True
        return False

    def _on_search_activate(self, entry):
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
        self._do_search()
        GLib.idle_add(self._focus_first_card)

    def _do_search(self):
        self._search_timeout = None
        query = self._search_entry.get_text().strip()
        self._current_query = query
        self._load_movies(reset=True)
        return False

    # ── Loading ────────────────────────────────────────────────────────────

    def _load_movies(self, reset: bool = False):
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
            target=self._fetch_movies_worker,
            args=(query, page, reset),
            daemon=True
        ).start()

    def _fetch_movies_worker(self, query: str, page: int, reset: bool):
        settings = SettingsService()
        self._tmdb.set_api_key(settings.tmdb_api_key)

        if not query:
            trending = self._tmdb.get_trending(page=page) or []
            popular = self._tmdb.get_popular(page=page) or []
            seen = set()
            movies = []
            for m in trending + popular:
                mid = m.get('id')
                if mid and mid not in seen:
                    seen.add(mid)
                    movies.append(m)
        else:
            movies = self._tmdb.search_movies(query, page=page) or []

        GLib.idle_add(self._render_movies, movies, query, page, reset)

    def _render_movies(self, movies: List[Dict[str, Any]], query: str, page: int, reset: bool):
        # Guard against stale results from an old query
        if query != self._current_query:
            self._is_loading = False
            return False

        self._spinner.stop()
        self._spinner.set_visible(False)
        self._footer_spinner.set_visible(False)
        self._footer_spinner.stop()
        self._is_loading = False

        # Deduplicate across pages
        new_movies = []
        for m in movies:
            mid = m.get('id')
            if mid and mid not in self._seen_ids:
                self._seen_ids.add(mid)
                new_movies.append(m)

        if page == 1 and reset:
            # Clear existing cards
            while True:
                child = self._flowbox.get_first_child()
                if child is None:
                    break
                self._flowbox.remove(child)

        if not new_movies and page == 1:
            self._scroll.set_visible(False)
            self._no_results.set_visible(True)
            self._has_more = False
            return False

        if not new_movies:
            # No more results from further pages
            self._has_more = False
            return False

        self._no_results.set_visible(False)
        self._scroll.set_visible(True)
        self._has_more = len(movies) > 0

        for m in new_movies:
            card = MovieCard(m)
            card.connect('clicked-movie', self._on_card_clicked)
            card.connect('play-movie', self._on_card_play)
            card.connect('navigate-grid', self._on_card_navigate)
            card.connect('toggle-watchlist', self._on_card_watchlist)
            self._flowbox.append(card)
            child = card.get_parent()
            if child:
                child.set_focusable(False)
                child.set_focus_on_click(False)

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
        # Trigger load when within 600px of bottom
        if upper - (value + page_size) < 600:
            if not self._is_loading and self._has_more:
                self._footer_spinner.set_visible(True)
                self._footer_spinner.start()
                self._load_movies(reset=False)

    # ── Signal forwarding ──────────────────────────────────────────────────

    def _on_card_clicked(self, card, movie_data):
        self.emit('movie-selected', movie_data)

    def _on_card_play(self, card, stream_data):
        self.emit('play-movie', stream_data)

    def _on_card_watchlist(self, card, data):
        movie, added = data
        title = movie.get('title') or movie.get('name') or 'Item'
        msg = f"Added '{title}' to Watchlist" if added else f"Removed '{title}' from Watchlist"
        win = self.get_root()
        if win and hasattr(win, 'show_toast'):
            win.show_toast(msg, timeout=2)

    def refresh(self):
        self._load_movies(reset=True)
