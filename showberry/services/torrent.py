"""Sequential torrent streaming service with built-in HTTP Range server."""

import os
import re
import sys
import time
import socket
import logging
import threading
import mimetypes
from pathlib import Path
from typing import Optional, Dict, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import urllib.request

from gi.repository import GLib

logger = logging.getLogger(__name__)

try:
    import libtorrent as lt
    HAS_LIBTORRENT = True
except ImportError:
    HAS_LIBTORRENT = False
    logger.warning("libtorrent not found. Torrent streaming will be unavailable.")

TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://explodie.org:6969/announce",
]

VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.webm', '.mov', '.ts', '.m4v')


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server so multiple ranges / requests can be served concurrently."""
    daemon_threads = True
    allow_reuse_address = True


class TorrentStreamRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler supporting Byte Range (HTTP 206 Partial Content) requests."""

    def log_message(self, format, *args):
        # Suppress noisy HTTP access logs
        pass

    def do_HEAD(self):
        self._serve(head_only=True)

    def do_GET(self):
        self._serve(head_only=False)

    def _serve(self, head_only=False):
        streamer: TorrentStreamer = self.server.streamer
        file_path = streamer.video_file_path
        total_size = streamer.video_file_size

        if not file_path or total_size <= 0:
            self.send_error(503, "Torrent metadata or video file not yet ready")
            return

        range_header = self.headers.get('Range')
        start = 0
        end = total_size - 1

        if range_header:
            match = re.match(r'bytes=(\d+)-(\d*)', range_header)
            if match:
                start = int(match.group(1))
                if match.group(2):
                    end = int(match.group(2))

        if start >= total_size or start > end:
            self.send_error(416, "Requested Range Not Satisfiable")
            return

        length = end - start + 1
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = 'video/mp4' if file_path.endswith('.mp4') else 'video/x-matroska'

        if range_header:
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{end}/{total_size}')
        else:
            self.send_response(200)

        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()

        if head_only:
            return

        # Stream bytes from disk, prioritizing pieces as requested
        try:
            streamer.stream_bytes(self.wfile, start, length)
        except (BrokenPipeError, ConnectionResetError):
            pass


