"""VidLink streaming provider."""

import base64
import ctypes
import ctypes.util
import logging
import struct
import time
from typing import Optional

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    import requests as curl_requests

import requests  # fallback for explicit requests.get calls

from showberry.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)

VIDLINK_KEY_HEX = "c75136c5668bbfe65a7ecad431a745db68b5f381555b38d8f6c699449cf11fcd"
VIDLINK_KEY = bytes.fromhex(VIDLINK_KEY_HEX)
VIDLINK_NONCE = bytes(24)

# Load libsodium for native XSalsa20-Poly1305 SecretBox encryption
_sodium = None
for lib_name in ['libsodium.so.26', 'libsodium.so', 'sodium']:
    try:
        _sodium = ctypes.CDLL(lib_name)
        break
    except OSError:
        continue
if not _sodium:
    lib_path = ctypes.util.find_library('sodium')
    if lib_path:
        try:
            _sodium = ctypes.CDLL(lib_path)
        except OSError:
            pass


def _encrypt_token_native(media_id: str) -> Optional[str]:
    """Encrypt media ID with XSalsa20-Poly1305 using libsodium."""
    if not _sodium:
        return None
    try:
        timestamp = int(time.time() + 480)
        message = media_id.encode('utf-8') + struct.pack('>Q', timestamp)
        mlen = len(message)
        # crypto_secretbox_MACBYTES = 16
        c = ctypes.create_string_buffer(mlen + 16)
        ret = _sodium.crypto_secretbox_easy(c, message, mlen, VIDLINK_NONCE, VIDLINK_KEY)
        if ret != 0:
            return None
        full_payload = VIDLINK_NONCE + c.raw
        return base64.urlsafe_b64encode(full_payload).decode('utf-8').rstrip('=')
    except Exception as e:
        logger.error(f"libsodium encryption failed: {e}")
        return None


def _encrypt_token_fallback(media_id: str) -> Optional[str]:
    """Fallback token encryption via public enc-dec API."""
    import requests
    try:
        resp = requests.get(f"https://enc-dec.app/api/enc-vidlink?text={media_id}", timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') == 200:
                return data.get('result')
    except Exception as e:
        logger.error(f"Fallback enc-dec failed: {e}")
    return None


def encrypt_media_token(media_id: str) -> Optional[str]:
    token = _encrypt_token_native(media_id)
    if not token:
        token = _encrypt_token_fallback(media_id)
    return token


class VidLinkProvider(BaseProvider):
    """VidLink.pro streaming provider."""

    name = 'VidLink'
    base_url = 'https://vidlink.pro'

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Get stream URL from VidLink."""
        try:
            media_id = str(tmdb_id)
            token = encrypt_media_token(media_id)
            if not token:
                logger.error(f"Could not encrypt media ID {media_id} for VidLink")
                return None

            if season is not None and episode is not None:
                api_url = f"{self.base_url}/api/b/tv/{token}/{season}/{episode}?multiLang=1"
            else:
                api_url = f"{self.base_url}/api/b/movie/{token}?multiLang=1"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
                'Origin': self.base_url,
                'Referer': f"{self.base_url}/",
            }

            # Use curl_cffi with chrome impersonation to avoid TLS fingerprint blocks, fallback to requests
            resp = None
            if hasattr(curl_requests, 'get') and 'impersonate' in curl_requests.get.__code__.co_varnames:
                try:
                    resp = curl_requests.get(api_url, headers=headers, impersonate='chrome124', timeout=8)
                except Exception as ce:
                    logger.debug(f"VidLink curl_cffi failed ({ce}), falling back to requests")
            if resp is None:
                resp = requests.get(api_url, headers=headers, timeout=8)

            if resp.status_code != 200:
                logger.warning(f"VidLink API returned status {resp.status_code}")
                return None

            data = resp.json()
            if not data or 'stream' not in data:
                logger.warning("VidLink returned response without stream field")
                return None

            stream_info = data['stream']
            stream_type = stream_info.get('type')  # 'file' or 'hls'
            stream_url = None
            quality = '1080p'
            stream_headers = {}

            # Parse qualities (e.g. 1080, 720, 480, 360)
            qualities = stream_info.get('qualities', {})
            if qualities:
                # Pick highest quality available
                for q in ['1080', '720', '480', '360']:
                    if q in qualities and qualities[q].get('url'):
                        stream_url = qualities[q]['url']
                        quality = f"{q}p"
                        stream_headers = qualities[q].get('headers', {})
                        break

            # If not in qualities, check direct playlist or url
            if not stream_url:
                if stream_info.get('playlist'):
                    stream_url = stream_info['playlist']
                elif stream_info.get('url'):
                    stream_url = stream_info['url']

            if not stream_url:
                return None

            referer = stream_headers.get('referer', 'https://filmboom.top/')
            origin = stream_headers.get('origin', 'https://filmboom.top')

            # Extract captions/subtitles
            subtitles = []
            captions = data.get('captions', [])
            for c in captions:
                if c.get('url'):
                    subtitles.append({
                        'url': c['url'],
                        'lang': c.get('language', 'en'),
                        'label': c.get('label', c.get('language', 'English')),
                    })

            media_format = 'mp4' if stream_type == 'file' or '.mp4' in stream_url else 'hls'

            return StreamResult(
                url=stream_url,
                referer=referer,
                origin=origin,
                quality=quality,
                format=media_format,
                headers=stream_headers,
                subtitles=subtitles,
                provider_name=self.name,
            )
        except Exception as e:
            logger.error(f"VidLink resolution error: {e}")
            return None

