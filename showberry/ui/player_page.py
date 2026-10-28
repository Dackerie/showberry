"""Player page - MPV video player with controls, subtitle sync, and progress tracking."""

from __future__ import annotations

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, GObject, Gdk, Pango

import locale
locale.setlocale(locale.LC_NUMERIC, 'C')

import sys
import os
import logging
import subprocess
import threading
from typing import Optional, List, Dict, Any, Tuple

if sys.platform == 'win32':
    for p in (
        os.path.dirname(sys.executable),
        os.path.join(os.path.dirname(sys.executable), '_internal'),
        getattr(sys, '_MEIPASS', ''),
        os.getcwd(),
        r'C:\msys64\ucrt64\bin',
    ):
        if p and os.path.isdir(p):
            abs_p = os.path.abspath(p)
            if hasattr(os, 'add_dll_directory'):
                try:
                    os.add_dll_directory(abs_p)
                except Exception:
                    pass
            if abs_p not in os.environ.get('PATH', ''):
                os.environ['PATH'] = abs_p + os.pathsep + os.environ.get('PATH', '')
else:
    import ctypes.util
    _orig_find_library = ctypes.util.find_library
    def _find_library_with_fallback(name):
        res = _orig_find_library(name)
        if res:
            return res
        if name in ('mpv', 'libmpv'):
            appdir = os.environ.get('APPDIR')
            candidates = []
            if appdir:
                candidates.extend([
                    os.path.join(appdir, 'usr', 'lib', 'libmpv.so'),
                    os.path.join(appdir, 'usr', 'lib', 'libmpv.so.2'),
                    os.path.join(appdir, 'usr', 'lib', 'libmpv.so.1'),
                    os.path.join(appdir, 'usr', 'lib', 'x86_64-linux-gnu', 'libmpv.so'),
                    os.path.join(appdir, 'usr', 'lib', 'x86_64-linux-gnu', 'libmpv.so.2'),
                    os.path.join(appdir, 'usr', 'lib', 'x86_64-linux-gnu', 'libmpv.so.1'),
                ])
            exe_dir = os.path.dirname(sys.executable)
            candidates.extend([
                os.path.join(exe_dir, '..', 'lib', 'libmpv.so'),
                os.path.join(exe_dir, '..', 'lib', 'libmpv.so.2'),
                os.path.join(exe_dir, '..', 'lib', 'libmpv.so.1'),
            ])
            for c in candidates:
                if os.path.exists(c):
                    return c
        return None
    ctypes.util.find_library = _find_library_with_fallback

try:
    import mpv
    from mpv import MPV, MpvGlGetProcAddressFn, MpvRenderContext
    HAS_MPV = True
except Exception as e:
    import logging
    logging.getLogger(__name__).error("Failed to load mpv library: %s", e)
    mpv = None
    MPV = None
    MpvGlGetProcAddressFn = None
    MpvRenderContext = None
    HAS_MPV = False

if sys.platform != 'win32':
    try:
        from OpenGL import GL
        HAS_OPENGL = True
    except ImportError:
        HAS_OPENGL = False
        GL = None
else:
    HAS_OPENGL = False
    GL = None

from showberry.providers.base import StreamResult, ProviderManager
from showberry.services.database import DatabaseService
from showberry.services.subtitles import SubtitleService
from showberry.services.tmdb import TMDBClient
from showberry.services.torrent import get_torrent_streamer
from showberry.services.settings import SettingsService
from showberry.services.sleep_inhibitor import SleepInhibitor

logger = logging.getLogger(__name__)

ASPECT_MODES = [
    ('Fit (Original)', '-1', 0.0),
    ('Fill / Crop', '-1', 1.0),
    ('Stretch 16:9', '16:9', 0.0),
    ('Stretch 21:9', '21:9', 0.0),
    ('Stretch 4:3', '4:3', 0.0),
]


def get_proc_address_wrapper():
    """Get OpenGL proc address for MPV across Linux, Windows, and macOS."""
    import ctypes
    import sys

    epoxy_get_proc = None
    wgl_get_proc = None
    wgl_get_current_ctx = None
    win_gl = None
    egl_get_proc = None
    egl_get_current_ctx = None
    gles_lib = None
    gl_get_proc = None
    gl_lib = None
    mac_gl = None

    if sys.platform == 'win32':
        # Check for libepoxy (used by GTK 4 on Windows to resolve GL/GLES/WGL/EGL)
        for epoxy_name in ('libepoxy-0.dll', 'libepoxy.dll', 'epoxy-0.dll'):
            try:
                epoxy = ctypes.CDLL(epoxy_name)
                epoxy_get_proc = epoxy.epoxy_get_proc_address
                epoxy_get_proc.restype = ctypes.c_void_p
                epoxy_get_proc.argtypes = [ctypes.c_char_p]
                break
            except Exception:
                pass

        # Check for EGL / ANGLE (used by GTK 4 on Windows when GLES is used)
        for egl_name in ('libEGL.dll', 'libEGL'):
            try:
                egl = ctypes.CDLL(egl_name)
                egl_get_proc = egl.eglGetProcAddress
                egl_get_proc.restype = ctypes.c_void_p
                egl_get_proc.argtypes = [ctypes.c_char_p]
                try:
                    egl_get_current_ctx = egl.eglGetCurrentContext
                    egl_get_current_ctx.restype = ctypes.c_void_p
                except Exception:
                    pass
                break
            except Exception:
                pass

        for gles_name in ('libGLESv2.dll', 'libGLESv2'):
            try:
                gles_lib = ctypes.CDLL(gles_name)
                break
            except Exception:
                pass

        # Check for WGL / Desktop OpenGL (used by GTK 4 on Windows with native GPU drivers)
        try:
            win_gl = ctypes.windll.opengl32
            wgl_get_proc = win_gl.wglGetProcAddress
            wgl_get_proc.restype = ctypes.c_void_p
            wgl_get_proc.argtypes = [ctypes.c_char_p]
            try:
                wgl_get_current_ctx = win_gl.wglGetCurrentContext
                wgl_get_current_ctx.restype = ctypes.c_void_p
            except Exception:
                pass
        except Exception:
            pass
    elif sys.platform == 'darwin':
        for cand in (None, 'OpenGL.framework/OpenGL', '/System/Library/Frameworks/OpenGL.framework/OpenGL'):
            try:
                mac_gl = ctypes.CDLL(cand)
                break
            except Exception:
                pass
    else:
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
            name_bytes = name.encode('utf-8')
            name_str = name
        else:
            name_bytes = name
            name_str = name.decode('utf-8', errors='ignore')

        res = None

        # 1. Try libepoxy if available (matches GTK4's active context resolver)
        if epoxy_get_proc:
            try:
                res = epoxy_get_proc(name_bytes)
            except Exception:
                res = None
            if res and (res <= 3 or res in (-1, 0xFFFFFFFFFFFFFFFF, 18446744073709551615)):
                res = None

        # 2. On Windows, determine whether EGL or WGL is current
        is_egl_current = False
        if not res and sys.platform == 'win32' and egl_get_current_ctx:
            try:
                is_egl_current = bool(egl_get_current_ctx())
            except Exception:
                pass

        if not res and (is_egl_current or not win_gl):
            # Query EGL proc address first, then GLES export
            if egl_get_proc:
                try:
                    res = egl_get_proc(name_bytes)
                except Exception:
                    res = None
            if (not res or res <= 3 or res in (-1, 0xFFFFFFFFFFFFFFFF, 18446744073709551615)) and gles_lib:
                try:
                    res = ctypes.cast(getattr(gles_lib, name_str), ctypes.c_void_p).value
                except Exception:
                    res = None
            if res and (res <= 3 or res in (-1, 0xFFFFFFFFFFFFFFFF, 18446744073709551615)):
                res = None

        if not res and win_gl:
            try:
                res = ctypes.cast(getattr(win_gl, name_str), ctypes.c_void_p).value
            except Exception:
                res = None
            if (not res or res <= 3 or res in (-1, 0xFFFFFFFFFFFFFFFF, 18446744073709551615)) and wgl_get_proc:
                try:
                    res = wgl_get_proc(name_bytes)
                except Exception:
                    res = None
            if res and (res <= 3 or res in (-1, 0xFFFFFFFFFFFFFFFF, 18446744073709551615)):
                res = None

        # Fallback to EGL / GLES if not queried yet
        if not res and egl_get_proc:
            try:
                res = egl_get_proc(name_bytes)
            except Exception:
                pass
            if res and (res <= 3 or res in (-1, 0xFFFFFFFFFFFFFFFF, 18446744073709551615)):
                res = None
        if not res and gles_lib:
            try:
                res = ctypes.cast(getattr(gles_lib, name_str), ctypes.c_void_p).value
            except Exception:
                pass

        if not res and mac_gl:
            try:
                res = ctypes.cast(getattr(mac_gl, name_str), ctypes.c_void_p).value
            except Exception:
                pass
        if not res and gl_get_proc:
            try:
                res = gl_get_proc(name_bytes)
            except Exception:
                pass
        if not res and gl_lib:
            try:
                res = ctypes.cast(getattr(gl_lib, name_str), ctypes.c_void_p).value
            except Exception:
                pass
        return res or 0

    return get_proc_address