class TorrentStreamer:
    """Manages sequential downloading of a torrent and local HTTP streaming."""

    def __init__(self, cache_dir: Optional[str] = None):
        if not HAS_LIBTORRENT:
            raise RuntimeError("libtorrent is required for TorrentStreamer")

        if cache_dir is None:
            cache_dir = Path(GLib.get_user_cache_dir()) / 'showberry' / 'torrents'
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.session: Optional[lt.session] = None
        self.handle: Optional[lt.torrent_handle] = None
        self.httpd: Optional[ThreadedHTTPServer] = None
        self.http_thread: Optional[threading.Thread] = None
        self.current_info_hash: Optional[str] = None
        self.current_file_idx: Optional[int] = None
        self.http_port: int = 0

        self.video_file_path: Optional[str] = None
        self.video_file_idx: int = -1
        self.video_file_size: int = 0
        self.piece_length: int = 0
        self.start_piece: int = 0
        self.end_piece: int = 0

        self.is_running = False
        self._stop_event = threading.Event()
        self.state_string = "idle"
        self._current_stream_piece: int = 0
        self._sequential_thread: Optional[threading.Thread] = None

    def _init_session(self):
        """Initialize libtorrent session with DHT, LSD, and ephemeral port."""
        settings = {
            'listen_interfaces': '0.0.0.0:0,[::]:0',
            'enable_dht': True,
            'enable_lsd': True,
            'enable_upnp': True,
            'enable_natpmp': True,
            'alert_mask': lt.alert.category_t.error_notification | lt.alert.category_t.status_notification,
        }
        self.session = lt.session(settings)
        # Add public DHT bootstrap nodes
        for host, port in [
            ('router.bittorrent.com', 6881),
            ('dht.transmissionbt.com', 6881),
            ('router.utorrent.com', 6881),
            ('dht.aelitis.com', 6881),
        ]:
            try:
                self.session.add_dht_node((host, port))
            except Exception:
                pass

    def start_stream(
        self,
        magnet_or_hash: str,
        torrent_url: Optional[str] = None,
        file_idx: Optional[int] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        timeout: int = 35
    ) -> str:
        """
        Start downloading torrent sequentially and return streaming HTTP URL.
        Supports instant metadata loading via direct .torrent URLs and cache mirrors.
        """
        self.stop()
        self._stop_event.clear()
        self.is_running = True
        self.state_string = "fetching_metadata"

        self._init_session()

        info_hash = magnet_or_hash.strip().lower() if not magnet_or_hash.startswith('magnet:') else None
        self.current_info_hash = info_hash
        self.current_file_idx = file_idx

        # 1. Attempt instantaneous direct .torrent fetch (bypassing DHT metadata wait)
        torrent_bytes = None
        urls_to_try = []
        if torrent_url:
            urls_to_try.append(torrent_url)
        if info_hash and len(info_hash) == 40:
            urls_to_try.extend([
                f"https://itorrents.org/torrent/{info_hash.upper()}.torrent",
                f"https://torrage.info/torrent.php?h={info_hash}",
            ])

        for u in urls_to_try:
            try:
                req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    if resp.status == 200:
                        raw = resp.read()
                        if raw and raw.startswith(b'd8:announce'):
                            torrent_bytes = raw
                            logger.info(f"Direct .torrent file loaded from {u[:50]}")
                            break
            except Exception as e:
                logger.debug(f"Direct .torrent fetch failed from {u[:50]}: {e}")

        if torrent_bytes:
            try:
                ti = lt.torrent_info(torrent_bytes)
                params = lt.add_torrent_params()
                params.ti = ti
                params.save_path = str(self.cache_dir)
                if hasattr(lt, 'storage_mode_t'):
                    params.storage_mode = lt.storage_mode_t.storage_mode_sparse
                params.flags |= lt.torrent_flags.sequential_download
                self.handle = self.session.add_torrent(params)
            except Exception as e:
                logger.warning(f"Failed to load torrent_info from bytes: {e}")

        if not self.handle or not self.handle.is_valid():
            if magnet_or_hash.startswith('magnet:'):
                magnet_uri = magnet_or_hash
            else:
                trackers_str = ''.join(f'&tr={tr}' for tr in TRACKERS)
                magnet_uri = f"magnet:?xt=urn:btih:{info_hash}{trackers_str}"

            params = lt.parse_magnet_uri(magnet_uri)
            params.save_path = str(self.cache_dir)
            if hasattr(lt, 'storage_mode_t'):
                params.storage_mode = lt.storage_mode_t.storage_mode_sparse
            params.flags |= lt.torrent_flags.sequential_download
            self.handle = self.session.add_torrent(params)

        self.handle.set_flags(lt.torrent_flags.sequential_download)

        # Wait for metadata with thread-safe checks
        start_time = time.time()
        while True:
            if self._stop_event.is_set():
                raise RuntimeError("Torrent streaming cancelled")

            handle = self.handle
            if not handle or not handle.is_valid():
                raise RuntimeError("Torrent handle became invalid or was stopped")

            try:
                st = handle.status()
                if st.has_metadata:
                    break
            except Exception as ex:
                logger.debug(f"Torrent status check failed: {ex}")

            if time.time() - start_time > timeout:
                raise TimeoutError("Timed out waiting for torrent metadata")
            time.sleep(0.4)

        info = self.handle.torrent_file()
        num_files = info.num_files()
        files = info.files()

        best_idx = -1
        max_size = -1

        # 1. Exact file_idx from Torrentio/MediaFusion
        if file_idx is not None and 0 <= file_idx < num_files:
            best_idx = file_idx
            max_size = files.file_size(best_idx)

        # 2. Match TV episode patterns (e.g. S01E03, 1x03, E03)
        if best_idx == -1 and season is not None and episode is not None:
            patterns = [
                re.compile(rf'\b[sS]{season:02d}[eE]{episode:02d}\b', re.IGNORECASE),
                re.compile(rf'\b{season}[xX]{episode:02d}\b', re.IGNORECASE),
                re.compile(rf'\b[eE]{episode:02d}\b', re.IGNORECASE),
            ]
            for pat in patterns:
                for i in range(num_files):
                    fn = files.file_path(i).lower()
                    if pat.search(fn) and any(fn.endswith(ext) for ext in VIDEO_EXTS):
                        best_idx = i
                        max_size = files.file_size(i)
                        break
                if best_idx != -1:
                    break

        # 3. Fallback: Find largest video file
        if best_idx == -1:
            for i in range(num_files):
                fn = files.file_path(i).lower()
                sz = files.file_size(i)
                if sz > max_size and any(fn.endswith(ext) for ext in VIDEO_EXTS):
                    max_size = sz
                    best_idx = i

        if best_idx == -1:
            # Fallback to absolute largest file
            for i in range(num_files):
                sz = files.file_size(i)
                if sz > max_size:
                    max_size = sz
                    best_idx = i

        if best_idx == -1 or max_size <= 0:
            raise RuntimeError("No playable video file found in torrent")

        self.video_file_idx = best_idx
        self.video_file_size = max_size
        rel_path = files.file_path(best_idx)
        self.video_file_path = str(self.cache_dir / rel_path)
        self.piece_length = info.piece_length()

        # Prioritize video file only
        priorities = [0] * num_files
        priorities[best_idx] = 7
        self.handle.prioritize_files(priorities)

        req_start = info.map_file(best_idx, 0, 1)
        req_end = info.map_file(best_idx, max_size - 1, 1)
        self.start_piece = req_start.piece
        self.end_piece = req_end.piece
        self._current_stream_piece = self.start_piece

        # Zero out all pieces across entire torrent so peers don't waste bandwidth on random pieces
        num_pieces = info.num_pieces()
        try:
            self.handle.prioritize_pieces([0] * num_pieces)
        except Exception as e:
            logger.debug(f"Failed to initialize zero piece priorities: {e}")

        # Prioritize header pieces (first 8 pieces) and footer pieces (last 4 pieces for MP4 moov / MKV cues)
        for p in range(self.start_piece, min(self.start_piece + 8, self.end_piece + 1)):
            self.handle.piece_priority(p, 7)
            self.handle.set_piece_deadline(p, 0)

        for p in range(max(self.start_piece, self.end_piece - 4), self.end_piece + 1):
            self.handle.piece_priority(p, 7)
            self.handle.set_piece_deadline(p, 0)

        # Start HTTP server on an ephemeral free port and begin active sequential window scheduler
        self._start_http_server()
        self._start_sequential_worker()
        self.state_string = "buffering"

        # Wait for start piece (container header) to ensure file creation before MPV connects
        wait_start = time.time()
        while not self._stop_event.is_set():
            handle = self.handle
            if not handle or not handle.is_valid():
                raise RuntimeError("Torrent handle became invalid or was stopped")
            if handle.have_piece(self.start_piece):
                # Ensure OS file flush has occurred
                for _ in range(40):
                    if os.path.exists(self.video_file_path) and os.path.getsize(self.video_file_path) > 0:
                        break
                    time.sleep(0.05)
                break
            if time.time() - wait_start > 30.0:
                logger.info("Initial piece wait reached 30s limit; proceeding with streaming")
                break
            time.sleep(0.1)

        self.state_string = "ready"
        return f"http://127.0.0.1:{self.http_port}/stream"

    def _start_http_server(self):
        """Bind and run HTTP Range server on loopback."""
        # Find free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            self.http_port = s.getsockname()[1]

        self.httpd = ThreadedHTTPServer(('127.0.0.1', self.http_port), TorrentStreamRequestHandler)
        self.httpd.streamer = self

        self.http_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.http_thread.start()

    def _start_sequential_worker(self):
        """Start background sliding-window piece prioritizer."""
        if self._sequential_thread and self._sequential_thread.is_alive():
            return
        self._sequential_thread = threading.Thread(target=self._sequential_loop, daemon=True)
        self._sequential_thread.start()

    def _sequential_loop(self):
        """Continuously enforce an active sliding window around the current playback head."""
        last_window_center = -1
        while not self._stop_event.is_set():
            handle = self.handle
            if not handle or not handle.is_valid():
                break

            try:
                curr = self._current_stream_piece
                # 1. Urgent window: curr to curr + 8 (priority 7, deadline 0)
                urgent_end = min(curr + 9, self.end_piece + 1)
                for p in range(curr, urgent_end):
                    if not handle.have_piece(p):
                        handle.piece_priority(p, 7)
                        handle.set_piece_deadline(p, 0)

                # 2. Buffer window: curr + 9 to curr + 32 (priority 7, graduated deadlines)
                buf_end = min(curr + 33, self.end_piece + 1)
                for p in range(urgent_end, buf_end):
                    if not handle.have_piece(p):
                        handle.piece_priority(p, 7)
                        handle.set_piece_deadline(p, (p - curr) * 1000)

                # 3. Lookahead window: curr + 33 to curr + 64 (priority 6)
                lookahead_end = min(curr + 65, self.end_piece + 1)
                for p in range(buf_end, lookahead_end):
                    if not handle.have_piece(p):
                        handle.piece_priority(p, 6)

                # 4. If playback head moved, de-prioritize far-ahead pieces to 0
                if curr != last_window_center:
                    last_window_center = curr
                    footer_start = max(self.start_piece, self.end_piece - 4)
                    for p in range(lookahead_end, footer_start):
                        if not handle.have_piece(p):
                            handle.piece_priority(p, 0)

                # 5. Always maintain footer pieces (essential for container duration/index)
                for p in range(max(self.start_piece, self.end_piece - 4), self.end_piece + 1):
                    if not handle.have_piece(p):
                        handle.piece_priority(p, 7)
                        handle.set_piece_deadline(p, 0)

            except Exception as ex:
                logger.debug(f"Sequential loop error: {ex}")

            time.sleep(0.2)

    def stream_bytes(self, wfile, offset: int, length: int, chunk_size: int = 65536):
        """Stream bytes from disk, keeping HTTP connection open during buffering and enforcing piece readiness."""
        if not self.handle or not self.handle.is_valid():
            return

        info = self.handle.torrent_file()
        bytes_sent = 0

        # Update current playback piece from requested offset
        req_piece = info.map_file(self.video_file_idx, offset, 1).piece
        self._current_stream_piece = req_piece

        # If seeking to a piece that's not ready, prioritize it immediately
        if not self.handle.have_piece(req_piece):
            try:
                self.handle.clear_piece_deadlines()
            except Exception:
                pass
            self.handle.piece_priority(req_piece, 7)
            self.handle.set_piece_deadline(req_piece, 0)

        # Wait for file to appear on disk if libtorrent disk I/O thread is still writing initial blocks
        wait_file_start = time.time()
        while not self._stop_event.is_set() and not os.path.exists(self.video_file_path):
            time.sleep(0.05)
            if time.time() - wait_file_start > 15.0:
                break

        if not os.path.exists(self.video_file_path):
            logger.warning(f"Video file not yet on disk: {self.video_file_path}")
            return

        try:
            with open(self.video_file_path, 'rb') as f:
                while bytes_sent < length and not self._stop_event.is_set():
                    curr_pos = offset + bytes_sent
                    chunk_to_read = min(chunk_size, length - bytes_sent)

                    p_start = info.map_file(self.video_file_idx, curr_pos, 1).piece
                    p_end = info.map_file(self.video_file_idx, curr_pos + chunk_to_read - 1, 1).piece
                    self._current_stream_piece = p_start

                    # Check if all pieces required for this chunk are downloaded
                    if not all(self.handle.have_piece(p) for p in range(p_start, p_end + 1)):
                        self.state_string = "buffering"
                        for p in range(p_start, p_end + 1):
                            if not self.handle.have_piece(p):
                                self.handle.piece_priority(p, 7)
                                self.handle.set_piece_deadline(p, 0)

                        # Wait patiently for required pieces without closing the HTTP socket
                        while not self._stop_event.is_set():
                            if all(self.handle.have_piece(p) for p in range(p_start, p_end + 1)):
                                break
                            time.sleep(0.04)

                        if self._stop_event.is_set():
                            break

                    self.state_string = "ready"
                    f.seek(curr_pos)
                    data = f.read(chunk_to_read)
                    if not data:
                        time.sleep(0.02)
                        continue

                    try:
                        wfile.write(data)
                        wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        # Client disconnected or seeked
                        break

                    bytes_sent += len(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            logger.debug(f"stream_bytes error: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Return live torrent status dictionary."""
        if not self.handle or not self.handle.is_valid():
            return {
                'state': 'idle',
                'progress': 0.0,
                'download_rate': 0,
                'peers': 0,
                'seeds': 0,
                'info_hash': self.current_info_hash,
                'file_idx': self.current_file_idx,
            }

        st = self.handle.status()
        return {
            'state': self.state_string,
            'progress': st.progress,
            'download_rate': st.download_rate,
            'upload_rate': st.upload_rate,
            'peers': st.num_peers,
            'seeds': st.num_seeds,
            'total_done': st.total_done,
            'total_size': self.video_file_size,
            'video_file_name': os.path.basename(self.video_file_path) if self.video_file_path else None,
            'info_hash': self.current_info_hash,
            'file_idx': self.current_file_idx,
        }

    def stop(self):
        """Stop streaming and clean up server and torrent session."""
        self._stop_event.set()
        self.is_running = False
        self.state_string = "stopped"

        if self._sequential_thread and self._sequential_thread.is_alive():
            try:
                self._sequential_thread.join(timeout=0.5)
            except Exception:
                pass
            self._sequential_thread = None


        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None

        if self.session and self.handle and self.handle.is_valid():
            try:
                self.session.remove_torrent(self.handle)
            except Exception:
                pass
            self.handle = None

        if self.session:
            self.session = None

        # Prune cache according to user's settings
        try:
            from showberry.services.settings import SettingsService
            settings = SettingsService()
            max_cache_gb = settings.torrent_cache_size_gb
            video_path = self.video_file_path
            if max_cache_gb == 0 and video_path and os.path.exists(video_path):
                # Clean up immediately for stream-only mode
                try:
                    p = Path(video_path)
                    if p.parent != self.cache_dir and p.parent.parent == self.cache_dir:
                        import shutil
                        shutil.rmtree(p.parent)
                    elif p.exists():
                        p.unlink()
                except Exception:
                    pass
            else:
                prune_torrent_cache(self.cache_dir, max_cache_gb)
        except Exception as e:
            logger.debug(f"Cache cleanup error: {e}")


def prune_torrent_cache(cache_dir: Path, max_size_gb: int, current_file: Optional[str] = None):
    """Prune oldest torrent files/directories to adhere to configured cache size."""
    try:
        if max_size_gb < 0:  # Unlimited
            return
        if not cache_dir.exists():
            return

        import shutil
        if max_size_gb == 0:
            # Stream only: remove any files not currently active
            for item in cache_dir.iterdir():
                if current_file and str(item) in current_file:
                    continue
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except Exception as ex:
                    logger.debug(f"Failed to clean stream-only cache {item}: {ex}")
            return

        max_bytes = max_size_gb * (1024 ** 3)
        entries = []
        total_size = 0
        for item in cache_dir.iterdir():
            if item.is_dir():
                sz = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                mt = item.stat().st_mtime
                entries.append((mt, sz, item))
                total_size += sz
            elif item.is_file():
                sz = item.stat().st_size
                mt = item.stat().st_mtime
                entries.append((mt, sz, item))
                total_size += sz

        if total_size <= max_bytes:
            return

        # Oldest first
        entries.sort(key=lambda x: x[0])
        for mt, sz, item in entries:
            if total_size <= max_bytes:
                break
            if current_file and str(item) in current_file:
                continue
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                total_size -= sz
                logger.info(f"Evicted old torrent cache: {item.name} ({sz / (1024**2):.1f} MB)")
            except Exception as ex:
                logger.debug(f"Failed to evict {item}: {ex}")
    except Exception as e:
        logger.warning(f"Error during torrent cache pruning: {e}")


_streamer_instance: Optional[TorrentStreamer] = None


def get_torrent_streamer() -> Optional[TorrentStreamer]:
    global _streamer_instance
    if not HAS_LIBTORRENT:
        return None
    if _streamer_instance is None:
        try:
            _streamer_instance = TorrentStreamer()
        except RuntimeError:
            return None
    return _streamer_instance
