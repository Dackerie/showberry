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
YTS_MIRRORS = [
    "https://movies-api.accel.li/api/v2/list_movies.json",
    "https://yts.gg/api/v2/list_movies.json",
]


class TorrentProvider(BaseProvider):
    """Provider that discovers torrents via Torrentio & YTS and streams them sequentially via libtorrent."""

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
            if not quality:
                quality = '1080p' if '1080' in title else ('720p' if '720' in title else 'HD')

            logger.info(f"Selected torrent {info_hash} ({quality}) for streaming: {title}")

            # Start sequential torrent streaming server
            streamer = get_torrent_streamer()
            http_url = streamer.start_stream(info_hash, timeout=25)

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
                                torrents.append({
                                    'infoHash': h,
                                    'title': f"YTS {q} 👤 {seeds}",
                                    'name': f"YTS {t.get('type', 'bluray')}",
                                    'quality': q,
                                    'seeds': seeds,
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

    def _select_best_stream(self, streams: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Rank streams based on seeders and resolution."""
        def score(stream):
            title = stream.get('title', '')
            seeds = stream.get('seeds')
            if seeds is None:
                seeds_match = re.search(r'👤\s*(\d+)', title)
                seeds = int(seeds_match.group(1)) if seeds_match else 0

            res_bonus = 0
            tl = title.lower()
            if '1080p' in tl or stream.get('quality') == '1080p':
                res_bonus = 500
            elif '720p' in tl or stream.get('quality') == '720p':
                res_bonus = 300
            elif '4k' in tl or '2160p' in tl:
                res_bonus = 100
            elif 'cam' in tl or 'telesync' in tl:
                res_bonus = -1000

            source_bonus = 100 if 'yts' in tl else 0

            return seeds + res_bonus + source_bonus

        sorted_streams = sorted(streams, key=score, reverse=True)
        return sorted_streams[0] if sorted_streams else None
