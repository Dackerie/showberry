"""Movie and TV show detail page with backdrop, info, season/episode browser, and playback options."""

import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, GObject, Pango, Graphene, Gdk

from showberry.services.tmdb import TMDBClient, genre_id_to_name
from showberry.services.image_cache import ImageCache
from showberry.services.database import DatabaseService
from showberry.providers import get_all_providers


class BackdropWidget(Gtk.Widget):
    """Backdrop widget that scales with COVER but anchors to the TOP (draw_y = 0.0).

    Ensures actors' heads, hair, and sky are never cut off.
    Minimum width is 0 to allow the window to shrink smoothly to mobile sizes.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._paintable = None
        self._can_shrink = True
        self.set_valign(Gtk.Align.START)
        self.set_vexpand(False)
        self.add_css_class('movie-backdrop')

    def set_paintable(self, paintable):
        self._paintable = paintable
        self.queue_draw()

    def get_paintable(self):
        return self._paintable

    def set_can_shrink(self, val: bool):
        self._can_shrink = val

    def get_can_shrink(self) -> bool:
        return getattr(self, '_can_shrink', True)

    def set_content_fit(self, fit):
        pass

    def do_snapshot(self, snapshot):
        if not self._paintable:
            return
        w = self.get_width()
        h = self.get_height()
        if w <= 0 or h <= 0:
            return

        pw = self._paintable.get_intrinsic_width()
        ph = self._paintable.get_intrinsic_height()
        if pw <= 0 or ph <= 0:
            self._paintable.snapshot(snapshot, w, h)
            return

        scale = max(w / pw, h / ph)
        draw_w = pw * scale
        draw_h = ph * scale
        draw_x = (w - draw_w) / 2.0
        if draw_h > h:
            # Upper-bias framing: preserves headroom/sky while capturing characters' faces and bodies
            draw_y = (h - draw_h) * 0.20
        else:
            draw_y = (h - draw_h) / 2.0

        rect = Graphene.Rect()
        rect.init(0, 0, w, h)
        snapshot.push_clip(rect)
        snapshot.save()
        snapshot.translate(Graphene.Point().init(draw_x, draw_y))
        self._paintable.snapshot(snapshot, draw_w, draw_h)
        snapshot.restore()
        snapshot.pop()

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 0, 0, -1, -1
        else:
            if for_size > 0:
                calc_h = int(for_size * 0.28)
                target_h = max(260, min(480, calc_h))
                return target_h, target_h, -1, -1
            return 260, 320, -1, -1


class MoviePage(Adw.NavigationPage):
    """Media detail page with backdrop, poster, info, TV season/episode selector, and play button."""

    __gsignals__ = {
        'play-movie': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'movie-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'watchlist-toggled': (GObject.SignalFlags.RUN_FIRST, None, (object, bool)),
    }

    def __init__(self, movie=None):
        self._movie = movie or {}

        media_type = self._movie.get('media_type')
        if not media_type:
            if 'first_air_date' in self._movie or 'number_of_seasons' in self._movie:
                media_type = 'tv'
            else:
                media_type = 'movie'
        self._media_type = media_type

        movie_title = self._movie.get('title') or self._movie.get('name') or 'Details'
        if 'title' not in self._movie and 'name' in self._movie:
            self._movie['title'] = self._movie['name']
        if 'release_date' not in self._movie and 'first_air_date' in self._movie:
            self._movie['release_date'] = self._movie['first_air_date']

        tmdb_id = self._movie.get('id') or self._movie.get('tmdb_id')
        if tmdb_id:
            try:
                tmdb_id = int(tmdb_id)
                self._movie['id'] = tmdb_id
                self._movie['tmdb_id'] = tmdb_id
            except (ValueError, TypeError):
                pass

        detail_tag = f'detail-{tmdb_id}-{id(self)}' if tmdb_id else f'detail-{id(self)}'
        super().__init__(title=movie_title, tag=detail_tag)

        self._tmdb = TMDBClient()
        self._db = DatabaseService()
        self._detailed_media = None
        self._episodes_data: List[Dict[str, Any]] = []

        self._setup_ui()
        self._setup_keybindings()
        self.connect('map', self._on_page_mapped)
        # Pre-populate images immediately from card data (0ms — already cached from grid).
        # The network detail call (_load_details_async) may update them later if needed.
        self._load_images_async()
        self._load_details_async()

    def _setup_keybindings(self):
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect('key-pressed', self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_page_mapped(self, widget):
        def _focus_play():
            if hasattr(self, '_resume_button') and self._resume_button.get_visible():
                self._resume_button.grab_focus()
            elif hasattr(self, '_play_button') and self._play_button.get_visible():
                self._play_button.grab_focus()
            return False
        GLib.idle_add(_focus_play)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        root = self.get_root()
        focus = root.get_focus() if root else None
        if focus and isinstance(focus, (Gtk.Editable, Gtk.Entry)):
            return False

        if keyval in (Gdk.KEY_space, Gdk.KEY_p, Gdk.KEY_P):
            if hasattr(self, '_resume_button') and self._resume_button.get_visible():
                self._on_resume_clicked(None)
            else:
                self._on_play_clicked(None)
            return True
        elif keyval in (Gdk.KEY_w, Gdk.KEY_W):
            self._on_watchlist_toggled(None)
            return True
        elif keyval in (Gdk.KEY_s, Gdk.KEY_S, Gdk.KEY_t, Gdk.KEY_T):
            self._on_select_stream_clicked(None)
            return True
        elif keyval in (Gdk.KEY_Escape, Gdk.KEY_BackSpace):
            if root and hasattr(root, '_nav_view'):
                root._nav_view.pop()
                return True
        return False


    def _setup_ui(self):
        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        # Watchlist toggle button in header bar
        self._watchlist_btn = Gtk.Button.new_from_icon_name('bookmark-new-symbolic')
        self._watchlist_btn.add_css_class('flat')
        self._watchlist_btn.set_tooltip_text("Toggle Watchlist")
        self._update_watchlist_btn_state()
        self._watchlist_btn.connect('clicked', self._on_watchlist_toggled)
        wl_key = Gtk.EventControllerKey.new()
        wl_key.connect('key-pressed', self._on_watchlist_key_pressed)
        self._watchlist_btn.add_controller(wl_key)
        header_bar.pack_end(self._watchlist_btn)

        # Scrollable content
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Backdrop image with overlay (top-anchored snapshot widget)
        backdrop_overlay = Gtk.Overlay()
        backdrop_overlay.set_valign(Gtk.Align.START)
        backdrop_overlay.set_vexpand(False)

        self._backdrop = BackdropWidget()
        backdrop_overlay.set_child(self._backdrop)

        scrim = Gtk.Box()
        scrim.add_css_class('backdrop-scrim')
        scrim.set_valign(Gtk.Align.FILL)
        scrim.set_vexpand(True)
        scrim.set_can_target(False)
        backdrop_overlay.add_overlay(scrim)

        content.append(backdrop_overlay)

        # Info section
        self._info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self._info_box.set_margin_start(24)
        self._info_box.set_margin_end(24)
        self._info_box.set_margin_top(16)
        self._info_box.set_margin_bottom(16)

        # Poster (strict 2:3 aspect ratio, never stretches vertically)
        self._poster = Gtk.Picture()
        self._poster.set_size_request(200, 300)
        self._poster.set_content_fit(Gtk.ContentFit.COVER)
        self._poster.set_can_shrink(True)
        self._poster.set_valign(Gtk.Align.START)
        self._poster.add_css_class('card-poster')
        self._info_box.append(self._poster)

        # Details
        self._details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._details.set_vexpand(True)
        self._details.set_valign(Gtk.Align.START)

        # Title
        self._title_label = Gtk.Label(label=self._movie.get('title', ''))
        self._title_label.add_css_class('title-1')
        self._title_label.set_xalign(0)
        self._title_label.set_wrap(True)
        self._details.append(self._title_label)

        # Tagline
        self._tagline_label = Gtk.Label()
        self._tagline_label.add_css_class('dim-label')
        self._tagline_label.add_css_class('italic')
        self._tagline_label.set_xalign(0)
        self._tagline_label.set_wrap(True)
        self._tagline_label.set_visible(False)
        self._details.append(self._tagline_label)

        # Rating, year, runtime
        self._meta_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._meta_box.set_margin_top(4)

        self._rating_label = Gtk.Label()
        self._rating_label.add_css_class('meta-rating')
        self._rating_label.add_css_class('title-4')
        self._meta_box.append(self._rating_label)

        self._year_label = Gtk.Label()
        self._year_label.add_css_class('dim-label')
        self._year_label.add_css_class('title-4')
        self._meta_box.append(self._year_label)

        self._runtime_label = Gtk.Label()
        self._runtime_label.add_css_class('dim-label')
        self._runtime_label.add_css_class('title-4')
        self._runtime_label.set_wrap(True)
        self._meta_box.append(self._runtime_label)

        self._details.append(self._meta_box)

        # Dedicated Director label (instant display, clean typography)
        self._director_label = Gtk.Label()
        self._director_label.add_css_class('dim-label')
        self._director_label.set_xalign(0)
        self._director_label.set_wrap(True)
        self._director_label.set_visible(False)
        self._details.append(self._director_label)

        # Genres (FlowBox so pills wrap cleanly on narrow/mobile screens)
        self._genres_box = Gtk.FlowBox()
        self._genres_box.add_css_class('genres-flowbox')
        self._genres_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._genres_box.set_homogeneous(False)
        self._genres_box.set_min_children_per_line(1)
        self._genres_box.set_max_children_per_line(10)
        self._genres_box.set_row_spacing(6)
        self._genres_box.set_column_spacing(6)
        self._genres_box.set_margin_top(6)
        self._details.append(self._genres_box)

        # Action buttons row (Play + Resume + Provider)
        self._actions_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._actions_row.set_margin_top(10)
        self._actions_row.set_margin_bottom(4)

        actions_key = Gtk.EventControllerKey.new()
        actions_key.connect('key-pressed', self._on_actions_key_pressed)
        self._actions_row.add_controller(actions_key)

        self._play_button = Gtk.Button(label='▶  Play')
        self._play_button.add_css_class('suggested-action')
        self._play_button.add_css_class('pill')
        self._play_button.set_size_request(130, -1)
        self._play_button.connect('clicked', self._on_play_clicked)
        self._actions_row.append(self._play_button)

        # Resume button (if previously watched)
        self._resume_button = Gtk.Button(label='Resume')
        self._resume_button.add_css_class('pill')
        self._resume_button.set_visible(False)
        self._resume_button.connect('clicked', self._on_resume_clicked)
        self._actions_row.append(self._resume_button)

        # Provider selector
        self._provider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._provider_box.set_valign(Gtk.Align.CENTER)
        provider_label = Gtk.Label(label='Provider:')
        provider_label.add_css_class('dim-label')
        self._provider_box.append(provider_label)

        self._provider_dropdown = Gtk.DropDown()
        self._provider_dropdown.set_size_request(160, -1)
        self._provider_box.append(self._provider_dropdown)
        self._actions_row.append(self._provider_box)

        # Select specific torrent stream button
        self._select_stream_btn = Gtk.Button.new_from_icon_name('view-list-bullet-symbolic')
        self._select_stream_btn.add_css_class('flat')
        self._select_stream_btn.set_tooltip_text("Browse and select torrent stream")
        self._select_stream_btn.connect('clicked', self._on_select_stream_clicked)
        self._actions_row.append(self._select_stream_btn)

        self._details.append(self._actions_row)

        # Overview
        self._overview_label = Gtk.Label(label=self._movie.get('overview', ''))
        self._overview_label.set_xalign(0)
        self._overview_label.set_wrap(True)
        self._overview_label.set_hexpand(True)
        self._overview_label.set_margin_top(8)
        self._details.append(self._overview_label)

        self._info_box.append(self._details)
        content.append(self._info_box)

        # TV Shows Section (Seasons & Episodes)
        self._tv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._tv_box.set_margin_start(24)
        self._tv_box.set_margin_end(24)
        self._tv_box.set_margin_bottom(24)
        self._tv_box.set_visible(self._media_type == 'tv')

        tv_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        tv_title = Gtk.Label(label="Episodes")
        tv_title.add_css_class('title-3')
        tv_header.append(tv_title)

        season_label = Gtk.Label(label="Season:")
        season_label.add_css_class('dim-label')
        season_label.set_margin_start(16)
        tv_header.append(season_label)

        self._season_dropdown = Gtk.DropDown()
        self._season_dropdown.connect('notify::selected', self._on_season_changed)
        season_key = Gtk.EventControllerKey.new()
        season_key.connect('key-pressed', self._on_season_key_pressed)
        self._season_dropdown.add_controller(season_key)
        tv_header.append(self._season_dropdown)

        self._tv_box.append(tv_header)

        # Episode ListBox
        self._episodes_listbox = Gtk.ListBox()
        self._episodes_listbox.add_css_class('boxed-list')
        self._episodes_listbox.connect('row-activated', self._on_episode_row_activated)
        ep_key = Gtk.EventControllerKey.new()
        ep_key.connect('key-pressed', self._on_episodes_key_pressed)
        self._episodes_listbox.add_controller(ep_key)
        self._tv_box.append(self._episodes_listbox)

        content.append(self._tv_box)

        # Top Cast Section (fills empty void below details)
        self._cast_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._cast_box.set_margin_start(24)
        self._cast_box.set_margin_end(24)
        self._cast_box.set_margin_bottom(20)
        self._cast_box.set_visible(False)

        cast_title = Gtk.Label(label="Top Cast")
        cast_title.add_css_class('title-3')
        cast_title.set_xalign(0)
        self._cast_box.append(cast_title)

        cast_scroll = Gtk.ScrolledWindow()
        cast_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        cast_scroll.set_min_content_height(54)
        cast_scroll.set_vexpand(False)

        self._cast_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._cast_row.set_margin_top(4)
        self._cast_row.set_margin_bottom(8)
        self._cast_row.set_valign(Gtk.Align.CENTER)
        cast_scroll.set_child(self._cast_row)
        self._cast_box.append(cast_scroll)

        content.append(self._cast_box)

        # More Like This (Recommendations) Section
        self._recs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._recs_box.set_margin_start(24)
        self._recs_box.set_margin_end(24)
        self._recs_box.set_margin_bottom(32)
        self._recs_box.set_visible(False)

        recs_title = Gtk.Label(label="More Like This")
        recs_title.add_css_class('title-3')
        recs_title.set_xalign(0)
        self._recs_box.append(recs_title)

        recs_scroll = Gtk.ScrolledWindow()
        recs_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        recs_scroll.set_vexpand(False)

        self._recs_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self._recs_row.set_margin_top(4)
        self._recs_row.set_margin_bottom(8)
        recs_scroll.set_child(self._recs_row)
        self._recs_box.append(recs_scroll)

        content.append(self._recs_box)

        scroll.set_child(content)

        # Breakpoint for mobile/narrow screen sizes (< 780px)
        self._breakpoint_bin = Adw.BreakpointBin()
        self._breakpoint_bin.set_size_request(320, 200)
        bp = Adw.Breakpoint.new(Adw.breakpoint_condition_parse("max-width: 780px"))
        bp.add_setter(self._info_box, "orientation", Gtk.Orientation.VERTICAL)
        bp.add_setter(self._info_box, "spacing", 12)
        bp.add_setter(self._poster, "halign", Gtk.Align.CENTER)
        bp.add_setter(self._poster, "width-request", 160)
        bp.add_setter(self._poster, "height-request", 240)
        bp.add_setter(self._actions_row, "orientation", Gtk.Orientation.VERTICAL)
        bp.add_setter(self._genres_box, "halign", Gtk.Align.CENTER)
        bp.add_setter(self._details, "halign", Gtk.Align.FILL)
        bp.add_setter(self._title_label, "xalign", 0.5)
        bp.add_setter(self._title_label, "justify", Gtk.Justification.CENTER)
        bp.add_setter(self._tagline_label, "xalign", 0.5)
        bp.add_setter(self._meta_box, "halign", Gtk.Align.CENTER)
        bp.add_setter(self._director_label, "xalign", 0.5)
        bp.add_setter(self._play_button, "hexpand", True)
        bp.add_setter(self._resume_button, "hexpand", True)
        bp.add_setter(self._provider_box, "halign", Gtk.Align.CENTER)
        self._breakpoint_bin.add_breakpoint(bp)
        self._breakpoint_bin.set_child(scroll)

        toolbar_view.set_content(self._breakpoint_bin)
        self.set_child(toolbar_view)

        # Populate initial movie/show fields
        self._update_ui()

    def _update_ui(self):
        """Update UI with movie data."""
        movie = self._movie

        self._title_label.set_text(movie.get('title') or movie.get('name') or '')

        tagline = movie.get('tagline') or ''
        if tagline:
            self._tagline_label.set_text(f'"{tagline}"')
            self._tagline_label.set_visible(True)
        else:
            self._tagline_label.set_visible(False)

        rating = movie.get('vote_average') or 0
        if rating > 0:
            self._rating_label.set_text(f'★ {rating:.1f}')
        else:
            self._rating_label.set_text('')

        release_date = movie.get('release_date') or movie.get('first_air_date') or ''
        if release_date:
            year = str(release_date)[:4]
            self._year_label.set_text(year)
        else:
            self._year_label.set_text('')

        runtime = movie.get('runtime')
        if runtime:
            self._runtime_label.set_text(self._format_runtime_ends_at(runtime))
        else:
            self._runtime_label.set_text('')


        directors = movie.get('directors') or []
        if directors:
            self._director_label.set_text(f"Directed by {', '.join(directors)}")
            self._director_label.set_visible(True)
        else:
            self._director_label.set_visible(False)

        # Genres
        genre_names = movie.get('genre_names', [])
        genre_ids = movie.get('genre_ids', [])
        if not genre_names and genre_ids:
            genre_names = [genre_id_to_name(gid) for gid in genre_ids]

        while True:
            child = self._genres_box.get_first_child()
            if child is None:
                break
            self._genres_box.remove(child)

        for genre_name in genre_names[:5]:
            label = Gtk.Label(label=genre_name)
            label.add_css_class('genre-pill')
            self._genres_box.append(label)

        overview = movie.get('overview') or ''
        self._overview_label.set_text(overview)

        # Check watch history for Resume button
        tmdb_id = movie.get('id')
        if tmdb_id:
            progress = self._db.get_item_progress(tmdb_id)
            if progress and progress.get('progress_seconds', 0) > 15:
                pos = int(progress['progress_seconds'])
                mins = pos // 60
                secs = pos % 60
                self._resume_button.set_label(f"Resume ({mins}:{secs:02d})")
                self._resume_button.set_visible(True)
                self._resume_pos = pos
                self._resume_info_hash = progress.get('info_hash')
                self._resume_file_idx = progress.get('file_idx')

        # Render cast & recommendations if already available
        if movie.get('cast'):
            self._render_cast(movie.get('cast', []))
        if movie.get('recommendations'):
            self._render_recommendations(movie.get('recommendations', []))

        self._load_images_async()
        self._setup_providers()

    def _render_cast(self, cast_list):
        """Render top cast member chips in horizontal scrolling row."""
        while True:
            child = self._cast_row.get_first_child()
            if child is None:
                break
            self._cast_row.remove(child)

        if not cast_list:
            self._cast_box.set_visible(False)
            return

        for person in cast_list[:12]:
            chip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            chip.add_css_class('cast-card')
            chip.set_valign(Gtk.Align.CENTER)

            name = person.get('name', '')
            char = person.get('character', '')

            name_lbl = Gtk.Label(label=name)
            name_lbl.add_css_class('cast-name')
            name_lbl.set_xalign(0.5)
            name_lbl.set_wrap(False)
            name_lbl.set_single_line_mode(True)
            chip.append(name_lbl)

            if char:
                char_lbl = Gtk.Label(label=char)
                char_lbl.add_css_class('cast-character')
                char_lbl.add_css_class('dim-label')
                char_lbl.set_xalign(0.5)
                char_lbl.set_wrap(False)
                char_lbl.set_single_line_mode(True)
                chip.append(char_lbl)

            self._cast_row.append(chip)

        self._cast_box.set_visible(True)

    def _render_recommendations(self, recs_list):
        """Render 'More Like This' movie cards in horizontal scrolling row."""
        while True:
            child = self._recs_row.get_first_child()
            if child is None:
                break
            self._recs_row.remove(child)

        if not recs_list:
            self._recs_box.set_visible(False)
            return

        from showberry.ui.movie_card import MovieCard
        for rec in recs_list[:12]:
            card = MovieCard(rec)
            card.connect('play-movie', lambda c, sd: self.emit('play-movie', sd))
            card.connect('clicked-movie', lambda c, md: self.emit('movie-selected', md))
            card.connect('navigate-grid', self._on_rec_navigate)
            self._recs_row.append(card)

        self._recs_box.set_visible(True)

    def _on_watchlist_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Down:
            if hasattr(self, '_play_button') and self._play_button.get_visible():
                self._play_button.grab_focus()
                return True
        return False

    def _on_actions_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Up:
            if hasattr(self, '_watchlist_btn') and self._watchlist_btn.get_visible():
                self._watchlist_btn.grab_focus()
                return True
        elif keyval == Gdk.KEY_Down:
            if self._media_type == 'tv' and hasattr(self, '_season_dropdown') and self._tv_box.get_visible():
                self._season_dropdown.grab_focus()
                return True
            elif hasattr(self, '_recs_box') and self._recs_box.get_visible():
                first_card = self._recs_row.get_first_child()
                if first_card and hasattr(first_card, 'grab_focus'):
                    first_card.grab_focus()
                    return True
        return False

    def _on_season_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Up:
            if hasattr(self, '_play_button'):
                self._play_button.grab_focus()
                return True
        elif keyval == Gdk.KEY_Down:
            if hasattr(self, '_episodes_listbox'):
                first_row = self._episodes_listbox.get_row_at_index(0)
                if first_row and hasattr(first_row, 'grab_focus'):
                    first_row.grab_focus()
                    return True
        return False

    def _on_episodes_key_pressed(self, controller, keyval, keycode, state):
        sel = self._episodes_listbox.get_selected_row()
        if not sel:
            root = self.get_root()
            focus = root.get_focus() if root else None
            if focus and isinstance(focus, Gtk.ListBoxRow):
                sel = focus
            elif focus and focus.get_ancestor(Gtk.ListBoxRow):
                sel = focus.get_ancestor(Gtk.ListBoxRow)

        if keyval == Gdk.KEY_Up:
            if sel and sel.get_index() == 0:
                if hasattr(self, '_season_dropdown') and self._season_dropdown.get_visible():
                    self._season_dropdown.grab_focus()
                    return True
                elif hasattr(self, '_play_button'):
                    self._play_button.grab_focus()
                    return True
        elif keyval == Gdk.KEY_Down:
            total_rows = len(self._episodes_data)
            if sel and sel.get_index() >= max(0, total_rows - 1):
                if hasattr(self, '_recs_box') and self._recs_box.get_visible():
                    first_card = self._recs_row.get_first_child()
                    if first_card and hasattr(first_card, 'grab_focus'):
                        first_card.grab_focus()
                        return True
        return False

    def _on_rec_navigate(self, card, direction: str):
        if direction == 'up':
            if self._media_type == 'tv' and hasattr(self, '_episodes_listbox') and self._tv_box.get_visible():
                total_rows = len(self._episodes_data)
                last_row = self._episodes_listbox.get_row_at_index(max(0, total_rows - 1))
                if last_row and hasattr(last_row, 'grab_focus'):
                    last_row.grab_focus()
                    return
            if hasattr(self, '_play_button'):
                self._play_button.grab_focus()
                return
        elif direction == 'left':
            prev_sibling = card.get_prev_sibling()
            if prev_sibling and hasattr(prev_sibling, 'grab_focus'):
                prev_sibling.grab_focus()
        elif direction == 'right':
            next_sibling = card.get_next_sibling()
            if next_sibling and hasattr(next_sibling, 'grab_focus'):
                next_sibling.grab_focus()

    def _format_runtime_ends_at(self, runtime_minutes: int) -> str:
        """Format runtime as '2h 19m • Ends at 9:55 PM'."""
        hours = runtime_minutes // 60
        mins = runtime_minutes % 60
        if hours > 0:
            rt_str = f'{hours}h {mins}m' if mins else f'{hours}h'
        else:
            rt_str = f'{mins}m'
        ends_at = datetime.now() + timedelta(minutes=runtime_minutes)
        ends_str = ends_at.strftime('%-I:%M %p')
        return f'{rt_str} • Ends at {ends_str}'

    def _update_watchlist_btn_state(self):
        tmdb_id = self._movie.get('id')
        if tmdb_id and self._db.is_in_watchlist(tmdb_id):
            self._watchlist_btn.set_icon_name('starred-symbolic')
            self._watchlist_btn.add_css_class('watchlist-active')
            self._watchlist_btn.set_tooltip_text("Remove from Watchlist")
        else:
            self._watchlist_btn.set_icon_name('non-starred-symbolic')
            self._watchlist_btn.remove_css_class('watchlist-active')
            self._watchlist_btn.set_tooltip_text("Add to Watchlist")

    def _on_watchlist_toggled(self, button):
        tmdb_id = self._movie.get('id')
        if not tmdb_id:
            return

        window = self.get_root()
        is_added = False
        if self._db.is_in_watchlist(tmdb_id):
            self._db.remove_from_watchlist(tmdb_id)
            if hasattr(window, 'show_toast'):
                window.show_toast("Removed from Watchlist")
        else:
            self._db.add_to_watchlist(
                tmdb_id=tmdb_id,
                title=self._movie.get('title', 'Unknown'),
                media_type=self._media_type,
                poster_url=self._movie.get('poster_url'),
                release_date=self._movie.get('release_date'),
                vote_average=self._movie.get('vote_average', 0.0),
            )
            is_added = True
            if hasattr(window, 'show_toast'):
                window.show_toast("Added to Watchlist")
        self._update_watchlist_btn_state()
        self.emit('watchlist-toggled', self._movie, is_added)

    def _load_images_async(self):
        """Load poster and backdrop asynchronously from cache (instant if already in disk cache)."""
        cache = ImageCache()
        movie = self._movie

        poster_url = (
            movie.get('poster_url')
            or movie.get('poster_url_small')
            or (f"https://image.tmdb.org/t/p/w500{movie['poster_path']}" if movie.get('poster_path') else None)
        )
        backdrop_url = (
            movie.get('backdrop_url')
            or (f"https://image.tmdb.org/t/p/w1280{movie['backdrop_path']}" if movie.get('backdrop_path') else None)
        )

        def worker():
            if poster_url:
                tex = cache.get_image(poster_url, width=200, height=300)
                if tex:
                    GLib.idle_add(self._poster.set_paintable, tex)
            if backdrop_url:
                tex = cache.get_image(backdrop_url, width=1280, height=720)
                if tex:
                    GLib.idle_add(self._backdrop.set_paintable, tex)

        threading.Thread(target=worker, daemon=True).start()


    def _setup_providers(self):
        providers = get_all_providers()
        self._provider_names = ['Auto (Best)'] + [p.name for p in providers]
        self._provider_dropdown.set_model(Gtk.StringList.new(self._provider_names))
        self._provider_dropdown.set_selected(0)

    def _load_details_async(self):
        movie_id = self._movie.get('id')
        if not movie_id:
            return

        threading.Thread(target=self._fetch_details_worker, args=(movie_id,), daemon=True).start()

    def _fetch_details_worker(self, movie_id):
        from showberry.services.settings import SettingsService
        api_key = SettingsService().tmdb_api_key
        if api_key:
            self._tmdb.set_api_key(api_key)

        if self._media_type == 'tv':
            tv_details = self._tmdb.get_tv_details(movie_id)
            if tv_details:
                GLib.idle_add(self._on_tv_details_loaded, tv_details)
        else:
            details = self._tmdb.get_movie_details(movie_id)
            if details:
                GLib.idle_add(self._on_movie_details_loaded, details)

    def _on_movie_details_loaded(self, details):
        self._detailed_media = details
        self._movie.update(details)

        overview = details.get('overview') or self._movie.get('overview') or ''
        if overview:
            self._overview_label.set_text(overview)

        tagline = details.get('tagline') or ''
        if tagline:
            self._tagline_label.set_text(f'"{tagline}"')
            self._tagline_label.set_visible(True)

        rating = details.get('vote_average') or 0
        if rating > 0:
            self._rating_label.set_text(f'★ {rating:.1f}')

        release_date = details.get('release_date') or self._movie.get('release_date') or ''
        if release_date:
            self._year_label.set_text(str(release_date)[:4])

        directors = details.get('directors') or []
        if directors:
            self._director_label.set_text(f"Directed by {', '.join(directors)}")
            self._director_label.set_visible(True)

        runtime = details.get('runtime')
        if runtime:
            self._runtime_label.set_text(self._format_runtime_ends_at(runtime))

        genre_names = details.get('genre_names', [])
        if genre_names:
            while True:
                child = self._genres_box.get_first_child()
                if child is None:
                    break
                self._genres_box.remove(child)
            for gname in genre_names[:5]:
                lbl = Gtk.Label(label=gname)
                lbl.add_css_class('genre-pill')
                self._genres_box.append(lbl)

        # Render cast & recommendations
        self._render_cast(details.get('cast', []))
        self._render_recommendations(details.get('recommendations', []))

        # Check watch history for Resume button
        movie_id = details.get('id') or self._movie.get('id')
        if movie_id:
            progress = self._db.get_item_progress(movie_id)
            if progress and progress.get('progress_seconds', 0) > 15:
                pos = int(progress['progress_seconds'])
                mins = pos // 60
                secs = pos % 60
                self._resume_button.set_label(f"Resume ({mins}:{secs:02d})")
                self._resume_button.set_visible(True)
                self._resume_pos = pos
                self._resume_info_hash = progress.get('info_hash')
                self._resume_file_idx = progress.get('file_idx')

        self._load_images_async()

    def _on_tv_details_loaded(self, tv_details):
        self._detailed_media = tv_details
        self._movie.update(tv_details)
        self._tv_box.set_visible(True)

        overview = tv_details.get('overview') or self._movie.get('overview') or ''
        if overview:
            self._overview_label.set_text(overview)

        tagline = tv_details.get('tagline')
        if tagline:
            self._tagline_label.set_text(f'"{tagline}"')
            self._tagline_label.set_visible(True)

        rating = tv_details.get('vote_average', 0)
        if rating > 0:
            self._rating_label.set_text(f'★ {rating:.1f}')

        # Render cast & recommendations for TV too
        self._render_cast(tv_details.get('cast', []))
        self._render_recommendations(tv_details.get('recommendations', []))

        seasons = tv_details.get('seasons', [])
        # Filter out Season 0 (Specials) if preferred, or keep all
        valid_seasons = [s for s in seasons if s.get('season_number', 0) > 0]
        if not valid_seasons:
            valid_seasons = seasons

        season_labels = [f"Season {s.get('season_number')}" for s in valid_seasons]
        self._seasons_list = valid_seasons
        if season_labels:
            self._season_dropdown.set_model(Gtk.StringList.new(season_labels))
            self._season_dropdown.set_selected(0)
            # Automatically fetch episodes for the first season
            first_season = valid_seasons[0].get('season_number', 1)
            threading.Thread(
                target=self._fetch_season_worker,
                args=(self._movie.get('id'), first_season),
                daemon=True
            ).start()

        # Check resume button for TV show
        movie_id = tv_details.get('id') or self._movie.get('id')
        if movie_id:
            progress = self._db.get_item_progress(movie_id)
            if progress and progress.get('progress_seconds', 0) > 15:
                pos = int(progress['progress_seconds'])
                mins = pos // 60
                secs = pos % 60
                s = progress.get('season', 1)
                ep = progress.get('episode', 1)
                self._resume_button.set_label(f"Resume S{s}E{ep} ({mins}:{secs:02d})")
                self._resume_button.set_visible(True)
                self._resume_pos = pos
                self._resume_season = s
                self._resume_episode = ep
                self._resume_info_hash = progress.get('info_hash')
                self._resume_file_idx = progress.get('file_idx')

        self._load_images_async()

    def _on_season_changed(self, dropdown, pspec):
        sel = dropdown.get_selected()
        if hasattr(self, '_seasons_list') and sel < len(self._seasons_list):
            season_num = self._seasons_list[sel].get('season_number', 1)
            threading.Thread(
                target=self._fetch_season_worker,
                args=(self._movie.get('id'), season_num),
                daemon=True
            ).start()

    def _fetch_season_worker(self, tv_id, season_num):
        episodes = self._tmdb.get_tv_season(tv_id, season_num)
        GLib.idle_add(self._render_episodes, season_num, episodes)

    def _render_episodes(self, season_num, episodes):
        self._episodes_data = episodes
        while True:
            child = self._episodes_listbox.get_first_child()
            if child is None:
                break
            self._episodes_listbox.remove(child)

        if not episodes:
            empty_row = Adw.ActionRow()
            empty_row.set_title("No episodes found for this season")
            self._episodes_listbox.append(empty_row)
            return

        for ep in episodes:
            row = Adw.ActionRow()
            ep_num = ep.get('episode_number')
            ep_name = ep.get('name', f"Episode {ep_num}")
            runtime = ep.get('runtime')
            rating = ep.get('vote_average', 0)

            meta_parts = []
            if rating > 0:
                meta_parts.append(f"★ {rating:.1f}")
            if runtime:
                meta_parts.append(f"{runtime}m")
            meta_str = f" ({' • '.join(meta_parts)})" if meta_parts else ""

            row.set_title(f"{ep_num}. {ep_name}{meta_str}")
            overview = ep.get('overview', '')
            if overview:
                row.set_subtitle(overview)
            row.set_activatable(True)

            play_icon = Gtk.Image.new_from_icon_name('media-playback-start-symbolic')
            play_icon.set_tooltip_text(f"Play Episode {ep_num}")
            row.add_suffix(play_icon)
            row._episode_data = ep
            row._season_num = season_num
            self._episodes_listbox.append(row)

    def _on_episode_row_activated(self, listbox, row):
        ep = getattr(row, '_episode_data', None)
        season_num = getattr(row, '_season_num', 1)
        if ep:
            self._start_playback(season=season_num, episode=ep.get('episode_number'))

    def _on_play_clicked(self, button):
        self._start_playback(start_pos=0)

    def _on_resume_clicked(self, button):
        start_pos = getattr(self, '_resume_pos', 0)
        season = getattr(self, '_resume_season', None)
        episode = getattr(self, '_resume_episode', None)
        info_hash = getattr(self, '_resume_info_hash', None)
        file_idx = getattr(self, '_resume_file_idx', None)
        chosen_stream = None
        if info_hash:
            chosen_stream = {'infoHash': info_hash, 'fileIdx': file_idx}
        self._start_playback(season=season, episode=episode, start_pos=start_pos, chosen_stream=chosen_stream)

    def _start_playback(self, season=None, episode=None, start_pos=0, chosen_stream=None):
        selected = self._provider_dropdown.get_selected()
        pref_name = None
        if hasattr(self, '_provider_names') and 0 < selected < len(self._provider_names):
            pref_name = self._provider_names[selected]

        # Ensure id is always present
        if 'id' not in self._movie and 'tmdb_id' in self._movie:
            self._movie['id'] = self._movie['tmdb_id']

        # Default to S1E1 if TV series and no episode specified
        if self._media_type == 'tv' and season is None:
            season = 1
            episode = 1

        stream_data = {
            'movie': self._movie,
            'provider': pref_name,
            'media_type': self._media_type,
            'season': season,
            'episode': episode,
            'start_position': start_pos,
        }
        if chosen_stream:
            stream_data['chosen_stream'] = chosen_stream
            stream_data['provider'] = 'torrent'
        self.emit('play-movie', stream_data)

    def _on_select_stream_clicked(self, button):
        from showberry.ui.stream_dialogs import TorrentStreamChooserDialog
        window = self.get_root()
        season = None
        episode = None
        if self._media_type == 'tv':
            sel = self._episodes_listbox.get_selected_row() if hasattr(self, '_episodes_listbox') else None
            if sel and hasattr(sel, '_episode_data'):
                episode = sel._episode_data.get('episode_number')
                season = getattr(sel, '_season_num', 1)
            else:
                season = 1
                episode = 1

        dialog = TorrentStreamChooserDialog(
            parent_window=window,
            movie_data=self._movie,
            season=season,
            episode=episode,
            on_stream_selected=self._on_custom_stream_selected
        )
        dialog.present()

    def _on_custom_stream_selected(self, stream_info: Dict[str, Any]):
        """Stream a specific chosen torrent using background resolver pipeline."""
        info_hash = stream_info.get('infoHash')
        if not info_hash:
            return

        season = None
        episode = None
        if self._media_type == 'tv':
            sel = self._episodes_listbox.get_selected_row() if hasattr(self, '_episodes_listbox') else None
            if sel and hasattr(sel, '_episode_data'):
                episode = sel._episode_data.get('episode_number')
                season = getattr(sel, '_season_num', 1)
            else:
                season = 1
                episode = 1

        stream_data = {
            'movie': self._movie,
            'provider': 'torrent',
            'media_type': self._media_type,
            'season': season,
            'episode': episode,
            'start_position': 0,
            'chosen_stream': stream_info,
        }
        self.emit('play-movie', stream_data)

