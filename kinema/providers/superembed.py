"""SuperEmbed streaming provider."""

import logging
import re
from typing import Optional

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    import requests as curl_requests
import requests

from kinema.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)


class SuperEmbedProvider(BaseProvider):
    """SuperEmbed.stream provider."""

    name = 'SuperEmbed'
    base_url = 'https://superembed.stream'

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Get stream URL from SuperEmbed."""
        try:
            if season is not None and episode is not None:
                url = f"{self.base_url}/?video_id={tmdb_id}&tmdb=1&s={season}&e={episode}"
            else:
                url = f"{self.base_url}/?video_id={tmdb_id}&tmdb=1"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': f"{self.base_url}/",
            }

            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code != 200:
                return None

            match = re.search(r'["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', resp.text)
            if match:
                stream_url = match.group(1)
                fmt = 'hls' if '.m3u8' in stream_url else 'mp4'
                return StreamResult(
                    url=stream_url,
                    referer=f"{self.base_url}/",
                    quality="1080p",
                    format=fmt,
                    provider_name=self.name,
                )

            return None
        except Exception as e:
            logger.error(f"SuperEmbed error: {e}")
            return None
