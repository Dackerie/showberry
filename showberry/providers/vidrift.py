"""VidRift streaming provider (https://vidrift.in/)."""

import json
import logging
import re
from typing import Optional

import requests

from showberry.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)


class VidRiftProvider(BaseProvider):
    """VidRift streaming provider (https://vidrift.in/)."""

    name = 'VidRift'
    base_url = 'https://embed.vidrift.in'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Referer': 'https://vidrift.in/',
        'Origin': 'https://vidrift.in',
    }

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Resolve stream URL from VidRift."""
        try:
            is_tv = season is not None and episode is not None
            if is_tv:
                embed_url = f'{self.base_url}/embed/tv/{tmdb_id}/{season}/{episode}'
            else:
                embed_url = f'{self.base_url}/embed/movie/{tmdb_id}'

            resp = requests.get(embed_url, headers=self.headers, timeout=8)
            if resp.status_code != 200:
                logger.debug(f"VidRift embed returned status {resp.status_code}")
                return None

            html = resp.text

            # Parse embedMeta JSON object
            meta_match = re.search(r'var embedMeta\s*=\s*(\{.*?\});', html)
            if not meta_match:
                logger.debug("VidRift embedMeta not found in HTML")
                return None

            meta = json.loads(meta_match.group(1))
            selfhost_url = meta.get('selfhostUrl')
            if not selfhost_url:
                logger.debug("VidRift selfhostUrl not found in embedMeta")
                return None

            # Parse subtitleTracks JSON array if present
            subtitles = []
            sub_match = re.search(r'var subtitleTracks\s*=\s*(\[.*?\]);', html)
            if sub_match:
                try:
                    sub_data = json.loads(sub_match.group(1))
                    for item in sub_data:
                        if item.get('url'):
                            subtitles.append({
                                'lang': item.get('label') or item.get('code', 'en'),
                                'url': item['url'],
                            })
                except Exception as e:
                    logger.debug(f"VidRift subtitle parse error: {e}")

            return StreamResult(
                url=selfhost_url,
                referer=f'{self.base_url}/',
                origin=self.base_url,
                quality='1080p',
                format='hls' if '.m3u8' in selfhost_url else 'mp4',
                headers={'Referer': f'{self.base_url}/', 'Origin': self.base_url},
                subtitles=subtitles,
                provider_name=self.name,
            )
        except Exception as e:
            logger.error(f"VidRift resolution error: {e}")
            return None
