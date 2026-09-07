"""Dialogs for selecting torrent streams and inspecting live stream buffer statistics."""

import logging
import threading
from typing import Any, Callable, Dict, List, Optional
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango

from kinema.providers.torrent import TorrentProvider
from kinema.services.torrent import get_torrent_streamer

logger = logging.getLogger(__name__)


class TorrentStreamChooserDialog(Adw.Window):
    """Modal dialog allowing the user to view and choose from all available torrent streams."""

    def __init__(
        self,
        parent_window: Gtk.Window,
        movie_data: Dict[str, Any],
        season: Optional[int] = None,
        episode: Optional[int] = None,
        on_stream_selected: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        super().__init__()
        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_default_size(680, 520)

        self._movie = movie_data
        self._season = season
        self._episode = episode
        self._on_stream_selected = on_stream_selected
        self._is_closed = False

        title = movie_data.get('title', 'Select Stream')
        if season is not None and episode is not None:
            self.set_title(f"Select Stream • {title} S{season}E{episode}")
        else:
            self.set_title(f"Select Stream • {title}")

        self._setup_ui()
        self._load_streams_async()

    def _setup_ui(self):
        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._content_box.set_margin_start(18)
        self._content_box.set_margin_end(18)
        self._content_box.set_margin_top(16)
        self._content_box.set_margin_bottom(18)

        # Loading view
        self._loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._loading_box.set_valign(Gtk.Align.CENTER)
        self._loading_box.set_vexpand(True)
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(36, 36)
        self._spinner.start()
        self._loading_box.append(self._spinner)

        loading_lbl = Gtk.Label(label="Searching torrent swarms (YTS, Torrentio, MediaFusion)...")
        loading_lbl.add_css_class('dim-label')
        self._loading_box.append(loading_lbl)
        self._content_box.append(self._loading_box)

        # Streams list inside ScrolledWindow
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_vexpand(True)
        self._scroll.set_visible(False)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(650)

        self._list_box = Gtk.ListBox()
        self._list_box.add_css_class('boxed-list')
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        clamp.set_child(self._list_box)
        self._scroll.set_child(clamp)
        self._content_box.append(self._scroll)

        # Empty state
        self._empty_label = Gtk.Label(label="No torrent streams found for this title.")
        self._empty_label.add_css_class('dim-label')
        self._empty_label.set_valign(Gtk.Align.CENTER)
        self._empty_label.set_vexpand(True)
        self._empty_label.set_visible(False)
        self._content_box.append(self._empty_label)

        toolbar_view.set_content(self._content_box)
        self.set_content(toolbar_view)

    def _load_streams_async(self):
        tmdb_id = self._movie.get('id') or self._movie.get('tmdb_id')
        if not tmdb_id:
            self._loading_box.set_visible(False)
            self._empty_label.set_visible(True)
            return

        def _bg():
            tp = TorrentProvider()
            streams = tp.fetch_stream_choices(
                tmdb_id=int(tmdb_id),
                season=self._season,
                episode=self._episode
            )
            if not self._is_closed:
                GLib.idle_add(self._display_streams, streams)

        threading.Thread(target=_bg, daemon=True).start()

    def _display_streams(self, streams: List[Dict[str, Any]]):
        self._spinner.stop()
        self._loading_box.set_visible(False)

        if not streams:
            self._empty_label.set_visible(True)
            return

        self._scroll.set_visible(True)

        for s in streams:
            row = Adw.ActionRow()
            title = s.get('title', 'Torrent Stream')
            clean_title = title.split('\n')[0].strip()
            row.set_title(clean_title)
            row.set_subtitle(s.get('name') or s.get('provider') or 'Torrent')
            row.set_title_lines(1)
            row.set_subtitle_lines(1)

            # Suffix badges
            suffixes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            suffixes.set_valign(Gtk.Align.CENTER)

            # Quality badge
            q = s.get('quality', '1080p')
            q_badge = Gtk.Label(label=q)
            q_badge.add_css_class('badge')
            suffixes.append(q_badge)

            # Size badge
            size_gb = s.get('size_gb')
            if size_gb:
                s_badge = Gtk.Label(label=f"{size_gb:.1f} GB")
                s_badge.add_css_class('badge')
                s_badge.add_css_class('dim-label')
                suffixes.append(s_badge)

            # Seeds badge
            seeds = s.get('seeds')
            if seeds is not None:
                seeds_badge = Gtk.Label(label=f"👤 {seeds}")
                seeds_badge.add_css_class('badge')
                suffixes.append(seeds_badge)

            # Play action button
            play_btn = Gtk.Button.new_from_icon_name('media-playback-start-symbolic')
            play_btn.add_css_class('flat')
            play_btn.set_tooltip_text("Stream this torrent")
            play_btn.connect('clicked', self._on_row_play, s)
            suffixes.append(play_btn)

            row.add_suffix(suffixes)
            row.set_activatable(True)
            row.connect('activated', self._on_row_play, s)
            self._list_box.append(row)

    def _on_row_play(self, widget, stream_info):
        self._is_closed = True
        self.close()
        if self._on_stream_selected:
            self._on_stream_selected(stream_info)


class StreamDetailsDialog(Adw.Window):
    """Modal dialog displaying live buffer, download rate, and swarm health."""

    def __init__(self, parent_window: Gtk.Window, player_page):
        super().__init__()
        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_default_size(480, 420)
        self.set_title("Stream & Buffer Details")

        self._player_page = player_page
        self._timer_id = None

        self._setup_ui()
        self.connect('close-request', self._on_close_request)

        # Start live monitoring timer (every 500ms)
        self._update_stats()
        self._timer_id = GLib.timeout_add(500, self._update_stats)

    def _setup_ui(self):
        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(460)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        clamp.set_margin_top(16)
        clamp.set_margin_bottom(16)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)

        # Status group
        group = Adw.PreferencesGroup()
        group.set_title("Playback & Buffer Health")

        # Row 1: Source
        self._source_row = Adw.ActionRow()
        self._source_row.set_title("Source")
        self._source_val = Gtk.Label(label="Initializing...")
        self._source_val.add_css_class('dim-label')
        self._source_row.add_suffix(self._source_val)
        group.add(self._source_row)

        # Row 2: File Name
        self._file_row = Adw.ActionRow()
        self._file_row.set_title("Media File")
        self._file_val = Gtk.Label(label="—")
        self._file_val.add_css_class('dim-label')
        self._file_val.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._file_val.set_max_width_chars(28)
        self._file_row.add_suffix(self._file_val)
        group.add(self._file_row)

        # Row 3: Buffer & Download Progress
        self._progress_row = Adw.ActionRow()
        self._progress_row.set_title("Buffer & Download")
        p_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        p_box.set_valign(Gtk.Align.CENTER)
        self._progress_val = Gtk.Label(label="0%")
        self._progress_val.set_xalign(1)
        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.set_size_request(140, 8)
        p_box.append(self._progress_val)
        p_box.append(self._progress_bar)
        self._progress_row.add_suffix(p_box)
        group.add(self._progress_row)

        # Row 4: Network Speed
        self._speed_row = Adw.ActionRow()
        self._speed_row.set_title("Transfer Speed")
        self._speed_val = Gtk.Label(label="—")
        self._speed_val.add_css_class('dim-label')
        self._speed_row.add_suffix(self._speed_val)
        group.add(self._speed_row)

        # Row 5: Swarm Peers & Seeds
        self._swarm_row = Adw.ActionRow()
        self._swarm_row.set_title("Swarm Health")
        self._swarm_val = Gtk.Label(label="—")
        self._swarm_val.add_css_class('dim-label')
        self._swarm_row.add_suffix(self._swarm_val)
        group.add(self._swarm_row)

        # Row 6: Playback Cache
        self._cache_row = Adw.ActionRow()
        self._cache_row.set_title("Player Cache Ahead")
        self._cache_val = Gtk.Label(label="0.0s")
        self._cache_val.add_css_class('dim-label')
        self._cache_row.add_suffix(self._cache_val)
        group.add(self._cache_row)

        vbox.append(group)
        clamp.set_child(vbox)
        toolbar_view.set_content(clamp)
        self.set_content(toolbar_view)

    def _update_stats(self) -> bool:
        """Query MPV and TorrentStreamer to update status labels."""
        stream_data = getattr(self._player_page, '_stream_data', {}) or {}
        provider = stream_data.get('provider') or 'Auto'
        movie = stream_data.get('movie', {})
        self._source_val.set_text(f"{provider.capitalize()} Stream")

        streamer = get_torrent_streamer()
        is_torrent = streamer and streamer.is_running

        if is_torrent:
            st = streamer.get_status()
            progress = st.get('progress', 0.0)
            self._progress_bar.set_fraction(progress)

            total_done = st.get('total_done', 0)
            total_size = st.get('video_file_size', 0)
            done_mb = total_done / (1024 * 1024)
            size_mb = total_size / (1024 * 1024)
            if size_mb > 0:
                self._progress_val.set_text(f"{done_mb:.1f} / {size_mb:.1f} MB ({progress * 100:.1f}%)")
            else:
                self._progress_val.set_text(f"{progress * 100:.1f}%")

            down_rate = st.get('download_rate', 0) / (1024 * 1024)
            up_rate = st.get('upload_rate', 0) / (1024 * 1024)
            self._speed_val.set_text(f"⬇ {down_rate:.2f} MB/s  •  ⬆ {up_rate:.2f} MB/s")

            seeds = st.get('seeds', 0)
            peers = st.get('peers', 0)
            self._swarm_val.set_text(f"👤 {seeds} seeds, {peers} peers")

            fname = st.get('video_file_name') or movie.get('title', 'Video')
            self._file_val.set_text(fname)
        else:
            self._speed_row.set_visible(False)
            self._swarm_row.set_visible(False)
            self._file_val.set_text(movie.get('title', 'HTTP Stream'))
            self._progress_val.set_text("Direct Stream")
            self._progress_bar.set_fraction(1.0)

        # Query player cache from MPV
        mpv_w = getattr(self._player_page, '_mpv_widget', None)
        if mpv_w and mpv_w._mpv:
            try:
                cache_sec = mpv_w._mpv.demuxer_cache_duration or 0.0
                self._cache_val.set_text(f"+{cache_sec:.1f}s buffered")
            except Exception:
                self._cache_val.set_text("—")

        return True

    def _on_close_request(self, *_):
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        return False