class MpvWidget(Gtk.GLArea):
    """GTK4 GLArea widget that renders MPV video."""

    __gsignals__ = {
        'stream-ready': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'buffering': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        'playback-ended': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'pause-changed': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
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

        self._ctx = None
        self._gl_context_ref = None
        self._redraw_pending = False
        self._pending_subtitles = []
        self._pending_local_subs: List[Tuple[str, str, str, bool]] = []
        self._wait_first_frame = False  # set True while A/V sync wait is active
        self._is_active = True
        self._has_drawn_first_frame = False
        self._is_stream_active = False
        self._current_media_path = None
        self._unpause_watchdog_id = None

        if not HAS_MPV or MPV is None:
            self._mpv = None
            logger.error("MPV backend is not available; video playback disabled")
            return

        from showberry.services.settings import SettingsService
        settings = SettingsService()
        initial_sub_pos = settings.sub_pos
        initial_sub_scale = 1.0
        initial_sub_font_size = getattr(settings, 'sub_font_size', 28)

        def _on_mpv_log(level, component, message):
            msg = message.rstrip()
            if not msg:
                return
            mpv_log = logging.getLogger(f"mpv.{component}")
            lvl = level.lower()
            if lvl in ('fatal', 'error'):
                mpv_log.error("%s", msg)
            elif lvl == 'warn':
                mpv_log.warning("%s", msg)
            elif lvl == 'info':
                mpv_log.info("%s", msg)
            else:
                mpv_log.debug("%s", msg)

            # Auto-fallback to software decode if display driver or VM fails hardware surface allocation
            if any(s in msg for s in (
                'AVHWFramesContext', 'dxva2_vld', 'Failed to allocate AVHWDeviceContext',
                'VK_ERROR', 'hwaccel', 'hardware decoding failed', 'Could not create the surfaces',
                'Failed setup for format', 'Error creating an internal frame pool', 'd3d11va', 'dxva2'
            )):
                if getattr(self, '_mpv', None):
                    try:
                        cur_hwdec = self._mpv['hwdec']
                        if cur_hwdec != ['no'] and cur_hwdec != 'no':
                            logger.warning("Hardware acceleration failed on display driver (%s); falling back to software decoding", msg)
                            self._mpv['hwdec'] = 'no'
                    except Exception:
                        pass

        is_debug = ('--debug' in sys.argv or '--verbose' in sys.argv or os.environ.get('SHOWBERRY_DEBUG'))
        mpv_loglevel = 'v' if is_debug else 'warn'

        hwdec_pref = getattr(settings, 'hwdec_mode', 'auto')
        if hwdec_pref == 'off':
            chosen_hwdec = 'no'
        elif sys.platform == 'win32':
            # On Windows with OpenGL FBO rendering in Gtk.GLArea:
            # Direct zero-copy hwdec (d3d11va) outputs D3D11 surfaces that cannot be directly
            # displayed on the OpenGL FBO without specialized interop, causing a black video screen.
            # 'auto-copy' (d3d11va-copy / dxva2-copy / nvdec-copy) performs hardware decoding on GPU
            # and copies the decoded frames to system RAM to upload as standard OpenGL textures.
            # This is 100% reliable across all Windows GPUs (NVIDIA, AMD, Intel) and drivers.
            chosen_hwdec = 'auto-copy'
        else:
            chosen_hwdec = 'auto-safe'

        mpv_opts = {
            'vo': 'libmpv',
            'keep_open': 'yes',
            'input_default_bindings': False,
            'cursor_autohide': 1000,
            'volume_max': 130,
            'cache': 'yes',
            'demuxer_max_bytes': 150 * 1024 * 1024,
            'demuxer_readahead_secs': 30,
            'cache_secs': 30,
            'cache_pause_initial': 'yes',
            'cache_pause_wait': 1.0,
            'network_timeout': 60,
            'hwdec': chosen_hwdec,
            'video_sync': 'audio',
            'vd_lavc_threads': 0,
            'framedrop': 'vo',
            'scale': 'bilinear',
            'cscale': 'bilinear',
            'dscale': 'bilinear',
            'slang': 'eng,en,enUS,en-US',
            'sub_scale_with_window': 'yes',
            'sub_font_size': initial_sub_font_size,
            'sub_pos': initial_sub_pos,
            'sub_scale': 1.0,
            'sub_margin_y': 10,
            'log_handler': _on_mpv_log,
            'loglevel': mpv_loglevel,
            'stop_screensaver': 'yes',
        }
        if sys.platform == 'win32':
            mpv_opts['gpu_api'] = 'opengl'


        # Ensure C numeric locale for libmpv across platforms
        try:
            locale.setlocale(locale.LC_NUMERIC, 'C')
        except Exception:
            pass
        if sys.platform == 'win32':
            try:
                import ctypes
                ctypes.cdll.msvcrt.setlocale(4, b'C')
            except Exception:
                pass

        self._mpv = MPV(**mpv_opts)

        @self._mpv.property_observer('pause')
        def _on_pause_prop_change(name, value):
            if getattr(self, '_is_active', False):
                GLib.idle_add(self.emit, 'pause-changed', bool(value))

        @self._mpv.property_observer('paused-for-cache')
        def _on_paused_for_cache(name, value):
            if getattr(self, '_is_active', False):
                GLib.idle_add(self.emit, 'buffering', bool(value))

        @self._mpv.property_observer('eof-reached')
        def _on_eof_reached(name, value):
            if value and getattr(self, '_is_active', False):
                GLib.idle_add(self.emit, 'playback-ended')

        @self._mpv.event_callback('playback-restart')
        def _on_playback_restart(event):
            if getattr(self, '_is_active', False):
                GLib.idle_add(self._on_mpv_playback_restarted)

        @self._mpv.event_callback('file-loaded')
        def _on_file_loaded(event):
            if getattr(self, '_is_active', False):
                GLib.idle_add(self._flush_pending_local_subs)

        self._current_sub_path = None

    def _on_mpv_playback_restarted(self):
        if not getattr(self, '_is_active', False):
            return
        self._has_drawn_first_frame = True
        self._wait_first_frame = False
        if getattr(self, '_unpause_watchdog_id', None):
            GLib.source_remove(self._unpause_watchdog_id)
            self._unpause_watchdog_id = None
        self.emit('stream-ready')
        self.queue_render()
        self._flush_pending_local_subs()

    def activate(self):
        """Re-enable rendering and event handling."""
        self._is_active = True
        if self._ctx:
            self._ctx.update_cb = self._on_mpv_callback

    def deactivate(self):
        """Immediately stop playback and disable render callbacks to prevent deadlocks."""
        self._is_active = False
        self._is_stream_active = False
        self._has_drawn_first_frame = False
        if getattr(self, '_unpause_watchdog_id', None):
            GLib.source_remove(self._unpause_watchdog_id)
            self._unpause_watchdog_id = None
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
        self._is_active = True
        if not getattr(self, '_mpv', None):
            return

        # GTK realize can overwrite numeric locale
        try:
            locale.setlocale(locale.LC_NUMERIC, 'C')
        except Exception:
            pass
        if sys.platform == 'win32':
            try:
                import ctypes
                ctypes.cdll.msvcrt.setlocale(4, b'C')
            except Exception:
                pass

        self.make_current()
        curr_gdk_ctx = self.get_context()
        if curr_gdk_ctx:
            try:
                use_es = curr_gdk_ctx.get_use_es()
                ver = curr_gdk_ctx.get_version()
                logger.info("Realized GdkGLContext: use_es=%s, version=%s", use_es, ver)
            except Exception:
                pass

        # If the underlying GdkGLContext was recreated (e.g. across navigation pops and pushes),
        # the previous MpvRenderContext is bound to a destroyed OpenGL context and cannot render.
        # Safely free it while the new OpenGL context is current before creating a fresh one.
        if self._ctx and self._gl_context_ref != curr_gdk_ctx:
            logger.info("OpenGL context changed; resetting MpvRenderContext")
            try:
                self._ctx.free()
            except Exception:
                pass
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
        if getattr(self, '_unpause_watchdog_id', None):
            GLib.source_remove(self._unpause_watchdog_id)
            self._unpause_watchdog_id = None
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
                GLib.idle_add(self._trigger_redraw, priority=GLib.PRIORITY_HIGH)
        except Exception:
            pass

    def _trigger_redraw(self, *_):
        self._redraw_pending = False
        if not self._is_active:
            return False
        self.queue_render()
        return False

    def _on_render(self, area, gl_context):
        return self.do_render(gl_context)

    def do_render(self, *_):
        if not self._is_active:
            return False

        if not self._ctx:
            self._on_realize()
            if not self._ctx:
                return False

        factor = self.get_scale_factor()
        width = int(self.get_width() * factor)
        height = int(self.get_height() * factor)
        if width <= 0 or height <= 0:
            return False

        # Ensure Gtk.GLArea context is current and buffers are attached
        try:
            self.make_current()
            self.attach_buffers()
        except Exception:
            pass

        # Clear any residual OpenGL error flags from context switching
        if HAS_OPENGL and GL:
            try:
                while GL.glGetError() != GL.GL_NO_ERROR:
                    pass
            except Exception:
                pass

        # Query current FBO with safe fallback across Desktop OpenGL and GLES
        fbo = 0
        if HAS_OPENGL and GL:
            try:
                fbo = GL.glGetIntegerv(GL.GL_DRAW_FRAMEBUFFER_BINDING)
            except Exception:
                fbo = 0

        if not fbo and sys.platform == 'win32':
            # 1. Desktop OpenGL (opengl32.dll) - used by GTK4 with native NVIDIA / AMD / Intel drivers
            try:
                import ctypes
                win_gl = ctypes.windll.opengl32
                gl_get_int = getattr(win_gl, 'glGetIntegerv', None)
                if gl_get_int:
                    gl_get_int.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
                    gl_get_int.restype = None
                    raw_fbo = ctypes.c_int(0)
                    gl_get_int(0x8CA6, ctypes.byref(raw_fbo))  # GL_DRAW_FRAMEBUFFER_BINDING
                    fbo = raw_fbo.value
                    if not fbo:
                        gl_get_int(0x8CA7, ctypes.byref(raw_fbo))  # GL_FRAMEBUFFER_BINDING fallback
                        fbo = raw_fbo.value
            except Exception:
                pass

            # 2. GLES (libGLESv2.dll) - used by ANGLE / EGL on Windows
            if not fbo:
                try:
                    import ctypes
                    gles = ctypes.CDLL('libGLESv2.dll')
                    gles_get_int = getattr(gles, 'glGetIntegerv', None)
                    if gles_get_int:
                        gles_get_int.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
                        gles_get_int.restype = None
                        raw_fbo = ctypes.c_int(0)
                        gles_get_int(0x8CA6, ctypes.byref(raw_fbo))  # GL_DRAW_FRAMEBUFFER_BINDING
                        fbo = raw_fbo.value
                        if not fbo:
                            gles_get_int(0x8CA7, ctypes.byref(raw_fbo))  # GL_FRAMEBUFFER_BINDING fallback
                            fbo = raw_fbo.value
                except Exception:
                    pass

            # 3. Dynamic resolver via epoxy_get_proc_address
            if not fbo:
                try:
                    import ctypes
                    epoxy = ctypes.CDLL('libepoxy-0.dll')
                    get_proc = getattr(epoxy, 'epoxy_get_proc_address', None)
                    if get_proc:
                        get_proc.restype = ctypes.c_void_p
                        get_proc.argtypes = [ctypes.c_char_p]
                        ptr = get_proc(b'glGetIntegerv')
                        if ptr and ptr > 3:
                            PROTO = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.POINTER(ctypes.c_int))
                            func = PROTO(ptr)
                            raw_fbo = ctypes.c_int(0)
                            func(0x8CA6, ctypes.byref(raw_fbo))
                            fbo = raw_fbo.value
                            if not fbo:
                                func(0x8CA7, ctypes.byref(raw_fbo))
                                fbo = raw_fbo.value
                except Exception:
                    pass

        # Advance internal presentation timing right at moment of render
        try:
            self._ctx.update()
        except Exception:
            pass

        # Render MPV frame
        try:
            self._ctx.render(
                flip_y=True,
                opengl_fbo={'w': width, 'h': height, 'fbo': fbo},
                block_for_target_time=False,
            )
        except Exception as e:
            logger.error("MPV render error: %s", e)
            return False

        if self._is_stream_active and not self._has_drawn_first_frame:
            try:
                vid = self._mpv.vid
                time_pos = self._mpv.time_pos
                has_frame = (vid is not None and vid != 'no') and (time_pos is not None or not self._mpv.eof_reached)
            except Exception:
                has_frame = True

            if has_frame:
                self._has_drawn_first_frame = True
                GLib.idle_add(self.emit, 'stream-ready')

        # Audio/video sync: unpause on the very first rendered frame so audio
        # never runs ahead of visible video frames.
        if self._wait_first_frame and self._has_drawn_first_frame:
            self._wait_first_frame = False
            if getattr(self, '_unpause_watchdog_id', None):
                GLib.source_remove(self._unpause_watchdog_id)
                self._unpause_watchdog_id = None
            try:
                self._mpv.pause = False
            except Exception:
                pass

        return True

    def _safety_unpause(self):
        """Safety watchdog: guarantee unpausing after timeout so playback never stalls."""
        self._unpause_watchdog_id = None
        if getattr(self, '_wait_first_frame', False) and getattr(self, '_is_stream_active', False):
            logger.info("Safety watchdog: unpausing MPV after render wait timeout")
            self._wait_first_frame = False
            self._has_drawn_first_frame = True
            try:
                if self._mpv:
                    self._mpv.pause = False
            except Exception:
                pass
            GLib.idle_add(self.emit, 'stream-ready')
        return False

    def _on_resize(self, widget, width, height):
        if self._ctx:
            self._ctx.update()

    def play(self, url, referer=None, origin=None, headers=None, subtitles=None, start_pos=0):
        """Play a video URL with custom referer/origin headers and subtitles."""
        self._is_active = True
        if self._ctx:
            self._ctx.update_cb = self._on_mpv_callback
        self._is_stream_active = True
        self._has_drawn_first_frame = False
        self._wait_first_frame = True
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
            self._mpv.pause = False
        except Exception:
            pass
        self._current_media_path = url
        self._current_sub_path = None
        self._mpv.play(url)

        if getattr(self, '_unpause_watchdog_id', None):
            GLib.source_remove(self._unpause_watchdog_id)
            self._unpause_watchdog_id = None
        self._unpause_watchdog_id = GLib.timeout_add(15000, self._safety_unpause)
        self.queue_render()

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
            if not self._mpv:
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
                        if local_path and self._mpv:
                            GLib.idle_add(self._add_local_subtitle, local_path, label, lang)
                    except Exception as err:
                        logger.warning(f"Failed downloading subtitle from {url_or_path}: {err}")
                threading.Thread(target=_bg_dl, daemon=True).start()
            else:
                self._add_local_subtitle(url_or_path, label, lang)
        except Exception as e:
            logger.debug(f"Could not load subtitle {url_or_path}: {e}")

    def _remove_existing_sub_track(self, label: str, lang: str):
        """Remove any existing external subtitle track in MPV with the same title or language to prevent duplicates."""
        try:
            if not self._mpv:
                return
            track_list = self._mpv.track_list or []
            norm_label = (label or '').strip().lower()
            norm_lang = (lang or '').strip().lower()
            for t in list(track_list):
                if t.get('type') != 'sub' or not t.get('external', False):
                    continue
                t_id = t.get('id')
                t_title = (t.get('title') or '').strip().lower()
                t_lang = (t.get('lang') or '').strip().lower()
                if t_id is not None and (
                    (norm_label and t_title == norm_label)
                    or (norm_lang and norm_lang != 'und' and t_lang == norm_lang)
                ):
                    try:
                        self._mpv.command('sub-remove', t_id)
                    except Exception:
                        pass
        except Exception:
            pass

    def _add_local_subtitle(self, path: str, label: str = 'Subtitle', lang: str = 'eng', select: bool = True):
        try:
            if not self._mpv:
                return
            file_loaded = False
            try:
                file_loaded = bool(self._mpv.filename)
            except Exception:
                file_loaded = False

            if not file_loaded:
                # Replace any existing pending entry for the same label/lang
                self._pending_local_subs = [
                    item for item in self._pending_local_subs
                    if item[1] != label and (not lang or item[2] != lang)
                ]
                self._pending_local_subs.append((path, label, lang, select))
                logger.info(f"Queued local subtitle track (waiting for video load): {label} ({path})")
                return

            self._remove_existing_sub_track(label, lang)
            self._current_sub_path = path
            mode = 'select' if select else 'auto'
            self._mpv.command('sub-add', path, mode, label, lang)
            if select:
                try:
                    tracks = self.get_sub_tracks()
                    if tracks:
                        self._mpv['sid'] = tracks[-1]['id']
                except Exception:
                    pass
            logger.info(f"Added local subtitle track: {label} ({path}) mode={mode}")
            if hasattr(self, '_on_sub_loaded') and callable(self._on_sub_loaded):
                self._on_sub_loaded(path, label, lang)
        except Exception as e:
            logger.debug(f"Could not add local subtitle {path}: {e}")

    def _flush_pending_local_subs(self):
        if not getattr(self, '_pending_local_subs', None) or not self._mpv:
            return
        try:
            if not self._mpv.filename:
                return
        except Exception:
            return

        logger.info(f"Flushing {len(self._pending_local_subs)} pending local subtitles")
        pending = list(self._pending_local_subs)
        self._pending_local_subs.clear()
        for path, label, lang, select in pending:
            self._add_local_subtitle(path, label, lang, select=select)


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
        try:
            self._mpv.pause = True
        except Exception:
            pass

    def resume(self):
        try:
            self._mpv.pause = False
        except Exception:
            pass

    def toggle_pause(self):
        try:
            self._mpv.pause = not self._mpv.pause
            return self._mpv.pause
        except Exception:
            return False

    def seek(self, seconds, reference='relative'):
        try:
            self._mpv.seek(seconds, reference=reference)
        except Exception:
            pass

    def set_volume(self, volume):
        try:
            v = max(0.0, min(130.0, float(volume)))
            self._mpv.volume = v
            if v > 0 and self.is_muted():
                self._mpv.mute = False
        except Exception:
            pass

    def get_volume(self):
        try:
            val = self._mpv.volume
            return 100.0 if val is None else float(val)
        except Exception:
            return 100.0

    def toggle_mute(self):
        try:
            self._mpv.mute = not self._mpv.mute
            return self._mpv.mute
        except Exception:
            return False

    def is_muted(self):
        try:
            return bool(self._mpv.mute)
        except Exception:
            return False

    def set_sub_delay(self, seconds: float):
        try:
            self._mpv.sub_delay = round(seconds, 2)
        except Exception:
            pass

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

    def set_sub_speed(self, multiplier: float):
        try:
            self._mpv.sub_speed = round(multiplier, 4)
        except Exception:
            pass

    def get_sub_speed(self) -> float:
        try:
            return float(self._mpv.sub_speed or 1.0)
        except Exception:
            return 1.0

    def adjust_sub_speed(self, delta: float) -> float:
        current = self.get_sub_speed()
        new_val = round(current + delta, 4)
        self.set_sub_speed(new_val)
        return new_val

    def set_sub_pos(self, pos: int):
        try:
            clamped = max(50, min(int(pos), 100))
            self._mpv.sub_pos = clamped
            from showberry.services.settings import SettingsService
            SettingsService().sub_pos = clamped
        except Exception:
            pass

    def get_sub_pos(self) -> int:
        try:
            return int(self._mpv.sub_pos or 94)
        except Exception:
            return 94

    def adjust_sub_pos(self, delta: int) -> int:
        current = self.get_sub_pos()
        new_val = max(50, min(current + delta, 100))
        self.set_sub_pos(new_val)
        return new_val

    def set_sub_scale(self, scale: float):
        try:
            clamped = round(max(0.5, min(float(scale), 2.5)), 2)
            self._mpv.sub_scale = clamped
            from showberry.services.settings import SettingsService
            SettingsService().sub_scale = clamped
        except Exception:
            pass

    def get_sub_scale(self) -> float:
        try:
            return float(self._mpv.sub_scale or 1.0)
        except Exception:
            return 1.0

    def adjust_sub_scale(self, delta: float) -> float:
        current = self.get_sub_scale()
        new_val = round(max(0.5, min(current + delta, 2.5)), 2)
        self.set_sub_scale(new_val)
        return new_val

    def set_sub_font_size(self, size: int):
        try:
            clamped = max(12, min(int(size), 72))
            self._mpv.sub_scale = 1.0
            self._mpv.sub_font_size = clamped
            from showberry.services.settings import SettingsService
            SettingsService().sub_scale = 1.0
            SettingsService().sub_font_size = clamped
        except Exception:
            pass

    def get_sub_font_size(self) -> int:
        try:
            return int(self._mpv.sub_font_size or 28)
        except Exception:
            return 28

    def adjust_sub_font_size(self, delta: int) -> int:
        current = self.get_sub_font_size()
        new_val = max(12, min(current + delta, 72))
        self.set_sub_font_size(new_val)
        return new_val

    def get_audio_tracks(self) -> List[Dict[str, Any]]:
        """Get list of all available audio tracks."""
        tracks = []
        try:
            track_list = self._mpv.track_list or []
            for t in track_list:
                if t.get('type') == 'audio':
                    tracks.append({
                        'id': t.get('id'),
                        'title': t.get('title') or t.get('lang') or f"Track {t.get('id')}",
                        'lang': t.get('lang', ''),
                        'codec': t.get('codec', ''),
                        'channels': t.get('audio-channels', ''),
                        'selected': bool(t.get('selected', False)),
                    })
        except Exception as e:
            logger.warning(f"Error fetching audio tracks: {e}")
        return tracks

    def set_audio_track(self, track_id: Any):
        """Select an audio track ID or 'no'/'auto'."""
        try:
            self._mpv['aid'] = track_id
        except Exception as e:
            logger.warning(f"Error selecting audio track {track_id}: {e}")

    def get_audio_track(self):
        try:
            return self._mpv['aid']
        except Exception:
            return 'auto'

    def cycle_audio_track(self) -> Optional[Dict[str, Any]]:
        """Cycle to the next audio track and return its metadata."""
        tracks = self.get_audio_tracks()
        if not tracks:
            return None
        current_aid = self.get_audio_track()
        curr_idx = -1
        for i, t in enumerate(tracks):
            if str(t['id']) == str(current_aid) or (current_aid == 'auto' and t.get('selected')):
                curr_idx = i
                break
        next_idx = (curr_idx + 1) % len(tracks)
        target = tracks[next_idx]
        self.set_audio_track(target['id'])
        return target

    def get_speed(self) -> float:
        """Get current playback speed."""
        try:
            val = self._mpv.speed
            return float(val) if val is not None else 1.0
        except Exception:
            return 1.0

    def set_speed(self, speed: float) -> float:
        """Set playback speed clamped between 0.25x and 3.0x."""
        try:
            s = max(0.25, min(3.0, round(float(speed), 2)))
            self._mpv.speed = s
            return s
        except Exception:
            return 1.0

    def adjust_speed(self, delta: float) -> float:
        """Adjust playback speed by delta."""
        new_speed = round(self.get_speed() + delta, 2)
        return self.set_speed(new_speed)

    def cycle_aspect_ratio(self) -> str:
        """Cycle through aspect ratio / zoom modes."""
        if not hasattr(self, '_aspect_mode_idx'):
            self._aspect_mode_idx = 0
        self._aspect_mode_idx = (self._aspect_mode_idx + 1) % len(ASPECT_MODES)
        label, aspect_override, panscan = ASPECT_MODES[self._aspect_mode_idx]
        try:
            self._mpv['video-aspect-override'] = aspect_override
            self._mpv['panscan'] = panscan
        except Exception as e:
            logger.warning(f"Error setting aspect ratio: {e}")
        return label

    def get_aspect_ratio_mode(self) -> str:
        idx = getattr(self, '_aspect_mode_idx', 0)
        return ASPECT_MODES[idx][0]

    def get_position(self):
        try:
            return self._mpv.time_pos or 0
        except Exception:
            return 0

    def get_duration(self):
        try:
            return self._mpv.duration or 0
        except Exception:
            return 0

    def is_paused(self):
        try:
            return bool(self._mpv.pause)
        except Exception:
            return False

    def stop(self):
        if getattr(self, '_unpause_watchdog_id', None):
            GLib.source_remove(self._unpause_watchdog_id)
            self._unpause_watchdog_id = None
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
    """Vidy-style popover menu for selecting subtitles, searching OpenSubtitles, and appearance controls."""

    def __init__(
        self,
        player: Optional[MpvWidget] = None,
        on_timing_changed=None,
        on_upload_requested=None,
        on_refresh_requested=None,
        on_auto_sync=None,
        on_select_builtin=None,
    ):
        super().__init__()
        self.add_css_class('player-popover')
        self.add_css_class('sub-popover')
        self._player = player
        self._on_timing_changed = on_timing_changed
        self._on_upload_requested = on_upload_requested
        self._on_refresh_requested = on_refresh_requested
        self._on_auto_sync = on_auto_sync
        self._on_select_builtin = on_select_builtin
        self._available_subtitles: List[Dict[str, Any]] = []
        self._provider_subtitles: List[Dict[str, Any]] = []
        self._language_subtitles: List[Dict[str, Any]] = []
        self._on_select_external = None

        self._is_searching = False
        self._search_error: Optional[str] = None
        self._search_attempted = False

        self._updating_size = False
        self._updating_pos = False

        # Stack to hold Main, Search, and Appearance views
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_transition_duration(200)
        self._stack.set_vhomogeneous(False)
        self._stack.set_hhomogeneous(False)
        self._stack.set_interpolate_size(True)

        # Build views
        self._main_view = self._build_main_view()
        self._search_view = self._build_search_view()
        self._appearance_view = self._build_appearance_view()

        # Aliases for backward compatibility with existing tests/callers
        self._delay_label = self._delay_val_label
        self._pos_label = self._pos_val_label
        self._scale_label = self._size_val_label

        self._stack.add_named(self._main_view, 'main')
        self._stack.add_named(self._search_view, 'search')
        self._stack.add_named(self._appearance_view, 'appearance')

        self.set_child(self._stack)
        self.connect('map', self._on_show)

    def _build_main_view(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(14)
        box.set_margin_end(14)
        box.set_size_request(300, -1)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="Subtitles")
        title.add_css_class('heading')
        title.set_xalign(0)
        title.set_hexpand(True)
        header.append(title)
        box.append(header)

        # Tracks list inside scrolled window
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_max_content_height(190)
        self._scroll.set_propagate_natural_height(True)

        self._tracks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._scroll.set_child(self._tracks_box)
        box.append(self._scroll)

        # Upload Subtitles button
        upload_btn = Gtk.Button()
        upload_btn.add_css_class('flat')
        upload_btn.add_css_class('sub-upload-btn')
        upload_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        upload_box.set_halign(Gtk.Align.CENTER)
        up_icon = Gtk.Image.new_from_icon_name('document-open-symbolic')
        up_label = Gtk.Label(label="Upload Subtitles")
        upload_box.append(up_icon)
        upload_box.append(up_label)
        upload_btn.set_child(upload_box)
        upload_btn.connect('clicked', self._on_upload_clicked)
        box.append(upload_btn)

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Navigation row 1: Search OpenSubtitles
        nav_search_btn = Gtk.Button()
        nav_search_btn.add_css_class('flat')
        nav_search_btn.add_css_class('sub-nav-btn')
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        search_icon = Gtk.Image.new_from_icon_name('system-search-symbolic')
        search_lbl = Gtk.Label(label="Search OpenSubtitles")
        search_lbl.set_xalign(0)
        search_lbl.set_hexpand(True)

        self._nav_search_badge = Gtk.Label(label="")
        self._nav_search_badge.add_css_class('sub-badge')
        self._nav_search_badge.set_visible(False)

        search_arrow = Gtk.Image.new_from_icon_name('go-next-symbolic')

        search_row.append(search_icon)
        search_row.append(search_lbl)
        search_row.append(self._nav_search_badge)
        search_row.append(search_arrow)
        nav_search_btn.set_child(search_row)
        nav_search_btn.connect('clicked', lambda b: self._go_to_search())
        box.append(nav_search_btn)

        # Navigation row 2: Customize Appearance
        nav_app_btn = Gtk.Button()
        nav_app_btn.add_css_class('flat')
        nav_app_btn.add_css_class('sub-nav-btn')
        app_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        app_icon = Gtk.Image.new_from_icon_name('preferences-system-symbolic')
        app_lbl = Gtk.Label(label="Customize Appearance")
        app_lbl.set_xalign(0)
        app_lbl.set_hexpand(True)

        app_arrow = Gtk.Image.new_from_icon_name('go-next-symbolic')

        app_row.append(app_icon)
        app_row.append(app_lbl)
        app_row.append(app_arrow)
        nav_app_btn.set_child(app_row)
        nav_app_btn.connect('clicked', lambda b: self._go_to_appearance())
        box.append(nav_app_btn)

        return box

    def _build_search_view(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(14)
        box.set_margin_end(14)
        box.set_size_request(300, -1)

        # Header with Back button, Title, and Reload button
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        back_btn = Gtk.Button.new_from_icon_name('go-previous-symbolic')
        back_btn.add_css_class('flat')
        back_btn.set_tooltip_text("Back to Subtitles")
        back_btn.connect('clicked', lambda b: self._stack.set_visible_child_name('main'))
        header.append(back_btn)

        title = Gtk.Label(label="OpenSubtitles")
        title.add_css_class('heading')
        title.set_xalign(0)
        title.set_hexpand(True)
        header.append(title)

        reload_btn = Gtk.Button.new_from_icon_name('view-refresh-symbolic')
        reload_btn.add_css_class('flat')
        reload_btn.set_tooltip_text("Refresh OpenSubtitles")
        reload_btn.connect('clicked', lambda b: self._on_reload_search())
        header.append(reload_btn)

        box.append(header)

        # Search Entry
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Search language or release...")
        self._search_entry.connect('search-changed', lambda e: self._populate_search_results())
        box.append(self._search_entry)

        # Scrolled Results List
        self._search_scroll = Gtk.ScrolledWindow()
        self._search_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._search_scroll.set_max_content_height(220)
        self._search_scroll.set_propagate_natural_height(True)

        self._search_results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._search_scroll.set_child(self._search_results_box)
        box.append(self._search_scroll)

        return box

    def _build_appearance_view(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(14)
        box.set_margin_end(14)
        box.set_size_request(300, -1)

        # Header with Back button, Title, and Reset button
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        back_btn = Gtk.Button.new_from_icon_name('go-previous-symbolic')
        back_btn.add_css_class('flat')
        back_btn.set_tooltip_text("Back to Subtitles")
        back_btn.connect('clicked', lambda b: self._stack.set_visible_child_name('main'))
        header.append(back_btn)

        title = Gtk.Label(label="Appearance")
        title.add_css_class('heading')
        title.set_xalign(0)
        title.set_hexpand(True)
        header.append(title)

        reset_btn = Gtk.Button.new_from_icon_name('edit-undo-symbolic')
        reset_btn.add_css_class('flat')
        reset_btn.set_tooltip_text("Reset Subtitle Appearance")
        reset_btn.connect('clicked', lambda b: self._reset_appearance())
        header.append(reset_btn)
        box.append(header)

        # Section 1: Font Size
        size_hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        size_lbl = Gtk.Label(label="Font Size")
        size_lbl.set_xalign(0)
        size_lbl.set_hexpand(True)
        size_lbl.add_css_class('dim-label')
        size_lbl.add_css_class('caption')

        self._size_val_label = Gtk.Label(label="28px")
        self._size_val_label.add_css_class('sub-badge')

        size_hdr_box.append(size_lbl)
        size_hdr_box.append(self._size_val_label)
        box.append(size_hdr_box)

        size_ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sc_dn_btn = Gtk.Button(label="A⁻")
        sc_dn_btn.add_css_class('flat')
        sc_dn_btn.add_css_class('sub-stepper-btn')
        sc_dn_btn.set_tooltip_text("Smaller Subtitles")
        sc_dn_btn.connect('clicked', lambda b: self._adjust_font_size(-2))
        size_ctrl_box.append(sc_dn_btn)

        self._size_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 12, 60, 2)
        self._size_scale.set_hexpand(True)
        self._size_scale.set_draw_value(False)
        self._size_scale.set_value(28)
        self._size_scale.connect('value-changed', self._on_size_scale_changed)
        size_ctrl_box.append(self._size_scale)

        sc_up_btn = Gtk.Button(label="A⁺")
        sc_up_btn.add_css_class('flat')
        sc_up_btn.add_css_class('sub-stepper-btn')
        sc_up_btn.set_tooltip_text("Larger Subtitles")
        sc_up_btn.connect('clicked', lambda b: self._adjust_font_size(2))
        size_ctrl_box.append(sc_up_btn)
        box.append(size_ctrl_box)

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Section 2: Position (Vertical Alignment)
        pos_hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pos_lbl = Gtk.Label(label="Position")
        pos_lbl.set_xalign(0)
        pos_lbl.set_hexpand(True)
        pos_lbl.add_css_class('dim-label')
        pos_lbl.add_css_class('caption')

        self._pos_val_label = Gtk.Label(label="94%")
        self._pos_val_label.add_css_class('sub-badge')

        pos_hdr_box.append(pos_lbl)
        pos_hdr_box.append(self._pos_val_label)
        box.append(pos_hdr_box)

        pos_ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pos_up_btn = Gtk.Button(label="⤒")
        pos_up_btn.add_css_class('flat')
        pos_up_btn.add_css_class('sub-stepper-btn')
        pos_up_btn.set_tooltip_text("Raise Subtitles")
        pos_up_btn.connect('clicked', lambda b: self._adjust_pos(-2))
        pos_ctrl_box.append(pos_up_btn)

        self._pos_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 60, 100, 1)
        self._pos_scale.set_hexpand(True)
        self._pos_scale.set_draw_value(False)
        self._pos_scale.set_value(94)
        self._pos_scale.connect('value-changed', self._on_pos_scale_changed)
        pos_ctrl_box.append(self._pos_scale)

        pos_dn_btn = Gtk.Button(label="⤓")
        pos_dn_btn.add_css_class('flat')
        pos_dn_btn.add_css_class('sub-stepper-btn')
        pos_dn_btn.set_tooltip_text("Lower Subtitles")
        pos_dn_btn.connect('clicked', lambda b: self._adjust_pos(2))
        pos_ctrl_box.append(pos_dn_btn)
        box.append(pos_ctrl_box)

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Section 3: Delay
        delay_hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        delay_lbl = Gtk.Label(label="Delay")
        delay_lbl.set_xalign(0)
        delay_lbl.set_hexpand(True)
        delay_lbl.add_css_class('dim-label')
        delay_lbl.add_css_class('caption')

        self._delay_val_label = Gtk.Label(label="0.0s")
        self._delay_val_label.add_css_class('sub-badge')

        delay_hdr_box.append(delay_lbl)
        delay_hdr_box.append(self._delay_val_label)
        box.append(delay_hdr_box)

        timing_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        timing_btn_box.set_halign(Gtk.Align.CENTER)

        for btn_label, delta in [("−0.5s", -0.5), ("−0.1s", -0.1), ("0.0s", 0.0), ("+0.1s", 0.1), ("+0.5s", 0.5)]:
            t_btn = Gtk.Button(label=btn_label)
            t_btn.add_css_class('flat')
            t_btn.add_css_class('sub-stepper-btn')
            if delta == 0.0:
                t_btn.connect('clicked', lambda b: self._set_timing(0.0))
            else:
                t_btn.connect('clicked', lambda b, d=delta: self._adjust_timing(d))
            timing_btn_box.append(t_btn)
        box.append(timing_btn_box)

        return box

    def set_player(self, player: MpvWidget):
        self._player = player

    def set_searching(self, is_searching: bool = True):
        self._is_searching = is_searching
        if is_searching:
            self._search_error = None
            self._search_attempted = True
        self._populate_search_results()

    def set_search_error(self, error: Optional[str] = None):
        self._is_searching = False
        self._search_error = error
        self._search_attempted = True
        self._populate_search_results()

    def set_provider_subtitles(self, subs: List[Dict[str, Any]], on_select_builtin=None):
        self._provider_subtitles = list(subs or [])
        if on_select_builtin:
            self._on_select_builtin = on_select_builtin
        self.refresh_tracks()

    def set_language_subtitles(self, subs: List[Dict[str, Any]], on_select_external=None):
        self._language_subtitles = list(subs or [])
        if on_select_external:
            self._on_select_external = on_select_external
        self.refresh_tracks()

    def set_available_subtitles(self, subs: List[Dict[str, Any]], on_select_external=None):
        self._is_searching = False
        self._search_error = None
        self._search_attempted = True
        self._available_subtitles = subs or []
        if on_select_external:
            self._on_select_external = on_select_external
        if hasattr(self, '_nav_search_badge'):
            count = len(self._available_subtitles)
            self._nav_search_badge.set_visible(count > 0)
            self._nav_search_badge.set_text(str(count))
        self._populate_search_results()

    def _on_show(self, *_):
        self._stack.set_visible_child_name('main')
        self.refresh_tracks()
        self.refresh_appearance()

    def _go_to_search(self):
        if not self._available_subtitles and not getattr(self, '_is_searching', False) and not getattr(self, '_search_attempted', False):
            self._on_reload_search()
        else:
            self._populate_search_results()
        self._stack.set_visible_child_name('search')
        self._search_entry.grab_focus()

    def _on_reload_search(self):
        self.set_searching(True)
        if self._on_refresh_requested:
            self._on_refresh_requested()

    def _go_to_appearance(self):
        self.refresh_appearance()
        self._stack.set_visible_child_name('appearance')

    def _on_upload_clicked(self, _):
        self.popdown()
        if self._on_upload_requested:
            self._on_upload_requested()

    def refresh_tracks(self):
        self._refreshing_tracks = True
        try:
            while True:
                child = self._tracks_box.get_first_child()
                if child is None:
                    break
                self._tracks_box.remove(child)

            tracks = self._player.get_sub_tracks() if self._player else []
            current_sid = self._player.get_sub_track() if self._player else 'no'
            pending_lbl = getattr(self, '_pending_selected_label', None)
            is_off = (current_sid in ('no', False, None, 0)) and not pending_lbl

            # "Off" button
            off_btn = Gtk.CheckButton(label="Off")
            off_btn.set_active(is_off)
            off_btn.connect('toggled', self._on_track_toggled, 'no')
            self._tracks_box.append(off_btn)
            group = off_btn

            from showberry.services.subtitles import LANG_FLAGS, LANG_NAMES
            loaded_langs = set()
            loaded_titles = set()

            has_named_subs = (
                any(
                    bool((tr.get('title') or '').strip())
                    and not (tr.get('title') or '').strip().lower().startswith('track ')
                    for tr in tracks
                )
                or bool(getattr(self, '_provider_subtitles', []))
                or bool(getattr(self, '_language_subtitles', []))
            )

            # Deduplicate tracks so if MPV briefly holds two tracks for the same title/lang, the newest/selected one wins
            deduped_tracks = []
            seen_track_keys = set()
            for t in reversed(tracks):
                raw_t = (t.get('title') or '').replace('(Built-in)', '').strip().lower()
                l_code = (t.get('lang') or '').strip().lower()
                key = l_code if (l_code and l_code != 'und') else raw_t
                if key and key in seen_track_keys:
                    continue
                if key:
                    seen_track_keys.add(key)
                deduped_tracks.append(t)
            deduped_tracks.reverse()

            for t in deduped_tracks:
                tid = t['id']
                raw_title = (t.get('title') or '').replace('(Built-in)', '').strip()
                lang_code = (t.get('lang') or '').lower()

                if not raw_title or raw_title.lower().startswith('track '):
                    if lang_code and lang_code in LANG_NAMES:
                        flag = LANG_FLAGS.get(lang_code, '🌐')
                        title = f"{flag} {LANG_NAMES[lang_code]}"
                    else:
                        if has_named_subs:
                            continue
                        title = f"Track {tid}"
                elif lang_code and lang_code in LANG_NAMES:
                    flag = LANG_FLAGS.get(lang_code, '')
                    if flag and flag not in raw_title:
                        title = f"{flag} {raw_title}"
                    else:
                        title = raw_title
                else:
                    title = raw_title

                clean_title = title.strip().lower()
                if clean_title in loaded_titles or (lang_code and lang_code != 'und' and lang_code in loaded_langs):
                    continue

                if lang_code and lang_code != 'und':
                    loaded_langs.add(lang_code)
                loaded_titles.add(clean_title)
                if raw_title:
                    loaded_titles.add(raw_title.strip().lower())

                btn = Gtk.CheckButton(label=title)
                btn.set_group(group)
                is_track_selected = not is_off and (t.get('selected') or str(current_sid) == str(tid))
                if pending_lbl:
                    if clean_title == pending_lbl:
                        btn.set_active(True)
                        if is_track_selected:
                            self._pending_selected_label = None
                elif is_track_selected:
                    btn.set_active(True)
                btn.connect('toggled', self._on_track_toggled, tid)
                self._tracks_box.append(btn)

            # Provider built-in subtitles not yet loaded into MPV
            for ps in getattr(self, '_provider_subtitles', []):
                lang = (ps.get('lang') or '').lower()
                lang_name = ps.get('lang_name') or LANG_NAMES.get(lang, lang.capitalize())
                flag = ps.get('flag') or LANG_FLAGS.get(lang, '🌐')
                display_label = f"{flag} {lang_name}".strip()

                clean_disp = display_label.lower()
                clean_name = lang_name.lower()
                if lang in loaded_langs or any(clean_name in lt or clean_disp in lt for lt in loaded_titles):
                    continue

                loaded_langs.add(lang)
                loaded_titles.add(clean_disp)

                btn = Gtk.CheckButton(label=display_label)
                btn.set_group(group)
                if pending_lbl and clean_disp == pending_lbl:
                    btn.set_active(True)
                btn.connect('toggled', self._on_builtin_track_toggled, ps)
                self._tracks_box.append(btn)

            # Unique language subtitles from OpenSubtitles for quick language selection
            for ls in getattr(self, '_language_subtitles', []):
                lang = (ls.get('lang') or '').lower()
                lang_name = ls.get('lang_name') or LANG_NAMES.get(lang, lang.capitalize())
                flag = ls.get('flag') or LANG_FLAGS.get(lang, '🌐')
                display_label = f"{flag} {lang_name}".strip()

                clean_disp = display_label.lower()
                clean_name = lang_name.lower()
                if lang in loaded_langs or any(clean_name in lt or clean_disp in lt for lt in loaded_titles):
                    continue

                loaded_langs.add(lang)
                loaded_titles.add(clean_disp)

                btn = Gtk.CheckButton(label=display_label)
                btn.set_group(group)
                if pending_lbl and clean_disp == pending_lbl:
                    btn.set_active(True)
                btn.connect('toggled', self._on_language_track_toggled, ls)
                self._tracks_box.append(btn)

            has_any_subs = bool(tracks or getattr(self, '_provider_subtitles', []) or getattr(self, '_language_subtitles', []))
            if not has_any_subs:
                if self._player and getattr(self._player, '_pending_local_subs', None):
                    loading_lbl = Gtk.Label(label="Loading subtitle...")
                    loading_lbl.add_css_class('dim-label')
                    loading_lbl.add_css_class('caption')
                    loading_lbl.set_margin_top(4)
                    loading_lbl.set_margin_bottom(4)
                    self._tracks_box.append(loading_lbl)
                else:
                    no_subs = Gtk.Label(label="No subtitles loaded yet")
                    no_subs.add_css_class('dim-label')
                    no_subs.add_css_class('caption')
                    no_subs.set_margin_top(4)
                    no_subs.set_margin_bottom(4)
                    self._tracks_box.append(no_subs)
        finally:
            self._refreshing_tracks = False

    def _on_builtin_track_toggled(self, button, sub_data):
        if getattr(self, '_refreshing_tracks', False):
            return
        if button.get_active() and self._on_select_builtin:
            label_text = (button.get_label() or "Subtitle").strip()
            self._pending_selected_label = label_text.lower()
            self._on_select_builtin(sub_data)
            if self._on_timing_changed:
                self._on_timing_changed(None, f"Subtitle: {label_text}")

    def _on_language_track_toggled(self, button, sub_data):
        if getattr(self, '_refreshing_tracks', False):
            return
        if button.get_active() and self._on_select_external:
            label_text = (button.get_label() or "Subtitle").strip()
            self._pending_selected_label = label_text.lower()
            self._on_select_external(sub_data)
            if self._on_timing_changed:
                self._on_timing_changed(None, f"Subtitle: {label_text}")

    def _on_track_toggled(self, button, track_id):
        if getattr(self, '_refreshing_tracks', False):
            return
        if button.get_active() and self._player:
            self._pending_selected_label = None
            self._player.set_sub_track(track_id)
            if self._on_timing_changed:
                label_text = button.get_label() or "Subtitle"
                self._on_timing_changed(None, f"Subtitle: {label_text}")

    def _populate_search_results(self):
        while True:
            child = self._search_results_box.get_first_child()
            if child is None:
                break
            self._search_results_box.remove(child)

        query = self._search_entry.get_text() if hasattr(self, '_search_entry') else ""
        from showberry.services.subtitles import SubtitleService
        filtered = SubtitleService().filter_subtitles(self._available_subtitles, query)

        # 1. Active searching state
        if getattr(self, '_is_searching', False):
            search_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            search_box.set_halign(Gtk.Align.CENTER)
            search_box.set_margin_top(24)
            search_box.set_margin_bottom(24)

            spinner = Gtk.Spinner()
            spinner.start()
            search_box.append(spinner)

            search_lbl = Gtk.Label(label="Searching OpenSubtitles...")
            search_lbl.add_css_class('dim-label')
            search_lbl.add_css_class('caption')
            search_box.append(search_lbl)

            self._search_results_box.append(search_box)
            return

        # 2. Error state
        if getattr(self, '_search_error', None):
            err_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            err_box.set_halign(Gtk.Align.CENTER)
            err_box.set_margin_top(20)
            err_box.set_margin_bottom(20)

            err_lbl = Gtk.Label(label=self._search_error)
            err_lbl.add_css_class('dim-label')
            err_lbl.add_css_class('caption')
            err_box.append(err_lbl)

            retry_btn = Gtk.Button(label="↻ Retry")
            retry_btn.add_css_class('flat')
            retry_btn.add_css_class('pill')
            retry_btn.connect('clicked', lambda b: self._on_reload_search())
            err_box.append(retry_btn)

            self._search_results_box.append(err_box)
            return

        # 3. Empty results (no subtitles found)
        if not self._available_subtitles:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            empty_box.set_halign(Gtk.Align.CENTER)
            empty_box.set_margin_top(20)
            empty_box.set_margin_bottom(20)

            empty_lbl = Gtk.Label(label="No subtitles found on OpenSubtitles")
            empty_lbl.add_css_class('dim-label')
            empty_lbl.add_css_class('caption')
            empty_box.append(empty_lbl)

            retry_btn = Gtk.Button(label="↻ Search Again")
            retry_btn.add_css_class('flat')
            retry_btn.add_css_class('pill')
            retry_btn.connect('clicked', lambda b: self._on_reload_search())
            empty_box.append(retry_btn)

            self._search_results_box.append(empty_box)
            return

        # 4. Search query produced no matches
        if not filtered:
            no_match = Gtk.Label(label=f"No subtitles matching '{query}'" if query else "No matching subtitles")
            no_match.add_css_class('dim-label')
            no_match.add_css_class('caption')
            no_match.set_margin_top(20)
            no_match.set_margin_bottom(20)
            self._search_results_box.append(no_match)
            return

        # 5. Render results
        for sub in filtered[:50]:
            btn = Gtk.Button()
            btn.add_css_class('flat')
            btn.add_css_class('sub-result-btn')

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.set_hexpand(True)

            flag = sub.get('flag', '🌐')
            flag_lbl = Gtk.Label(label=flag)

            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text_box.set_hexpand(True)

            lang_lbl = Gtk.Label(label=sub.get('lang_name') or sub.get('lang', 'Unknown'))
            lang_lbl.set_xalign(0)
            lang_lbl.add_css_class('bold')
            text_box.append(lang_lbl)

            release_str = sub.get('release_name') or sub.get('label', '')
            if release_str:
                rel_lbl = Gtk.Label(label=release_str)
                rel_lbl.set_xalign(0)
                rel_lbl.add_css_class('dim-label')
                rel_lbl.add_css_class('caption')
                rel_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                text_box.append(rel_lbl)

            row.append(flag_lbl)
            row.append(text_box)
            btn.set_child(row)
            btn.connect('clicked', self._on_external_clicked, sub)
            self._search_results_box.append(btn)

    def _on_external_clicked(self, button, sub):
        button.set_sensitive(False)
        from showberry.services.subtitles import LANG_FLAGS, LANG_NAMES
        lang = (sub.get('lang') or 'eng').lower()
        lang_name = sub.get('lang_name') or LANG_NAMES.get(lang, lang.upper())
        flag = sub.get('flag') or LANG_FLAGS.get(lang, '🌐')
        self._pending_selected_label = f"{flag} {lang_name}".strip().lower()
        if self._on_select_external:
            self._on_select_external(sub)
        self.refresh_tracks()
        GLib.timeout_add(150, lambda: self._stack.set_visible_child_name('main'))

    def _reset_appearance(self):
        if self._player:
            self._player.set_sub_font_size(28)
            self._player.set_sub_pos(96)
            self._player.set_sub_delay(0.0)
            self.refresh_appearance()
            if self._on_timing_changed:
                self._on_timing_changed(0.0, "Subtitles Appearance Reset")

    def _on_size_scale_changed(self, scale):
        if getattr(self, '_updating_size', False):
            return
        val = int(scale.get_value())
        if self._player:
            self._player.set_sub_font_size(val)
        if hasattr(self, '_size_val_label'):
            self._size_val_label.set_text(f"{val}px")

    def _adjust_font_size(self, delta: int):
        if self._player:
            new_val = self._player.adjust_sub_font_size(delta)
            self._updating_size = True
            if hasattr(self, '_size_scale'):
                self._size_scale.set_value(new_val)
            self._updating_size = False
            if hasattr(self, '_size_val_label'):
                self._size_val_label.set_text(f"{new_val}px")

    def _on_pos_scale_changed(self, scale):
        if getattr(self, '_updating_pos', False):
            return
        val = int(scale.get_value())
        if self._player:
            self._player.set_sub_pos(val)
        if hasattr(self, '_pos_val_label'):
            self._pos_val_label.set_text(f"{val}%")

    def _adjust_pos(self, delta: int):
        if self._player:
            new_val = self._player.adjust_sub_pos(delta)
            self._updating_pos = True
            if hasattr(self, '_pos_scale'):
                self._pos_scale.set_value(new_val)
            self._updating_pos = False
            if hasattr(self, '_pos_val_label'):
                self._pos_val_label.set_text(f"{new_val}%")

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

    def refresh_delay_label(self):
        if self._player and hasattr(self, '_delay_val_label'):
            delay = self._player.get_sub_delay()
            sign = "+" if delay > 0 else ""
            self._delay_val_label.set_text(f"{sign}{delay:.1f}s")

    def refresh_pos_label(self):
        if self._player and hasattr(self, '_pos_val_label'):
            pos = self._player.get_sub_pos()
            self._pos_val_label.set_text(f"{pos}%")
            if hasattr(self, '_pos_scale') and not self._updating_pos:
                self._updating_pos = True
                self._pos_scale.set_value(pos)
                self._updating_pos = False

    def refresh_scale_label(self):
        if self._player and hasattr(self, '_size_val_label'):
            size = self._player.get_sub_font_size()
            self._size_val_label.set_text(f"{size}px")
            if hasattr(self, '_size_scale') and not self._updating_size:
                self._updating_size = True
                self._size_scale.set_value(size)
                self._updating_size = False

    def refresh_appearance(self):
        self.refresh_delay_label()
        self.refresh_pos_label()
        self.refresh_scale_label()


