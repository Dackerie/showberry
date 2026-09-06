"""Provider system for streaming sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class StreamResult:
    """Result from a provider stream resolution."""
    url: str
    referer: str = ''
    origin: str = ''
    quality: str = ''
    format: str = 'hls'  # 'hls', 'dash', or 'mp4'
    headers: Dict[str, str] = field(default_factory=dict)
    subtitles: List[Dict[str, str]] = field(default_factory=list)
    provider_name: str = ''

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class BaseProvider(ABC):
    """Abstract base class for streaming providers."""

    name: str = 'Unknown'
    base_url: str = ''

    @abstractmethod
    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """
        Get stream URL for a movie or TV show.

        Args:
            tmdb_id: TMDB movie/show ID
            season: Season number (for TV shows)
            episode: Episode number (for TV shows)

        Returns:
            StreamResult with URL and metadata, or None on failure
        """
        pass

    def __repr__(self):
        return f'<{self.__class__.__name__}: {self.name}>'


class ProviderManager:
    """Manages providers and provides automatic fallback cascade resolution."""

    @staticmethod
    def get_providers() -> List[BaseProvider]:
        return get_all_providers()

    @staticmethod
    def get_provider_by_name(name: str) -> Optional[BaseProvider]:
        for p in get_all_providers():
            if p.name.lower() == name.lower():
                return p
        return None

    @classmethod
    def resolve_stream(
        cls,
        tmdb_id: int,
        season: int = None,
        episode: int = None,
        preferred_provider_name: Optional[str] = None
    ) -> Optional[StreamResult]:
        """
        Resolve stream for given media, falling back through available providers.
        """
        all_providers = cls.get_providers()
        ordered_providers: List[BaseProvider] = []

        if preferred_provider_name:
            pref = cls.get_provider_by_name(preferred_provider_name)
            if pref:
                ordered_providers.append(pref)

        for p in all_providers:
            if p not in ordered_providers:
                ordered_providers.append(p)

        for provider in ordered_providers:
            try:
                logger.info(f"Attempting stream resolution with {provider.name} for TMDB {tmdb_id}")
                res = provider.get_stream_url(tmdb_id, season=season, episode=episode)
                if res and res.url:
                    if not res.provider_name:
                        res.provider_name = provider.name
                    logger.info(f"Successfully resolved stream with {provider.name}")
                    return res
            except Exception as e:
                logger.warning(f"Provider {provider.name} failed: {e}")
                continue

        return None


def get_all_providers():
    """Get all available providers ordered by reliability and priority."""
    from kinema.providers.vidlink import VidLinkProvider
    from kinema.providers.videasy import VidEasyProvider
    from kinema.providers.vidfast import VidFastProvider
    from kinema.providers.vidnest import VidNestProvider
    from kinema.providers.superembed import SuperEmbedProvider
    from kinema.providers.primewire import PrimeWireProvider
    from kinema.providers.cinesrc import CineSrcProvider
    from kinema.providers.vidzee import VidZeeProvider
    from kinema.providers.vidsrc import VidSrcProvider
    from kinema.providers.torrent import TorrentProvider

    return [
        VidLinkProvider(),
        VidEasyProvider(),
        VidFastProvider(),
        VidNestProvider(),
        SuperEmbedProvider(),
        PrimeWireProvider(),
        CineSrcProvider(),
        VidZeeProvider(),
        VidSrcProvider(),
        TorrentProvider(),
    ]

