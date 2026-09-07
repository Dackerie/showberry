"""Torrent P2P streaming provider using Torrentio, YTS, and libtorrent."""

import re
import json
import logging
import urllib.request
from typing import Optional, List, Dict, Any

from kinema.providers.base import BaseProvider, StreamResult
from kinema.services.tmdb import TMDBClient
from kinema.services.torrent import get_torrent_streamer, HAS_LIBTORRENT

logger = logging.getLogger(__name__)

TORRENTIO_BASE = "https://torrentio.strem.fun/stream"
MEDIAFUSION_BASE = "https://mediafusion.elfhosted.com/stream"
YTS_MIRRORS = [
    "https://movies-api.accel.li/api/v2/list_movies.json",
    "https://yts.gg/api/v2/list_movies.json",
]


def parse_stream_size_gb(stream: Dict[str, Any]) -> Optional[float]:
    """Parse torrent file size in gigabytes from metadata or title."""
    if 'size_bytes' in stream and stream['size_bytes']:
        try:
            return float(stream['size_bytes']) / (1024 ** 3)
        except (ValueError, TypeError):
            pass

    title = stream.get('title', '')
    match = re.search(r'💾\s*([\d.]+)\s*(GB|MB|TB)', title, re.IGNORECASE)
    if not match:
        match = re.search(r'\b([\d.]+)\s*(GB|MB|TB)\b', title, re.IGNORECASE)
    if match:
        try:
            val = float(match.group(1))
            unit = match.group(2).upper()
            if unit == 'GB':
                return val
            elif unit == 'MB':
                return val / 1024.0
            elif unit == 'TB':
                return val * 1024.0
        except (ValueError, TypeError):
            pass
    return None


