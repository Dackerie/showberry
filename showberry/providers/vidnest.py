"""VidNest streaming provider."""

import logging
import re
from typing import Optional

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    import requests as curl_requests

from showberry.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)


class VidNestProvider(BaseProvider):
    """VidNest.fun streaming provider."""

    name = 'VidNest'
    base_url = 'https://vidnest.fun'

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Get stream URL from VidNest."""
        try:
            if season is not None and episode is not None:
                url = f"{self.base_url}/tv/{tmdb_id}/{season}/{episode}"
            else:
                url = f"{self.base_url}/movie/{tmdb_id}"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
                'Referer': f"{self.base_url}/",
            }

            resp = None
            if hasattr(curl_requests, 'get') and 'impersonate' in curl_requests.get.__code__.co_varnames:
                try:
                    resp = curl_requests.get(url, headers=headers, impersonate='chrome124', timeout=10)
                except Exception as ce:
                    logger.debug(f"VidNest curl_cffi failed ({ce}), falling back to requests")
            if resp is None:
                import requests
                resp = requests.get(url, headers=headers, timeout=10)

            if resp.status_code != 200:
                return None

            # Look for direct m3u8 or video file
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
            logger.error(f"VidNest resolution error: {e}")
            return None
