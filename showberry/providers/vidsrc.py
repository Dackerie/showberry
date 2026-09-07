"""VidSrc streaming provider."""

import logging
import re
import requests
from typing import Optional

from showberry.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)


class VidSrcProvider(BaseProvider):
    """VidSrc streaming provider."""

    name = 'VidSrc'
    domains = ['https://vidsrc.me', 'https://vidsrc.in', 'https://vidsrc.pm', 'https://vidsrc.cc']

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Get stream URL from VidSrc mirrors."""
        for base_url in self.domains:
            try:
                if season is not None and episode is not None:
                    path = f'/embed/tv?tmdb={tmdb_id}&season={season}&episode={episode}'
                else:
                    path = f'/embed/movie?tmdb={tmdb_id}'

                url = f'{base_url}{path}'
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': f'{base_url}/',
                }

                response = requests.get(url, headers=headers, timeout=3)
                if response.status_code != 200:
                    continue

                html = response.text
                match = re.search(r'["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', html)
                if match:
                    stream_url = match.group(1)
                    return StreamResult(
                        url=stream_url,
                        referer=f'{base_url}/',
                        quality='1080p',
                        format='hls' if '.m3u8' in stream_url else 'mp4',
                        provider_name=self.name,
                    )
            except Exception as e:
                logger.debug(f"VidSrc attempt with {base_url} failed: {e}")
                continue

        return None