class AudioPopover(Gtk.Popover):
    """Popover menu for selecting available audio tracks."""

    def __init__(self, player: Optional[MpvWidget] = None, on_audio_changed=None):
        super().__init__()
        self.add_css_class('player-popover')
        self._player = player
        self._on_audio_changed = on_audio_changed

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._box.set_margin_top(12)
        self._box.set_margin_bottom(12)
        self._box.set_margin_start(14)
        self._box.set_margin_end(14)
        self._box.set_size_request(250, -1)

        # Header with Title and Refresh button
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_label = Gtk.Label(label="Audio Tracks")
        title_label.add_css_class('heading')
        title_label.set_xalign(0)
        title_label.set_hexpand(True)
        header_box.append(title_label)

        refresh_btn = Gtk.Button.new_from_icon_name('view-refresh-symbolic')
        refresh_btn.add_css_class('flat')
        refresh_btn.set_tooltip_text("Reload audio tracks")
        refresh_btn.connect('clicked', lambda b: self.refresh_tracks())
        header_box.append(refresh_btn)
        self._box.append(header_box)

        # Scrolled tracks container
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_max_content_height(200)
        self._scroll.set_propagate_natural_height(True)

        self._tracks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._scroll.set_child(self._tracks_box)
        self._box.append(self._scroll)

        self.set_child(self._box)
        self.connect('show', self._on_show)

    def set_player(self, player: MpvWidget):
        self._player = player

    def _on_show(self, *_):
        self.refresh_tracks()

    def refresh_tracks(self):
        while True:
            child = self._tracks_box.get_first_child()
            if child is None:
                break
            self._tracks_box.remove(child)

        if not self._player:
            return

        tracks = self._player.get_audio_tracks()
        current_aid = self._player.get_audio_track()

        first_btn = None
        for track in tracks:
            title = track.get('title') or 'Audio Track'
            codec = track.get('codec') or ''
            channels = track.get('channels')
            detail_parts = []
            if codec:
                detail_parts.append(codec.upper())
            if channels:
                detail_parts.append(f"{channels}ch")
            details = f" ({' • '.join(detail_parts)})" if detail_parts else ""

            label = f"{title}{details}"
            btn = Gtk.CheckButton.new_with_label(label)
            btn.add_css_class('flat')
            if first_btn is None:
                first_btn = btn
            else:
                btn.set_group(first_btn)

            is_active = (str(track['id']) == str(current_aid)) or (current_aid == 'auto' and track.get('selected'))
            if is_active:
                btn.set_active(True)

            btn.connect('toggled', self._on_track_toggled, track['id'], label)
            self._tracks_box.append(btn)

        if not tracks:
            no_audio = Gtk.Label(label="No audio tracks found")
            no_audio.add_css_class('dim-label')
            no_audio.add_css_class('caption')
            no_audio.set_margin_top(4)
            no_audio.set_margin_bottom(4)
            self._tracks_box.append(no_audio)

    def _on_track_toggled(self, button, track_id, track_label):
        if button.get_active() and self._player:
            self._player.set_audio_track(track_id)
            if self._on_audio_changed:
                self._on_audio_changed(f"Audio: {track_label}")


