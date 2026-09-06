"""Movie card widget with Heartive-style hover play overlay, badges, runtime, and progress bar."""

import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Pango', '1.0')
from gi.repository import Gtk, Pango, GObject, GLib, Gdk

from kinema.services.image_cache import ImageCache
from kinema.services.database import DatabaseService

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
        'clicked-movie': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'play-movie':    (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'remove-item':   (GObject.SignalFlags.RUN_FIRST, None, (int,)),
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
        # Fixed width so cards don't stretch when window is resized
        self.set_size_request(196, -1)
        self.set_hexpand(False)
        self.set_halign(Gtk.Align.START)

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

        # ── Centered 48 px play circle (visible on hover) ─────────────────
        self._play_overlay = Gtk.Box()
        self._play_overlay.set_halign(Gtk.Align.CENTER)
        self._play_overlay.set_valign(Gtk.Align.CENTER)
        self._play_overlay.add_css_class('card-play-overlay')
        self._play_overlay.set_visible(False)

        play_icon = Gtk.Image.new_from_icon_name('media-playback-start-symbolic')
        play_icon.set_pixel_size(24)
        self._play_overlay.append(play_icon)
        poster_overlay.add_overlay(self._play_overlay)

        # Click on play circle → emit play-movie
        play_click = Gtk.GestureClick.new()
        play_click.set_button(Gdk.BUTTON_PRIMARY)
        play_click.connect('released', self._on_play_released)
        self._play_overlay.add_controller(play_click)

        # ── Badge (network / in theaters) ─────────────────────────────────
        badge_label = _get_badge_label(self._movie)
        if badge_label:
            badge = Gtk.Label(label=badge_label)
            badge.add_css_class('genre-pill')
            badge.add_css_class('card-badge')
            badge.set_halign(Gtk.Align.START)
            badge.set_valign(Gtk.Align.START)
            badge.set_margin_top(6)
            badge.set_margin_start(6)
            poster_overlay.add_overlay(badge)

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

        runtime_str = _format_runtime(self._movie.get('runtime'))
        if runtime_str:
            rt_label = Gtk.Label(label=runtime_str)
            rt_label.add_css_class('dim-label')
            rt_label.add_css_class('caption')
            meta_box.append(rt_label)

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

        # ── Load poster asynchronously ─────────────────────────────────────
        self._load_poster()

    # ── Interaction callbacks ──────────────────────────────────────────────

    def _on_hover_enter(self, controller, x, y):
        self._play_overlay.set_visible(True)

    def _on_hover_leave(self, controller):
        self._play_overlay.set_visible(False)

    def _on_body_released(self, gesture, n_press, x, y):
        """Card body click → navigate to detail page."""
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.emit('clicked-movie', self._movie)

    def _on_play_released(self, gesture, n_press, x, y):
        """Play circle click → start or resume stream directly."""
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._start_play()

    def _on_remove_released(self, gesture, n_press, x, y):
        """Delete button → remove from continue-watching."""
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

    # ── Image loading ──────────────────────────────────────────────────────

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
