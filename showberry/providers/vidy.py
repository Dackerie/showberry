"""Vidy streaming provider (https://www.vidy.st/)."""

import base64
import json
import logging
from typing import Optional, Dict, Any, List

import requests

from showberry.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)

# Constants for StreamCrypto cipher
_L = [
    1116352408, 1899447441, 3049323471, 3921009573,
    961987163, 1508970993, 2453635748, 2870763221,
    3624381080, 310598401, 607225278, 1426881987,
    1925078388, 2162078206, 2614888103, 3248222580
]
_MAGIC = [109, 118, 109, 49]  # "mvm1" magic header


def _imul(a: int, b: int) -> int:
    return ((a & 0xFFFFFFFF) * (b & 0xFFFFFFFF)) & 0xFFFFFFFF


def _p_fn(e: int) -> int:
    e &= 0xFFFFFFFF
    e ^= (e >> 16)
    e = _imul(e, 2246822507)
    e ^= (e >> 13)
    e = _imul(e, 3266489909)
    e ^= (e >> 16)
    return e & 0xFFFFFFFF


def _g_fn(e: int, t: int) -> int:
    e &= 0xFFFFFFFF
    t &= 31
    if t == 0:
        return e
    return ((e << t) | (e >> (32 - t))) & 0xFFFFFFFF


def _decrypt_vidy(ciphertext: str, seed_str: str, media_id: int) -> str:
    """Decrypt Vidy's encrypted source response in pure Python."""
    padded = ciphertext.replace('-', '+').replace('_', '/')
    padded += '=' * (-len(padded) % 4)
    raw = bytearray(base64.b64decode(padded))
    length = len(raw)

    t_fnv = 2166136261
    for ch in seed_str:
        t_fnv = _imul(t_fnv ^ ord(ch), 16777619)
    fnv_res = _p_fn(t_fnv)

    n = _p_fn(fnv_res ^ _p_fn((media_id & 0xFFFFFFFF) ^ 2654435769))
    a: Dict[int, int] = {}
    for e in range(8):
        t = n % 61
        n = _g_fn((n + 2654435769) & 0xFFFFFFFF, 7 + (7 & e))
        a[t] = (n ^ _p_fn(n)) & 0xFFFFFFFF
        n = _p_fn((n + t) & 0xFFFFFFFF)

    state = {'S': a, 'acc': _p_fn(2779096485 ^ n)}
    keystream = bytearray(length)
    s_cnt = 0
    e_idx = 0

    while e_idx < length:
        r = state['S']
        s = state['acc']
        o = s % 61
        i = -1 if (o in r) else 0
        d = r.get(o, 0)
        n_term = (d ^ _imul(2654435769, s_cnt + 1)) & 0xFFFFFFFF
        s_cnt += 1
        a_term = s
        l_val = ((a_term ^ n_term) | (a_term & n_term & i)) & 0xFFFFFFFF
        term1 = _g_fn((l_val + s) & 0xFFFFFFFF, 31 & o)
        term2 = _g_fn(s, 31 & _imul(o, 7))
        l_val = (term1 ^ term2) & 0xFFFFFFFF
        s = _p_fn((l_val + 2654435769) & 0xFFFFFFFF)
        r[o] = s
        state['acc'] = s
        t_val = s

        keystream[e_idx] = t_val & 0xFF
        e_idx += 1
        if e_idx < length:
            keystream[e_idx] = (t_val >> 8) & 0xFF
            e_idx += 1
        if e_idx < length:
            keystream[e_idx] = (t_val >> 16) & 0xFF
            e_idx += 1
        if e_idx < length:
            keystream[e_idx] = (t_val >> 24) & 0xFF
            e_idx += 1

    for i in range(length):
        raw[i] ^= keystream[i]

    for i in range(len(_MAGIC)):
        if raw[i] != _MAGIC[i]:
            raise ValueError('Vidy decrypt failed: magic header mismatch')

    return raw[len(_MAGIC):].decode('utf-8')


class VidyProvider(BaseProvider):
    """Vidy streaming provider (https://www.vidy.st/)."""

    name = 'Vidy'
    api_url = 'https://api.wecollege.net'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Referer': 'https://www.vidy.st/',
        'Origin': 'https://www.vidy.st',
    }

    # Available Vidy server routes in order of preference
    servers = ['miami', 'atlanta', 'seattle', 'denver', 'dallas', 'tampa']

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Resolve stream URL from Vidy."""
        try:
            # Step 1: Fetch session seed
            seed_resp = requests.get(
                f'{self.api_url}/seed',
                params={'mediaId': tmdb_id},
                headers=self.headers,
                timeout=6,
            )
            if seed_resp.status_code != 200:
                logger.warning(f"Vidy seed request failed with status {seed_resp.status_code}")
                return None

            seed_data = seed_resp.json()
            seed = seed_data.get('seed')
            if not seed:
                return None

            is_tv = season is not None and episode is not None

            # Build query params
            params = {
                'mediaType': 'tv' if is_tv else 'movie',
                'tmdbId': tmdb_id,
                'enc': '2',
                'seed': seed,
            }
            if is_tv:
                params['seasonId'] = season
                params['episodeId'] = episode

            # Try servers in order
            for server in self.servers:
                try:
                    res = requests.get(
                        f'{self.api_url}/{server}/sources',
                        params=params,
                        headers=self.headers,
                        timeout=6,
                    )
                    if res.status_code != 200:
                        continue

                    decrypted_text = _decrypt_vidy(res.text, seed, tmdb_id)
                    data = json.loads(decrypted_text)
                    sources = data.get('sources') or []
                    subtitles = data.get('subtitles') or []

                    if not sources and not data.get('playlist'):
                        continue

                    # Prefer 1080p, else highest quality or master playlist
                    stream_url = data.get('playlist') or ''
                    stream_quality = '1080p'

                    for s in sources:
                        if s.get('quality') == '1080p' and s.get('url'):
                            stream_url = s['url']
                            stream_quality = '1080p'
                            break
                    if not stream_url and sources:
                        stream_url = sources[0].get('url', '')
                        stream_quality = sources[0].get('quality', '')

                    if stream_url:
                        return StreamResult(
                            url=stream_url,
                            referer='https://www.vidy.st/',
                            origin='https://www.vidy.st',
                            quality=stream_quality,
                            format='hls' if '.m3u8' in stream_url else 'mp4',
                            headers=dict(self.headers),
                            subtitles=subtitles,
                            provider_name=self.name,
                        )
                except Exception as e:
                    logger.debug(f"Vidy server {server} failed: {e}")
                    continue

            return None
        except Exception as e:
            logger.error(f"Vidy resolution error: {e}")
            return None