class SpeedPopover(Gtk.Popover):
    """Popover menu for selecting playback speed."""

    SPEED_OPTIONS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

    def __init__(self, player: Optional[MpvWidget] = None, on_speed_changed=None):
        super().__init__()
        self.add_css_class('player-popover')
        self._player = player
        self._on_speed_changed = on_speed_changed

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._box.set_margin_top(10)
        self._box.set_margin_bottom(10)
        self._box.set_margin_start(12)
        self._box.set_margin_end(12)
        self._box.set_size_request(160, -1)

        title_label = Gtk.Label(label="Playback Speed")
        title_label.add_css_class('heading')
        title_label.set_xalign(0)
        self._box.append(title_label)

        self._options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._box.append(self._options_box)

        self.set_child(self._box)
        self.connect('show', self._on_show)

    def set_player(self, player: MpvWidget):
        self._player = player

    def _on_show(self, *_):
        self.refresh_speeds()

    def refresh_speeds(self):
        while True:
            child = self._options_box.get_first_child()
            if child is None:
                break
            self._options_box.remove(child)

        current_speed = self._player.get_speed() if self._player else 1.0

        first_btn = None
        for spd in self.SPEED_OPTIONS:
            label = f"{spd}x" if spd != 1.0 else "1.0x (Normal)"
            btn = Gtk.CheckButton.new_with_label(label)
            btn.add_css_class('flat')
            if first_btn is None:
                first_btn = btn
            else:
                btn.set_group(first_btn)

            if abs(current_speed - spd) < 0.05:
                btn.set_active(True)

            btn.connect('toggled', self._on_speed_toggled, spd)
            self._options_box.append(btn)

    def _on_speed_toggled(self, button, speed_val):
        if button.get_active() and self._player:
            self._player.set_speed(speed_val)
            if self._on_speed_changed:
                self._on_speed_changed(speed_val)


