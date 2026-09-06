"""PrimeWire streaming provider."""

import logging
import requests
from typing import Optional

from kinema.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)


class PrimeWireProvider(BaseProvider):
    """PrimeWire.mov streaming provider."""

    name = 'PrimeWire'
    base_url = 'https://primewire.mov'

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Get stream URL from PrimeWire."""
        try:
            is_tv = (season is not None and episode is not None)
            url = f"{self.base_url}/api/v1/s?type={'tv' if is_tv else 'movie'}&tmdb={tmdb_id}"
            if is_tv:
                url += f"&season={season}&episode={episode}"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': f"{self.base_url}/",
            }

            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code != 200:
                return None

            data = resp.json()
            servers = data.get('servers', [])
            if not servers:
                return None

            for srv in servers:
                key = srv.get('key')
                if not key:
                    continue
                try:
                    link_resp = requests.get(f"{self.base_url}/api/v1/l?key={key}", headers=headers, timeout=6)
                    if link_resp.status_code == 200:
                        link_data = link_resp.json()
                        stream_url = link_data.get('link') or link_data.get('url')
                        if stream_url:
                            fmt = 'hls' if '.m3u8' in stream_url else 'mp4'
                            return StreamResult(
                                url=stream_url,
                                referer=f"{self.base_url}/",
                                quality=srv.get('quality', '1080p') or '1080p',
                                format=fmt,
                                provider_name=self.name,
                            )
                except Exception:
                    continue

            return None
        except Exception as e:
            logger.error(f"PrimeWire error: {e}")
            return None
