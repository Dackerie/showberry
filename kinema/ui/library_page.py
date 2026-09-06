"""Library page displaying Continue Watching and Watchlist (Home view)."""

import logging
from typing import Dict, Any

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject

from kinema.services.database import DatabaseService
from kinema.ui.movie_card import MovieCard

logger = logging.getLogger(__name__)


class LibraryPage(Gtk.Box):
    """Personal library view displaying Continue Watching and Watchlist."""

    __gsignals__ = {
        'movie-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'play-movie':     (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._db = DatabaseService()

        # Scrolled container
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_vexpand(True)

        self._clamp = Adw.Clamp()
        self._clamp.set_maximum_size(1400)
        self._clamp.set_tightening_threshold(800)

        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self._content_box.set_margin_start(16)
        self._content_box.set_margin_end(16)
        self._content_box.set_margin_top(12)
        self._content_box.set_margin_bottom(24)

        # ── 1. Continue Watching Section ───────────────────────────────────
        self._cw_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        cw_header = Gtk.Label(label="Continue Watching")
        cw_header.add_css_class('title-section')
        cw_header.set_xalign(0)
        self._cw_section.append(cw_header)

        cw_scroll = Gtk.ScrolledWindow()
        cw_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        cw_scroll.set_min_content_height(350)
        self._cw_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self._cw_box.set_halign(Gtk.Align.START)
        self._cw_box.set_margin_start(4)
        self._cw_box.set_margin_end(4)
        self._cw_box.set_margin_top(4)
        self._cw_box.set_margin_bottom(8)
        cw_scroll.set_child(self._cw_box)
        self._cw_section.append(cw_scroll)
        self._content_box.append(self._cw_section)

        # ── 2. Watchlist Section ───────────────────────────────────────────
        self._wl_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        wl_header = Gtk.Label(label="Watchlist")
        wl_header.add_css_class('title-section')
        wl_header.set_xalign(0)
        self._wl_section.append(wl_header)

        self._wl_flowbox = Gtk.FlowBox()
        self._wl_flowbox.set_homogeneous(True)
        self._wl_flowbox.set_column_spacing(14)
        self._wl_flowbox.set_row_spacing(14)
        self._wl_flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._wl_flowbox.set_halign(Gtk.Align.START)
        self._wl_flowbox.set_margin_start(4)
        self._wl_flowbox.set_margin_end(4)
        self._wl_flowbox.set_margin_top(4)
        self._wl_flowbox.set_margin_bottom(12)

        self._wl_section.append(self._wl_flowbox)
        self._content_box.append(self._wl_section)

        self._clamp.set_child(self._content_box)
        self._scroll.set_child(self._clamp)
        self.append(self._scroll)

        # ── 3. Empty Status Page ───────────────────────────────────────────
        self._empty_status = Adw.StatusPage()
        self._empty_status.set_icon_name('emblem-favorite-symbolic')
        self._empty_status.set_title('Your Library is Empty')
        self._empty_status.set_description('Movies and TV series you watch or bookmark will appear here.')
        self._empty_status.set_vexpand(True)
        self._empty_status.set_visible(False)
        self.append(self._empty_status)

        self.refresh()

    def refresh(self):
        """Reload watch history and watchlist from SQLite."""
        history = self._db.get_watch_history(limit=20)
        watchlist = self._db.get_watchlist(limit=50)

        # Clear Continue Watching items
        while True:
            child = self._cw_box.get_first_child()
            if child is None:
                break
            self._cw_box.remove(child)

        # Clear Watchlist items
        while True:
            child = self._wl_flowbox.get_first_child()
            if child is None:
                break
            self._wl_flowbox.remove(child)

        has_cw = bool(history)
        has_wl = bool(watchlist)

        self._cw_section.set_visible(has_cw)
        self._wl_section.set_visible(has_wl)

        if not has_cw and not has_wl:
            self._scroll.set_visible(False)
            self._empty_status.set_visible(True)
            return

        self._scroll.set_visible(True)
        self._empty_status.set_visible(False)

        # ── Populate Continue Watching (with remove button) ────────────────
        if has_cw:
            for item in history:
                card = MovieCard(item, show_remove_button=True)
                card.connect('clicked-movie', self._on_card_clicked)
                card.connect('play-movie',    self._on_card_play)
                card.connect('remove-item',   self._on_remove_item)
                self._cw_box.append(card)

        # ── Populate Watchlist ─────────────────────────────────────────────
        if has_wl:
            for item in watchlist:
                card = MovieCard(item)
                card.connect('clicked-movie', self._on_card_clicked)
                card.connect('play-movie',    self._on_card_play)
                self._wl_flowbox.append(card)

    def _on_card_clicked(self, card, movie_data):
        self.emit('movie-selected', movie_data)

    def _on_card_play(self, card, stream_data):
        self.emit('play-movie', stream_data)

    def _on_remove_item(self, card, tmdb_id: int):
        """Remove a single item from watch history and refresh the row."""
        try:
            self._db.delete_history_item(tmdb_id)
        except Exception as e:
            logger.warning(f"Failed to remove history item {tmdb_id}: {e}")
        # Find and remove the card from the CW box immediately (instant feedback)
        child = self._cw_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            if child is card:
                self._cw_box.remove(child)
                break
            child = next_child
        # If the CW row is now empty, hide it
        if self._cw_box.get_first_child() is None:
            self._cw_section.set_visible(False)
            has_wl = self._wl_flowbox.get_first_child() is not None
            if not has_wl:
                self._scroll.set_visible(False)
                self._empty_status.set_visible(True)
        # Show a toast notification via the root window
        root = self.get_root()
        if root and hasattr(root, 'show_toast'):
            root.show_toast("Removed from Continue Watching")