class TorrentProvider(BaseProvider):
    """Provider that discovers torrents via Torrentio, MediaFusion & YTS and streams them sequentially via libtorrent."""

    name = 'Torrent (P2P)'

    def __init__(self):
        self._tmdb = TMDBClient()

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        if not HAS_LIBTORRENT:
            logger.warning("libtorrent is not installed; Torrent provider cannot stream.")
            return None

        try:
            is_tv = (season is not None and episode is not None)
            imdb_id = self._tmdb.get_imdb_id(tmdb_id, is_tv=is_tv)

            if not imdb_id:
                logger.warning(f"Could not find IMDB ID for TMDB {tmdb_id}")
                return None

            all_streams: List[Dict[str, Any]] = []

            # 1. For movies, query YTS high-seed torrents
            if not is_tv:
                yts_streams = self._fetch_yts_torrents(imdb_id)
                all_streams.extend(yts_streams)

            # 2. Query Torrentio multi-tracker streams (movies and TV series)
            torrentio_streams = self._fetch_torrentio_streams(imdb_id, is_tv, season, episode)
            all_streams.extend(torrentio_streams)

            # 3. Query MediaFusion streams (additional tracker sources)
            mediafusion_streams = self._fetch_mediafusion_streams(imdb_id, is_tv, season, episode)
            all_streams.extend(mediafusion_streams)

            if not all_streams:
                logger.info(f"No torrent streams found for {imdb_id}")
                return None

            # Deduplicate by infoHash
            seen_hashes = set()
            unique_streams = []
            for s in all_streams:
                h = (s.get('infoHash') or '').lower()
                if h and h not in seen_hashes:
                    seen_hashes.add(h)
                    unique_streams.append(s)

            # Pick best stream based on resolution, seeders, and release health
            best_stream = self._select_best_stream(unique_streams)
            if not best_stream or not best_stream.get('infoHash'):
                return None

            info_hash = best_stream['infoHash']
            title = best_stream.get('title', '')
            quality = best_stream.get('quality')
            torrent_url = best_stream.get('torrent_url')
            if not quality:
                quality = '1080p' if '1080' in title else ('720p' if '720' in title else 'HD')

            logger.info(f"Selected torrent {info_hash} ({quality}) for streaming: {title}")

            # Start sequential torrent streaming server
            file_idx = best_stream.get('fileIdx')
            streamer = get_torrent_streamer()
            http_url = streamer.start_stream(
                info_hash,
                torrent_url=torrent_url,
                file_idx=file_idx,
                season=season,
                episode=episode,
                timeout=35
            )

            return StreamResult(
                url=http_url,
                quality=quality,
                format='mp4',
                provider_name=self.name,
            )

        except Exception as e:
            logger.error(f"TorrentProvider failed to resolve stream: {e}")
            return None

    def _fetch_yts_torrents(self, imdb_id: str) -> List[Dict[str, Any]]:
        """Fetch high-seed verified torrents from YTS API."""
        torrents = []
        for base in YTS_MIRRORS:
            try:
                url = f"{base}?query_term={imdb_id}"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status != 200:
                        continue
                    data = json.loads(resp.read().decode())
                    movies = data.get('data', {}).get('movies', [])
                    if movies:
                        for t in movies[0].get('torrents', []):
                            h = t.get('hash')
                            if h:
                                q = t.get('quality', '720p')
                                seeds = t.get('seeds', 0)
                                size_str = t.get('size', '')
                                size_part = f" 💾 {size_str}" if size_str else ""
                                torrents.append({
                                    'infoHash': h,
                                    'title': f"YTS {q} 👤 {seeds}{size_part}",
                                    'name': f"YTS {t.get('type', 'bluray')}",
                                    'quality': q,
                                    'seeds': seeds,
                                    'size_bytes': t.get('size_bytes'),
                                    'torrent_url': t.get('url'),
                                })
                        break
            except Exception as e:
                logger.debug(f"YTS mirror query failed: {e}")
        return torrents

    def _fetch_torrentio_streams(self, imdb_id: str, is_tv: bool, season: int = None, episode: int = None) -> List[Dict[str, Any]]:
        """Fetch multi-tracker torrent streams from Torrentio."""
        if is_tv:
            url = f"{TORRENTIO_BASE}/series/{imdb_id}:{season}:{episode}.json"
        else:
            url = f"{TORRENTIO_BASE}/movie/{imdb_id}.json"

        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'})
            with urllib.request.urlopen(req, timeout=7) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    return data.get('streams', [])
        except Exception as e:
            logger.warning(f"Torrentio query failed: {e}")
        return []

    def _fetch_mediafusion_streams(self, imdb_id: str, is_tv: bool, season: int = None, episode: int = None) -> List[Dict[str, Any]]:
        """Fetch multi-tracker torrent streams from MediaFusion."""
        if is_tv:
            url = f"{MEDIAFUSION_BASE}/series/{imdb_id}:{season}:{episode}.json"
        else:
            url = f"{MEDIAFUSION_BASE}/movie/{imdb_id}.json"

        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    return data.get('streams', [])
        except Exception as e:
            logger.debug(f"MediaFusion query failed: {e}")
        return []

    def _select_best_stream(self, streams: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Rank streams based on user quality preferences, max size limits, seeds, and release health."""
        from kinema.services.settings import SettingsService
        settings = SettingsService()
        pref_quality = (settings.preferred_torrent_quality or '1080p').lower()
        max_size_gb = settings.max_torrent_size_gb or 0

        def score(stream):
            title = stream.get('title', '')
            tl = title.lower()
            seeds = stream.get('seeds')
            if seeds is None:
                seeds_match = re.search(r'👤\s*(\d+)', title)
                seeds = int(seeds_match.group(1)) if seeds_match else 0

            # Cap seeds contribution to avoid huge multi-movie packs overpowering single movies
            seeds_score = min(seeds, 150)

            # Check size limits: if configured, penalize oversized torrents to preserve user data
            size_penalty = 0
            if max_size_gb > 0:
                stream_size = parse_stream_size_gb(stream)
                if stream_size is not None and stream_size > max_size_gb:
                    size_penalty = -20000  # Disqualify streams exceeding user's size threshold

            # Resolution detection
            is_1080 = '1080p' in tl or stream.get('quality') == '1080p'
            is_720 = '720p' in tl or stream.get('quality') == '720p'
            is_4k = '4k' in tl or '2160p' in tl or stream.get('quality') in ('4k', '2160p')

            res_bonus = 0
            if pref_quality == '720p':
                if is_720:
                    res_bonus = 1000
                elif is_1080:
                    res_bonus = 200
                elif is_4k:
                    res_bonus = -500
            elif pref_quality == '4k':
                if is_4k:
                    res_bonus = 1000
                elif is_1080:
                    res_bonus = 300
                elif is_720:
                    res_bonus = 100
            elif pref_quality == 'auto':
                if is_1080:
                    res_bonus = 500
                elif is_720:
                    res_bonus = 300
                elif is_4k:
                    res_bonus = 200
            else:  # Default '1080p'
                if is_1080:
                    res_bonus = 1000
                elif is_720:
                    res_bonus = 300
                elif is_4k:
                    res_bonus = 100

            if 'cam' in tl or 'telesync' in tl:
                res_bonus -= 2000

            source_bonus = 100 if 'yts' in tl else 0
            # Direct .torrent download URLs resolve immediately without DHT overhead
            direct_torrent_bonus = 1000 if stream.get('torrent_url') else 0

            # Penalize box sets / collection packs that have slow multi-file downloads
            pack_penalty = -1500 if re.search(r'\b(pack|complete|collection|anthology|movies)\b', tl) else 0

            return seeds_score + res_bonus + source_bonus + direct_torrent_bonus + pack_penalty + size_penalty

        sorted_streams = sorted(streams, key=score, reverse=True)
        return sorted_streams[0] if sorted_streams else None
