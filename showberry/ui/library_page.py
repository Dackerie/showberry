"""Library page displaying Continue Watching and Watchlist (Home view)."""

import logging
from typing import Dict, Any

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, GLib

from showberry.services.database import DatabaseService
from showberry.ui.movie_card import MovieCard

logger = logging.getLogger(__name__)


class LibraryPage(Gtk.Box):
    """Personal library view displaying Continue Watching and Watchlist."""

    __gsignals__ = {
        'movie-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'play-movie':     (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'focus-tabs':     (GObject.SignalFlags.RUN_FIRST, None, ()),
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

        self._refresh_timer = None
        self.refresh()

    def schedule_refresh(self, delay_ms: int = 200):
        """Debounce refresh requests so rapid tab switching doesn't thrash DB and widgets."""
        if self._refresh_timer:
            GLib.source_remove(self._refresh_timer)
        self._refresh_timer = GLib.timeout_add(delay_ms, self._on_scheduled_refresh)

    def _on_scheduled_refresh(self):
        self._refresh_timer = None
        self.refresh()
        return False

    def refresh(self):
        """Reload watch history and watchlist from SQLite."""
        if self._refresh_timer:
            GLib.source_remove(self._refresh_timer)
            self._refresh_timer = None
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
                card.connect('navigate-grid', self._on_cw_navigate)
                self._cw_box.append(card)

        # ── Populate Watchlist ─────────────────────────────────────────────
        if has_wl:
            for item in watchlist:
                card = MovieCard(item)
                card.connect('clicked-movie', self._on_card_clicked)
                card.connect('play-movie',    self._on_card_play)
                card.connect('navigate-grid', self._on_wl_navigate)
                card.connect('toggle-watchlist', self._on_wl_card_toggled)
                self._wl_flowbox.append(card)
                child = card.get_parent()
                if child:
                    child_key = Gtk.EventControllerKey.new()
                    child_key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
                    child_key.connect('key-pressed', lambda ctrl, val, code, st, c=card: c._on_key_pressed(ctrl, val, code, st))
                    child.add_controller(child_key)

    def focus_first(self) -> bool:
        """Focus the first item in Continue Watching, or first item in Watchlist."""
        if self._cw_section.get_visible():
            first_cw = self._cw_box.get_first_child()
            if first_cw and hasattr(first_cw, 'grab_focus'):
                first_cw.grab_focus()
                return True
        first_wl = self._wl_flowbox.get_child_at_index(0)
        if first_wl:
            wl_card = first_wl.get_child()
            if wl_card and hasattr(wl_card, 'grab_focus'):
                wl_card.grab_focus()
            else:
                first_wl.grab_focus()
            return True
        return False

    def _on_cw_navigate(self, card, direction: str):
        if direction == 'right':
            sib = card.get_next_sibling()
            if sib and hasattr(sib, 'grab_focus'):
                sib.grab_focus()
        elif direction == 'left':
            sib = card.get_prev_sibling()
            if sib and hasattr(sib, 'grab_focus'):
                sib.grab_focus()
        elif direction == 'up':
            root = self.get_root()
            if root and hasattr(root, 'focus_tabs'):
                root.focus_tabs()
            self.emit('focus-tabs')
        elif direction == 'down':
            # Move down into the matching column in Watchlist if available
            cw_idx = 0
            curr = self._cw_box.get_first_child()
            while curr and curr != card:
                cw_idx += 1
                curr = curr.get_next_sibling()

            target_child = self._wl_flowbox.get_child_at_index(cw_idx)
            if not target_child:
                target_child = self._wl_flowbox.get_child_at_index(0)
            if target_child:
                wl_card = target_child.get_child()
                if wl_card and hasattr(wl_card, 'grab_focus'):
                    wl_card.grab_focus()
                else:
                    target_child.grab_focus()

    def _on_wl_navigate(self, card, direction: str):
        parent = card.get_parent()
        if not parent or not hasattr(parent, 'get_index'):
            return
        idx = parent.get_index()

        width = self._scroll.get_width()
        if width <= 1:
            width = 1000
        available_width = min(width - 32, 1400)
        cols = max(1, available_width // 210)

        if direction == 'up':
            if idx < cols:
                # First row of Watchlist -> navigate up to Continue Watching if visible
                if self._cw_section.get_visible():
                    cw_children = []
                    curr = self._cw_box.get_first_child()
                    while curr:
                        cw_children.append(curr)
                        curr = curr.get_next_sibling()
                    if cw_children:
                        target_cw = cw_children[min(idx, len(cw_children) - 1)]
                        if hasattr(target_cw, 'grab_focus'):
                            target_cw.grab_focus()
                            return

                # Continue Watching is not visible (or has no children) -> navigate up to tabs
                root = self.get_root()
                if root and hasattr(root, 'focus_tabs'):
                    root.focus_tabs()
                self.emit('focus-tabs')
                return
            else:
                target_idx = max(0, idx - cols)
                target_child = self._wl_flowbox.get_child_at_index(target_idx)
                if target_child:
                    c = target_child.get_child()
                    if c and hasattr(c, 'grab_focus'):
                        c.grab_focus()
                    else:
                        target_child.grab_focus()
        elif direction == 'down':
            target_idx = idx + cols
            target_child = self._wl_flowbox.get_child_at_index(target_idx)
            if not target_child:
                last_idx = idx
                while self._wl_flowbox.get_child_at_index(last_idx + 1):
                    last_idx += 1
                if last_idx > idx:
                    target_idx = last_idx
                else:
                    return
            target_child = self._wl_flowbox.get_child_at_index(target_idx)
            if target_child:
                c = target_child.get_child()
                if c and hasattr(c, 'grab_focus'):
                    c.grab_focus()
                else:
                    target_child.grab_focus()
        elif direction == 'left':
            if idx > 0:
                target_child = self._wl_flowbox.get_child_at_index(idx - 1)
                if target_child:
                    c = target_child.get_child()
                    if c and hasattr(c, 'grab_focus'):
                        c.grab_focus()
                    else:
                        target_child.grab_focus()
        elif direction == 'right':
            target_child = self._wl_flowbox.get_child_at_index(idx + 1)
            if target_child:
                c = target_child.get_child()
                if c and hasattr(c, 'grab_focus'):
                    c.grab_focus()
                else:
                    target_child.grab_focus()

    def _on_wl_card_toggled(self, card, data):
        movie, added = data
        if not added:
            # Removed from watchlist; refresh watchlist row
            self.refresh()

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

        # Shift focus to adjacent card before removal
        if card:
            next_focus = card.get_next_sibling() or card.get_prev_sibling()
            if next_focus and hasattr(next_focus, 'grab_focus'):
                next_focus.grab_focus()
            elif not next_focus:
                first_wl = self._wl_flowbox.get_child_at_index(0)
                if first_wl:
                    wl_card = first_wl.get_child()
                    if wl_card and hasattr(wl_card, 'grab_focus'):
                        wl_card.grab_focus()
                    else:
                        first_wl.grab_focus()
                else:
                    root = self.get_root()
                    if root and hasattr(root, 'focus_tabs'):
                        root.focus_tabs()
                    self.emit('focus-tabs')

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

        root = self.get_root()
        if root and hasattr(root, 'show_toast'):
            root.show_toast("Removed from Continue Watching")
