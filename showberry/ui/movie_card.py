"""Movie card widget with Heartive-style hover play overlay, badges, runtime, and progress bar."""

import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Pango', '1.0')
from gi.repository import Gtk, Pango, GObject, GLib, Gdk

from showberry.services.image_cache import ImageCache
from showberry.services.database import DatabaseService

logger = logging.getLogger(__name__)

# Heartive-style known streaming network badge labels
_NETWORK_BADGE_MAP = {
    'netflix': 'NETFLIX',
    'hbo': 'HBO',
    'hbo max': 'HBO MAX',
    'max': 'MAX',
    'amazon': 'PRIME VIDEO',
    'prime video': 'PRIME VIDEO',
    'amazon prime': 'PRIME VIDEO',
    'amazon prime video': 'PRIME VIDEO',
    'disney': 'DISNEY+',
    'disney+': 'DISNEY+',
    'apple': 'APPLE TV+',
    'apple tv+': 'APPLE TV+',
    'apple tv': 'APPLE TV+',
    'hulu': 'HULU',
    'peacock': 'PEACOCK',
    'paramount': 'PARAMOUNT+',
    'paramount+': 'PARAMOUNT+',
    'crunchyroll': 'CRUNCHYROLL',
    'funimation': 'FUNIMATION',
    'tokyo mx': 'TOKYO MX',
    'tv tokyo': 'TV TOKYO',
    'nhk': 'NHK',
    'fuji tv': 'FUJI TV',
    'tbs': 'TBS',
    'abc': 'ABC',
    'nbc': 'NBC',
    'cbs': 'CBS',
    'fox': 'FOX',
    'showtime': 'SHOWTIME',
    'fx': 'FX',
    'amc': 'AMC',
    'starz': 'STARZ',
    'bbc': 'BBC',
    'bbc one': 'BBC',
    'bbc two': 'BBC',
    'channel 4': 'CHANNEL 4',
    'itv': 'ITV',
}


def _get_badge_label(movie_data: Dict[str, Any]) -> Optional[str]:
    """Return a Heartive-style badge string or None."""
    media_type = movie_data.get('media_type', 'movie')

    if media_type == 'tv':
        network = (movie_data.get('network') or '').lower().strip()
        if network:
            mapped = _NETWORK_BADGE_MAP.get(network)
            if mapped:
                return mapped
            # Unknown network — show raw name, up to 14 chars
            return network.upper()[:14]
        return None

    # Movie: check release date for "IN THEATERS"
    release_str = movie_data.get('release_date') or ''
    if release_str:
        try:
            rel_date = datetime.strptime(release_str[:10], '%Y-%m-%d')
            days_ago = (datetime.now() - rel_date).days
            if 0 <= days_ago <= 60:
                return 'IN THEATERS'
        except ValueError:
            pass
    return None


def _format_runtime(minutes: Optional[int]) -> str:
    """Format runtime minutes → '2h 19m' or '45m'."""
    if not minutes or minutes <= 0:
        return ''
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f'{hours}h {mins}m' if mins else f'{hours}h'
    return f'{mins}m'


