"""Movie and TV show detail page with backdrop, info, season/episode browser, and playback options."""

import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, GObject, Pango

from kinema.services.tmdb import TMDBClient, genre_id_to_name
from kinema.services.image_cache import ImageCache
from kinema.services.database import DatabaseService
from kinema.providers import get_all_providers


class MoviePage(Adw.NavigationPage):
    """Media detail page with backdrop, poster, info, TV season/episode selector, and play button."""

    __gsignals__ = {
        'play-movie': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
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

        super().__init__(title=movie_title, tag='detail')

        self._tmdb = TMDBClient()
        self._db = DatabaseService()
        self._detailed_media = None
        self._episodes_data: List[Dict[str, Any]] = []

        self._setup_ui()
        # Pre-populate images immediately from card data (0ms — already cached from grid).
        # The network detail call (_load_details_async) may update them later if needed.
        self._load_images_async()
        self._load_details_async()


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
        header_bar.pack_end(self._watchlist_btn)

        # Scrollable content
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Backdrop image with overlay
        backdrop_overlay = Gtk.Overlay()
        self._backdrop = Gtk.Picture()
        self._backdrop.set_size_request(-1, 320)
        self._backdrop.set_content_fit(Gtk.ContentFit.COVER)
        self._backdrop.add_css_class('movie-backdrop')
        backdrop_overlay.set_child(self._backdrop)
        content.append(backdrop_overlay)

        # Info section
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        info_box.set_margin_start(24)
        info_box.set_margin_end(24)
        info_box.set_margin_top(16)
        info_box.set_margin_bottom(16)

        # Poster (strict 2:3 aspect ratio, never stretches vertically)
        self._poster = Gtk.Picture()
        self._poster.set_size_request(200, 300)
        self._poster.set_content_fit(Gtk.ContentFit.COVER)
        self._poster.set_can_shrink(True)
        self._poster.set_valign(Gtk.Align.START)
        self._poster.add_css_class('card-poster')
        info_box.append(self._poster)


        # Details
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        details.set_vexpand(True)
        details.set_valign(Gtk.Align.START)

        # Title
        self._title_label = Gtk.Label(label=self._movie.get('title', ''))
        self._title_label.add_css_class('title-1')
        self._title_label.set_xalign(0)
        self._title_label.set_wrap(True)
        details.append(self._title_label)

        # Tagline
        self._tagline_label = Gtk.Label()
        self._tagline_label.add_css_class('dim-label')
        self._tagline_label.add_css_class('italic')
        self._tagline_label.set_xalign(0)
        self._tagline_label.set_visible(False)
        details.append(self._tagline_label)

        # Rating, year, runtime
        meta_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        meta_box.set_margin_top(4)

        self._rating_label = Gtk.Label()
        self._rating_label.add_css_class('meta-rating')
        self._rating_label.add_css_class('title-4')
        meta_box.append(self._rating_label)

        self._year_label = Gtk.Label()
        self._year_label.add_css_class('dim-label')
        self._year_label.add_css_class('title-4')
        meta_box.append(self._year_label)

        self._runtime_label = Gtk.Label()
        self._runtime_label.add_css_class('dim-label')
        self._runtime_label.add_css_class('title-4')
        meta_box.append(self._runtime_label)

        details.append(meta_box)

        # Genres
        self._genres_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._genres_box.set_margin_top(6)
        details.append(self._genres_box)

        # Overview
        self._overview_label = Gtk.Label(label=self._movie.get('overview', ''))
        self._overview_label.set_xalign(0)
        self._overview_label.set_wrap(True)
        self._overview_label.set_max_width_chars(80)
        self._overview_label.set_margin_top(10)
        details.append(self._overview_label)

        info_box.append(details)
        content.append(info_box)

        # Play / Provider section
        play_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        play_box.set_margin_start(24)
        play_box.set_margin_end(24)
        play_box.set_margin_top(8)
        play_box.set_margin_bottom(16)

        # Provider selector
        provider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        provider_label = Gtk.Label(label='Provider:')
        provider_label.add_css_class('dim-label')
        provider_box.append(provider_label)

        self._provider_dropdown = Gtk.DropDown()
        self._provider_dropdown.set_size_request(200, -1)
        provider_box.append(self._provider_dropdown)
        play_box.append(provider_box)

        # Action buttons row (Play + Resume)
        actions_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        self._play_button = Gtk.Button(label='Play')
        self._play_button.add_css_class('suggested-action')
        self._play_button.add_css_class('pill')
        self._play_button.set_size_request(160, -1)
        self._play_button.connect('clicked', self._on_play_clicked)
        actions_row.append(self._play_button)

        # Resume button (if previously watched)
        self._resume_button = Gtk.Button(label='Resume')
        self._resume_button.add_css_class('pill')
        self._resume_button.set_visible(False)
        self._resume_button.connect('clicked', self._on_resume_clicked)
        actions_row.append(self._resume_button)

        play_box.append(actions_row)
        content.append(play_box)

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
        tv_header.append(self._season_dropdown)

        self._tv_box.append(tv_header)

        # Episode ListBox
        self._episodes_listbox = Gtk.ListBox()
        self._episodes_listbox.add_css_class('boxed-list')
        self._episodes_listbox.connect('row-activated', self._on_episode_row_activated)
        self._tv_box.append(self._episodes_listbox)

        content.append(self._tv_box)

        scroll.set_child(content)
        toolbar_view.set_content(scroll)
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

        self._load_images_async()
        self._setup_providers()

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
            if hasattr(window, 'show_toast'):
                window.show_toast("Added to Watchlist")
        self._update_watchlist_btn_state()

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
                tex = cache.get_image(backdrop_url, height=320)
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
        from kinema.services.settings import SettingsService
        api_key = SettingsService().tmdb_api_key
        if api_key:
            self._tmdb.set_api_key(api_key)

        if self._media_type == 'tv':
            tv_details = self._tmdb.get_tv_details(movie_id)
            if tv_details:
                GLib.idle_add(self._on_tv_details_loaded, tv_details)
        else:
            details = self._tmdb.get_movie_details(movie_id)
            credits = self._tmdb.get_movie_credits(movie_id)
            directors = credits.get('directors', []) if credits else []
            if details:
                GLib.idle_add(self._on_movie_details_loaded, details, directors)
            elif directors:
                GLib.idle_add(
                    self._year_label.set_text,
                    f"{self._year_label.get_text()} • Directed by {', '.join(directors)}"
                )

    def _on_movie_details_loaded(self, details, directors):
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
        year_str = str(release_date)[:4] if release_date else self._year_label.get_text()
        if directors:
            self._year_label.set_text(f"{year_str} • Directed by {', '.join(directors)}")
        elif year_str:
            self._year_label.set_text(year_str)

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
        self._start_playback(season=season, episode=episode, start_pos=start_pos)

    def _start_playback(self, season=None, episode=None, start_pos=0):
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
        self.emit('play-movie', stream_data)

