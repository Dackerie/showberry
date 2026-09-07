"""VidEasy streaming provider with seed-based keystream decryption."""

import base64
import json
import logging
from typing import Optional, List, Dict, Any

import requests

from showberry.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)

# Constants for keystream decryption
F_CONSTS = [
    1116352408, 1899447441, 3049323471, 3921009573, 961987163, 1508970993,
    2453635748, 2870763221, 3624381080, 310598401, 607225278, 1426881987,
    1925078388, 2162078206, 2614888103, 3248222580
]
MAGIC_HEADER = [109, 118, 109, 49]  # "mvm1" in ASCII


def _imul(a: int, b: int) -> int:
    return ((a & 0xFFFFFFFF) * (b & 0xFFFFFFFF)) & 0xFFFFFFFF


def _w(e: int) -> int:
    e = e & 0xFFFFFFFF
    e ^= (e >> 16)
    e = _imul(e, 2246822507)
    e ^= (e >> 13)
    e = _imul(e, 3266489909)
    e ^= (e >> 16)
    return e & 0xFFFFFFFF


def _v(e: int, t: int) -> int:
    e = e & 0xFFFFFFFF
    t = t & 31
    if t == 0:
        return e
    return ((e << t) | (e >> (32 - t))) & 0xFFFFFFFF


def _b_test(e: int) -> bool:
    return ((e * (e + 1)) & 1) == 0


def _init_state(seed_str: str, media_id_val: int) -> Dict[str, Any]:
    media_id_int = int(media_id_val)
    t = 2166136261
    for ch in seed_str:
        t = _imul(t ^ ord(ch), 16777619)
    fn_val = _w(t)

    a = _w(fn_val ^ _w((media_id_int ^ 2654435769) & 0xFFFFFFFF))

    s_map: Dict[int, int] = {}
    for i in range(8):
        if _b_test(i):
            idx = a % 61
            a = _v((a + 2654435769) & 0xFFFFFFFF, 7 + (7 & i))
            s_map[idx] = (a ^ _w(a)) & 0xFFFFFFFF
            a = _w((a + idx) & 0xFFFFFFFF)
        else:
            s_map[i] = F_CONSTS[15 & i]

    acc = (_w(2779096485 ^ a)) & 0xFFFFFFFF
    return {'S': s_map, 'acc': acc}


def _gen_keystream(state: Dict[str, Any], length: int) -> bytearray:
    out = bytearray(length)
    o = 0
    idx = 0
    s_map = state['S']
    o_acc = state['acc']
    while idx < length:
        n = o_acc % 61
        is_in = (n in s_map)
        i = -1 if is_in else 0
        d = s_map.get(n, 0)
        s_val = o_acc
        a_val = (d ^ (_imul(2654435769, o + 1))) & 0xFFFFFFFF
        l_val = ((s_val ^ a_val) | (s_val & a_val & i)) & 0xFFFFFFFF
        o_acc = _w((_v((l_val + o_acc) & 0xFFFFFFFF, 31 & n) ^ _v(o_acc, 31 & _imul(n, 7))) + 2654435769)
        s_map[n] = o_acc
        t_word = o_acc

        out[idx] = t_word & 255
        idx += 1
        if idx < length:
            out[idx] = (t_word >> 8) & 255
            idx += 1
        if idx < length:
            out[idx] = (t_word >> 16) & 255
            idx += 1
        if idx < length:
            out[idx] = (t_word >> 24) & 255
            idx += 1
        o += 1
    return out


def decrypt_videasy_payload(payload_str: str, seed: str, media_id: int) -> Optional[Dict[str, Any]]:
    """Decrypt the payload returned by speedracelight/videasy."""
    try:
        b64_clean = payload_str.strip().strip('"').replace('-', '+').replace('_', '/')
        b64_clean += '=' * ((4 - len(b64_clean) % 4) % 4)
        raw = bytearray(base64.b64decode(b64_clean))

        st = _init_state(seed, media_id)
        ks = _gen_keystream(st, len(raw))

        for i in range(len(raw)):
            raw[i] ^= ks[i]

        if list(raw[:4]) != MAGIC_HEADER:
            logger.warning(f"Decryption magic header mismatch: {list(raw[:4])} vs {MAGIC_HEADER}")
            return None

        json_bytes = raw[4:]
        decrypted_text = json_bytes.decode('utf-8', errors='ignore')
        return json.loads(decrypted_text)
    except Exception as e:
        logger.error(f"Failed to decrypt videasy payload: {e}")
        return None


class VidEasyProvider(BaseProvider):
    """VidEasy.to / Speedracelight streaming provider."""

    name = 'VidEasy'
    api_url = 'https://api.speedracelight.com'
    player_url = 'https://player.videasy.to'

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Get stream URL from VidEasy."""
        try:
            media_id = int(tmdb_id)
            is_tv = (season is not None and episode is not None)

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': f'{self.player_url}/',
                'Origin': self.player_url,
            }

            # 1. Fetch seed for media ID
            seed_req_url = f'{self.api_url}/seed?mediaId={media_id}'
            seed_resp = requests.get(seed_req_url, headers=headers, timeout=8)
            if seed_resp.status_code != 200:
                logger.warning(f"VidEasy seed request failed: {seed_resp.status_code}")
                return None

            seed_data = seed_resp.json()
            seed = seed_data.get('seed')
            if not seed:
                logger.warning("VidEasy returned empty seed")
                return None

            # 2. Query sources endpoints (try cdn, then lamovie, then downloader2)
            endpoints = ['/cdn/sources-with-title', '/lamovie/sources-with-title', '/downloader2/sources-with-title']
            params: Dict[str, Any] = {
                'mediaType': 'tv' if is_tv else 'movie',
                'tmdbId': media_id,
                'enc': '2',
                'seed': seed,
            }
            if is_tv:
                params['seasonId'] = season
                params['episodeId'] = episode

            for ep in endpoints:
                try:
                    src_resp = requests.get(f'{self.api_url}{ep}', params=params, headers=headers, timeout=8)
                    if src_resp.status_code != 200 or not src_resp.text:
                        continue

                    decrypted = decrypt_videasy_payload(src_resp.text, seed, media_id)
                    if not decrypted:
                        continue

                    sources = decrypted.get('sources', [])
                    if not sources:
                        continue

                    # Select best quality source (prefer 1080p, then 720p, or first available)
                    best_src = None
                    for q in ['1080p', '720p', '480p', '2160p']:
                        for s in sources:
                            if s.get('quality') == q and s.get('url'):
                                best_src = s
                                break
                        if best_src:
                            break

                    if not best_src and sources:
                        best_src = sources[0]

                    if best_src and best_src.get('url'):
                        stream_url = best_src['url']
                        subtitles = []
                        for sub in decrypted.get('subtitles', []):
                            if sub.get('url'):
                                subtitles.append({
                                    'url': sub['url'],
                                    'lang': sub.get('lang', 'eng'),
                                    'label': sub.get('label', sub.get('language', 'English')),
                                })

                        return StreamResult(
                            url=stream_url,
                            referer=f'{self.player_url}/',
                            origin=self.player_url,
                            quality=best_src.get('quality', '1080p'),
                            format='hls',
                            headers={
                                'User-Agent': headers['User-Agent'],
                                'Referer': f'{self.player_url}/',
                                'Origin': self.player_url,
                            },
                            subtitles=subtitles,
                            provider_name=self.name,
                        )
                except Exception as ex:
                    logger.debug(f"VidEasy endpoint {ep} attempt failed: {ex}")
                    continue

            return None
        except Exception as e:
            logger.error(f"VidEasy get_stream_url error: {e}")
            return None
