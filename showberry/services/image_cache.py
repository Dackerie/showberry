"""Image caching service for movie posters and backdrops."""

import os
import hashlib
from pathlib import Path
import gi
gi.require_version('Gdk', '4.0')
from gi.repository import GLib, Gdk, GdkPixbuf

from showberry.services.tmdb import TMDBClient


class ImageCache:
    """Cache for downloaded images."""

    def __init__(self, cache_dir=None):
        if cache_dir is None:
            cache_dir = Path(GLib.get_user_cache_dir()) / 'showberry' / 'images'
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, url):
        """Get local cache path for a URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        # Use extension from URL or default to jpg
        ext = 'jpg'
        if '.png' in url:
            ext = 'png'
        return self._cache_dir / f"{url_hash}.{ext}"

    def get_image(self, url, width=None, height=None):
        """Get a cached Gdk.Texture for the given URL."""
        if not url:
            return None

        cache_path = self._get_cache_path(url)

        # Try to load from cache
        if cache_path.exists():
            return self._load_texture(str(cache_path), width, height)

        # Download the image
        return self._download_and_cache(url, cache_path, width, height)

    def _load_texture(self, path, width=None, height=None):
        """Load a Gdk.Texture from a file path."""
        try:
            if width and height:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    path, width, height, True
                )
                succ, data = pixbuf.save_to_bufferv('png', [], [])
                if succ:
                    return Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
                return None
            else:
                return Gdk.Texture.new_from_filename(path)
        except (GLib.Error, Exception):
            return None

    def _download_and_cache(self, url, cache_path, width=None, height=None):
        """Download an image and cache it."""
        import requests

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            # Write to cache
            with open(cache_path, 'wb') as f:
                f.write(response.content)

            return self._load_texture(str(cache_path), width, height)
        except (requests.RequestException, GLib.Error):
            return None

    def clear(self):
        """Clear the entire image cache."""
        for file in self._cache_dir.glob('*'):
            file.unlink()

    def get_size(self):
        """Get cache size in bytes."""
        total = 0
        for file in self._cache_dir.glob('*'):
            total += file.stat().st_size
        return total
