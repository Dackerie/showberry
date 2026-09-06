"""VidZee streaming provider."""

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


class VidZeeProvider(BaseProvider):
    """VidZee.wtf streaming provider."""

    name = 'VidZee'
    base_url = 'https://player.vidzee.wtf'

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Get stream URL from VidZee."""
        try:
            if season is not None and episode is not None:
                url = f"{self.base_url}/embed/tv/{tmdb_id}/{season}/{episode}"
            else:
                url = f"{self.base_url}/embed/movie/{tmdb_id}"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': f"{self.base_url}/",
            }

            if hasattr(curl_requests, 'get') and 'impersonate' in curl_requests.get.__code__.co_varnames:
                resp = curl_requests.get(url, headers=headers, impersonate='chrome124', timeout=4)
            else:
                resp = curl_requests.get(url, headers=headers, timeout=4)

            if resp.status_code != 200:
                return None

            # Check for direct m3u8 or video source in HTML
            match = re.search(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', resp.text)
            if match:
                stream_url = match.group(1)
                return StreamResult(
                    url=stream_url,
                    referer=f"{self.base_url}/",
                    quality="1080p",
                    format="hls",
                    provider_name=self.name,
                )

            return None
        except Exception as e:
            logger.error(f"VidZee error: {e}")
            return None
