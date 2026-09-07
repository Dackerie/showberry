"""Player page - MPV video player with controls, subtitle sync, and progress tracking."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, GObject, Gdk, Pango

import locale
locale.setlocale(locale.LC_NUMERIC, 'C')

import logging
import threading
from typing import Optional, List, Dict, Any

import mpv
from mpv import MPV, MpvGlGetProcAddressFn, MpvRenderContext

try:
    from OpenGL import GL
    HAS_OPENGL = True
except ImportError:
    HAS_OPENGL = False

from kinema.providers.base import StreamResult, ProviderManager
from kinema.services.database import DatabaseService
from kinema.services.subtitles import SubtitleService
from kinema.services.tmdb import TMDBClient
from kinema.services.torrent import get_torrent_streamer

logger = logging.getLogger(__name__)


def get_proc_address_wrapper():
    """Get OpenGL proc address for MPV using direct ctypes bindings for EGL and GLX."""
    import ctypes
    egl_get_proc = None
    gl_get_proc = None
    gl_lib = None

    try:
        egl = ctypes.CDLL('libEGL.so.1')
        egl_get_proc = egl.eglGetProcAddress
        egl_get_proc.restype = ctypes.c_void_p
        egl_get_proc.argtypes = [ctypes.c_char_p]
    except Exception:
        pass

    try:
        gl_lib = ctypes.CDLL('libGL.so.1')
        gl_get_proc = getattr(gl_lib, 'glXGetProcAddressARB', getattr(gl_lib, 'glXGetProcAddress', None))
        if gl_get_proc:
            gl_get_proc.restype = ctypes.c_void_p
            gl_get_proc.argtypes = [ctypes.c_char_p]
    except Exception:
        pass

    def get_proc_address(*args):
        # libmpv passes (ctx, name)
        name = args[-1]
        if not isinstance(name, bytes):
            name = name.encode('utf-8')
        res = None
        if egl_get_proc:
            res = egl_get_proc(name)
        if not res and gl_get_proc:
            res = gl_get_proc(name)
        if not res and gl_lib:
            try:
                res = ctypes.cast(getattr(gl_lib, name.decode('utf-8')), ctypes.c_void_p).value
            except Exception:
                pass
        return res or 0

    return get_proc_address


class MpvWidget(Gtk.GLArea):
    """GTK4 GLArea widget that renders MPV video."""

    __gsignals__ = {
        'stream-ready': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, **properties):
        super().__init__(**properties)
        self.set_auto_render(False)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.connect('realize', self._on_realize)
        self.connect('unrealize', self._on_unrealize)
        self.connect('resize', self._on_resize)
        self.connect('render', self._on_render)

        self._mpv = MPV(
            vo='libmpv',
            keep_open='yes',
            hwdec='auto-safe',
            input_default_bindings=False,
            cursor_autohide=1000,
            cache='yes',
            demuxer_max_bytes=150 * 1024 * 1024,
            demuxer_max_back_bytes=50 * 1024 * 1024,
            demuxer_readahead_secs=120,
            cache_secs=120,
            network_timeout=15,
        )
        self._ctx = None
        self._gl_context_ref = None
        self._redraw_pending = False
        self._pending_subtitles = []
        self._wait_first_frame = False  # set True while A/V sync wait is active
        self._is_active = True
        self._has_drawn_first_frame = False

    def activate(self):
        """Re-enable rendering and event handling."""
        self._is_active = True

    def deactivate(self):
        """Immediately stop playback and disable render callbacks to prevent deadlocks."""
        self._is_active = False
        try:
            if self._ctx:
                self._ctx.update_cb = None
        except Exception:
            pass
        try:
            self.pause()
            self.stop()
        except Exception:
            pass

    def _on_realize(self, *_):
        self.make_current()
        curr_gdk_ctx = self.get_context()

        # If the underlying GdkGLContext was recreated (e.g. across navigation pops and pushes),
        # the previous MpvRenderContext is bound to a destroyed OpenGL context and cannot render.
        # Safely free it while the new OpenGL context is current before creating a fresh one.
        if self._ctx and self._gl_context_ref != curr_gdk_ctx:
            logger.info("GL context changed across realize cycles; recreating MPV render context")
            try:
                self._ctx.free()
            except Exception as e:
                logger.warning(f"Error freeing stale MPV render context: {e}")
            self._ctx = None

        self._gl_context_ref = curr_gdk_ctx

        if self._ctx:
            self._ctx.update_cb = self._on_mpv_callback
            return

        try:
            self._ctx = MpvRenderContext(
                self._mpv,
                'opengl',
                opengl_init_params={
                    'get_proc_address': MpvGlGetProcAddressFn(get_proc_address_wrapper())
                }
            )
            self._ctx.update_cb = self._on_mpv_callback
            logger.info("Successfully initialized MPV OpenGL render context")
        except Exception as e:
            logger.error(f"Failed to create MPV render context: {e}")

    def _on_unrealize(self, *_):
        # Do NOT free MpvRenderContext here during tear down; it will be cleanly
        # freed and recreated on the next _on_realize() with the active context.
        self._is_active = False
        try:
            if self._ctx:
                self._ctx.update_cb = None
        except Exception:
            pass

    def _on_mpv_callback(self):
        try:
            if not getattr(self, '_is_active', False):
                return
            if not getattr(self, '_redraw_pending', False):
                self._redraw_pending = True
                GLib.idle_add(self._trigger_redraw)
        except Exception:
            pass

    def _trigger_redraw(self, *_):
        self._redraw_pending = False
        if not self._is_active:
            return False
        if self._ctx and self._ctx.update():
            self.queue_render()
        return False

    def _on_render(self, area, gl_context):
        return self.do_render(gl_context)

    def do_render(self, *_):
        if not self._is_active or not self._ctx:
            return False

        factor = self.get_scale_factor()
        width = int(self.get_width() * factor)
        height = int(self.get_height() * factor)
        if width <= 0 or height <= 0:
            return False

        # Ensure Gtk.GLArea context is current
        try:
            self.make_current()
        except Exception:
            pass

        # Clear any residual OpenGL error flags from context switching
        try:
            while GL.glGetError() != GL.GL_NO_ERROR:
                pass
        except Exception:
            pass

        # Query current FBO with safe fallback
        try:
            fbo = GL.glGetIntegerv(GL.GL_DRAW_FRAMEBUFFER_BINDING)
        except Exception:
            fbo = 0

        # Render MPV frame
        try:
            self._ctx.render(
                flip_y=True,
                opengl_fbo={'w': width, 'h': height, 'fbo': fbo},
                block_for_target_time=False,
            )
        except Exception:
            return False

        # Clear any error state left by libmpv
        try:
            while GL.glGetError() != GL.GL_NO_ERROR:
                pass
        except Exception:
            pass

        if not self._has_drawn_first_frame:
            self._has_drawn_first_frame = True
            GLib.idle_add(self.emit, 'stream-ready')

        # Audio/video sync: unpause on the very first rendered frame so audio
        # never runs ahead of visible video frames.
        if self._wait_first_frame:
            self._wait_first_frame = False
            try:
                self._mpv.pause = False
            except Exception:
                pass

        return True


    def _on_resize(self, widget, width, height):
        if self._ctx:
            self._ctx.update()

    def play(self, url, referer=None, origin=None, headers=None, subtitles=None, start_pos=0):
        """Play a video URL with custom referer/origin headers and subtitles."""
        if referer:
            try:
                self._mpv['referrer'] = referer
            except Exception:
                pass

        ua = None
        if headers:
            ua = headers.get('User-Agent') or headers.get('user-agent')
        if not ua:
            ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        try:
            self._mpv['user-agent'] = ua
        except Exception:
            pass

        header_list = []
        if origin:
            header_list.append(f'Origin: {origin}')
        if headers:
            for k, v in headers.items():
                if k.lower() not in ('user-agent', 'referer'):
                    header_list.append(f'{k}: {v}')
        if header_list:
            try:
                self._mpv['http-header-fields'] = ','.join(header_list)
            except Exception:
                pass

        if start_pos and start_pos > 5:
            try:
                self._mpv['start'] = f"+{int(start_pos)}"
            except Exception:
                pass
        else:
            try:
                self._mpv['start'] = 'none'
            except Exception:
                pass

        self._is_active = True
        try:
            if self._ctx:
                self._ctx.update_cb = self._on_mpv_callback
        except Exception:
            pass
        self._has_drawn_first_frame = False
        self._wait_first_frame = True
        try:
            self._mpv.pause = True
        except Exception:
            pass
        self._mpv.play(url)

        self._pending_subtitles = list(subtitles or [])
        if self._pending_subtitles:
            GLib.timeout_add(1000, self._apply_pending_subtitles)


    def _apply_pending_subtitles(self):
        subs = list(self._pending_subtitles)
        self._pending_subtitles.clear()
        for sub in subs:
            sub_url = sub.get('url')
            if sub_url:
                self.add_subtitle(
                    sub_url,
                    label=sub.get('label', 'Subtitle'),
                    lang=sub.get('lang', 'eng'),
                    referer=sub.get('referer'),
                    headers=sub.get('headers')
                )
        return False

    def add_subtitle(
        self,
        url_or_path: str,
        label: str = 'Subtitle',
        lang: str = 'eng',
        referer: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None
    ):
        """Add external subtitle to playback (only when MPV has a file loaded).
        If url_or_path is a remote HTTP URL, downloads it to local cache in a thread first
        so MPV's demuxer never blocks on remote sockets during playback.
        """
        try:
            if not self._mpv or not self._mpv.filename:
                return
            if url_or_path.startswith(('http://', 'https://')):
                def _bg_dl():
                    try:
                        local_path = SubtitleService().download_subtitle(
                            url_or_path,
                            filename_hint=label,
                            headers=headers,
                            referer=referer
                        )
                        if local_path and self._mpv and self._mpv.filename:
                            GLib.idle_add(self._add_local_subtitle, local_path, label, lang)
                    except Exception as err:
                        logger.warning(f"Failed downloading subtitle from {url_or_path}: {err}")
                threading.Thread(target=_bg_dl, daemon=True).start()
            else:
                self._add_local_subtitle(url_or_path, label, lang)
        except Exception as e:
            logger.debug(f"Could not load subtitle {url_or_path}: {e}")

    def _add_local_subtitle(self, path: str, label: str = 'Subtitle', lang: str = 'eng'):
        try:
            if not self._mpv or not self._mpv.filename:
                return
            self._mpv.command('sub-add', path, 'auto', label, lang)
            logger.info(f"Added local subtitle track: {label} ({path})")
        except Exception as e:
            logger.debug(f"Could not add local subtitle {path}: {e}")


    def get_sub_tracks(self) -> List[Dict[str, Any]]:
        """Get list of all available subtitle tracks."""
        tracks = []
        try:
            track_list = self._mpv.track_list or []
            for t in track_list:
                if t.get('type') == 'sub':
                    tracks.append({
                        'id': t.get('id'),
                        'title': t.get('title') or t.get('lang') or f"Track {t.get('id')}",
                        'lang': t.get('lang', ''),
                        'selected': t.get('selected', False),
                    })
        except Exception as e:
            logger.warning(f"Error fetching sub tracks: {e}")
        return tracks

    def set_sub_track(self, track_id: Any):
        """Select a subtitle track or 'no' to disable."""
        try:
            self._mpv['sid'] = track_id
        except Exception as e:
            logger.warning(f"Error selecting subtitle track {track_id}: {e}")

    def get_sub_track(self):
        try:
            return self._mpv['sid']
        except Exception:
            return 'no'

    def pause(self):
        self._mpv.pause = True

    def resume(self):
        self._mpv.pause = False

    def toggle_pause(self):
        self._mpv.pause = not self._mpv.pause
        return self._mpv.pause

    def seek(self, seconds, reference='relative'):
        self._mpv.seek(seconds, reference=reference)

    def set_volume(self, volume):
        v = max(0.0, min(100.0, float(volume)))
        self._mpv.volume = v
        if v > 0 and self.is_muted():
            self._mpv.mute = False

    def get_volume(self):
        try:
            val = self._mpv.volume
            return 100.0 if val is None else float(val)
        except Exception:
            return 100.0

    def toggle_mute(self):
        self._mpv.mute = not self._mpv.mute
        return self._mpv.mute

    def is_muted(self):
        return bool(self._mpv.mute)

    def set_sub_delay(self, seconds: float):
        self._mpv.sub_delay = round(seconds, 2)

    def get_sub_delay(self) -> float:
        try:
            return float(self._mpv.sub_delay or 0.0)
        except Exception:
            return 0.0

    def adjust_sub_delay(self, delta: float) -> float:
        current = self.get_sub_delay()
        new_val = round(current + delta, 2)
        self.set_sub_delay(new_val)
        return new_val

    def get_position(self):
        return self._mpv.time_pos or 0

    def get_duration(self):
        return self._mpv.duration or 0

    def is_paused(self):
        return self._mpv.pause

    def stop(self):
        try:
            self._mpv.command('stop')
        except Exception:
            pass

    def terminate(self):
        self._is_active = False
        try:
            if self._ctx:
                self.make_current()
                self._ctx.free()
                self._ctx = None
        except Exception:
            pass
        try:
            self._mpv.terminate()
        except Exception:
            pass


class SubtitlePopover(Gtk.Popover):
    """Popover menu for selecting subtitle tracks and adjusting timing."""

    def __init__(self, player: Optional[MpvWidget] = None, on_timing_changed=None):
        super().__init__()
        self._player = player
        self._on_timing_changed = on_timing_changed
        self._available_subtitles: List[Dict[str, Any]] = []
        self._on_select_external = None

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._box.set_margin_top(12)
        self._box.set_margin_bottom(12)
        self._box.set_margin_start(14)
        self._box.set_margin_end(14)
        self._box.set_size_request(260, -1)

        # Header with Title and Refresh button
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_label = Gtk.Label(label="Subtitles")
        title_label.add_css_class('heading')
        title_label.set_xalign(0)
        title_label.set_hexpand(True)
        header_box.append(title_label)

        refresh_btn = Gtk.Button.new_from_icon_name('view-refresh-symbolic')
        refresh_btn.add_css_class('flat')
        refresh_btn.set_tooltip_text("Reload available subtitles")
        refresh_btn.connect('clicked', lambda b: self.refresh_tracks())
        header_box.append(refresh_btn)
        self._box.append(header_box)

        # Tracks list inside scrolled window
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_max_content_height(220)
        self._scroll.set_propagate_natural_height(True)

        self._tracks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._scroll.set_child(self._tracks_box)
        self._box.append(self._scroll)

        self._box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Timing sync section
        sync_label = Gtk.Label(label="Subtitle Timing")
        sync_label.add_css_class('heading')
        sync_label.set_xalign(0)
        self._box.append(sync_label)

        self._delay_label = Gtk.Label(label="Delay: 0.0 s")
        self._delay_label.add_css_class('dim-label')
        self._box.append(self._delay_label)

        timing_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        timing_btn_box.set_halign(Gtk.Align.CENTER)

        minus_btn = Gtk.Button(label="-100ms")
        minus_btn.add_css_class('flat')
        minus_btn.connect('clicked', lambda b: self._adjust_timing(-0.1))
        timing_btn_box.append(minus_btn)

        reset_btn = Gtk.Button(label="Reset")
        reset_btn.add_css_class('flat')
        reset_btn.connect('clicked', lambda b: self._set_timing(0.0))
        timing_btn_box.append(reset_btn)

        plus_btn = Gtk.Button(label="+100ms")
        plus_btn.add_css_class('flat')
        plus_btn.connect('clicked', lambda b: self._adjust_timing(0.1))
        timing_btn_box.append(plus_btn)

        self._box.append(timing_btn_box)

        self.set_child(self._box)
        self.connect('map', self._on_show)

    def set_player(self, player: MpvWidget):
        self._player = player

    def set_available_subtitles(self, subs: List[Dict[str, Any]], on_select_external=None):
        self._available_subtitles = subs or []
        self._on_select_external = on_select_external
        self.refresh_tracks()

    def _on_show(self, *_):
        self.refresh_tracks()
        self.refresh_delay_label()

    def refresh_delay_label(self):
        if self._player:
            delay = self._player.get_sub_delay()
            sign = "+" if delay > 0 else ""
            self._delay_label.set_text(f"Delay: {sign}{delay:.1f} s ({sign}{int(delay * 1000)} ms)")

    def _adjust_timing(self, delta: float):
        if self._player:
            new_val = self._player.adjust_sub_delay(delta)
            self.refresh_delay_label()
            if self._on_timing_changed:
                self._on_timing_changed(new_val)

    def _set_timing(self, val: float):
        if self._player:
            self._player.set_sub_delay(val)
            self.refresh_delay_label()
            if self._on_timing_changed:
                self._on_timing_changed(val)

    def refresh_tracks(self):
        # Clear track buttons
        while True:
            child = self._tracks_box.get_first_child()
            if child is None:
                break
            self._tracks_box.remove(child)

        if not self._player:
            return

        tracks = self._player.get_sub_tracks()
        current_sid = self._player.get_sub_track()
        is_off = (current_sid in ('no', False, None, 0))

        # "Off" button
        off_btn = Gtk.CheckButton(label="Off")
        off_btn.set_active(is_off)
        off_btn.connect('toggled', self._on_track_toggled, 'no')
        self._tracks_box.append(off_btn)
        group = off_btn

        loaded_titles = set()
        for t in tracks:
            tid = t['id']
            title = t.get('title') or f"Track {tid}"
            loaded_titles.add(title.strip().lower())
            btn = Gtk.CheckButton(label=title)
            btn.set_group(group)
            if not is_off and (t.get('selected') or str(current_sid) == str(tid)):
                btn.set_active(True)
            btn.connect('toggled', self._on_track_toggled, tid)
            self._tracks_box.append(btn)

        # External / online subtitles that haven't been loaded yet
        unloaded = [
            s for s in self._available_subtitles
            if s.get('label', '').strip().lower() not in loaded_titles
        ]
        if unloaded:
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.set_margin_top(6)
            sep.set_margin_bottom(4)
            self._tracks_box.append(sep)

            hdr = Gtk.Label(label="Available Online")
            hdr.add_css_class('dim-label')
            hdr.add_css_class('caption')
            hdr.set_xalign(0)
            self._tracks_box.append(hdr)

            for sub in unloaded[:12]:
                btn = Gtk.Button()
                lbl = Gtk.Label(label=sub.get('label', 'Subtitle'))
                lbl.set_xalign(0)
                lbl.set_hexpand(True)
                btn.set_child(lbl)
                btn.add_css_class('flat')
                btn.connect('clicked', self._on_external_clicked, sub)
                self._tracks_box.append(btn)

        if not tracks and not unloaded:
            no_subs = Gtk.Label(label="No subtitles loaded yet")
            no_subs.add_css_class('dim-label')
            no_subs.add_css_class('caption')
            no_subs.set_margin_top(4)
            no_subs.set_margin_bottom(4)
            self._tracks_box.append(no_subs)

    def _on_external_clicked(self, button, sub):
        button.set_sensitive(False)
        child = button.get_child()
        if isinstance(child, Gtk.Label):
            child.set_text(f"Loading {sub.get('label', 'subtitle')}...")
        elif hasattr(button, 'set_label'):
            button.set_label(f"Loading {sub.get('label', 'subtitle')}...")
        if self._on_select_external:
            self._on_select_external(sub)

    def _on_track_toggled(self, button, track_id):
        if button.get_active() and self._player:
            self._player.set_sub_track(track_id)
            if self._on_timing_changed and track_id != 'no':
                self._on_timing_changed(None, f"Subtitle: {button.get_label()}")


class PlayerControls(Gtk.Box):
    """Floating OSD player control bar with play/pause, seek, volume, subtitles."""

    __gsignals__ = {
        'close': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'fullscreen-toggle': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'timing-notification': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class('player-controls')
        self.set_margin_start(0)
        self.set_margin_end(0)
        self.set_margin_bottom(0)
        self.set_valign(Gtk.Align.END)
        self.set_hexpand(True)

        self._player: Optional[MpvWidget] = None
        self._is_dragging = False
        self._last_progress_save = 0.0
        self._pre_mute_volume = 100.0
        self._updating_volume_scale = False

        # Seek bar row with time
        seek_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        seek_box.set_hexpand(True)

        self._curr_time_label = Gtk.Label(label='0:00')
        self._curr_time_label.add_css_class('dim-label')
        self._curr_time_label.add_css_class('caption')
        seek_box.append(self._curr_time_label)

        self._seek_bar = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
        self._seek_bar.set_hexpand(True)
        self._seek_bar.set_draw_value(False)

        drag_gesture = Gtk.GestureDrag.new()
        drag_gesture.connect('drag-begin', self._on_seek_drag_begin)
        drag_gesture.connect('drag-end', self._on_seek_drag_end)
        self._seek_bar.add_controller(drag_gesture)
        self._seek_bar.connect('value-changed', self._on_seek_value_changed)
        seek_box.append(self._seek_bar)

        self._total_time_label = Gtk.Label(label='0:00')
        self._total_time_label.add_css_class('dim-label')
        self._total_time_label.add_css_class('caption')
        seek_box.append(self._total_time_label)

        self.append(seek_box)

        # Buttons row
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        controls.set_margin_top(4)

        # Seek back 10s button
        self._seek_back_btn = Gtk.Button.new_from_icon_name('media-seek-backward-symbolic')
        self._seek_back_btn.add_css_class('flat')
        self._seek_back_btn.set_tooltip_text("Seek back 10s (Left Arrow)")
        self._seek_back_btn.set_focusable(False)
        self._seek_back_btn.connect('clicked', lambda b: self._seek_relative(-10))
        controls.append(self._seek_back_btn)

        # Play/Pause button
        self._play_button = Gtk.Button.new_from_icon_name('media-playback-start-symbolic')
        self._play_button.add_css_class('suggested-action')
        self._play_button.add_css_class('circular')
        self._play_button.set_tooltip_text("Play/Pause (Space)")
        self._play_button.set_focusable(False)
        self._play_button.connect('clicked', self._on_play_pause)
        controls.append(self._play_button)

        # Seek forward 10s button
        self._seek_fwd_btn = Gtk.Button.new_from_icon_name('media-seek-forward-symbolic')
        self._seek_fwd_btn.add_css_class('flat')
        self._seek_fwd_btn.set_tooltip_text("Seek forward 10s (Right Arrow)")
        self._seek_fwd_btn.set_focusable(False)
        self._seek_fwd_btn.connect('clicked', lambda b: self._seek_relative(10))
        controls.append(self._seek_fwd_btn)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        controls.append(spacer)

        # Volume controls
        self._volume_btn = Gtk.Button.new_from_icon_name('audio-volume-high-symbolic')
        self._volume_btn.add_css_class('flat')
        self._volume_btn.set_tooltip_text("Mute/Unmute (M)")
        self._volume_btn.set_focusable(False)
        self._volume_btn.connect('clicked', self._on_mute_clicked)
        controls.append(self._volume_btn)

        self._volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self._volume_scale.set_size_request(100, -1)
        self._volume_scale.set_value(100)
        self._volume_scale.set_draw_value(False)
        self._volume_scale.set_focusable(False)
        self._volume_scale.connect('value-changed', self._on_volume_changed)
        controls.append(self._volume_scale)

        # Subtitle Menu Button with Popover
        self._sub_popover = SubtitlePopover(on_timing_changed=self._on_sub_timing_adjusted)
        self._sub_btn = Gtk.MenuButton()
        self._sub_btn.set_icon_name('media-view-subtitles-symbolic')
        self._sub_btn.add_css_class('flat')
        self._sub_btn.set_tooltip_text("Subtitles & Timing (Z: -100ms, X: +100ms)")
        self._sub_btn.set_popover(self._sub_popover)
        self._sub_btn.set_focusable(False)
        controls.append(self._sub_btn)

        # Fullscreen button
        self._fullscreen_button = Gtk.Button.new_from_icon_name('view-fullscreen-symbolic')
        self._fullscreen_button.add_css_class('flat')
        self._fullscreen_button.set_tooltip_text("Toggle Fullscreen (F)")
        self._fullscreen_button.set_focusable(False)
        self._fullscreen_button.connect('clicked', lambda b: self.emit('fullscreen-toggle'))
        controls.append(self._fullscreen_button)

        # Close button
        self._close_button = Gtk.Button.new_from_icon_name('window-close-symbolic')
        self._close_button.add_css_class('flat')
        self._close_button.set_tooltip_text("Exit Player (Esc)")
        self._close_button.set_focusable(False)
        self._close_button.connect('clicked', lambda b: self.emit('close'))
        controls.append(self._close_button)

        self.append(controls)
        self._update_id = None

    def _seek_relative(self, delta):
        if self._player:
            self._player.seek(delta)
            sign = "+" if delta > 0 else ""
            self.emit('timing-notification', f"Seek {sign}{delta}s")

    def _on_sub_timing_adjusted(self, delay: Optional[float] = None, message: Optional[str] = None):
        if message:
            self.emit('timing-notification', message)
        elif delay is not None:
            sign = "+" if delay > 0 else ""
            self.emit('timing-notification', f"Subtitle Delay: {sign}{delay:.2f}s ({sign}{int(delay * 1000)}ms)")

    def set_player(self, player: MpvWidget):
        self._player = player
        if hasattr(self, '_sub_popover'):
            self._sub_popover.set_player(player)

    def set_available_subtitles(self, subs: List[Dict[str, Any]], on_select_cb=None):
        if hasattr(self, '_sub_popover'):
            self._sub_popover.set_available_subtitles(subs, on_select_cb)

    def refresh_subtitles(self):
        if hasattr(self, '_sub_popover'):
            self._sub_popover.refresh_tracks()

    def reset(self, start_pos: float = 0.0, total_duration: float = 0.0):
        """Reset seekbar, labels, and state to clean defaults."""
        self._is_dragging = False
        try:
            self._seek_bar.handler_block_by_func(self._on_seek_value_changed)
        except Exception:
            pass

        if total_duration > 0 and start_pos > 0:
            val = min(100.0, (start_pos / total_duration) * 100.0)
            self._seek_bar.set_value(val)
        else:
            self._seek_bar.set_value(0.0)

        try:
            self._seek_bar.handler_unblock_by_func(self._on_seek_value_changed)
        except Exception:
            pass

        self._curr_time_label.set_text(self._format_time(start_pos))
        self._total_time_label.set_text(self._format_time(total_duration))
        self._play_button.set_icon_name('media-playback-start-symbolic')
        if hasattr(self, '_sub_popover'):
            self._sub_popover.set_available_subtitles([])

    def start_update_timer(self, player: MpvWidget):
        """Start periodic updates of seek bar and time."""
        self.set_player(player)
        self.stop_update_timer()
        self._update_id = GLib.timeout_add(250, self._update_position)

    def stop_update_timer(self):
        if self._update_id:
            GLib.source_remove(self._update_id)
            self._update_id = None
        self.reset(0.0, 0.0)

    def _update_position(self):
        """Update seek bar and time display."""
        if not self._player:
            return False

        try:
            pos = self._player.get_position()
            dur = self._player.get_duration()

            if dur > 0 and not self._is_dragging:
                self._seek_bar.handler_block_by_func(self._on_seek_value_changed)
                self._seek_bar.set_value((pos / dur) * 100)
                self._seek_bar.handler_unblock_by_func(self._on_seek_value_changed)

                self._curr_time_label.set_text(self._format_time(pos))
                self._total_time_label.set_text(self._format_time(dur))

            # Update play/pause icon
            if self._player.is_paused():
                self._play_button.set_icon_name('media-playback-start-symbolic')
            else:
                self._play_button.set_icon_name('media-playback-pause-symbolic')
        except Exception:
            pass

        return True

    def _format_time(self, seconds):
        seconds = max(0, int(seconds))
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f'{hours}:{minutes:02d}:{secs:02d}'
        return f'{minutes}:{secs:02d}'

    def _on_play_pause(self, button):
        if self._player:
            paused = self._player.toggle_pause()
            self.emit('timing-notification', "Paused" if paused else "Playing")

    def _on_seek_drag_begin(self, gesture, x, y):
        self._is_dragging = True

    def _on_seek_drag_end(self, gesture, offset_x, offset_y):
        self._is_dragging = False
        if self._player:
            val = self._seek_bar.get_value()
            dur = self._player.get_duration()
            if dur > 0:
                target = (val / 100.0) * dur
                self._player.seek(target, reference='absolute')

    def _on_seek_value_changed(self, scale):
        if self._is_dragging and self._player:
            val = scale.get_value()
            dur = self._player.get_duration()
            if dur > 0:
                target = (val / 100.0) * dur
                self._curr_time_label.set_text(self._format_time(target))

    def _on_mute_clicked(self, button):
        if not self._player:
            return
        muted = self._player.toggle_mute()
        if muted:
            curr_vol = self._volume_scale.get_value()
            if curr_vol > 0:
                self._pre_mute_volume = curr_vol
            self._updating_volume_scale = True
            self._volume_scale.set_value(0.0)
            self._updating_volume_scale = False
            self._volume_btn.set_icon_name('audio-volume-muted-symbolic')
            self.emit('timing-notification', "Muted")
        else:
            restore_vol = getattr(self, '_pre_mute_volume', 100.0) or 100.0
            self._player.set_volume(restore_vol)
            self._updating_volume_scale = True
            self._volume_scale.set_value(restore_vol)
            self._updating_volume_scale = False
            if restore_vol < 50:
                self._volume_btn.set_icon_name('audio-volume-low-symbolic')
            else:
                self._volume_btn.set_icon_name('audio-volume-high-symbolic')
            self.emit('timing-notification', f"Volume: {int(restore_vol)}%")

    def _on_volume_changed(self, scale):
        if getattr(self, '_updating_volume_scale', False):
            return
        if self._player:
            val = scale.get_value()
            self._player.set_volume(val)
            if val == 0:
                self._volume_btn.set_icon_name('audio-volume-muted-symbolic')
            elif val < 50:
                self._volume_btn.set_icon_name('audio-volume-low-symbolic')
            else:
                self._volume_btn.set_icon_name('audio-volume-high-symbolic')
            if val > 0:
                self._pre_mute_volume = val
                if self._player.is_muted():
                    self._player.toggle_mute()


class PlayerPage(Adw.NavigationPage):
    """Full player page with video overlay, floating controls, and progress persistence."""

    __gsignals__ = {
        'close-player': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'stream-failed': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__(title="Player", tag="player")
        self.add_css_class('player-page')

        self._stream_data = None
        self._hide_timeout = None
        self._osd_hide_timeout = None
        self._db = DatabaseService()
        self._tmdb = TMDBClient()
        self._subtitles_service = SubtitleService()

        self._last_progress_saved = 0.0
        self._progress_timer_id = None
        self._last_pointer_x = None
        self._last_pointer_y = None
        self._cursor_hidden = False
        self._session_id = 0
        self._pending_sub_query = None
        self._available_subtitles = []

        self.set_focusable(True)
        self.connect('map', lambda w: self.grab_focus())

        self._setup_ui()
        self._setup_keybindings()
        self.connect('unrealize', lambda w: self._set_cursor_visible(True))

    def _setup_ui(self):
        self._overlay = Gtk.Overlay()
        self._overlay.set_hexpand(True)
        self._overlay.set_vexpand(True)

        self._mpv_widget = MpvWidget()
        self._mpv_widget.connect('stream-ready', self._on_stream_ready)
        self._overlay.set_child(self._mpv_widget)

        # Loading spinner
        self._spinner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._spinner_box.set_halign(Gtk.Align.CENTER)
        self._spinner_box.set_valign(Gtk.Align.CENTER)
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(64, 64)
        self._spinner_label = Gtk.Label(label="Connecting to stream...")
        self._spinner_label.add_css_class('title-4')
        self._spinner_box.append(self._spinner)
        self._spinner_box.append(self._spinner_label)
        self._overlay.add_overlay(self._spinner_box)

        # Floating Top Bar (Back button, Media Title, Provider badge, Fullscreen)
        self._top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._top_bar.add_css_class('player-top-bar')
        self._top_bar.set_valign(Gtk.Align.START)
        self._top_bar.set_margin_start(20)
        self._top_bar.set_margin_end(20)
        self._top_bar.set_margin_top(16)

        back_btn = Gtk.Button.new_from_icon_name('go-previous-symbolic')
        back_btn.add_css_class('circular')
        back_btn.add_css_class('flat')
        back_btn.set_tooltip_text("Back to details (Esc)")
        back_btn.set_focusable(False)
        back_btn.connect('clicked', lambda b: self._on_close(None))
        self._top_bar.append(back_btn)

        self._title_label = Gtk.Label()
        self._title_label.add_css_class('heading')
        self._title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._title_label.set_max_width_chars(50)
        self._title_label.set_xalign(0)
        self._top_bar.append(self._title_label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self._top_bar.append(spacer)

        self._provider_badge = Gtk.Label()
        self._provider_badge.add_css_class('genre-pill')
        self._provider_badge.set_visible(False)
        self._top_bar.append(self._provider_badge)

        top_fs_btn = Gtk.Button.new_from_icon_name('view-fullscreen-symbolic')
        top_fs_btn.add_css_class('circular')
        top_fs_btn.add_css_class('flat')
        top_fs_btn.set_tooltip_text("Toggle Fullscreen (F)")
        top_fs_btn.set_focusable(False)
        top_fs_btn.connect('clicked', lambda b: self._on_fullscreen_toggle(None))
        self._top_bar.append(top_fs_btn)

        self._overlay.add_overlay(self._top_bar)

        # Floating OSD pill for notifications (volume, seek, timing feedback)
        self._osd_pill = Gtk.Label(label="")
        self._osd_pill.add_css_class('osd-pill')
        self._osd_pill.set_halign(Gtk.Align.CENTER)
        self._osd_pill.set_valign(Gtk.Align.START)
        self._osd_pill.set_margin_top(96)
        self._osd_pill.set_visible(False)
        self._overlay.add_overlay(self._osd_pill)

        # Controls overlay
        self._controls = PlayerControls()
        self._controls.set_player(self._mpv_widget)
        self._controls.connect('close', self._on_close)
        self._controls.connect('fullscreen-toggle', self._on_fullscreen_toggle)
        self._controls.connect('timing-notification', lambda c, msg: self.show_osd_notification(msg))
        self._overlay.add_overlay(self._controls)

        self.set_child(self._overlay)

        # Motion controller for auto-hiding controls and cursor
        motion = Gtk.EventControllerMotion.new()
        motion.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        motion.connect('motion', self._on_motion)
        self._overlay.add_controller(motion)

        # Single click: play/pause, Double click: fullscreen
        click_gesture = Gtk.GestureClick.new()
        click_gesture.set_button(Gdk.BUTTON_PRIMARY)
        click_gesture.connect('released', self._on_video_clicked)
        self._overlay.add_controller(click_gesture)

        # Vertical scroll: volume adjustment
        scroll_controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_controller.connect('scroll', self._on_video_scroll)
        self._overlay.add_controller(scroll_controller)

    def show_osd_notification(self, text: str):
        """Show temporary floating OSD pill on video surface."""
        self._osd_pill.set_text(text)
        self._osd_pill.set_visible(True)
        if self._osd_hide_timeout:
            GLib.source_remove(self._osd_hide_timeout)
        self._osd_hide_timeout = GLib.timeout_add(1500, self._hide_osd_pill)

    def _hide_osd_pill(self):
        self._osd_pill.set_visible(False)
        self._osd_hide_timeout = None
        return False

    def _setup_keybindings(self):
        """Configure keyboard shortcuts for media playback."""
        key_controller = Gtk.EventControllerKey.new()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect('key-pressed', self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        keyname = Gdk.keyval_name(keyval)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        if keyname in ['space', 'k', 'K']:
            paused = self._mpv_widget.toggle_pause()
            self.show_osd_notification("Paused" if paused else "Playing")
            self._show_controls_briefly()
            return True
        elif keyname == 'Left':
            delta = -60 if shift else -10
            self._mpv_widget.seek(delta)
            sign = "+" if delta > 0 else ""
            self.show_osd_notification(f"Seek {sign}{delta}s")
            self._show_controls_briefly()
            return True
        elif keyname == 'Right':
            delta = 60 if shift else 10
            self._mpv_widget.seek(delta)
            sign = "+" if delta > 0 else ""
            self.show_osd_notification(f"Seek {sign}{delta}s")
            self._show_controls_briefly()
            return True
        elif keyname == 'Up':
            if self._mpv_widget.is_muted():
                self._mpv_widget.toggle_mute()
            curr = self._mpv_widget.get_volume()
            vol = min(100.0, curr + 5.0)
            self._controls._volume_scale.set_value(vol)
            self.show_osd_notification(f"Volume: {int(vol)}%")
            self._show_controls_briefly()
            return True
        elif keyname == 'Down':
            curr = self._mpv_widget.get_volume()
            vol = max(0.0, curr - 5.0)
            self._controls._volume_scale.set_value(vol)
            if vol <= 0.0:
                self.show_osd_notification("Volume: 0% (Muted)")
            else:
                self.show_osd_notification(f"Volume: {int(vol)}%")
            self._show_controls_briefly()
            return True
        elif keyname in ['m', 'M']:
            self._controls._on_mute_clicked(None)
            self._show_controls_briefly()
            return True
        elif keyname in ['f', 'F', 'F11']:
            self._on_fullscreen_toggle(None)
            return True
        elif keyname in ['Escape', 'BackSpace']:
            window = self.get_root()
            if window and window.is_fullscreen():
                window.unfullscreen()
            else:
                self._on_close(None)
            return True
        elif keyname in ['s', 'S']:
            self._controls._sub_btn.activate()
            return True
        elif keyname in ['z', 'Z']:
            delta = -0.5 if shift else -0.1
            new_delay = self._mpv_widget.adjust_sub_delay(delta)
            sign = "+" if new_delay > 0 else ""
            self.show_osd_notification(f"Subtitle Delay: {sign}{new_delay:.2f}s ({sign}{int(new_delay * 1000)}ms)")
            self._controls._sub_popover.refresh_delay_label()
            self._show_controls_briefly()
            return True
        elif keyname in ['x', 'X']:
            delta = 0.5 if shift else 0.1
            new_delay = self._mpv_widget.adjust_sub_delay(delta)
            sign = "+" if new_delay > 0 else ""
            self.show_osd_notification(f"Subtitle Delay: {sign}{new_delay:.2f}s ({sign}{int(new_delay * 1000)}ms)")
            self._controls._sub_popover.refresh_delay_label()
            self._show_controls_briefly()
            return True

        return False

    def load_stream(self, stream_data):
        """Load and play a stream asynchronously."""
        self._stream_data = stream_data
        provider_name = stream_data.get('provider')
        movie = stream_data.get('movie', {})
        season = stream_data.get('season')
        episode = stream_data.get('episode')
        self._start_pos = stream_data.get('start_position', 0)
        self._controls.reset(self._start_pos, 0.0)
        self._available_subtitles = []
        self._controls.set_available_subtitles([])

        tmdb_id = movie.get('id') or movie.get('tmdb_id')
        if not tmdb_id:
            self.emit('stream-failed', "Missing TMDB media identifier.")
            return

        try:
            tmdb_id = int(tmdb_id)
            movie['id'] = tmdb_id
            movie['tmdb_id'] = tmdb_id
        except (ValueError, TypeError):
            pass

        self._spinner_box.set_visible(True)
        self._spinner.start()
        title = movie.get('title', 'Media')
        if season is not None and episode is not None:
            display_title = f"{title} • S{season}E{episode}"
        else:
            year = (movie.get('release_date') or '')[:4]
            display_title = f"{title} ({year})" if year else title
        self.set_title(display_title)
        self._title_label.set_text(display_title)
        if provider_name:
            self._provider_badge.set_text(provider_name)
            self._provider_badge.set_visible(True)
        else:
            self._provider_badge.set_visible(False)
        self._spinner_label.set_text(f"Resolving stream for {display_title}...")

        self._session_id += 1
        current_session = self._session_id

        threading.Thread(
            target=self._resolve_thread,
            args=(tmdb_id, season, episode, provider_name, movie, current_session),
            daemon=True
        ).start()

    def _resolve_thread(self, tmdb_id, season, episode, provider_name, movie, session_id: int):
        """Background thread: resolve stream first, start playback ASAP, then fetch subs in parallel."""
        try:
            result = ProviderManager.resolve_stream(
                tmdb_id=tmdb_id,
                season=season,
                episode=episode,
                preferred_provider_name=provider_name
            )

            if session_id != self._session_id:
                return

            if result and result.url:
                # Save query params to fetch OpenSubtitles AFTER video visibly begins rendering
                self._pending_sub_query = (tmdb_id, season, episode, movie, session_id)
            else:
                self._pending_sub_query = None

            # Start playback immediately
            GLib.idle_add(self._on_stream_resolved, result, [], session_id)

        except Exception as e:
            if session_id != self._session_id:
                return
            GLib.idle_add(self._on_stream_error, str(e), session_id)

    def _fetch_subtitles_background(self, tmdb_id, season, episode, movie, session_id: int):
        """Fetch OpenSubtitles in background and add to available subtitles."""
        try:
            if session_id != self._session_id:
                return
            imdb_id = movie.get('imdb_id')
            if not imdb_id:
                imdb_id = self._tmdb.get_imdb_id(tmdb_id, is_tv=(season is not None))

            if not imdb_id or session_id != self._session_id:
                return

            subs = self._subtitles_service.get_subtitles(imdb_id, season=season, episode=episode)
            if session_id != self._session_id:
                return

            # Combine OpenSubtitles with existing provider subtitles
            existing_labels = {s.get('label', '').strip().lower() for s in self._available_subtitles}
            for s in subs:
                if s.get('label', '').strip().lower() not in existing_labels:
                    self._available_subtitles.append(s)

            GLib.idle_add(
                self._controls.set_available_subtitles,
                self._available_subtitles,
                self._on_download_and_select_external_sub
            )

            # Auto-download and add primary OpenSubtitle ONLY if NO provider subtitle was loaded
            has_loaded = bool(self._mpv_widget and self._mpv_widget.get_sub_tracks())
            if not has_loaded and subs and session_id == self._session_id:
                primary_sub = subs[0]
                sub_url = primary_sub.get('url')
                if sub_url and session_id == self._session_id:
                    label = primary_sub.get('label', primary_sub.get('lang', 'Subtitle'))
                    lang = primary_sub.get('lang', 'eng')
                    local_path = self._subtitles_service.download_subtitle(sub_url, filename_hint=label)
                    if local_path and session_id == self._session_id:
                        GLib.idle_add(self._mpv_widget.add_subtitle, local_path, label, lang)
        except Exception as ex:
            logger.warning(f"Background subtitle fetch failed: {ex}")

    def _on_download_and_select_external_sub(self, sub: Dict[str, Any]):
        """User selected an available online subtitle from the popover."""
        sub_url = sub.get('url')
        label = sub.get('label', sub.get('lang', 'Subtitle'))
        lang = sub.get('lang', 'eng')
        headers = sub.get('headers')
        referer = sub.get('referer')
        current_session = self._session_id

        def _bg():
            local_path = self._subtitles_service.download_subtitle(
                sub_url,
                filename_hint=label,
                headers=headers,
                referer=referer
            )
            if local_path and current_session == self._session_id:
                GLib.idle_add(self._activate_external_subtitle, local_path, label, lang)

        threading.Thread(target=_bg, daemon=True).start()

    def _activate_external_subtitle(self, local_path: str, label: str, lang: str):
        if not self._mpv_widget:
            return
        self._mpv_widget._add_local_subtitle(local_path, label, lang)
        tracks = self._mpv_widget.get_sub_tracks()
        if tracks:
            new_id = tracks[-1]['id']
            self._mpv_widget.set_sub_track(new_id)
            self.show_osd_notification(f"Subtitle: {label}")
        self._controls.refresh_subtitles()

    def _on_stream_ready(self, widget):
        """Called when the first frame has rendered to GLArea."""
        self._spinner.stop()
        self._spinner_box.set_visible(False)

        # Defer subtitle fetch until stream is visibly rolling (3s delay, zero bandwidth/CPU competition during buffer)
        if self._pending_sub_query:
            query = self._pending_sub_query
            self._pending_sub_query = None
            current_session = self._session_id

            def _delayed_fetch():
                if current_session == self._session_id:
                    tmdb_id, season, episode, movie, sid = query
                    threading.Thread(
                        target=self._fetch_subtitles_background,
                        args=(tmdb_id, season, episode, movie, sid),
                        daemon=True
                    ).start()
                return False

            GLib.timeout_add_seconds(3, _delayed_fetch)

    def _on_stream_resolved(self, result: Optional[StreamResult], extra_subs: List[Dict[str, Any]], session_id: int = 0):
        """Executed on main GTK UI thread when stream result is available."""
        if session_id and session_id != self._session_id:
            return False

        if not result or not result.url:
            self._spinner.stop()
            self._spinner_box.set_visible(False)
            self.emit('stream-failed', "Could not find a playable stream from any available provider.")
            return False

        # Transition spinner text while MPV demuxes and buffers the first frame
        self._spinner_label.set_text("Buffering stream...")

        logger.info(f"Starting playback: {result.url}")

        if result.provider_name and hasattr(self, '_provider_badge'):
            q = f" • {result.quality}" if result.quality else ""
            self._provider_badge.set_text(f"{result.provider_name}{q}")
            self._provider_badge.set_visible(True)

        # Attach stream referer and headers to provider subtitles
        provider_subs = list(result.subtitles or [])
        for s in provider_subs:
            if 'referer' not in s and result.referer:
                s['referer'] = result.referer
            if 'headers' not in s and result.headers:
                s['headers'] = result.headers

        # Keep all provider subtitles in self._available_subtitles for on-demand selection
        self._available_subtitles = list(provider_subs)
        self._controls.set_available_subtitles(
            self._available_subtitles,
            self._on_download_and_select_external_sub
        )

        # Auto-download ONLY the primary English (or first) subtitle to avoid parallel thread flood
        initial_subs = []
        if provider_subs:
            eng_subs = [s for s in provider_subs if s.get('lang', '').lower() in ('eng', 'en')]
            primary_sub = eng_subs[0] if eng_subs else provider_subs[0]
            initial_subs = [primary_sub]

        self._mpv_widget.play(
            url=result.url,
            referer=result.referer,
            origin=result.origin,
            headers=result.headers,
            subtitles=initial_subs,
            start_pos=self._start_pos
        )
        self._controls.start_update_timer(self._mpv_widget)
        self._show_controls_briefly()

        # Start periodic progress persistence to SQLite
        self._start_progress_timer()

        if self._start_pos and self._start_pos > 15:
            mins = int(self._start_pos) // 60
            secs = int(self._start_pos) % 60
            self.show_osd_notification(f"Resumed at {mins}:{secs:02d}")

    def _start_progress_timer(self):
        self._stop_progress_timer()
        self._progress_timer_id = GLib.timeout_add(5000, self._save_watch_progress)

    def _stop_progress_timer(self):
        if self._progress_timer_id:
            GLib.source_remove(self._progress_timer_id)
            self._progress_timer_id = None

    def _save_watch_progress(self):
        """Save progress to SQLite database."""
        if not self._stream_data or not self._mpv_widget:
            return True

        try:
            pos = self._mpv_widget.get_position()
            dur = self._mpv_widget.get_duration()
            movie = self._stream_data.get('movie', {})
            tmdb_id = movie.get('id')

            if tmdb_id and dur > 30 and pos > 5:
                self._db.update_watch_progress(
                    tmdb_id=tmdb_id,
                    title=movie.get('title', 'Unknown'),
                    media_type=self._stream_data.get('media_type', 'movie'),
                    poster_url=movie.get('poster_url'),
                    backdrop_url=movie.get('backdrop_url'),
                    season=self._stream_data.get('season'),
                    episode=self._stream_data.get('episode'),
                    progress_seconds=pos,
                    duration_seconds=dur,
                )
        except Exception as e:
            logger.warning(f"Failed to persist watch progress: {e}")

        return True

    def _on_stream_error(self, err_msg: str, session_id: int = 0):
        if session_id and session_id != self._session_id:
            return False
        self._spinner.stop()
        self._spinner_box.set_visible(False)
        self.emit('stream-failed', f"Stream error: {err_msg}")
        return False

    def _on_close(self, controls):
        """Close playback safely, saving final progress and stopping services."""
        self._session_id += 1  # Invalidate any in-flight resolver or subtitle worker threads
        self._pending_sub_query = None
        self._available_subtitles = []

        # Capture progress before deactivating
        try:
            pos = self._mpv_widget.get_position()
            dur = self._mpv_widget.get_duration()
            stream_data = self._stream_data
        except Exception:
            pos, dur, stream_data = 0, 0, None

        # Deactivate widget synchronously: pauses, stops, and disables further render callbacks
        self._mpv_widget.deactivate()

        self._set_cursor_visible(True)
        if self._hide_timeout:
            GLib.source_remove(self._hide_timeout)
            self._hide_timeout = None
        if self._osd_hide_timeout:
            GLib.source_remove(self._osd_hide_timeout)
            self._osd_hide_timeout = None

        self._stop_progress_timer()
        self._controls.stop_update_timer()
        self._controls.reset(0.0)

        # Emit immediately so UI pops back instantly with zero freeze
        self.emit('close-player')

        # Run persistence & background service teardown in background daemon thread
        def cleanup_worker():
            try:
                if stream_data and pos > 5 and dur > 30:
                    movie = stream_data.get('movie', {})
                    tmdb_id = movie.get('id')
                    if tmdb_id:
                        self._db.update_watch_progress(
                            tmdb_id=tmdb_id,
                            title=movie.get('title', 'Unknown'),
                            media_type=stream_data.get('media_type', 'movie'),
                            poster_url=movie.get('poster_url'),
                            backdrop_url=movie.get('backdrop_url'),
                            season=stream_data.get('season'),
                            episode=stream_data.get('episode'),
                            progress_seconds=pos,
                            duration_seconds=dur,
                        )
            except Exception as ex:
                logger.warning(f"Error saving watch progress during cleanup: {ex}")

            try:
                get_torrent_streamer().stop()
            except Exception as ex:
                logger.warning(f"Error stopping torrent streamer: {ex}")

        threading.Thread(target=cleanup_worker, daemon=True).start()

    def _on_fullscreen_toggle(self, button):
        window = self.get_root()
        if window:
            if window.is_fullscreen():
                window.unfullscreen()
            else:
                window.fullscreen()

    def _on_motion(self, controller, x, y):
        if self._last_pointer_x is not None and self._last_pointer_y is not None:
            if abs(x - self._last_pointer_x) < 2 and abs(y - self._last_pointer_y) < 2:
                return

        self._last_pointer_x = x
        self._last_pointer_y = y
        self._show_controls_briefly()

    def _on_video_clicked(self, gesture, n_press, x, y):
        self.grab_focus()
        # If subtitle popover is currently open, dismiss it and do not toggle playback
        if hasattr(self, '_controls') and hasattr(self._controls, '_sub_popover'):
            if self._controls._sub_popover.get_visible():
                self._controls._sub_popover.popdown()
                return

        # Ignore clicks directly within interactive control boxes
        if hasattr(self, '_controls') and self._controls.get_visible():
            ctrl_alloc = self._controls.get_allocation()
            if (ctrl_alloc.x <= x <= ctrl_alloc.x + ctrl_alloc.width and
                ctrl_alloc.y <= y <= ctrl_alloc.y + ctrl_alloc.height):
                return
        if hasattr(self, '_top_bar') and self._top_bar.get_visible():
            top_alloc = self._top_bar.get_allocation()
            if (top_alloc.x <= x <= top_alloc.x + top_alloc.width and
                top_alloc.y <= y <= top_alloc.y + top_alloc.height):
                return

        if n_press == 1:
            paused = self._mpv_widget.toggle_pause()
            self.show_osd_notification("Paused" if paused else "Playing")
            self._show_controls_briefly()
        elif n_press == 2:
            self._on_fullscreen_toggle(None)

    def _on_video_scroll(self, controller, dx, dy):
        if self._mpv_widget.is_muted() and dy < 0:
            self._mpv_widget.toggle_mute()
        current_vol = self._mpv_widget.get_volume()
        delta = -5 if dy > 0 else 5
        new_vol = max(0, min(100, current_vol + delta))
        self._mpv_widget.set_volume(new_vol)
        if hasattr(self._controls, '_volume_scale'):
            self._controls._volume_scale.set_value(new_vol)
        if new_vol == 0:
            self.show_osd_notification("Volume: 0% (Muted)")
        else:
            self.show_osd_notification(f"Volume: {int(new_vol)}%")
        self._show_controls_briefly()
        return True

    def _set_cursor_visible(self, visible: bool):
        self._cursor_hidden = not visible
        cursor_name = "default" if visible else "none"
        try:
            self.set_cursor_from_name(cursor_name)
            self._overlay.set_cursor_from_name(cursor_name)
            self._mpv_widget.set_cursor_from_name(cursor_name)
            root = self.get_root()
            if root:
                root.set_cursor_from_name(cursor_name)
        except Exception:
            pass

    def _show_controls_briefly(self):
        if self._cursor_hidden:
            self._set_cursor_visible(True)
        if hasattr(self, '_top_bar'):
            self._top_bar.set_visible(True)
        self._controls.set_visible(True)
        if self._hide_timeout:
            GLib.source_remove(self._hide_timeout)
        self._hide_timeout = GLib.timeout_add(3000, self._hide_controls)

    def _hide_controls(self):
        # Don't hide if user is currently interacting with controls
        if getattr(self._controls, '_is_dragging', False):
            return True
        if hasattr(self._controls, '_sub_popover') and self._controls._sub_popover.get_visible():
            return True

        if not self._mpv_widget.is_paused():
            if hasattr(self, '_top_bar'):
                self._top_bar.set_visible(False)
            self._controls.set_visible(False)
            self._set_cursor_visible(False)

        self._hide_timeout = None
        return False
