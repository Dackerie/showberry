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

        # ── 1. Continue Watching Section (TV Shows & Movies) ───────────────
        self._cw_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        cw_header = Gtk.Label(label="Continue Watching")
        cw_header.add_css_class('title-section')
        cw_header.set_xalign(0)
        self._cw_section.append(cw_header)

        # 1a. Sub-section: TV Shows
        self._cw_tv_wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        cw_tv_hdr = Gtk.Label(label="TV Shows")
        cw_tv_hdr.add_css_class('title-subsection')
        cw_tv_hdr.set_xalign(0)
        self._cw_tv_wrapper.append(cw_tv_hdr)

        cw_tv_scroll = Gtk.ScrolledWindow()
        cw_tv_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        cw_tv_scroll.set_min_content_height(350)
        self._cw_tv_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self._cw_tv_box.set_halign(Gtk.Align.START)
        self._cw_tv_box.set_margin_start(4)
        self._cw_tv_box.set_margin_end(4)
        self._cw_tv_box.set_margin_top(4)
        self._cw_tv_box.set_margin_bottom(8)
        cw_tv_scroll.set_child(self._cw_tv_box)
        self._cw_tv_wrapper.append(cw_tv_scroll)
        self._cw_section.append(self._cw_tv_wrapper)

        # 1b. Sub-section: Movies
        self._cw_movie_wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        cw_movie_hdr = Gtk.Label(label="Movies")
        cw_movie_hdr.add_css_class('title-subsection')
        cw_movie_hdr.set_xalign(0)
        self._cw_movie_wrapper.append(cw_movie_hdr)

        cw_movie_scroll = Gtk.ScrolledWindow()
        cw_movie_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        cw_movie_scroll.set_min_content_height(350)
        self._cw_movie_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self._cw_movie_box.set_halign(Gtk.Align.START)
        self._cw_movie_box.set_margin_start(4)
        self._cw_movie_box.set_margin_end(4)
        self._cw_movie_box.set_margin_top(4)
        self._cw_movie_box.set_margin_bottom(8)
        cw_movie_scroll.set_child(self._cw_movie_box)
        self._cw_movie_wrapper.append(cw_movie_scroll)
        self._cw_section.append(self._cw_movie_wrapper)
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

        # ── 3. Completed Section ───────────────────────────────────────────
        self._completed_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        completed_header = Gtk.Label(label="Completed")
        completed_header.add_css_class('title-section')
        completed_header.set_xalign(0)
        self._completed_section.append(completed_header)

        self._completed_flowbox = Gtk.FlowBox()
        self._completed_flowbox.set_homogeneous(True)
        self._completed_flowbox.set_column_spacing(14)
        self._completed_flowbox.set_row_spacing(14)
        self._completed_flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._completed_flowbox.set_halign(Gtk.Align.START)
        self._completed_flowbox.set_margin_start(4)
        self._completed_flowbox.set_margin_end(4)
        self._completed_flowbox.set_margin_top(4)
        self._completed_flowbox.set_margin_bottom(12)

        self._completed_section.append(self._completed_flowbox)
        self._content_box.append(self._completed_section)

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

    def refresh(self, force: bool = False):
        """Reload watch history and watchlist from SQLite."""
        if self._refresh_timer:
            GLib.source_remove(self._refresh_timer)
            self._refresh_timer = None
        history = self._db.get_watch_history(limit=20)
        watchlist = self._db.get_watchlist(limit=50)
        completed = self._db.get_completed_items(limit=30)

        cw_fingerprint = [(h.get('tmdb_id'), h.get('progress_seconds')) for h in history]
        wl_fingerprint = [w.get('tmdb_id') for w in watchlist]
        comp_fingerprint = [c.get('tmdb_id') for c in completed]
        if not force and hasattr(self, '_last_cw_fp') and hasattr(self, '_last_wl_fp') and hasattr(self, '_last_comp_fp'):
            if self._last_cw_fp == cw_fingerprint and self._last_wl_fp == wl_fingerprint and self._last_comp_fp == comp_fingerprint:
                return  # Data has not changed; preserve existing widgets and active focus!
        self._last_cw_fp = cw_fingerprint
        self._last_wl_fp = wl_fingerprint
        self._last_comp_fp = comp_fingerprint

        # Clear Continue Watching items (TV & Movies)
        while True:
            child = self._cw_tv_box.get_first_child()
            if child is None:
                break
            self._cw_tv_box.remove(child)

        while True:
            child = self._cw_movie_box.get_first_child()
            if child is None:
                break
            self._cw_movie_box.remove(child)

        # Clear Watchlist items
        while True:
            child = self._wl_flowbox.get_first_child()
            if child is None:
                break
            self._wl_flowbox.remove(child)

        # Clear Completed items
        while True:
            child = self._completed_flowbox.get_first_child()
            if child is None:
                break
            self._completed_flowbox.remove(child)

        tv_history = [h for h in history if h.get('media_type') == 'tv']
        movie_history = [h for h in history if h.get('media_type') != 'tv']

        has_tv = bool(tv_history)
        has_movie = bool(movie_history)
        has_cw = has_tv or has_movie
        has_wl = bool(watchlist)
        has_comp = bool(completed)

        self._cw_section.set_visible(has_cw)
        self._cw_tv_wrapper.set_visible(has_tv)
        self._cw_movie_wrapper.set_visible(has_movie)
        self._wl_section.set_visible(has_wl)
        self._completed_section.set_visible(has_comp)

        if not has_cw and not has_wl and not has_comp:
            self._scroll.set_visible(False)
            self._empty_status.set_visible(True)
            return

        self._scroll.set_visible(True)
        self._empty_status.set_visible(False)

        # ── Populate Continue Watching TV Shows ────────────────────────────
        if has_tv:
            for item in tv_history:
                card = MovieCard(item, show_remove_button=True)
                card.connect('clicked-movie', self._on_card_clicked)
                card.connect('play-movie',    self._on_card_play)
                card.connect('remove-item',   self._on_remove_item)
                card.connect('navigate-grid', self._on_cw_tv_navigate)
                self._cw_tv_box.append(card)

        # ── Populate Continue Watching Movies ──────────────────────────────
        if has_movie:
            for item in movie_history:
                card = MovieCard(item, show_remove_button=True)
                card.connect('clicked-movie', self._on_card_clicked)
                card.connect('play-movie',    self._on_card_play)
                card.connect('remove-item',   self._on_remove_item)
                card.connect('navigate-grid', self._on_cw_movie_navigate)
                self._cw_movie_box.append(card)

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
                    child.set_focusable(False)
                    child.set_focus_on_click(False)

        # ── Populate Completed ─────────────────────────────────────────────
        if has_comp:
            for item in completed:
                card = MovieCard(item, show_remove_button=True)
                card.connect('clicked-movie', self._on_card_clicked)
                card.connect('play-movie',    self._on_card_play)
                card.connect('remove-item',   self._on_remove_completed_item)
                card.connect('navigate-grid', self._on_comp_navigate)
                self._completed_flowbox.append(card)
                child = card.get_parent()
                if child:
                    child.set_focusable(False)
                    child.set_focus_on_click(False)

    def focus_first(self) -> bool:
        """Focus the first item in TV Shows, Movies, Watchlist, or Completed."""
        if self._cw_section.get_visible():
            if self._cw_tv_wrapper.get_visible():
                first_tv = self._cw_tv_box.get_first_child()
                if first_tv and hasattr(first_tv, 'grab_focus'):
                    first_tv.grab_focus()
                    return True
            if self._cw_movie_wrapper.get_visible():
                first_movie = self._cw_movie_box.get_first_child()
                if first_movie and hasattr(first_movie, 'grab_focus'):
                    first_movie.grab_focus()
                    return True
        first_wl = self._wl_flowbox.get_child_at_index(0)
        if first_wl:
            wl_card = first_wl.get_child()
            if wl_card and hasattr(wl_card, 'grab_focus'):
                wl_card.grab_focus()
            else:
                first_wl.grab_focus()
            return True
        first_comp = self._completed_flowbox.get_child_at_index(0)
        if first_comp:
            comp_card = first_comp.get_child()
            if comp_card and hasattr(comp_card, 'grab_focus'):
                comp_card.grab_focus()
            else:
                first_comp.grab_focus()
            return True
        return False

    def _on_cw_tv_navigate(self, card, direction: str):
        if direction == 'right':
            sib = card.get_next_sibling()
            if sib and hasattr(sib, 'grab_focus'):
                sib.grab_focus()
        elif direction == 'left':
            sib = card.get_prev_sibling()
            if sib and hasattr(sib, 'grab_focus'):
                sib.grab_focus()
        elif direction == 'up':
            self._scroll.get_vadjustment().set_value(0.0)
            root = self.get_root()
            if root and hasattr(root, 'focus_tabs'):
                root.focus_tabs()
            self.emit('focus-tabs')
        elif direction == 'down':
            if self._cw_movie_wrapper.get_visible() and self._cw_movie_box.get_first_child():
                idx = 0
                curr = self._cw_tv_box.get_first_child()
                while curr and curr != card:
                    idx += 1
                    curr = curr.get_next_sibling()
                m_children = []
                c = self._cw_movie_box.get_first_child()
                while c:
                    m_children.append(c)
                    c = c.get_next_sibling()
                target = m_children[min(idx, len(m_children) - 1)]
                if target and hasattr(target, 'grab_focus'):
                    target.grab_focus()
                    return
            self._focus_wl_from_cw(card, self._cw_tv_box)

    def _on_cw_movie_navigate(self, card, direction: str):
        if direction == 'right':
            sib = card.get_next_sibling()
            if sib and hasattr(sib, 'grab_focus'):
                sib.grab_focus()
        elif direction == 'left':
            sib = card.get_prev_sibling()
            if sib and hasattr(sib, 'grab_focus'):
                sib.grab_focus()
        elif direction == 'up':
            if self._cw_tv_wrapper.get_visible() and self._cw_tv_box.get_first_child():
                idx = 0
                curr = self._cw_movie_box.get_first_child()
                while curr and curr != card:
                    idx += 1
                    curr = curr.get_next_sibling()
                tv_children = []
                c = self._cw_tv_box.get_first_child()
                while c:
                    tv_children.append(c)
                    c = c.get_next_sibling()
                target = tv_children[min(idx, len(tv_children) - 1)]
                if target and hasattr(target, 'grab_focus'):
                    target.grab_focus()
                    return
            self._scroll.get_vadjustment().set_value(0.0)
            root = self.get_root()
            if root and hasattr(root, 'focus_tabs'):
                root.focus_tabs()
            self.emit('focus-tabs')
        elif direction == 'down':
            self._focus_wl_from_cw(card, self._cw_movie_box)

    def _focus_wl_from_cw(self, card, parent_box):
        cw_idx = 0
        curr = parent_box.get_first_child()
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
        elif self._completed_section.get_visible():
            target_comp = self._completed_flowbox.get_child_at_index(cw_idx) or self._completed_flowbox.get_child_at_index(0)
            if target_comp:
                comp_card = target_comp.get_child()
                if comp_card and hasattr(comp_card, 'grab_focus'):
                    comp_card.grab_focus()
                else:
                    target_comp.grab_focus()

    def _on_cw_navigate(self, card, direction: str):
        return self._on_cw_tv_navigate(card, direction)

    @property
    def _cw_box(self):
        """Backwards compatibility alias for the active Continue Watching box."""
        if hasattr(self, '_cw_tv_box') and self._cw_tv_box.get_first_child():
            return self._cw_tv_box
        return getattr(self, '_cw_movie_box', None) or getattr(self, '_cw_tv_box', None)

    def _get_columns_count(self) -> int:
        fb = self._wl_flowbox
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
        width = self._wl_flowbox.get_width()
        if width <= 1:
            scroll_w = self._scroll.get_width()
            if scroll_w <= 1:
                scroll_w = 1200
            clamped_w = min(1400, 800 + (scroll_w - 800) * 0.5) if scroll_w > 800 else scroll_w
            width = max(100, clamped_w - 32)
        return max(1, int((width + 14) // 224))

    def _on_wl_navigate(self, card, direction: str):
        parent = card.get_parent()
        if not parent or not hasattr(parent, 'get_index'):
            return
        idx = parent.get_index()
        cols = self._get_columns_count()

        if direction == 'up':
            if idx < cols:
                # Reset scroll adjustment so Continue Watching and top header are in view
                self._scroll.get_vadjustment().set_value(0.0)
                # First row of Watchlist -> navigate up to Continue Watching if visible
                if self._cw_section.get_visible():
                    target_box = None
                    if self._cw_movie_wrapper.get_visible() and self._cw_movie_box.get_first_child():
                        target_box = self._cw_movie_box
                    elif self._cw_tv_wrapper.get_visible() and self._cw_tv_box.get_first_child():
                        target_box = self._cw_tv_box
                    if target_box:
                        cw_children = []
                        curr = target_box.get_first_child()
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
                # Transition to completed section if visible
                if self._completed_section.get_visible() and self._completed_flowbox.get_child_at_index(0):
                    col_offset = idx % cols
                    comp_target = self._completed_flowbox.get_child_at_index(col_offset)
                    if not comp_target:
                        last_c = 0
                        while self._completed_flowbox.get_child_at_index(last_c + 1):
                            last_c += 1
                        comp_target = self._completed_flowbox.get_child_at_index(last_c)
                    if comp_target:
                        c = comp_target.get_child()
                        if c and hasattr(c, 'grab_focus'):
                            c.grab_focus()
                        else:
                            comp_target.grab_focus()
                        return

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

    def _on_comp_navigate(self, card, direction: str):
        parent = card.get_parent()
        if not parent or not hasattr(parent, 'get_index'):
            return
        idx = parent.get_index()
        cols = self._get_columns_count()

        if direction == 'up':
            if idx < cols:
                # First row of Completed -> navigate up to Watchlist if visible
                if self._wl_section.get_visible() and self._wl_flowbox.get_child_at_index(0):
                    col_offset = idx % cols
                    wl_count = 0
                    while self._wl_flowbox.get_child_at_index(wl_count):
                        wl_count += 1
                    if wl_count > 0:
                        last_row_start = (wl_count - 1) - ((wl_count - 1) % cols)
                        target_wl_idx = min(last_row_start + col_offset, wl_count - 1)
                        target_wl = self._wl_flowbox.get_child_at_index(target_wl_idx)
                        if target_wl:
                            c = target_wl.get_child()
                            if c and hasattr(c, 'grab_focus'):
                                c.grab_focus()
                            else:
                                target_wl.grab_focus()
                            return
                elif self._cw_section.get_visible():
                    self._scroll.get_vadjustment().set_value(0.0)
                    target_box = None
                    if self._cw_movie_wrapper.get_visible() and self._cw_movie_box.get_first_child():
                        target_box = self._cw_movie_box
                    elif self._cw_tv_wrapper.get_visible() and self._cw_tv_box.get_first_child():
                        target_box = self._cw_tv_box
                    if target_box:
                        cw_children = []
                        curr = target_box.get_first_child()
                        while curr:
                            cw_children.append(curr)
                            curr = curr.get_next_sibling()
                        if cw_children:
                            target_cw = cw_children[min(idx % cols, len(cw_children) - 1)]
                            if hasattr(target_cw, 'grab_focus'):
                                target_cw.grab_focus()
                                return

                # Neither Watchlist nor Continue Watching visible -> focus tabs
                self._scroll.get_vadjustment().set_value(0.0)
                root = self.get_root()
                if root and hasattr(root, 'focus_tabs'):
                    root.focus_tabs()
                self.emit('focus-tabs')
                return
            else:
                target_idx = max(0, idx - cols)
                target_child = self._completed_flowbox.get_child_at_index(target_idx)
                if target_child:
                    c = target_child.get_child()
                    if c and hasattr(c, 'grab_focus'):
                        c.grab_focus()
                    else:
                        target_child.grab_focus()
        elif direction == 'down':
            target_idx = idx + cols
            target_child = self._completed_flowbox.get_child_at_index(target_idx)
            if not target_child:
                last_idx = idx
                while self._completed_flowbox.get_child_at_index(last_idx + 1):
                    last_idx += 1
                if last_idx > idx:
                    target_idx = last_idx
                else:
                    return
            target_child = self._completed_flowbox.get_child_at_index(target_idx)
            if target_child:
                c = target_child.get_child()
                if c and hasattr(c, 'grab_focus'):
                    c.grab_focus()
                else:
                    target_child.grab_focus()
        elif direction == 'left':
            if idx > 0:
                target_child = self._completed_flowbox.get_child_at_index(idx - 1)
                if target_child:
                    c = target_child.get_child()
                    if c and hasattr(c, 'grab_focus'):
                        c.grab_focus()
                    else:
                        target_child.grab_focus()
        elif direction == 'right':
            target_child = self._completed_flowbox.get_child_at_index(idx + 1)
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
                # If removing the last card in CW TV, try first card in CW Movies
                if self._cw_movie_wrapper.get_visible() and self._cw_movie_box.get_first_child():
                    m_first = self._cw_movie_box.get_first_child()
                    if m_first and hasattr(m_first, 'grab_focus'):
                        m_first.grab_focus()
                else:
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

        # Remove the card from its parent container immediately (instant feedback)
        parent_box = card.get_parent() if card else None
        if parent_box and hasattr(parent_box, 'remove'):
            parent_box.remove(card)
        else:
            for b in (self._cw_tv_box, self._cw_movie_box):
                curr = b.get_first_child()
                while curr:
                    nxt = curr.get_next_sibling()
                    if curr is card:
                        b.remove(curr)
                        break
                    curr = nxt

        # Update sub-section and section visibility
        has_tv = self._cw_tv_box.get_first_child() is not None
        has_movie = self._cw_movie_box.get_first_child() is not None
        self._cw_tv_wrapper.set_visible(has_tv)
        self._cw_movie_wrapper.set_visible(has_movie)
        self._cw_section.set_visible(has_tv or has_movie)

        has_wl = self._wl_flowbox.get_child_at_index(0) is not None
        has_comp = self._completed_flowbox.get_child_at_index(0) is not None
        if not (has_tv or has_movie or has_wl or has_comp):
            self._scroll.set_visible(False)
            self._empty_status.set_visible(True)

        self._last_cw_fp = None

        root = self.get_root()
        if root and hasattr(root, 'show_toast'):
            root.show_toast("Removed from Continue Watching")

    def _on_remove_completed_item(self, card, tmdb_id: int):
        """Remove an item from completed media and refresh/hide the completed section."""
        try:
            self._db.unmark_completed(tmdb_id)
        except Exception as e:
            logger.warning(f"Failed to remove completed item {tmdb_id}: {e}")

        # Shift focus to adjacent card before removal
        if card:
            parent_child = card.get_parent()
            next_focus = None
            if parent_child and hasattr(parent_child, 'get_next_sibling'):
                sib = parent_child.get_next_sibling() or parent_child.get_prev_sibling()
                if sib and hasattr(sib, 'get_child'):
                    next_focus = sib.get_child()
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
                elif self._cw_movie_wrapper.get_visible() and self._cw_movie_box.get_first_child():
                    m_card = self._cw_movie_box.get_first_child()
                    if m_card and hasattr(m_card, 'grab_focus'):
                        m_card.grab_focus()
                elif self._cw_tv_wrapper.get_visible() and self._cw_tv_box.get_first_child():
                    t_card = self._cw_tv_box.get_first_child()
                    if t_card and hasattr(t_card, 'grab_focus'):
                        t_card.grab_focus()
                else:
                    root = self.get_root()
                    if root and hasattr(root, 'focus_tabs'):
                        root.focus_tabs()
                    self.emit('focus-tabs')

        # Remove card's FlowBoxChild container from _completed_flowbox immediately
        parent_child = card.get_parent() if card else None
        if parent_child and hasattr(self._completed_flowbox, 'remove'):
            self._completed_flowbox.remove(parent_child)
            if hasattr(parent_child, 'set_child'):
                parent_child.set_child(None)

        # Update completed section visibility
        has_comp = self._completed_flowbox.get_child_at_index(0) is not None
        self._completed_section.set_visible(has_comp)

        has_tv = self._cw_tv_box.get_first_child() is not None
        has_movie = self._cw_movie_box.get_first_child() is not None
        has_wl = self._wl_flowbox.get_child_at_index(0) is not None
        if not (has_tv or has_movie or has_wl or has_comp):
            self._scroll.set_visible(False)
            self._empty_status.set_visible(True)

        self._last_comp_fp = None

        root = self.get_root()
        if root and hasattr(root, 'show_toast'):
            root.show_toast("Removed from Completed")