class ProviderPopover(Gtk.Popover):
    """Popover menu for switching stream provider during playback."""

    def __init__(self, on_provider_selected=None):
        super().__init__()
        self.add_css_class('player-popover')
        self.add_css_class('provider-popover')
        self._on_provider_selected = on_provider_selected
        self._current_provider = None

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._box.set_margin_top(12)
        self._box.set_margin_bottom(12)
        self._box.set_margin_start(14)
        self._box.set_margin_end(14)
        self._box.set_size_request(240, -1)

        title_label = Gtk.Label(label="Switch Provider")
        title_label.add_css_class('heading')
        title_label.set_xalign(0)
        self._box.append(title_label)

        desc_label = Gtk.Label(label="Select a provider to continue playback seamlessly")
        desc_label.add_css_class('dim-label')
        desc_label.add_css_class('caption')
        desc_label.set_xalign(0)
        desc_label.set_wrap(True)
        self._box.append(desc_label)

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_max_content_height(280)
        self._scroll.set_propagate_natural_height(True)

        self._providers_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._scroll.set_child(self._providers_box)
        self._box.append(self._scroll)

        self.set_child(self._box)
        self.connect('map', self._on_show)

    def set_current_provider(self, provider_name: Optional[str]):
        self._current_provider = provider_name
        self.refresh_providers()

    def _on_show(self, *_):
        self.refresh_providers()

    def refresh_providers(self):
        while True:
            child = self._providers_box.get_first_child()
            if child is None:
                break
            self._providers_box.remove(child)

        # 1. Auto (Best)
        auto_btn = Gtk.Button()
        auto_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        auto_lbl = Gtk.Label(label="Auto (Best)")
        auto_lbl.set_xalign(0)
        auto_lbl.set_hexpand(True)
        auto_box.append(auto_lbl)
        if not self._current_provider or self._current_provider.lower() in ('auto', 'auto (best)'):
            chk = Gtk.Image.new_from_icon_name('object-select-symbolic')
            auto_box.append(chk)
        auto_btn.set_child(auto_box)
        auto_btn.add_css_class('flat')
        auto_btn.connect('clicked', lambda b: self._select('Auto'))
        self._providers_box.append(auto_btn)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(4)
        sep.set_margin_bottom(4)
        self._providers_box.append(sep)

        # Individual providers
        from showberry.providers import get_all_providers
        from showberry.services.torrent import HAS_LIBTORRENT
        from showberry.services.settings import SettingsService
        torrent_allowed = SettingsService().torrent_enabled and HAS_LIBTORRENT
        providers = get_all_providers()
        for p in providers:
            p_name = p.name
            if 'torrent' in p_name.lower() and not torrent_allowed:
                continue
            btn = Gtk.Button()
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl = Gtk.Label(label=p_name if p_name != 'Torrent' else 'Torrent Swarms (P2P)...')
            lbl.set_xalign(0)
            lbl.set_hexpand(True)
            row_box.append(lbl)
            if self._current_provider and self._current_provider.lower() == p_name.lower():
                chk = Gtk.Image.new_from_icon_name('object-select-symbolic')
                row_box.append(chk)
            btn.set_child(row_box)
            btn.add_css_class('flat')
            btn.connect('clicked', lambda b, name=p_name: self._select(name))
            self._providers_box.append(btn)

    def _select(self, provider_name: str):
        self.popdown()
        if self._on_provider_selected:
            self._on_provider_selected(provider_name)