class MovieCard(Gtk.Box):
    """A card displaying movie poster, title, Heartive hover play circle, badges, runtime, and progress.

    Signals:
      clicked-movie(movie_data)  – card body clicked → open detail page
      play-movie(stream_data)    – play button clicked → start / resume stream directly
      remove-item(tmdb_id)       – delete button clicked → remove from continue-watching
    """

    __gsignals__ = {
        'clicked-movie':    (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'play-movie':       (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'remove-item':      (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'navigate-grid':    (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'toggle-watchlist': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, movie_data: Dict[str, Any], show_remove_button: bool = False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._movie = dict(movie_data)
        self._show_remove_button = show_remove_button
        self._db = DatabaseService()

        self.add_css_class('movie-card')
        self.set_margin_top(4)
        self.set_margin_bottom(6)
        self.set_margin_start(4)
        self.set_margin_end(4)
        # Fixed card width so cards never stretch horizontally
        self.set_size_request(196, -1)
        self.set_hexpand(False)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.START)
        self.set_focusable(True)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.set_margin_top(4)
        inner.set_margin_bottom(6)
        inner.set_margin_start(4)
        inner.set_margin_end(4)

        # ── Poster with overlay ────────────────────────────────────────────
        poster_overlay = Gtk.Overlay()

        self._poster = Gtk.Picture()
        self._poster.set_size_request(180, 270)
        self._poster.add_css_class('card-poster')
        self._poster.set_content_fit(Gtk.ContentFit.COVER)
        poster_overlay.set_child(self._poster)

        # ── Centered 64 px play circle (visible on hover) ─────────────────
        self._play_overlay = Gtk.Box()
        self._play_overlay.set_size_request(64, 64)
        self._play_overlay.set_halign(Gtk.Align.CENTER)
        self._play_overlay.set_valign(Gtk.Align.CENTER)
        self._play_overlay.add_css_class('card-play-overlay')
        self._play_overlay.set_visible(False)

        play_icon = Gtk.Image.new_from_icon_name('media-playback-start-symbolic')
        play_icon.set_pixel_size(34)
        play_icon.set_halign(Gtk.Align.CENTER)
        play_icon.set_valign(Gtk.Align.CENTER)
        play_icon.set_hexpand(True)
        play_icon.set_vexpand(True)
        # Optical centering offset for right-pointing triangle
        play_icon.set_margin_start(3)
        self._play_overlay.append(play_icon)
        poster_overlay.add_overlay(self._play_overlay)

        # Click on play circle → emit play-movie
        play_click = Gtk.GestureClick.new()
        play_click.set_button(Gdk.BUTTON_PRIMARY)
        play_click.connect('released', self._on_play_released)
        self._play_overlay.add_controller(play_click)

        # ── Badge (network / in theaters) ─────────────────────────────────
        self._badge = Gtk.Label()
        self._badge.add_css_class('genre-pill')
        self._badge.add_css_class('card-badge')
        self._badge.set_halign(Gtk.Align.START)
        self._badge.set_valign(Gtk.Align.START)
        self._badge.set_margin_top(6)
        self._badge.set_margin_start(6)
        badge_label = _get_badge_label(self._movie)
        if badge_label:
            self._badge.set_text(badge_label)
            self._badge.set_visible(True)
        else:
            self._badge.set_visible(False)
        poster_overlay.add_overlay(self._badge)

        # ── Delete button (top-right, only for continue-watching) ──────────
        if show_remove_button:
            remove_overlay = Gtk.Box()
            remove_overlay.set_halign(Gtk.Align.END)
            remove_overlay.set_valign(Gtk.Align.START)
            remove_overlay.set_margin_top(6)
            remove_overlay.set_margin_end(6)
            remove_overlay.add_css_class('card-remove-button')

            remove_icon = Gtk.Image.new_from_icon_name('window-close-symbolic')
            remove_icon.set_pixel_size(14)
            remove_overlay.append(remove_icon)
            poster_overlay.add_overlay(remove_overlay)

            remove_click = Gtk.GestureClick.new()
            remove_click.set_button(Gdk.BUTTON_PRIMARY)
            remove_click.connect('released', self._on_remove_released)
            remove_overlay.add_controller(remove_click)

        # ── Progress bar for Continue Watching ────────────────────────────
        progress_secs = self._movie.get('progress_seconds', 0)
        dur_secs = self._movie.get('duration_seconds', 0)
        if dur_secs > 0 and progress_secs > 10:
            fraction = min(1.0, float(progress_secs) / float(dur_secs))
            pbar = Gtk.ProgressBar()
            pbar.set_fraction(fraction)
            pbar.set_valign(Gtk.Align.END)
            pbar.set_margin_bottom(4)
            pbar.set_margin_start(6)
            pbar.set_margin_end(6)
            poster_overlay.add_overlay(pbar)

        inner.append(poster_overlay)

        # ── Title ──────────────────────────────────────────────────────────
        title_str = self._movie.get('title') or self._movie.get('name') or 'Unknown'
        title = Gtk.Label(label=title_str)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(20)
        title.set_xalign(0)
        title.add_css_class('caption')
        title.add_css_class('heading')
        inner.append(title)

        # ── Meta row: rating · year · runtime ─────────────────────────────
        meta_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        rating = self._movie.get('vote_average', 0)
        if rating and rating > 0:
            rating_label = Gtk.Label(label=f'★ {rating:.1f}')
            rating_label.set_xalign(0)
            rating_label.add_css_class('meta-rating')
            rating_label.add_css_class('caption')
            meta_box.append(rating_label)

        rel_date = self._movie.get('release_date') or self._movie.get('first_air_date') or ''
        if rel_date:
            year_label = Gtk.Label(label=str(rel_date)[:4])
            year_label.add_css_class('dim-label')
            year_label.add_css_class('caption')
            meta_box.append(year_label)

        self._runtime_label = Gtk.Label()
        self._runtime_label.add_css_class('dim-label')
        self._runtime_label.add_css_class('caption')
        runtime_str = _format_runtime(self._movie.get('runtime'))
        if not runtime_str and self._movie.get('media_type') == 'tv':
            seasons = self._movie.get('number_of_seasons')
            if seasons:
                runtime_str = f"{seasons} Season{'s' if seasons != 1 else ''}"
        if runtime_str:
            self._runtime_label.set_text(runtime_str)
            self._runtime_label.set_visible(True)
        else:
            self._runtime_label.set_visible(False)
        meta_box.append(self._runtime_label)

        inner.append(meta_box)
        self.append(inner)

        # ── Click on card body → open detail page ─────────────────────────
        body_click = Gtk.GestureClick.new()
        body_click.set_button(Gdk.BUTTON_PRIMARY)
        body_click.connect('released', self._on_body_released)
        self.add_controller(body_click)

        # ── Hover controller → reveal play circle ─────────────────────────
        motion = Gtk.EventControllerMotion.new()
        motion.connect('enter', self._on_hover_enter)
        motion.connect('leave', self._on_hover_leave)
        self.add_controller(motion)

        # ── Focus controller → reveal play circle when focused ────────────
        focus_controller = Gtk.EventControllerFocus.new()
        focus_controller.connect('enter', self._on_focus_enter)
        focus_controller.connect('leave', self._on_focus_leave)
        self.add_controller(focus_controller)

        # ── Key controller → keyboard navigation & activation ─────────────
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect('key-pressed', self._on_key_pressed)
        self.add_controller(key_controller)

        # ── Load poster and enrich metadata asynchronously ────────────────
        self._load_card_data()

    # ── Interaction callbacks ──────────────────────────────────────────────

    def _on_hover_enter(self, controller, x, y):
        self._play_overlay.set_visible(True)

    def _on_hover_leave(self, controller):
        if not self.is_focus():
            self._play_overlay.set_visible(False)

    def _on_focus_enter(self, controller):
        self._play_overlay.set_visible(True)

    def _on_focus_leave(self, controller):
        self._play_overlay.set_visible(False)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.emit('clicked-movie', self._movie)
            return True
        elif keyval in (Gdk.KEY_space, Gdk.KEY_p, Gdk.KEY_P):
            self._start_play()
            return True
        elif keyval in (Gdk.KEY_w, Gdk.KEY_W):
            self._toggle_watchlist()
            return True
        elif keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace, Gdk.KEY_r, Gdk.KEY_R) and self._show_remove_button:
            self._on_remove_released(None, 1, 0, 0)
            return True
        elif keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            self.emit('navigate-grid', 'up')
            return True
        elif keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            self.emit('navigate-grid', 'down')
            return True
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            self.emit('navigate-grid', 'left')
            return True
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            self.emit('navigate-grid', 'right')
            return True
        return False

    def _toggle_watchlist(self):
        mid = self._movie.get('id') or self._movie.get('tmdb_id')
        if not mid:
            return
        if self._db.is_in_watchlist(mid):
            self._db.remove_from_watchlist(mid)
            added = False
        else:
            self._db.add_to_watchlist(
                tmdb_id=mid,
                title=self._movie.get('title') or self._movie.get('name') or 'Unknown',
                media_type=self._movie.get('media_type', 'movie'),
                poster_url=self._movie.get('poster_path') or self._movie.get('poster_url'),
                release_date=self._movie.get('release_date') or self._movie.get('first_air_date'),
                vote_average=float(self._movie.get('vote_average') or 0.0),
                overview=self._movie.get('overview'),
                backdrop_url=self._movie.get('backdrop_path') or self._movie.get('backdrop_url'),
            )
            added = True
        self.emit('toggle-watchlist', (self._movie, added))

    def _on_body_released(self, gesture, n_press, x, y):
        """Card body click → navigate to detail page."""
        if gesture:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.grab_focus()
        self.emit('clicked-movie', self._movie)

    def _on_play_released(self, gesture, n_press, x, y):
        """Play circle click → start or resume stream directly."""
        if gesture:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._start_play()

    def _on_remove_released(self, gesture, n_press, x, y):
        """Delete button → remove from continue-watching."""
        if gesture:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        tmdb_id = self._movie.get('id') or self._movie.get('tmdb_id')
        if tmdb_id:
            self.emit('remove-item', int(tmdb_id))

    def _start_play(self):
        """Determine start position from watch history, then emit play-movie."""
        tmdb_id = self._movie.get('id') or self._movie.get('tmdb_id')
        start_pos = 0
        season = None
        episode = None
        media_type = self._movie.get('media_type', 'movie')

        if tmdb_id:
            try:
                progress = self._db.get_item_progress(int(tmdb_id))
                if progress and progress.get('progress_seconds', 0) > 15:
                    start_pos = int(progress['progress_seconds'])
                    season = progress.get('season')
                    episode = progress.get('episode')
            except Exception as e:
                logger.warning(f"Could not fetch watch progress: {e}")

        # Default TV to S1E1 if no history
        if media_type == 'tv' and season is None:
            season = 1
            episode = 1

        movie_data = dict(self._movie)
        if 'id' not in movie_data and 'tmdb_id' in movie_data:
            movie_data['id'] = movie_data['tmdb_id']

        stream_data = {
            'movie': movie_data,
            'provider': None,
            'media_type': media_type,
            'season': season,
            'episode': episode,
            'start_position': start_pos,
        }
        self.emit('play-movie', stream_data)

    # ── Asynchronous Data & Image Loading ──────────────────────────────────

    def _load_card_data(self):
        """Load poster and enrich missing metadata (runtime, TV network) asynchronously."""
        self._load_poster()

        tmdb_id = self._movie.get('id') or self._movie.get('tmdb_id')
        if not tmdb_id:
            return

        media_type = self._movie.get('media_type', 'movie')
        needs_tv_network = (media_type == 'tv' and not self._movie.get('network'))
        needs_runtime = (not self._movie.get('runtime'))

        if not needs_tv_network and not needs_runtime:
            return

        def enrich_worker():
            try:
                from showberry.services.tmdb import TMDBClient
                client = TMDBClient()
                if media_type == 'tv':
                    details = client.get_tv_details(int(tmdb_id))
                    if details:
                        if details.get('network'):
                            self._movie['network'] = details['network']
                        if details.get('runtime'):
                            self._movie['runtime'] = details['runtime']
                        if details.get('number_of_seasons'):
                            self._movie['number_of_seasons'] = details['number_of_seasons']
                else:
                    details = client.get_movie_details(int(tmdb_id))
                    if details:
                        if details.get('runtime'):
                            self._movie['runtime'] = details['runtime']
                        if details.get('release_date'):
                            self._movie['release_date'] = details['release_date']

                GLib.idle_add(self._update_enriched_ui)
            except Exception as e:
                logger.debug(f"Failed to enrich card metadata for TMDB {tmdb_id}: {e}")

        threading.Thread(target=enrich_worker, daemon=True).start()

    def _update_enriched_ui(self):
        # Update badge (network or in theaters)
        badge_label = _get_badge_label(self._movie)
        if badge_label:
            self._badge.set_text(badge_label)
            self._badge.set_visible(True)

        # Update runtime or TV seasons
        rt_str = _format_runtime(self._movie.get('runtime'))
        if not rt_str and self._movie.get('media_type') == 'tv':
            seasons = self._movie.get('number_of_seasons')
            if seasons:
                rt_str = f"{seasons} Season{'s' if seasons != 1 else ''}"
        if rt_str:
            self._runtime_label.set_text(rt_str)
            self._runtime_label.set_visible(True)
        return False

    def _load_poster(self):
        """Load poster image in background thread to prevent UI hitching."""
        poster_url = (
            self._movie.get('poster_url_small')
            or self._movie.get('poster_url')
            or self._movie.get('poster_path')
        )
        if not poster_url:
            return
        if not poster_url.startswith('http'):
            poster_url = f"https://image.tmdb.org/t/p/w342{poster_url}"

        def worker():
            cache = ImageCache()
            texture = cache.get_image(poster_url, width=180, height=270)
            if texture:
                GLib.idle_add(self._poster.set_paintable, texture)

        threading.Thread(target=worker, daemon=True).start()
