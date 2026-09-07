"""Subtitle service for discovering and downloading subtitles."""

import json
import logging
import os
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional
from gi.repository import GLib

logger = logging.getLogger(__name__)

STREMIO_SUBTITLES_URL = "https://opensubtitles-v3.strem.io/subtitles"

# Common language code mappings
LANG_NAMES = {
    'eng': 'English',
    'en': 'English',
    'spa': 'Spanish',
    'es': 'Spanish',
    'fre': 'French',
    'fra': 'French',
    'fr': 'French',
    'ger': 'German',
    'deu': 'German',
    'de': 'German',
    'ita': 'Italian',
    'it': 'Italian',
    'por': 'Portuguese',
    'pt': 'Portuguese',
    'pob': 'Portuguese (Brazil)',
    'rus': 'Russian',
    'ru': 'Russian',
    'ara': 'Arabic',
    'ar': 'Arabic',
    'chi': 'Chinese',
    'zho': 'Chinese',
    'zh': 'Chinese',
    'jpn': 'Japanese',
    'ja': 'Japanese',
    'kor': 'Korean',
    'ko': 'Korean',
    'hin': 'Hindi',
    'hi': 'Hindi',
    'pol': 'Polish',
    'pl': 'Polish',
    'tur': 'Turkish',
    'tr': 'Turkish',
    'dut': 'Dutch',
    'nld': 'Dutch',
    'nl': 'Dutch',
}


class SubtitleService:
    """Service to discover and download subtitles for movies and TV series."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return

        cache_dir = Path(GLib.get_user_cache_dir()) / 'showberry' / 'subtitles'
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir = cache_dir
        self._initialized = True

    def get_subtitles(
        self,
        imdb_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        language_filter: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch available subtitles for a movie or TV episode using OpenSubtitles.

        Args:
            imdb_id: IMDB ID (e.g. 'tt0137523')
            season: Season number (for TV series)
            episode: Episode number (for TV series)
            language_filter: Optional list of language codes to prioritize or filter

        Returns:
            List of subtitle dictionaries with 'id', 'url', 'lang', 'label'
        """
        if not imdb_id or not imdb_id.startswith('tt'):
            return []

        try:
            if season is not None and episode is not None:
                url = f"{STREMIO_SUBTITLES_URL}/series/{imdb_id}:{season}:{episode}.json"
            else:
                url = f"{STREMIO_SUBTITLES_URL}/movie/{imdb_id}.json"

            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )

            with urllib.request.urlopen(req, timeout=4) as resp:
                if resp.status != 200:
                    return []
                data = json.loads(resp.read().decode('utf-8', errors='replace'))

            subtitles = []
            for item in data.get('subtitles', []):
                sub_url = item.get('url')
                if not sub_url:
                    continue

                lang_code = item.get('lang', 'eng').lower()
                lang_label = LANG_NAMES.get(lang_code, lang_code.upper())
                file_name = item.get('subtitleFileName', '')
                if file_name and len(file_name) < 40:
                    label = f"{lang_label} ({file_name})"
                else:
                    label = f"{lang_label}"

                subtitles.append({
                    'id': str(item.get('id', '')),
                    'url': sub_url,
                    'lang': lang_code,
                    'label': label,
                    'format': 'srt'
                })

            # Sort so English / preferred languages come first
            if language_filter:
                filter_set = set(l.lower() for l in language_filter)
                subtitles.sort(key=lambda s: 0 if s['lang'] in filter_set else 1)
            else:
                subtitles.sort(key=lambda s: 0 if s['lang'] in ('eng', 'en') else 1)

            return subtitles

        except Exception as e:
            logger.warning(f"Failed to fetch subtitles from OpenSubtitles: {e}")
            return []

    def download_subtitle(
        self,
        sub_url: str,
        filename_hint: str = "subtitle.srt",
        headers: Optional[Dict[str, str]] = None,
        referer: Optional[str] = None
    ) -> Optional[str]:
        """
        Download subtitle to local cache and return the local path.
        Accepts optional referer and headers to authenticate against protected provider CDNs.
        """
        try:
            url_hash = hex(abs(hash(sub_url)))[2:]
            safe_filename = f"{url_hash}_{os.path.basename(filename_hint)}"
            if not safe_filename.endswith(('.srt', '.vtt')):
                safe_filename += '.srt'

            local_path = self._cache_dir / safe_filename
            if local_path.exists() and local_path.stat().st_size > 0:
                return str(local_path)

            req_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            if referer:
                req_headers['Referer'] = referer
                req_headers['Origin'] = referer.rstrip('/')
            if headers:
                for k, v in headers.items():
                    if k.lower() in ('referer', 'origin', 'user-agent', 'accept'):
                        req_headers[k] = v

            req = urllib.request.Request(sub_url, headers=req_headers)

            with urllib.request.urlopen(req, timeout=4) as resp:
                content = resp.read()

            with open(local_path, 'wb') as f:
                f.write(content)

            return str(local_path)
        except Exception as e:
            logger.warning(f"Error downloading subtitle {sub_url}: {e}")
            return None