class PlayerControls(Gtk.Box):
    """Floating OSD player control bar with play/pause, seek, volume, subtitles."""

    __gsignals__ = {
        'close': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'fullscreen-toggle': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'timing-notification': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'next-episode': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'upload-subtitles': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'refresh-subtitles': (GObject.SignalFlags.RUN_FIRST, None, ()),
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
        self._zero_pos_ticks = 0

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

        # Seek Hover Timestamp Popover
        self._duration = 0.0
        self._seek_popover = Gtk.Popover.new()
        self._seek_popover.add_css_class('seek-popover')
        self._seek_popover.set_autohide(False)
        self._seek_popover.set_has_arrow(True)
        self._seek_popover.set_position(Gtk.PositionType.TOP)
        self._seek_popover.set_parent(self._seek_bar)

        self._seek_popover_label = Gtk.Label()
        self._seek_popover_label.add_css_class('seek-popover-label')
        self._seek_popover.set_child(self._seek_popover_label)

        # Hover motion controller for seekbar
        seek_motion = Gtk.EventControllerMotion.new()
        seek_motion.connect('enter', self._on_seek_motion_enter)
        seek_motion.connect('motion', self._on_seek_motion_move)
        seek_motion.connect('leave', self._on_seek_motion_leave)
        self._seek_bar.add_controller(seek_motion)

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

        # Next episode button (TV shows only)
        self._next_ep_btn = Gtk.Button.new_from_icon_name('media-skip-forward-symbolic')
        self._next_ep_btn.add_css_class('flat')
        self._next_ep_btn.set_tooltip_text("Next Episode (Shift+N)")
        self._next_ep_btn.set_focusable(False)
        self._next_ep_btn.set_visible(False)
        self._next_ep_btn.connect('clicked', lambda b: self.emit('next-episode'))
        controls.append(self._next_ep_btn)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        controls.append(spacer)

        # Speed selector with Popover
        self._speed_popover = SpeedPopover(on_speed_changed=self._on_speed_changed)
        self._speed_btn = Gtk.MenuButton()
        self._speed_btn.set_label("1.0x")
        self._speed_btn.add_css_class('flat')
        self._speed_btn.add_css_class('speed-button')
        self._speed_btn.set_tooltip_text("Playback Speed ([ / ])")
        self._speed_btn.set_popover(self._speed_popover)
        self._speed_btn.set_focusable(False)
        controls.append(self._speed_btn)

        # Audio Track Menu Button with Popover
        self._audio_popover = AudioPopover(on_audio_changed=self._on_audio_changed)
        self._audio_btn = Gtk.MenuButton()
        self._audio_btn.set_icon_name('audio-headphones-symbolic')
        self._audio_btn.add_css_class('flat')
        self._audio_btn.set_tooltip_text("Audio Tracks (A)")
        self._audio_btn.set_popover(self._audio_popover)
        self._audio_btn.set_focusable(False)
        controls.append(self._audio_btn)

        # Subtitle Menu Button with Popover
        self._sub_popover = SubtitlePopover(
            on_timing_changed=self._on_sub_timing_adjusted,
            on_upload_requested=lambda: self.emit('upload-subtitles'),
            on_refresh_requested=lambda: self.emit('refresh-subtitles')
        )
        self._sub_btn = Gtk.MenuButton()
        self._sub_btn.set_icon_name('media-view-subtitles-symbolic')
        self._sub_btn.add_css_class('flat')
        self._sub_btn.set_tooltip_text("Subtitles (C: Toggle, S: Menu)")
        self._sub_btn.set_popover(self._sub_popover)
        self._sub_btn.set_focusable(False)
        controls.append(self._sub_btn)

        # Volume controls
        self._volume_btn = Gtk.Button.new_from_icon_name('audio-volume-high-symbolic')
        self._volume_btn.add_css_class('flat')
        self._volume_btn.set_tooltip_text("Mute/Unmute (M)")
        self._volume_btn.set_focusable(False)
        self._volume_btn.connect('clicked', self._on_mute_clicked)
        controls.append(self._volume_btn)

        self._volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 130, 1)
        self._volume_scale.set_size_request(110, -1)
        self._volume_scale.set_value(100)
        self._volume_scale.set_draw_value(False)
        self._volume_scale.set_focusable(False)
        self._volume_scale.add_css_class('volume-boost-scale')
        self._volume_scale.connect('value-changed', self._on_volume_changed)
        controls.append(self._volume_scale)

        # Fullscreen button
        self._fullscreen_button = Gtk.Button.new_from_icon_name('view-fullscreen-symbolic')
        self._fullscreen_button.add_css_class('flat')
        self._fullscreen_button.set_tooltip_text("Toggle Fullscreen (F)")
        self._fullscreen_button.set_focusable(False)
        self._fullscreen_button.connect('clicked', lambda b: self.emit('fullscreen-toggle'))
        controls.append(self._fullscreen_button)

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

    def _on_speed_changed(self, speed: float):
        self.set_speed_label(speed)
        self.emit('timing-notification', f"Speed: {speed:.2f}x")

    def _on_audio_changed(self, msg: str):
        self.emit('timing-notification', msg)

    def set_speed_label(self, speed: float):
        spd_str = f"{speed:.2f}".rstrip('0').rstrip('.') + "x"
        self._speed_btn.set_label(spd_str)

    def refresh_audio_tracks(self):
        if hasattr(self, '_audio_popover'):
            self._audio_popover.refresh_tracks()

    def set_next_episode_visible(self, visible: bool, tooltip: Optional[str] = None):
        self._next_ep_btn.set_visible(visible)
        if tooltip:
            self._next_ep_btn.set_tooltip_text(tooltip)

    def set_player(self, player: MpvWidget):
        self._player = player
        if hasattr(self, '_sub_popover'):
            self._sub_popover.set_player(player)
        if hasattr(self, '_audio_popover'):
            self._audio_popover.set_player(player)
        if hasattr(self, '_speed_popover'):
            self._speed_popover.set_player(player)

    def set_provider_subtitles(self, subs: List[Dict[str, Any]], on_select_cb=None):
        if hasattr(self, '_sub_popover'):
            self._sub_popover.set_provider_subtitles(subs, on_select_cb)

    def set_language_subtitles(self, subs: List[Dict[str, Any]], on_select_cb=None):
        if hasattr(self, '_sub_popover'):
            self._sub_popover.set_language_subtitles(subs, on_select_cb)

    def set_available_subtitles(self, subs: List[Dict[str, Any]], on_select_cb=None):
        if hasattr(self, '_sub_popover'):
            self._sub_popover.set_available_subtitles(subs, on_select_cb)

    def set_subtitles_searching(self, is_searching: bool = True):
        if hasattr(self, '_sub_popover'):
            self._sub_popover.set_searching(is_searching)

    def set_subtitles_error(self, error: Optional[str] = None):
        if hasattr(self, '_sub_popover'):
            self._sub_popover.set_search_error(error)

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

        self._duration = total_duration
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
        self._sub_popover.set_provider_subtitles([])
        self._sub_popover.set_language_subtitles([])
        self._sub_popover.set_available_subtitles([])
        self._zero_pos_ticks = 0

    def start_update_timer(self, player: MpvWidget):
        """Start periodic updates of seek bar and time."""
        self.set_player(player)
        if self._update_id:
            GLib.source_remove(self._update_id)
            self._update_id = None
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
            if dur > 0:
                self._duration = dur

            if dur > 0 and not self._is_dragging:
                self._seek_bar.handler_block_by_func(self._on_seek_value_changed)
                self._seek_bar.set_value((pos / dur) * 100)
                self._seek_bar.handler_unblock_by_func(self._on_seek_value_changed)

                self._curr_time_label.set_text(self._format_time(pos))
                self._total_time_label.set_text(self._format_time(dur))

            # Kickstart watchdog: If MPV has loaded the media (dur > 0), has cache buffered,
            # but is sitting at 0:00 without advancing, nudge it to ensure playback starts
            if dur > 0 and pos <= 0.05 and not self._player.is_paused():
                self._zero_pos_ticks = getattr(self, '_zero_pos_ticks', 0) + 1
                if self._zero_pos_ticks >= 4:  # ~1.0-1.5 seconds stuck at 0:00
                    try:
                        cache = getattr(self._player._mpv, 'demuxer_cache_duration', 0) or 0
                        if cache > 0.5:
                            logger.info("Kickstart: nudging MPV to start playback at 0:00")
                            self._player.resume()
                            self._player.queue_render()
                    except Exception:
                        pass
            else:
                self._zero_pos_ticks = 0

            # Self-healing black screen watchdog:
            # If audio has been playing and advancing (pos >= 1.0s), but no video frame has been
            # successfully presented to the OpenGL FBO (self._player._has_drawn_first_frame is False),
            # and hardware decoding is enabled (hwdec != 'no'), automatically fall back to software decoding!
            if pos >= 1.0 and not getattr(self._player, '_has_drawn_first_frame', False):
                try:
                    cur_hwdec = self._player._mpv['hwdec']
                    if cur_hwdec != ['no'] and cur_hwdec != 'no':
                        logger.warning(
                            "Black screen watchdog: Audio is advancing (pos=%.1fs) but no video frame rendered; "
                            "automatically disabling hardware decoding (falling back to software decoding)",
                            pos
                        )
                        self._player._mpv['hwdec'] = 'no'
                        self._player.queue_render()
                except Exception:
                    pass

            # Update play/pause icon
            if self._player.is_paused():
                self._play_button.set_icon_name('media-playback-start-symbolic')
            else:
                self._play_button.set_icon_name('media-playback-pause-symbolic')
        except Exception:
            pass

        return True

    def _on_seek_motion_enter(self, controller, x, y):
        if getattr(self, '_duration', 0) > 0:
            self._update_seek_tooltip(x)

    def _on_seek_motion_move(self, controller, x, y):
        if getattr(self, '_duration', 0) > 0:
            self._update_seek_tooltip(x)

    def _on_seek_motion_leave(self, controller):
        if hasattr(self, '_seek_popover'):
            self._seek_popover.popdown()

    def _update_seek_tooltip(self, x):
        width = self._seek_bar.get_width()
        if width <= 0 or not getattr(self, '_duration', 0):
            return

        clamped_x = max(0.0, min(float(x), float(width)))
        fraction = clamped_x / float(width)
        target_time = fraction * self._duration

        self._seek_popover_label.set_text(self._format_time(target_time))

        rect = Gdk.Rectangle()
        rect.x = int(clamped_x)
        rect.y = 0
        rect.width = 1
        rect.height = max(1, self._seek_bar.get_height())
        self._seek_popover.set_pointing_to(rect)
        if not self._seek_popover.get_visible() and self.get_root():
            try:
                self._seek_popover.popup()
            except Exception:
                pass

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
        val = scale.get_value()
        if val > 100:
            scale.add_css_class('volume-boosted')
        else:
            scale.remove_css_class('volume-boosted')

        if getattr(self, '_updating_volume_scale', False):
            return
        if self._player:
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
            self.emit('timing-notification', f"Volume: {int(val)}%")


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
        self._settings = SettingsService()
        self._sleep_inhibitor = SleepInhibitor(window_getter=lambda: self.get_root())

        self._last_progress_saved = 0.0
        self._progress_timer_id = None
        self._last_pointer_x = None
        self._last_pointer_y = None
        self._cursor_hidden = False
        self._session_id = 0
        self._pending_sub_query = None
        self._available_subtitles = []
        self._provider_subtitles = []
        self._reference_sub_path = None
        self._active_external_sub = None
        self._next_stream_data = None
        self._next_ep_dismissed = False
        self._next_ep_triggered = False
        self._countdown_timer_id = None
        self._countdown_seconds = 10
        self._active_sub_path = None
        self._start_pos = 0

        self.set_focusable(True)
        self.connect('map', lambda w: self.grab_focus())

        self._setup_ui()
        self._setup_keybindings()
        self.connect('unrealize', lambda w: (self._set_cursor_visible(True), self._sleep_inhibitor.uninhibit()))

        # Setup dynamic theme synchronization
        style_mgr = Adw.StyleManager.get_default()
        if style_mgr:
            style_mgr.connect('notify::dark', lambda *_: self._update_theme_classes())
        self._update_theme_classes()

    def _on_sub_loaded(self, path: str, label: str, lang: str):
        if not getattr(self, '_reference_sub_path', None) and path:
            self._reference_sub_path = path
            logger.info(f"Set reference subtitle for timing sync: {path}")
        self._controls.refresh_subtitles()

    def _setup_ui(self):
        self._overlay = Gtk.Overlay()
        self._overlay.set_hexpand(True)
        self._overlay.set_vexpand(True)

        self._mpv_widget = MpvWidget()
        self._mpv_widget._on_sub_loaded = self._on_sub_loaded
        self._mpv_widget.connect('stream-ready', self._on_stream_ready)
        self._mpv_widget.connect('buffering', self._on_buffering)
        self._mpv_widget.connect('playback-ended', self._on_playback_ended)
        self._mpv_widget.connect('pause-changed', self._on_pause_changed)
        self._overlay.set_child(self._mpv_widget)

        # Loading spinner
        self._spinner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._spinner_box.add_css_class('player-spinner-box')
        self._spinner_box.set_halign(Gtk.Align.CENTER)
        self._spinner_box.set_valign(Gtk.Align.CENTER)
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(64, 64)
        self._spinner_label = Gtk.Label(label="Connecting to stream...")
        self._spinner_label.add_css_class('title-4')
        self._spinner_box.append(self._spinner)
        self._spinner_box.append(self._spinner_label)
        self._overlay.add_overlay(self._spinner_box)

        # Docked Top Bar (Back button, Media Title, Provider dropdown, and Window Drag Handle)
        self._top_handle = Gtk.WindowHandle()
        self._top_handle.set_valign(Gtk.Align.START)

        self._top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._top_bar.add_css_class('player-top-bar')
        self._top_bar.set_valign(Gtk.Align.START)
        self._top_bar.set_margin_start(0)
        self._top_bar.set_margin_end(0)
        self._top_bar.set_margin_top(0)

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
        self._title_label.set_can_target(False)
        self._top_bar.append(self._title_label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        spacer.set_can_target(False)
        self._top_bar.append(spacer)

        self._provider_popover = ProviderPopover(on_provider_selected=lambda p: self._switch_provider(p))
        self._provider_menu_btn = Gtk.MenuButton()
        self._provider_menu_btn.add_css_class('flat')
        self._provider_menu_btn.add_css_class('provider-pill-btn')
        self._provider_menu_btn.set_tooltip_text("Switch Provider (P)")
        self._provider_menu_btn.set_popover(self._provider_popover)
        self._provider_menu_btn.set_focusable(False)

        provider_pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._provider_badge_label = Gtk.Label(label="Provider")
        provider_pill_box.append(self._provider_badge_label)
        provider_chevron = Gtk.Image.new_from_icon_name('pan-down-symbolic')
        provider_chevron.add_css_class('dim-label')
        provider_pill_box.append(provider_chevron)
        self._provider_menu_btn.set_child(provider_pill_box)
        self._provider_menu_btn.set_visible(False)
        self._top_bar.append(self._provider_menu_btn)

        self._switch_stream_btn = Gtk.Button.new_from_icon_name('view-list-bullet-symbolic')
        self._switch_stream_btn.add_css_class('circular')
        self._switch_stream_btn.add_css_class('flat')
        self._switch_stream_btn.set_tooltip_text("Switch stream / torrent")
        self._switch_stream_btn.set_focusable(False)
        self._switch_stream_btn.connect('clicked', self._on_open_stream_chooser)
        self._switch_stream_btn.set_visible(self._settings.torrent_enabled)
        self._top_bar.append(self._switch_stream_btn)

        self._stream_info_btn = Gtk.Button.new_from_icon_name('info-symbolic')
        self._stream_info_btn.add_css_class('circular')
        self._stream_info_btn.add_css_class('flat')
        self._stream_info_btn.set_tooltip_text("Stream & buffer details")
        self._stream_info_btn.set_focusable(False)
        self._stream_info_btn.connect('clicked', self._on_open_stream_details)
        self._top_bar.append(self._stream_info_btn)

        self._top_handle.set_child(self._top_bar)
        self._overlay.add_overlay(self._top_handle)

        # Floating OSD pill for notifications (volume, seek, timing feedback)
        self._osd_pill = Gtk.Label(label="")
        self._osd_pill.add_css_class('osd-pill')
        self._osd_pill.set_halign(Gtk.Align.CENTER)
        self._osd_pill.set_valign(Gtk.Align.START)
        self._osd_pill.set_margin_top(96)
        self._osd_pill.set_visible(False)
        self._overlay.add_overlay(self._osd_pill)

        # Floating Next Episode Countdown Card (bottom right, above controls)
        self._next_ep_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._next_ep_card.add_css_class('next-episode-card')
        self._next_ep_card.set_halign(Gtk.Align.END)
        self._next_ep_card.set_valign(Gtk.Align.END)
        self._next_ep_card.set_margin_end(28)
        self._next_ep_card.set_margin_bottom(148)
        self._next_ep_card.set_visible(False)

        next_ep_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._next_ep_title_label = Gtk.Label(label="Next Episode in 10s")
        self._next_ep_title_label.add_css_class('heading')
        self._next_ep_title_label.set_xalign(0)
        self._next_ep_title_label.set_hexpand(True)
        next_ep_top.append(self._next_ep_title_label)

        self._next_ep_dismiss_btn = Gtk.Button.new_from_icon_name('window-close-symbolic')
        self._next_ep_dismiss_btn.add_css_class('flat')
        self._next_ep_dismiss_btn.add_css_class('circular')
        self._next_ep_dismiss_btn.set_tooltip_text("Dismiss")
        self._next_ep_dismiss_btn.set_focusable(False)
        self._next_ep_dismiss_btn.connect('clicked', self._on_dismiss_next_episode)
        next_ep_top.append(self._next_ep_dismiss_btn)
        self._next_ep_card.append(next_ep_top)

        self._next_ep_sub_label = Gtk.Label(label="")
        self._next_ep_sub_label.add_css_class('dim-label')
        self._next_ep_sub_label.set_xalign(0)
        self._next_ep_card.append(self._next_ep_sub_label)

        next_ep_btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._next_ep_play_now_btn = Gtk.Button(label="Play Now")
        self._next_ep_play_now_btn.add_css_class('suggested-action')
        self._next_ep_play_now_btn.add_css_class('pill')
        self._next_ep_play_now_btn.set_focusable(False)
        self._next_ep_play_now_btn.connect('clicked', lambda b: self._play_next_episode())
        next_ep_btn_row.append(self._next_ep_play_now_btn)
        self._next_ep_card.append(next_ep_btn_row)

        # Controls overlay
        self._controls = PlayerControls()
        self._controls.set_player(self._mpv_widget)
        self._controls.connect('close', self._on_close)
        self._controls.connect('fullscreen-toggle', self._on_fullscreen_toggle)
        self._controls.connect('timing-notification', lambda c, msg: self.show_osd_notification(msg))
        self._controls.connect('next-episode', lambda b: self._play_next_episode())
        self._controls.connect('upload-subtitles', lambda _: self._open_subtitle_file_dialog())
        self._controls.connect('refresh-subtitles', lambda _: self._refresh_subtitles())
        self._overlay.add_overlay(self._controls)

        # Next episode card overlay added AFTER controls so it renders on top
        self._overlay.add_overlay(self._next_ep_card)

        self.set_child(self._overlay)

        # Motion controller for auto-hiding controls and cursor
        motion = Gtk.EventControllerMotion.new()
        motion.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        motion.connect('motion', self._on_motion)
        motion.connect('leave', self._on_pointer_leave)
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

    def _update_theme_classes(self):
        """Sync player page, controls, top bar, and all popovers with current light/dark scheme."""
        style_mgr = Adw.StyleManager.get_default()
        is_dark = style_mgr.get_dark() if style_mgr else True

        target_add = 'player-theme-dark' if is_dark else 'player-theme-light'
        target_remove = 'player-theme-light' if is_dark else 'player-theme-dark'

        self.remove_css_class(target_remove)
        self.add_css_class(target_add)

        widgets = [
            getattr(self, '_top_bar', None),
            getattr(self, '_controls', None),
            getattr(self, '_spinner_box', None),
            getattr(self, '_next_ep_card', None),
            getattr(self, '_provider_popover', None),
        ]
        if hasattr(self, '_controls'):
            for attr in ('_sub_popover', '_audio_popover', '_speed_popover', '_seek_popover'):
                pop = getattr(self._controls, attr, None)
                if pop:
                    widgets.append(pop)

        for w in widgets:
            if w:
                try:
                    w.remove_css_class(target_remove)
                    w.add_css_class(target_add)
                except Exception:
                    pass

    def show_osd_notification(self, text: str):

        """Show temporary floating OSD pill on video surface."""
        self._osd_pill.set_text(text)
        is_boosted = False
        if text.startswith("Volume:"):
            try:
                num = int(text.replace("Volume:", "").replace("%", "").strip())
                if num > 100:
                    is_boosted = True
            except Exception:
                pass
        if is_boosted:
            self._osd_pill.add_css_class('osd-pill-boosted')
        else:
            self._osd_pill.remove_css_class('osd-pill-boosted')
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
            return True
        elif keyname == 'Left':
            delta = -60 if shift else -10
            self._mpv_widget.seek(delta)
            sign = "+" if delta > 0 else ""
            self.show_osd_notification(f"Seek {sign}{delta}s")
            return True
        elif keyname == 'Right':
            delta = 60 if shift else 10
            self._mpv_widget.seek(delta)
            sign = "+" if delta > 0 else ""
            self.show_osd_notification(f"Seek {sign}{delta}s")
            return True
        elif keyname == 'Up':
            if shift:
                new_pos = self._mpv_widget.adjust_sub_pos(-2)
                self.show_osd_notification(f"Subtitle Position: {new_pos}%")
                if hasattr(self._controls, '_sub_popover'):
                    self._controls._sub_popover.refresh_pos_label()
                return True
            if self._mpv_widget.is_muted():
                self._mpv_widget.toggle_mute()
            curr = self._mpv_widget.get_volume()
            vol = min(130.0, curr + 5.0)
            self._controls._volume_scale.set_value(vol)
            self.show_osd_notification(f"Volume: {int(vol)}%")
            return True
        elif keyname == 'Down':
            if shift:
                new_pos = self._mpv_widget.adjust_sub_pos(2)
                self.show_osd_notification(f"Subtitle Position: {new_pos}%")
                if hasattr(self._controls, '_sub_popover'):
                    self._controls._sub_popover.refresh_pos_label()
                return True
            curr = self._mpv_widget.get_volume()
            vol = max(0.0, curr - 5.0)
            self._controls._volume_scale.set_value(vol)
            if vol <= 0.0:
                self.show_osd_notification("Volume: 0% (Muted)")
            else:
                self.show_osd_notification(f"Volume: {int(vol)}%")
            return True
        elif keyname in ['m', 'M']:
            self._controls._on_mute_clicked(None)
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
        elif keyname in ['c', 'C']:
            self._toggle_captions()
            return True
        elif keyname in ['p', 'P']:
            if hasattr(self, '_provider_menu_btn') and self._provider_menu_btn.get_visible():
                self._provider_menu_btn.popup()
            return True
        elif keyname in ['s', 'S']:
            if hasattr(self, '_controls') and hasattr(self._controls, '_sub_btn'):
                self._controls._sub_btn.popup()
            return True
        elif keyname in ['z', 'Z']:
            delta = -0.5 if shift else -0.1
            new_delay = self._mpv_widget.adjust_sub_delay(delta)
            sign = "+" if new_delay > 0 else ""
            self.show_osd_notification(f"Subtitle Delay: {sign}{new_delay:.2f}s ({sign}{int(new_delay * 1000)}ms)")
            self._controls._sub_popover.refresh_delay_label()
            return True
        elif keyname in ['x', 'X']:
            delta = 0.5 if shift else 0.1
            new_delay = self._mpv_widget.adjust_sub_delay(delta)
            sign = "+" if new_delay > 0 else ""
            self.show_osd_notification(f"Subtitle Delay: {sign}{new_delay:.2f}s ({sign}{int(new_delay * 1000)}ms)")
            self._controls._sub_popover.refresh_delay_label()
            return True
        elif keyname in ['t', 'T']:
            if self._settings.torrent_enabled:
                self._on_open_stream_chooser(None)
            else:
                self.show_osd_notification("Torrent streaming is disabled in Settings.")
            return True
        elif keyname in ['i', 'I']:
            self._on_open_stream_details(None)
            return True
        elif keyname in ['a', 'A']:
            track = self._mpv_widget.cycle_audio_track()
            if track:
                title = track.get('title') or 'Audio Track'
                codec = track.get('codec') or ''
                detail = f" ({codec.upper()})" if codec else ""
                self.show_osd_notification(f"Audio: {title}{detail}")
            else:
                self.show_osd_notification("Audio: Default")
            self._controls.refresh_audio_tracks()
            return True
        elif keyname in ['bracketleft', 'braceleft']:
            if shift:
                new_scale = self._mpv_widget.adjust_sub_scale(-0.1)
                self.show_osd_notification(f"Subtitle Size: {new_scale:.1f}x")
                if hasattr(self._controls, '_sub_popover'):
                    self._controls._sub_popover.refresh_scale_label()
                return True
            new_spd = self._mpv_widget.adjust_speed(-0.25)
            self.show_osd_notification(f"Speed: {new_spd:.2f}x")
            self._controls.set_speed_label(new_spd)
            return True
        elif keyname in ['bracketright', 'braceright']:
            if shift:
                new_scale = self._mpv_widget.adjust_sub_scale(0.1)
                self.show_osd_notification(f"Subtitle Size: {new_scale:.1f}x")
                if hasattr(self._controls, '_sub_popover'):
                    self._controls._sub_popover.refresh_scale_label()
                return True
            new_spd = self._mpv_widget.adjust_speed(0.25)
            self.show_osd_notification(f"Speed: {new_spd:.2f}x")
            self._controls.set_speed_label(new_spd)
            return True
        elif keyname in ['0', 'r', 'R']:
            self._mpv_widget.set_speed(1.0)
            self.show_osd_notification("Speed: 1.0x (Normal)")
            self._controls.set_speed_label(1.0)
            return True
        elif keyname in ['w', 'W']:
            mode_label = self._mpv_widget.cycle_aspect_ratio()
            self.show_osd_notification(f"Video Fit: {mode_label}")
            return True
        elif (keyname in ['n', 'N'] and shift) or keyname == 'N':
            if getattr(self, '_next_stream_data', None):
                self._play_next_episode()
            else:
                self.show_osd_notification("No Next Episode")
            return True

        return False

    def _toggle_captions(self):
        """Toggle subtitles on/off via 'c' key shortcut, defaulting to English."""
        if not self._mpv_widget:
            return

        current_sid = self._mpv_widget.get_sub_track()
        is_active = current_sid not in ('no', False, None, 0)

        if is_active:
            # Subtitles currently on -> turn off
            self._mpv_widget.set_sub_track('no')
            self.show_osd_notification("Captions: Off")
            self._controls.refresh_subtitles()
            return

        # Subtitles currently off -> turn on English by default
        tracks = self._mpv_widget.get_sub_tracks()
        eng_track = None
        for t in tracks:
            lang = (t.get('lang') or '').lower()
            title = (t.get('title') or '').lower()
            if lang in ('eng', 'en') or 'english' in title:
                eng_track = t
                break

        if eng_track:
            self._mpv_widget.set_sub_track(eng_track['id'])
            title = eng_track.get('title') or 'English'
            self.show_osd_notification(f"Captions: {title}")
            self._controls.refresh_subtitles()
            return

        # If tracks exist but none tagged with 'eng', select first loaded track
        if tracks:
            first_track = tracks[0]
            self._mpv_widget.set_sub_track(first_track['id'])
            title = first_track.get('title') or 'On'
            self.show_osd_notification(f"Captions: {title}")
            self._controls.refresh_subtitles()
            return

        # No tracks loaded in MPV yet, check self._available_subtitles
        eng_avail = None
        for s in self._available_subtitles:
            lang = (s.get('lang') or '').lower()
            label = (s.get('label') or '').lower()
            if lang in ('eng', 'en') or 'english' in label:
                eng_avail = s
                break

        target_sub = eng_avail or (self._available_subtitles[0] if self._available_subtitles else None)
        if target_sub:
            label = target_sub.get('label') or target_sub.get('lang') or 'English'
            self.show_osd_notification(f"Loading Captions: {label}...")
            self._on_download_and_select_external_sub(target_sub)
        else:
            self.show_osd_notification("No Captions Available")

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
        self._provider_subtitles = []
        self._opensubtitles_results = []
        self._opensubtitles_done = False
        self._stream_resolving = True
        self._has_provider_subtitles = False
        self._reference_sub_path = None
        self._active_external_sub = None
        self._active_sub_path = None
        self._controls.set_provider_subtitles([])
        self._controls.set_language_subtitles([])
        self._controls.set_available_subtitles([])
        self._controls.set_subtitles_searching(True)
        self._update_theme_classes()


        # Reset Next Episode and Intro state
        self._next_stream_data = None
        self._next_ep_dismissed = False
        self._next_ep_triggered = False
        self._cancel_next_ep_countdown()
        if hasattr(self, '_next_ep_card'):
            self._next_ep_card.set_visible(False)
        self._controls.set_next_episode_visible(False)
        if hasattr(self, '_provider_popover') and provider_name:
            self._provider_popover.set_current_provider(provider_name)

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

        if hasattr(self, '_mpv_widget') and self._mpv_widget:
            self._mpv_widget.stop()
            if hasattr(self._mpv_widget, '_pending_local_subs'):
                self._mpv_widget._pending_local_subs.clear()
            self._mpv_widget._is_stream_active = False
            self._mpv_widget._has_drawn_first_frame = False
            self._mpv_widget._wait_first_frame = True

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
            self._provider_badge_label.set_text(provider_name)
            self._provider_menu_btn.set_visible(True)
        else:
            self._provider_menu_btn.set_visible(False)
        self._spinner_label.set_text(f"Resolving stream for {display_title}...")

        self._session_id += 1
        current_session = self._session_id

        # For TV shows, resolve next episode metadata
        media_type = stream_data.get('media_type')
        if media_type == 'tv' or (season is not None and episode is not None):
            threading.Thread(
                target=self._resolve_next_episode_thread,
                args=(tmdb_id, season, episode, current_session),
                daemon=True
            ).start()

        chosen_stream = stream_data.get('chosen_stream')
        threading.Thread(
            target=self._resolve_thread,
            args=(tmdb_id, season, episode, provider_name, movie, current_session, chosen_stream),
            daemon=True
        ).start()

    def _resolve_thread(self, tmdb_id, season, episode, provider_name, movie, session_id: int, chosen_stream=None):
        """Background thread: resolve stream first, start playback ASAP, then fetch subs in parallel."""
        try:
            # Immediately launch background subtitle fetch in parallel with stream resolution
            threading.Thread(
                target=self._fetch_subtitles_background,
                args=(tmdb_id, season, episode, movie, session_id),
                daemon=True
            ).start()

            if chosen_stream and self._settings.torrent_enabled:
                from showberry.services.torrent import get_torrent_streamer
                from showberry.providers.base import StreamResult
                info_hash = chosen_stream.get('infoHash')
                torrent_url = chosen_stream.get('torrent_url')
                file_idx = chosen_stream.get('fileIdx')
                streamer = get_torrent_streamer()
                start_time = float(self._start_pos or 0)
                duration_secs = float(movie.get('runtime', 0) * 60) if movie.get('runtime') else 7200.0

                def _on_torrent_progress(st):
                    if session_id == self._session_id:
                        down_mb = st.get('download_rate', 0) / (1024 * 1024)
                        peers = st.get('peers', 0)
                        if down_mb > 0.05 or peers > 0:
                            GLib.idle_add(self._spinner_label.set_text, f"Buffering stream • {down_mb:.1f} MB/s ({peers} peers)...")

                http_url = streamer.start_stream(
                    info_hash,
                    torrent_url=torrent_url,
                    file_idx=file_idx,
                    season=season,
                    episode=episode,
                    start_time=start_time,
                    duration_secs=duration_secs,
                    on_progress=_on_torrent_progress,
                )
                if session_id != self._session_id:
                    return
                if not http_url:
                    raise RuntimeError("Could not start torrent stream server for chosen release.")
                result = StreamResult(
                    url=http_url,
                    provider_name='torrent',
                    quality=chosen_stream.get('quality', '1080p')
                )
            else:
                start_time = float(self._start_pos or 0)
                duration_secs = float(movie.get('runtime', 0) * 60) if movie.get('runtime') else 7200.0
                result = ProviderManager.resolve_stream(
                    tmdb_id=tmdb_id,
                    season=season,
                    episode=episode,
                    preferred_provider_name=provider_name,
                    start_time=start_time,
                    duration_secs=duration_secs,
                )

            if session_id != self._session_id:
                return

            # Start playback immediately
            GLib.idle_add(self._on_stream_resolved, result, [], session_id)

        except Exception as e:
            if session_id != self._session_id:
                return
            GLib.idle_add(self._on_stream_error, str(e), session_id)

    def _open_subtitle_file_dialog(self):
        """Open a file dialog allowing user to load custom local subtitle files."""
        root_window = self.get_root()
        parent = root_window if isinstance(root_window, Gtk.Window) else None
        dialog = Gtk.FileChooserNative.new(
            "Open Subtitle File",
            parent,
            Gtk.FileChooserAction.OPEN,
            "_Open",
            "_Cancel"
        )
        filter_sub = Gtk.FileFilter()
        filter_sub.set_name("Subtitle Files (*.srt, *.vtt, *.ass, *.sub)")
        for ext in ("*.srt", "*.vtt", "*.ass", "*.sub", "*.SRT", "*.VTT", "*.ASS", "*.SUB"):
            filter_sub.add_pattern(ext)
        dialog.add_filter(filter_sub)

        filter_all = Gtk.FileFilter()
        filter_all.set_name("All Files")
        filter_all.add_pattern("*")
        dialog.add_filter(filter_all)

        def _on_response(d, response_id):
            if response_id == Gtk.ResponseType.ACCEPT:
                gfile = d.get_file()
                if gfile:
                    path = gfile.get_path()
                    if path:
                        filename = os.path.basename(path)
                        def _bg_upload():
                            act_path = path
                            ref = getattr(self, '_reference_sub_path', None)
                            if ref and os.path.exists(ref):
                                synced = self._subtitles_service.sync_subtitle_with_reference(ref, path)
                                if synced:
                                    act_path = synced
                            GLib.idle_add(self._activate_external_subtitle, act_path, f"📁 {filename}", "und")
                        threading.Thread(target=_bg_upload, daemon=True).start()
            d.destroy()

        dialog.connect('response', _on_response)
        dialog.show()

    def _sync_subtitle_popover_lists(self, session_id: int):
        """Merge provider built-in subtitles and OpenSubtitles on the main GTK thread without races."""
        if session_id != self._session_id:
            return False

        provider_subs = list(getattr(self, '_provider_subtitles', []))
        opensubs = list(getattr(self, '_opensubtitles_results', []))
        self._available_subtitles = provider_subs + opensubs

        self._controls.set_provider_subtitles(
            provider_subs,
            self._on_download_and_select_builtin_sub
        )

        # Extract top unique subtitle per language from OpenSubtitles for quick language selection
        seen_langs = set()
        for ps in provider_subs:
            p_lang = (ps.get('lang') or '').lower()
            if p_lang:
                seen_langs.add(p_lang)

        unique_lang_subs = []
        for s in opensubs:
            lang = (s.get('lang') or '').lower()
            if not lang or lang in seen_langs:
                continue
            seen_langs.add(lang)
            s_copy = dict(s)
            s_copy['_is_quick_lang'] = True
            unique_lang_subs.append(s_copy)

        POPULAR_ORDER = ['eng', 'spa', 'fre', 'ger', 'ita', 'por', 'hin', 'chi', 'jpn', 'kor', 'rus', 'ara']
        def _lang_sort_key(item):
            l = (item.get('lang') or '').lower()
            if l in POPULAR_ORDER:
                return (0, POPULAR_ORDER.index(l))
            return (1, item.get('lang_name', ''))

        unique_lang_subs.sort(key=_lang_sort_key)

        self._controls.set_language_subtitles(
            unique_lang_subs,
            self._on_download_and_select_external_sub
        )

        if getattr(self, '_opensubtitles_done', False) or opensubs:
            self._controls.set_available_subtitles(
                self._available_subtitles,
                self._on_download_and_select_external_sub
            )

        # Auto-download primary OpenSubtitle ONLY after stream resolution finished with NO built-in subtitles
        if not getattr(self, '_stream_resolving', False) and not provider_subs and opensubs:
            current_sid = self._mpv_widget.get_sub_track() if self._mpv_widget else 'no'
            tracks = self._mpv_widget.get_sub_tracks() if self._mpv_widget else []
            has_active_sub = bool(
                getattr(self, '_active_external_sub', None)
                or getattr(self, '_reference_sub_path', None)
                or (tracks and current_sid not in ('no', False, None, 0))
                or (self._mpv_widget and getattr(self._mpv_widget, '_pending_local_subs', None))
            )
            if not has_active_sub:
                eng_subs = [s for s in opensubs if s.get('lang', '').lower() in ('eng', 'en')]
                primary_sub = eng_subs[0] if eng_subs else opensubs[0]
                self._on_download_and_select_external_sub(primary_sub)

        return False

    def _fetch_subtitles_background(self, tmdb_id, season, episode, movie, session_id: int):
        """Fetch OpenSubtitles in background and populate subtitles list."""
        try:
            if session_id != self._session_id:
                return

            imdb_id = movie.get('imdb_id')
            if not imdb_id:
                imdb_id = self._tmdb.get_imdb_id(tmdb_id, is_tv=(season is not None))
                if imdb_id and movie is not None:
                    movie['imdb_id'] = imdb_id

            if session_id != self._session_id:
                return

            if not imdb_id:
                logger.info(f"No IMDB ID found for TMDB {tmdb_id}; cannot fetch OpenSubtitles")
                GLib.idle_add(self._controls.set_subtitles_error, "No IMDb ID found for this title")
                return

            subs = self._subtitles_service.get_subtitles(imdb_id, season=season, episode=episode)
            if session_id != self._session_id:
                return

            self._opensubtitles_results = list(subs or [])
            self._opensubtitles_done = True
            GLib.idle_add(self._sync_subtitle_popover_lists, session_id)
        except Exception as ex:
            logger.warning(f"Background subtitle fetch failed: {ex}")
            if session_id == self._session_id:
                GLib.idle_add(self._controls.set_subtitles_error, "Failed to connect to OpenSubtitles")

    def _refresh_subtitles(self):
        """User requested manual refresh of subtitles from the UI."""
        if not self._stream_data:
            return
        movie = self._stream_data.get('movie', {})
        tmdb_id = movie.get('id') or movie.get('tmdb_id')
        if not tmdb_id:
            return
        season = self._stream_data.get('season')
        episode = self._stream_data.get('episode')
        self._controls.set_subtitles_searching(True)
        threading.Thread(
            target=self._fetch_subtitles_background,
            args=(int(tmdb_id), season, episode, movie, self._session_id),
            daemon=True
        ).start()

    def _on_download_and_select_builtin_sub(self, sub: Dict[str, Any]):
        """User selected a built-in provider subtitle (e.g. Spanish, French, Hindi) from the popover."""
        sub_url = sub.get('url')
        lang = sub.get('lang', 'eng')
        from showberry.services.subtitles import LANG_FLAGS, LANG_NAMES
        lang_name = sub.get('lang_name') or LANG_NAMES.get(lang.lower(), lang.upper())
        flag = sub.get('flag') or LANG_FLAGS.get(lang.lower(), '')
        display_label = f"{flag} {lang_name}".strip()
        headers = sub.get('headers')
        referer = sub.get('referer')
        current_session = self._session_id

        def _bg():
            local_path = self._subtitles_service.download_subtitle(
                sub_url,
                filename_hint=f"{lang_name}.vtt",
                headers=headers,
                referer=referer
            )
            if local_path and current_session == self._session_id:
                self._reference_sub_path = local_path
                GLib.idle_add(self._activate_external_subtitle, local_path, display_label, lang)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_download_and_select_external_sub(self, sub: Dict[str, Any]):
        """User selected an available online subtitle from the popover."""
        sub_url = sub.get('url')
        lang = (sub.get('lang') or 'eng').lower()
        from showberry.services.subtitles import LANG_FLAGS, LANG_NAMES
        lang_name = sub.get('lang_name') or LANG_NAMES.get(lang, lang.upper())
        flag = sub.get('flag') or LANG_FLAGS.get(lang, '')
        label = sub.get('label', '')
        display_label = f"{flag} {lang_name}".strip()
        headers = sub.get('headers')
        referer = sub.get('referer')
        is_builtin = sub.get('is_builtin', False) or 'built-in' in label.lower()
        current_session = self._session_id

        # Gather fallback candidates of the same language in case top release is broken or partial (CD1)
        candidates = [sub]
        if not is_builtin:
            for s in getattr(self, '_available_subtitles', []):
                if (s.get('lang') or '').lower() == lang and s.get('url') != sub_url and not s.get('is_builtin'):
                    candidates.append(s)
                    if len(candidates) >= 4:
                        break

        def _bg():
            ref = getattr(self, '_reference_sub_path', None)
            chosen_path = None
            for idx, cand in enumerate(candidates):
                if current_session != self._session_id:
                    return
                c_url = cand.get('url')
                if not c_url:
                    continue
                p = self._subtitles_service.download_subtitle(
                    c_url,
                    filename_hint=f"{lang_name}_{idx}.srt",
                    headers=cand.get('headers') or headers,
                    referer=cand.get('referer') or referer
                )
                if not p:
                    continue
                if chosen_path is None:
                    chosen_path = p
                # Verify it is not a partial (CD1) subtitle when we have a full reference subtitle
                if not is_builtin and ref and os.path.exists(ref) and len(candidates) > 1:
                    if self._subtitles_service.is_partial_subtitle(ref, p):
                        logger.info(f"Candidate {idx} for {lang_name} is partial; trying next candidate...")
                        continue
                chosen_path = p
                break

            if chosen_path and current_session == self._session_id:
                local_path = chosen_path
                if not is_builtin and ref and os.path.exists(ref):
                    logger.info(f"Auto-aligning external subtitle ({lang_name}) against reference: {ref}")
                    synced_path = self._subtitles_service.sync_subtitle_with_reference(ref, local_path)
                    if synced_path:
                        local_path = synced_path
                        logger.info(f"Using synced subtitle: {local_path}")
                elif is_builtin:
                    self._reference_sub_path = local_path
                GLib.idle_add(self._activate_external_subtitle, local_path, display_label, lang)

        threading.Thread(target=_bg, daemon=True).start()

    def _activate_external_subtitle(self, local_path: str, label: str, lang: str):
        if not self._mpv_widget:
            return
        clean_label = label.replace("(Built-in)", "").strip()
        if not getattr(self, '_reference_sub_path', None):
            self._reference_sub_path = local_path
        self._active_external_sub = (local_path, clean_label, lang)
        if hasattr(self, '_controls') and hasattr(self._controls, '_sub_popover'):
            self._controls._sub_popover._pending_selected_label = None
        self._mpv_widget.set_sub_delay(0.0)
        self._mpv_widget._add_local_subtitle(local_path, clean_label, lang, select=True)
        tracks = self._mpv_widget.get_sub_tracks()
        if tracks:
            new_id = tracks[-1]['id']
            self._mpv_widget.set_sub_track(new_id)
            self.show_osd_notification(f"Subtitle: {clean_label}")
        self._controls.refresh_subtitles()

    def _on_pause_changed(self, widget, is_paused: bool):
        """React to playback pausing or unpausing by toggling sleep inhibition."""
        if is_paused:
            self._sleep_inhibitor.uninhibit()
        else:
            self._sleep_inhibitor.inhibit()

    def _on_stream_ready(self, widget):
        """Called when the first frame has rendered to GLArea."""
        self._spinner.stop()
        self._spinner_box.set_visible(False)

        # Flush any queued subtitles and update subtitle tracks in controls
        if self._mpv_widget:
            self._mpv_widget._flush_pending_local_subs()
        if getattr(self, '_active_external_sub', None):
            self.show_osd_notification(f"Subtitle: {self._active_external_sub[1]}")
        self._controls.refresh_subtitles()

        # Inhibit screen and system sleep during active playback
        if self._mpv_widget and not self._mpv_widget.is_paused():
            self._sleep_inhibitor.inhibit()

        # Refresh audio tracks and playback speed in controls
        GLib.timeout_add(1000, lambda: self._controls.refresh_audio_tracks())
        if self._mpv_widget:
            self._controls.set_speed_label(self._mpv_widget.get_speed())

    def _on_buffering(self, widget, is_buffering: bool):
        """Called when MPV paused-for-cache property changes."""
        if not getattr(self, '_mpv_widget', None) or not getattr(self._mpv_widget, '_is_active', False):
            return
        if is_buffering:
            self._spinner_label.set_text("Buffering stream...")
            self._spinner_box.set_visible(True)
            self._spinner.start()
        else:
            if getattr(self._mpv_widget, '_has_drawn_first_frame', False):
                self._spinner.stop()
                self._spinner_box.set_visible(False)

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
        self._spinner_box.set_visible(True)
        self._spinner.start()

        logger.info(f"Starting playback: {result.url}")

        if result.provider_name and hasattr(self, '_provider_badge_label'):
            q = f" • {result.quality}" if result.quality else ""
            self._provider_badge_label.set_text(f"{result.provider_name}{q}")
            if hasattr(self, '_provider_popover'):
                self._provider_popover.set_current_provider(result.provider_name)
            self._provider_menu_btn.set_visible(True)

        # Format and attach stream referer and headers to provider subtitles
        provider_subs = list(result.subtitles or [])
        for s in provider_subs:
            if 'referer' not in s and result.referer:
                s['referer'] = result.referer
            if 'headers' not in s and result.headers:
                s['headers'] = result.headers
            lang = s.get('lang', 'eng').lower()
            from showberry.services.subtitles import LANG_FLAGS, LANG_NAMES
            flag = LANG_FLAGS.get(lang, '🌐')
            lang_name = LANG_NAMES.get(lang, lang.upper())
            s['flag'] = flag
            s['lang_name'] = lang_name
            s['label'] = f"{flag} {lang_name}".strip()
            s['is_builtin'] = True

        self._stream_resolving = False
        self._provider_subtitles = list(provider_subs)
        self._has_provider_subtitles = bool(provider_subs)
        self._sync_subtitle_popover_lists(self._session_id)

        self._mpv_widget.play(
            url=result.url,
            referer=result.referer,
            origin=result.origin,
            headers=result.headers,
            subtitles=[],
            start_pos=self._start_pos
        )

        # Auto-download ONLY the primary English (or first) subtitle once and set it as reference + active track
        if provider_subs:
            eng_subs = [s for s in provider_subs if s.get('lang', '').lower() in ('eng', 'en')]
            primary_sub = eng_subs[0] if eng_subs else provider_subs[0]

            current_sess = self._session_id
            def _fetch_ref(sub=primary_sub, sess=current_sess):
                p = self._subtitles_service.download_subtitle(
                    sub['url'],
                    filename_hint=sub.get('label', 'ref.srt'),
                    referer=sub.get('referer'),
                    headers=sub.get('headers')
                )
                if p and sess == self._session_id:
                    self._reference_sub_path = p
                    logger.info(f"Verified built-in reference subtitle set: {p}")
                    if not getattr(self, '_active_external_sub', None):
                        GLib.idle_add(
                            self._activate_external_subtitle,
                            p,
                            sub.get('label', '🇺🇸 English'),
                            sub.get('lang', 'eng')
                        )
            threading.Thread(target=_fetch_ref, daemon=True).start()
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
                media_type = self._stream_data.get('media_type', 'movie')
                season = self._stream_data.get('season')
                episode = self._stream_data.get('episode')
                is_completed = (dur > 0 and (pos >= dur * 0.90))

                if is_completed:
                    self._db.mark_completed(
                        tmdb_id=tmdb_id,
                        media_type=media_type,
                        season=season,
                        episode=episode,
                        title=movie.get('title', 'Unknown'),
                        poster_url=movie.get('poster_url'),
                        backdrop_url=movie.get('backdrop_url')
                    )
                    # If TV show and next episode resolved, advance watch_history to next episode at 0s
                    if media_type == 'tv' or (season is not None and episode is not None):
                        if self._next_stream_data:
                            n_season = self._next_stream_data.get('season')
                            n_episode = self._next_stream_data.get('episode')
                            self._db.update_watch_progress(
                                tmdb_id=tmdb_id,
                                title=movie.get('title', 'Unknown'),
                                media_type='tv',
                                poster_url=movie.get('poster_url'),
                                backdrop_url=movie.get('backdrop_url'),
                                season=n_season,
                                episode=n_episode,
                                progress_seconds=0.0,
                                duration_seconds=dur,
                                stream_provider=self._stream_data.get('provider'),
                            )
                    else:
                        self._db.delete_history_item(tmdb_id)
                else:
                    chosen = self._stream_data.get('chosen_stream') or {}
                    t_status = {}
                    try:
                        from showberry.services.torrent import get_torrent_streamer
                        _streamer = get_torrent_streamer()
                        if _streamer:
                            t_status = _streamer.get_status()
                    except Exception:
                        pass
                    info_hash = chosen.get('infoHash') or t_status.get('info_hash')
                    file_idx = chosen.get('fileIdx') if chosen.get('fileIdx') is not None else t_status.get('file_idx')
                    stream_provider = self._stream_data.get('provider') or ('torrent' if info_hash else None)

                    self._db.update_watch_progress(
                        tmdb_id=tmdb_id,
                        title=movie.get('title', 'Unknown'),
                        media_type=media_type,
                        poster_url=movie.get('poster_url'),
                        backdrop_url=movie.get('backdrop_url'),
                        season=season,
                        episode=episode,
                        progress_seconds=pos,
                        duration_seconds=dur,
                        stream_provider=stream_provider,
                        info_hash=info_hash,
                        file_idx=file_idx,
                    )
        except Exception as e:
            logger.warning(f"Failed to persist watch progress: {e}")

        return True

    def _show_next_episode_countdown(self):
        if not self._next_stream_data or self._next_ep_dismissed or self._next_ep_triggered:
            return
        from showberry.services.settings import SettingsService
        settings = SettingsService.get_instance()
        if not settings.auto_skip_enabled:
            return
        self._next_ep_triggered = True
        self._countdown_seconds = int(settings.auto_skip_countdown or 10)
        self._next_ep_title_label.set_text(f"Next Episode in {self._countdown_seconds}s")
        self._next_ep_card.set_visible(True)
        self._countdown_timer_id = GLib.timeout_add_seconds(1, self._on_countdown_tick)

    def _resolve_next_episode_thread(self, tmdb_id, season, episode, session_id: int):
        """Background worker to look up the subsequent episode."""
        try:
            s_num = int(season or 1)
            e_num = int(episode or 1)
            episodes = self._tmdb.get_tv_season(tmdb_id, s_num)
            next_info = None
            if episodes:
                for ep in episodes:
                    if ep.get('episode_number') == e_num + 1:
                        next_info = (s_num, e_num + 1, ep.get('name', f"Episode {e_num + 1}"))
                        break
            if not next_info:
                # Check next season episode 1
                next_season_eps = self._tmdb.get_tv_season(tmdb_id, s_num + 1)
                if next_season_eps:
                    first_ep = next_season_eps[0]
                    next_info = (s_num + 1, first_ep.get('episode_number', 1), first_ep.get('name', "Episode 1"))

            if next_info and session_id == self._session_id:
                GLib.idle_add(self._on_next_episode_resolved, next_info, session_id)
        except Exception as e:
            logger.debug(f"Error resolving next episode: {e}")

    def _on_next_episode_resolved(self, next_info, session_id: int):
        if session_id != self._session_id or not self._stream_data:
            return
        n_season, n_episode, n_title = next_info
        self._next_stream_data = {
            'movie': self._stream_data.get('movie', {}),
            'provider': self._stream_data.get('provider'),
            'media_type': 'tv',
            'season': n_season,
            'episode': n_episode,
            'start_position': 0,
            'title': n_title,
        }
        tooltip = f"Next Episode (Shift+N): S{n_season:02d}E{n_episode:02d} - {n_title}"
        self._controls.set_next_episode_visible(True, tooltip)
        self._next_ep_sub_label.set_text(f"S{n_season:02d}E{n_episode:02d} • {n_title}")

    def _on_countdown_tick(self):
        self._countdown_seconds -= 1
        if self._countdown_seconds <= 0:
            self._countdown_timer_id = None
            self._play_next_episode()
            return False
        self._next_ep_title_label.set_text(f"Next Episode in {self._countdown_seconds}s")
        return True

    def _on_dismiss_next_episode(self, button=None):
        self._cancel_next_ep_countdown()
        self._next_ep_dismissed = True
        self._next_ep_card.set_visible(False)

    def _cancel_next_ep_countdown(self):
        if hasattr(self, '_countdown_timer_id') and self._countdown_timer_id:
            try:
                GLib.source_remove(self._countdown_timer_id)
            except Exception:
                pass
            self._countdown_timer_id = None

    def _play_next_episode(self):
        if not self._next_stream_data:
            return
        data = self._next_stream_data
        self._cancel_next_ep_countdown()
        self._next_ep_card.set_visible(False)
        self.show_osd_notification(f"Starting S{data['season']:02d}E{data['episode']:02d}: {data.get('title', '')}")
        self.load_stream(data)

    def _on_playback_ended(self, widget=None):
        """Triggered strictly when MPV finishes playback (EOF reached)."""
        logger.info("Playback ended (EOF reached).")
        self._sleep_inhibitor.uninhibit()
        if not self._stream_data or not self._mpv_widget:
            return

        pos = self._mpv_widget.get_position()
        dur = self._mpv_widget.get_duration()

        # Guard: strictly verify that playback reached at least 85% of total runtime
        # before marking completed or deleting from watch history.
        # This prevents premature EOF (e.g. network disconnect, buffer dip, container probe)
        # from erroneously marking the movie as watched.
        if dur <= 30 or pos < (dur * 0.85):
            logger.warning(f"Premature EOF encountered (pos={pos:.1f}s / dur={dur:.1f}s). Ignoring playback-ended.")
            return

        movie = self._stream_data.get('movie', {})
        tmdb_id = movie.get('id')
        if tmdb_id:
            media_type = self._stream_data.get('media_type', 'movie')
            season = self._stream_data.get('season')
            episode = self._stream_data.get('episode')
            self._db.mark_completed(
                tmdb_id=tmdb_id,
                media_type=media_type,
                season=season,
                episode=episode,
                title=movie.get('title', 'Unknown'),
                poster_url=movie.get('poster_url'),
                backdrop_url=movie.get('backdrop_url')
            )
            if media_type == 'tv' or (season is not None and episode is not None):
                if self._next_stream_data:
                    n_season = self._next_stream_data.get('season')
                    n_episode = self._next_stream_data.get('episode')
                    self._db.update_watch_progress(
                        tmdb_id=tmdb_id,
                        title=movie.get('title', 'Unknown'),
                        media_type='tv',
                        poster_url=movie.get('poster_url'),
                        backdrop_url=movie.get('backdrop_url'),
                        season=n_season,
                        episode=n_episode,
                        progress_seconds=0.0,
                        duration_seconds=dur,
                        stream_provider=self._stream_data.get('provider'),
                    )
                else:
                    self._db.mark_completed(
                        tmdb_id=tmdb_id,
                        media_type='tv',
                        season=0,
                        episode=0,
                        title=movie.get('title', 'Unknown'),
                        poster_url=movie.get('poster_url'),
                        backdrop_url=movie.get('backdrop_url')
                    )
            else:
                self._db.delete_history_item(tmdb_id)

        # Trigger countdown strictly on EOF
        if self._next_stream_data and not getattr(self, '_next_ep_dismissed', False) and not getattr(self, '_next_ep_triggered', False):
            from showberry.services.settings import SettingsService
            if SettingsService.get_instance().auto_skip_enabled:
                self._show_next_episode_countdown()

    def _switch_provider(self, provider_name: str):
        """Switch stream provider on the fly while preserving current position."""
        if not self._stream_data or not self._mpv_widget:
            return

        if 'torrent' in provider_name.lower():
            from showberry.services.torrent import HAS_LIBTORRENT
            if not HAS_LIBTORRENT:
                self.show_osd_notification("Torrent streaming is unavailable (libtorrent not installed).")
                return
            self._on_open_stream_chooser(None)
            return

        pos = self._mpv_widget.get_position()
        self.show_osd_notification(f"Switching to {provider_name}...")

        new_data = dict(self._stream_data)
        new_data['provider'] = None if provider_name.lower() in ('auto', 'auto (best)') else provider_name
        new_data['start_position'] = pos
        new_data.pop('chosen_stream', None)
        self.load_stream(new_data)

    def _on_stream_error(self, err_msg: str, session_id: int = 0):
        self._sleep_inhibitor.uninhibit()
        if session_id and session_id != self._session_id:
            return False
        self._spinner.stop()
        self._spinner_box.set_visible(False)
        self.emit('stream-failed', f"Stream error: {err_msg}")
        return False

    def _on_close(self, controls):
        """Close playback safely, saving final progress and stopping services."""
        self._sleep_inhibitor.uninhibit()
        self._session_id += 1  # Invalidate any in-flight resolver or subtitle worker threads
        self._pending_sub_query = None
        self._available_subtitles = []
        self._active_external_sub = None
        self._cancel_next_ep_countdown()
        if hasattr(self, '_next_ep_card'):
            self._next_ep_card.set_visible(False)

        # Capture progress before deactivating
        try:
            pos = self._mpv_widget.get_position()
            dur = self._mpv_widget.get_duration()
            stream_data = self._stream_data
            next_stream_data = self._next_stream_data
        except Exception:
            pos, dur, stream_data, next_stream_data = 0, 0, None, None

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
                        media_type = stream_data.get('media_type', 'movie')
                        season = stream_data.get('season')
                        episode = stream_data.get('episode')
                        is_completed = (dur > 0 and (pos >= dur * 0.90))

                        if is_completed:
                            self._db.mark_completed(
                                tmdb_id=tmdb_id,
                                media_type=media_type,
                                season=season,
                                episode=episode,
                                title=movie.get('title', 'Unknown'),
                                poster_url=movie.get('poster_url'),
                                backdrop_url=movie.get('backdrop_url')
                            )
                            if (media_type == 'tv' or (season is not None and episode is not None)) and next_stream_data:
                                self._db.update_watch_progress(
                                    tmdb_id=tmdb_id,
                                    title=movie.get('title', 'Unknown'),
                                    media_type='tv',
                                    poster_url=movie.get('poster_url'),
                                    backdrop_url=movie.get('backdrop_url'),
                                    season=next_stream_data.get('season'),
                                    episode=next_stream_data.get('episode'),
                                    progress_seconds=0.0,
                                    duration_seconds=dur,
                                    stream_provider=stream_data.get('provider'),
                                )
                            else:
                                self._db.delete_history_item(tmdb_id)
                        else:
                            chosen = stream_data.get('chosen_stream') or {}
                            t_status = {}
                            try:
                                _streamer = get_torrent_streamer()
                                if _streamer:
                                    t_status = _streamer.get_status()
                            except Exception:
                                pass
                            info_hash = chosen.get('infoHash') or t_status.get('info_hash')
                            file_idx = chosen.get('fileIdx') if chosen.get('fileIdx') is not None else t_status.get('file_idx')
                            stream_provider = stream_data.get('provider') or ('torrent' if info_hash else None)

                            self._db.update_watch_progress(
                                tmdb_id=tmdb_id,
                                title=movie.get('title', 'Unknown'),
                                media_type=media_type,
                                poster_url=movie.get('poster_url'),
                                backdrop_url=movie.get('backdrop_url'),
                                season=season,
                                episode=episode,
                                progress_seconds=pos,
                                duration_seconds=dur,
                                stream_provider=stream_provider,
                                info_hash=info_hash,
                                file_idx=file_idx,
                            )
            except Exception as ex:
                logger.warning(f"Error saving watch progress during cleanup: {ex}")

            try:
                _streamer = get_torrent_streamer()
                if _streamer:
                    _streamer.stop()
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
        new_vol = max(0.0, min(130.0, current_vol + delta))
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

    def _on_pointer_leave(self, controller):
        """Accelerate hiding controls when the cursor leaves the player area."""
        self._last_pointer_x = None
        self._last_pointer_y = None
        if not self._mpv_widget.is_paused():
            if self._hide_timeout:
                GLib.source_remove(self._hide_timeout)
            self._hide_timeout = GLib.timeout_add(800, self._hide_controls)

    def _show_controls_briefly(self, timeout_ms: int = 1500):
        if self._cursor_hidden:
            self._set_cursor_visible(True)
        if hasattr(self, '_top_handle'):
            self._top_handle.set_visible(True)
        if hasattr(self, '_top_bar'):
            self._top_bar.set_visible(True)
        if hasattr(self, '_switch_stream_btn'):
            self._switch_stream_btn.set_visible(self._settings.torrent_enabled)
        self._controls.set_visible(True)
        if self._hide_timeout:
            GLib.source_remove(self._hide_timeout)
        self._hide_timeout = GLib.timeout_add(timeout_ms, self._hide_controls)

    def _hide_controls(self):
        # Don't hide if user is currently interacting with controls
        if getattr(self._controls, '_is_dragging', False):
            return True
        if hasattr(self._controls, '_sub_popover') and self._controls._sub_popover.get_visible():
            return True

        if not self._mpv_widget.is_paused():
            if hasattr(self, '_top_handle'):
                self._top_handle.set_visible(False)
            if hasattr(self, '_top_bar'):
                self._top_bar.set_visible(False)
            self._controls.set_visible(False)
            self._set_cursor_visible(False)

        self._hide_timeout = None
        return False

    def _on_open_stream_details(self, btn):
        """Open live buffer and download stats dialog."""
        from showberry.ui.stream_dialogs import StreamDetailsDialog
        window = self.get_root()
        dialog = StreamDetailsDialog(parent_window=window, player_page=self)
        dialog.present()

    def _on_open_stream_chooser(self, btn):
        """Open stream chooser to switch torrent streams on the fly."""
        if not self._settings.torrent_enabled:
            self.show_osd_notification("Torrent streaming is disabled in Settings.")
            return
        from showberry.services.torrent import HAS_LIBTORRENT
        if not HAS_LIBTORRENT:
            self.show_osd_notification("Torrent streaming is unavailable (libtorrent not installed).")
            return
        from showberry.ui.stream_dialogs import TorrentStreamChooserDialog
        window = self.get_root()
        movie = self._stream_data.get('movie', {})
        season = self._stream_data.get('season')
        episode = self._stream_data.get('episode')

        def _on_picked(stream_info):
            info_hash = stream_info.get('infoHash')
            if not info_hash:
                return
            quality = stream_info.get('quality', '')
            label = f"Switching to {quality} stream..." if quality else "Switching stream..."
            self.show_osd_notification(label)
            new_data = dict(self._stream_data)
            new_data['provider'] = 'torrent'
            new_data['chosen_stream'] = stream_info
            self.load_stream(new_data)

        dialog = TorrentStreamChooserDialog(
            parent_window=window,
            movie_data=movie,
            season=season,
            episode=episode,
            on_stream_selected=_on_picked
        )
        dialog.present()
