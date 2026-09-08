"""Cast and crew filmography detail page."""

import threading
from typing import Dict, Any, List, Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, GObject, Pango, Gdk

from showberry.services.tmdb import TMDBClient, TMDB_IMAGE_BASE
from showberry.services.image_cache import ImageCache
from showberry.ui.movie_card import MovieCard


class PersonPage(Adw.NavigationPage):
    """Person detail page showing profile photo, biography, and filmography grid."""

    __gsignals__ = {
        'movie-selected':  (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'play-movie':      (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'person-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, person_data: Dict[str, Any]):
        self._person_data = person_data or {}
        person_id = self._person_data.get('id') or 0
        person_name = self._person_data.get('name') or 'Cast'

        tag = f'person-{person_id}-{id(self)}'
        super().__init__(title=person_name, tag=tag)

        self._tmdb = TMDBClient()
        self._credits: List[Dict[str, Any]] = []
        self._filter_type = 'all'  # 'all', 'movie', 'tv'
        self._full_bio = ""
        self._collapsed_bio = ""

        self._setup_ui()
        self._setup_keybindings()
        self.connect('map', self._on_page_mapped)
        self._load_person_info(person_id)

    def _setup_ui(self):
        toolbar_view = Adw.ToolbarView()

        # ── HeaderBar ───────────────────────────────────────────────────────
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        # ── Main Scrolled Container ─────────────────────────────────────────
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_vexpand(True)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(1400)
        clamp.set_tightening_threshold(800)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content_box.set_margin_top(20)
        content_box.set_margin_bottom(30)
        content_box.set_margin_start(16)
        content_box.set_margin_end(16)

        # ── 1. Hero / Profile Header ─────────────────────────────────────────
        hero_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        hero_box.set_valign(Gtk.Align.START)

        # Avatar
        self._avatar = Adw.Avatar.new(100, self.get_title(), True)
        self._avatar.set_valign(Gtk.Align.START)
        hero_box.append(self._avatar)

        # Name, Department, Bio
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        info_box.set_hexpand(True)
        info_box.set_valign(Gtk.Align.START)

        self._name_label = Gtk.Label(label=self.get_title())
        self._name_label.add_css_class('title-1')
        self._name_label.set_xalign(0.0)
        self._name_label.set_wrap(True)
        info_box.append(self._name_label)

        self._dept_label = Gtk.Label(label="Known for Acting")
        self._dept_label.add_css_class('dim-label')
        self._dept_label.set_xalign(0.0)
        info_box.append(self._dept_label)

        self._bio_label = Gtk.Label()
        self._bio_label.set_xalign(0.0)
        self._bio_label.set_wrap(True)
        self._bio_label.set_lines(4)
        self._bio_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._bio_label.set_selectable(True)
        self._bio_label.set_visible(False)
        info_box.append(self._bio_label)

        self._bio_expand_btn = Gtk.Button(label="Read More")
        self._bio_expand_btn.add_css_class('bio-expand-btn')
        self._bio_expand_btn.set_cursor_from_name('pointer')
        self._bio_expand_btn.set_halign(Gtk.Align.START)
        self._bio_expand_btn.set_visible(False)
        self._bio_expand_btn.connect('clicked', self._on_expand_bio_clicked)
        bio_key = Gtk.EventControllerKey.new()
        def _on_bio_key(controller, keyval, keycode, state):
            if keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
                self._focus_active_filter_btn()
                return True
            return False
        bio_key.connect('key-pressed', _on_bio_key)
        self._bio_expand_btn.add_controller(bio_key)
        info_box.append(self._bio_expand_btn)

        hero_box.append(info_box)
        content_box.append(hero_box)

        content_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── 2. Filmography Filter Tabs & Header ──────────────────────────────
        filmo_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        filmo_header.set_valign(Gtk.Align.CENTER)

        filmo_title = Gtk.Label(label="Filmography")
        filmo_title.add_css_class('title-2')
        filmo_title.set_xalign(0.0)
        filmo_title.set_hexpand(True)
        filmo_header.append(filmo_title)

        # Type Filter Pills (All / Movies / TV Series)
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        filter_box.add_css_class('linked')

        self._btn_all = Gtk.ToggleButton(label="All")
        self._btn_all.set_active(True)
        self._btn_all.connect('toggled', self._on_filter_type_toggled, 'all')
        filter_box.append(self._btn_all)

        self._btn_movies = Gtk.ToggleButton(label="Movies")
        self._btn_movies.set_group(self._btn_all)
        self._btn_movies.connect('toggled', self._on_filter_type_toggled, 'movie')
        filter_box.append(self._btn_movies)

        self._btn_tv = Gtk.ToggleButton(label="TV Series")
        self._btn_tv.set_group(self._btn_all)
        self._btn_tv.connect('toggled', self._on_filter_type_toggled, 'tv')
        filter_box.append(self._btn_tv)

        filter_key = Gtk.EventControllerKey.new()
        filter_key.connect('key-pressed', self._on_filter_key_pressed)
        filter_box.add_controller(filter_key)

        filmo_header.append(filter_box)
        content_box.append(filmo_header)

        # ── 3. Filmography Grid ──────────────────────────────────────────────
        grid_overlay = Gtk.Overlay()

        self._flowbox = Gtk.FlowBox()
        self._flowbox.set_homogeneous(True)
        self._flowbox.set_column_spacing(14)
        self._flowbox.set_row_spacing(14)
        self._flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flowbox.set_halign(Gtk.Align.CENTER)
        self._flowbox.set_margin_top(8)
        self._flowbox.set_margin_bottom(24)
        grid_overlay.set_child(self._flowbox)

        # Spinner
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(48, 48)
        self._spinner.set_halign(Gtk.Align.CENTER)
        self._spinner.set_valign(Gtk.Align.CENTER)
        self._spinner.start()
        grid_overlay.add_overlay(self._spinner)

        # Empty status
        self._empty_status = Adw.StatusPage()
        self._empty_status.set_icon_name('video-x-generic-symbolic')
        self._empty_status.set_title("No Titles Found")
        self._empty_status.set_description("No filmography entries available for this category.")
        self._empty_status.set_visible(False)
        grid_overlay.add_overlay(self._empty_status)

        content_box.append(grid_overlay)

        clamp.set_child(content_box)
        self._scroll.set_child(clamp)
        toolbar_view.set_content(self._scroll)
        self.set_child(toolbar_view)

        # Load avatar if profile_path is present in initial data
        profile_path = self._person_data.get('profile_path')
        if profile_path:
            self._load_avatar(profile_path)

    def _load_avatar(self, profile_path: str):
        url = f"{TMDB_IMAGE_BASE}/w342{profile_path}"
        def _on_img(paintable):
            if paintable:
                self._avatar.set_custom_image(paintable)
        ImageCache.get_default().load_image(url, _on_img)

    def _load_person_info(self, person_id: int):
        threading.Thread(target=self._fetch_data_worker, args=(person_id,), daemon=True).start()

    def _fetch_data_worker(self, person_id: int):
        if not person_id and self._person_data.get('name'):
            results = self._tmdb.search_person(self._person_data['name'])
            if results:
                person_id = results[0].get('id') or 0

        details = self._tmdb.get_person_details(person_id) if person_id else None
        credits_list = self._tmdb.get_person_credits(person_id) if person_id else []
        GLib.idle_add(self._apply_data, details, credits_list)

    def _apply_data(self, details: Optional[Dict[str, Any]], credits_list: List[Dict[str, Any]]):
        self._spinner.stop()
        self._spinner.set_visible(False)

        if details:
            name = details.get('name') or self.get_title()
            self._name_label.set_text(name)
            self.set_title(name)

            dept = details.get('known_for_department')
            if dept:
                self._dept_label.set_text(f"Known for {dept}")

            bio = details.get('biography')
            if bio and bio.strip():
                self._full_bio = bio.strip()
                # Normalize whitespace for strict 4-line clamping across all paragraphs
                self._collapsed_bio = ' '.join(self._full_bio.split())
                self._bio_label.set_text(self._collapsed_bio)
                self._bio_label.set_lines(4)
                self._bio_label.set_ellipsize(Pango.EllipsizeMode.END)
                self._bio_label.set_visible(True)

                paras = [p for p in self._full_bio.split('\n') if p.strip()]
                if len(self._collapsed_bio) > 240 or len(paras) > 2:
                    self._bio_expand_btn.set_visible(True)
                    self._bio_expand_btn.set_label("Read More")
                else:
                    self._bio_expand_btn.set_visible(False)
            else:
                self._full_bio = ""
                self._collapsed_bio = ""
                self._bio_label.set_visible(False)
                self._bio_expand_btn.set_visible(False)

            profile_path = details.get('profile_path')
            if profile_path and not self._avatar.get_custom_image():
                self._load_avatar(profile_path)

        self._credits = credits_list or []
        self._update_filter_labels()
        self._render_grid()

    def _on_expand_bio_clicked(self, btn):
        if self._bio_label.get_lines() == 4:
            self._bio_label.set_lines(0)
            self._bio_label.set_ellipsize(Pango.EllipsizeMode.NONE)
            if self._full_bio:
                self._bio_label.set_text(self._full_bio)
            btn.set_label("Show Less")
        else:
            self._bio_label.set_lines(4)
            self._bio_label.set_ellipsize(Pango.EllipsizeMode.END)
            if self._collapsed_bio:
                self._bio_label.set_text(self._collapsed_bio)
            btn.set_label("Read More")

    def _on_filter_type_toggled(self, button, filter_type: str):
        if button.get_active():
            self._filter_type = filter_type
            self._render_grid()

    def _render_grid(self):
        # Clear existing cards
        while True:
            child = self._flowbox.get_first_child()
            if child is None:
                break
            self._flowbox.remove(child)

        # Filter credits
        if self._filter_type == 'movie':
            visible_items = [c for c in self._credits if c.get('media_type') != 'tv']
        elif self._filter_type == 'tv':
            visible_items = [c for c in self._credits if c.get('media_type') == 'tv']
        else:
            visible_items = self._credits

        if not visible_items:
            self._empty_status.set_visible(True)
            self._flowbox.set_visible(False)
            return

        self._empty_status.set_visible(False)
        self._flowbox.set_visible(True)

        for m in visible_items:
            card = MovieCard(m)
            card.connect('clicked-movie', lambda c, movie_data: self.emit('movie-selected', movie_data))
            card.connect('play-movie', lambda c, stream_data: self.emit('play-movie', stream_data))
            card.connect('navigate-grid', self._on_card_navigate)
            self._flowbox.append(card)

            child = card.get_parent()
            if child:
                child.set_focusable(False)
                child.set_focus_on_click(False)

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
                self._scroll.get_vadjustment().set_value(0.0)
                self._focus_active_filter_btn()
                return
            target_idx = max(0, idx - cols)
        elif direction == 'down':
            target_idx = idx + cols
            if not self._flowbox.get_child_at_index(target_idx):
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

    def _setup_keybindings(self):
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect('key-pressed', self._on_key_pressed)
        self.add_controller(key_ctrl)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        root = self.get_root()
        focus = root.get_focus() if root else None
        if focus and isinstance(focus, (Gtk.Editable, Gtk.Entry)):
            return False

        if keyval in (Gdk.KEY_Escape, Gdk.KEY_BackSpace):
            nav = self.get_ancestor(Adw.NavigationView)
            if nav:
                nav.pop()
                return True
            elif root and hasattr(root, '_nav_view'):
                root._nav_view.pop()
                return True
        return False

    def _on_filter_key_pressed(self, controller, keyval, keycode, state):
        if keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            if self._focus_first_card():
                return True
        elif keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            if hasattr(self, '_bio_expand_btn') and self._bio_expand_btn.get_visible():
                self._bio_expand_btn.grab_focus()
                return True
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            root = self.get_root()
            focus = root.get_focus() if root else None
            if focus == self._btn_tv:
                self._btn_movies.grab_focus()
                return True
            elif focus == self._btn_movies:
                self._btn_all.grab_focus()
                return True
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            root = self.get_root()
            focus = root.get_focus() if root else None
            if focus == self._btn_all:
                self._btn_movies.grab_focus()
                return True
            elif focus == self._btn_movies:
                self._btn_tv.grab_focus()
                return True
        return False

    def _focus_active_filter_btn(self):
        if self._btn_movies.get_active():
            self._btn_movies.grab_focus()
        elif self._btn_tv.get_active():
            self._btn_tv.grab_focus()
        else:
            self._btn_all.grab_focus()

    def _focus_first_card(self) -> bool:
        c0 = self._flowbox.get_child_at_index(0)
        if c0:
            card = c0.get_child()
            if card and hasattr(card, 'grab_focus'):
                card.grab_focus()
                return True
            elif hasattr(c0, 'grab_focus'):
                c0.grab_focus()
                return True
        return False

    def focus_first(self):
        """Focus active filter button or first card."""
        if not self._focus_first_card():
            self._focus_active_filter_btn()

    def _on_page_mapped(self, widget):
        def _initial_focus():
            self.focus_first()
            return False
        GLib.idle_add(_initial_focus)

    def _update_filter_labels(self):
        count_all = len(self._credits)
        count_movies = len([c for c in self._credits if c.get('media_type') != 'tv'])
        count_tv = len([c for c in self._credits if c.get('media_type') == 'tv'])
        if count_all > 0:
            self._btn_all.set_label(f"All ({count_all})")
            self._btn_movies.set_label(f"Movies ({count_movies})")
            self._btn_tv.set_label(f"TV Series ({count_tv})")
        else:
            self._btn_all.set_label("All")
            self._btn_movies.set_label("Movies")
            self._btn_tv.set_label("TV Series")
