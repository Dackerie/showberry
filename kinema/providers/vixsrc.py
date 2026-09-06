"""VixSrc streaming provider (https://vixsrc.to/)."""

import logging
from typing import Optional

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    import requests as curl_requests

from kinema.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)


class VixSrcProvider(BaseProvider):
    """VixSrc streaming provider (https://vixsrc.to/)."""

    name = 'VixSrc'
    base_url = 'https://vixsrc.to'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Referer': 'https://vixsrc.to/',
    }

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Resolve stream URL from VixSrc."""
        try:
            is_tv = season is not None and episode is not None
            if is_tv:
                url = f'{self.base_url}/tv/{tmdb_id}/{season}/{episode}'
            else:
                url = f'{self.base_url}/movie/{tmdb_id}'

            # VixSrc is protected by Cloudflare Turnstile; attempt curl_cffi chrome impersonation
            if hasattr(curl_requests, 'get') and 'impersonate' in curl_requests.get.__code__.co_varnames:
                resp = curl_requests.get(url, headers=self.headers, impersonate='chrome124', timeout=8)
            else:
                resp = curl_requests.get(url, headers=self.headers, timeout=8)

            if resp.status_code != 200:
                logger.debug(f"VixSrc returned status {resp.status_code}")
                return None

            # If bypassed, parse player source
            html = resp.text
            if 'cf-turnstile' in html or 'Just a moment...' in html:
                logger.debug("VixSrc Cloudflare challenge encountered")
                return None

            return None
        except Exception as e:
            logger.error(f"VixSrc resolution error: {e}")
            return None
