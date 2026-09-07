"""VidKing streaming provider (mirror of VidEasy)."""

import logging
from typing import Optional

from showberry.providers.base import BaseProvider, StreamResult
from showberry.providers.videasy import VidEasyProvider

logger = logging.getLogger(__name__)


class VidKingProvider(BaseProvider):
    """VidKing streaming provider (https://vidking.net/)."""

    name = 'VidKing'
    base_url = 'https://vidking.net'

    def __init__(self):
        super().__init__()
        self._videasy = VidEasyProvider()

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Resolve stream URL via VidKing / VidEasy mirror."""
        try:
            res = self._videasy.get_stream_url(tmdb_id, season=season, episode=episode)
            if res:
                res.provider_name = self.name
                return res
            return None
        except Exception as e:
            logger.error(f"VidKing resolution error: {e}")
            return None
