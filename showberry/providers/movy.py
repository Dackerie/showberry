"""Movy streaming provider (https://www.movy.bz/) with 14 worldwide city servers."""

import base64
import json
import logging
import urllib.parse
import urllib.request
from typing import Optional, Dict, Any, List

from showberry.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)

API_BASE = 'https://api.wecollege.net'
REFERER = 'https://www.movy.bz/'
ORIGIN = 'https://www.movy.bz'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

SERVERS = [
    {'endpoint': 'miami', 'name': 'Miami', 'note': 'Up to 4K', '4k': True},
    {'endpoint': 'seattle', 'name': 'Seattle', 'note': 'Original audio'},
    {'endpoint': 'denver', 'name': 'Denver', 'note': 'Original audio'},
    {'endpoint': 'chicago', 'name': 'Chicago', 'note': 'Original audio'},
    {'endpoint': 'dallas', 'name': 'Dallas', 'note': 'Original audio'},
    {'endpoint': 'atlanta', 'name': 'Atlanta', 'note': 'Original audio'},
    {'endpoint': 'houston', 'name': 'Houston', 'note': 'Original audio'},
    {'endpoint': 'austin', 'name': 'Austin', 'note': 'Original audio'},
    {'endpoint': 'boston', 'name': 'Boston', 'note': 'Original audio'},
    {'endpoint': 'munich', 'name': 'Munich', 'note': 'German audio', 'extra': 'language=german'},
    {'endpoint': 'berlin', 'name': 'Berlin', 'note': 'German audio'},
    {'endpoint': 'paris', 'name': 'Paris', 'note': 'French audio'},
    {'endpoint': 'delhi', 'name': 'Delhi', 'note': 'Hindi audio'},
    {'endpoint': 'cancun', 'name': 'Cancun', 'note': 'Spanish audio'},
]

MAGIC = [109, 118, 109, 49]  # "mvm1"


def _l(e: int) -> int:
    v = e & 0xFFFFFFFF
    v = (v ^ (v >> 16)) & 0xFFFFFFFF
    v = (v * 0x85ebca6b) & 0xFFFFFFFF
    v = (v ^ (v >> 13)) & 0xFFFFFFFF
    v = (v * 0xc2b2ae35) & 0xFFFFFFFF
    return (v ^ (v >> 16)) & 0xFFFFFFFF


def _u(e: int, t: int) -> int:
    shift = t & 31
    if shift == 0:
        return e & 0xFFFFFFFF
    return (((e << shift) & 0xFFFFFFFF) | ((e & 0xFFFFFFFF) >> (32 - shift))) & 0xFFFFFFFF


def _fnv1a(s: str) -> int:
    t = 0x811c9dc5
    for ch in s:
        code = ord(ch)
        t = (((t ^ code) & 0xFFFFFFFF) * 0x1000193) & 0xFFFFFFFF
    return _l(t)


class _KeyState:
    def __init__(self, s, is_set, acc):
        self.s = s
        self.is_set = is_set
        self.acc = acc


def _init_key_state(seed: str, tmdb_id: int) -> _KeyState:
    s = [0] * 61
    is_set = [False] * 61
    r = _l(_fnv1a(seed) ^ _l((tmdb_id & 0xFFFFFFFF) ^ 0x9e3779b9))
    for e in range(8):
        t = r % 61
        r = _u((r + 0x9e3779b9) & 0xFFFFFFFF, 7 + (7 & e))
        s[t] = (r ^ _l(r)) & 0xFFFFFFFF
        is_set[t] = True
        r = _l((r + t) & 0xFFFFFFFF)
    acc = _l(0xa5a5a5a5 ^ r)
    return _KeyState(s, is_set, acc)


def _next_keystream_word(state: _KeyState, t: int) -> int:
    r = state.s
    n_state = state.acc
    i = n_state % 61
    o_val = -1 if state.is_set[i] else 0
    d = r[i] if state.is_set[i] else 0
    c = ((t + 1) * 0x9e3779b9) & 0xFFFFFFFF
    a = n_state
    s_val = d ^ c
    h = ((a ^ s_val) | (a & s_val & o_val)) & 0xFFFFFFFF
    term1 = _u((h + n_state) & 0xFFFFFFFF, 31 & i)
    term2 = _u(n_state, 31 & (i * 7))
    n_state = _l(((term1 ^ term2) + 0x9e3779b9) & 0xFFFFFFFF)
    r[i] = n_state
    state.is_set[i] = True
    state.acc = n_state
    return n_state & 0xFFFFFFFF


def _generate_keystream(seed: str, tmdb_id: int, length: int) -> bytearray:
    state = _init_key_state(seed, tmdb_id)
    out = bytearray(length)
    word_idx = 0
    byte_idx = 0
    while byte_idx < length:
        word = _next_keystream_word(state, word_idx)
        word_idx += 1
        out[byte_idx] = word & 0xFF
        byte_idx += 1
        if byte_idx < length:
            out[byte_idx] = (word >> 8) & 0xFF
            byte_idx += 1
        if byte_idx < length:
            out[byte_idx] = (word >> 16) & 0xFF
            byte_idx += 1
        if byte_idx < length:
            out[byte_idx] = (word >> 24) & 0xFF
            byte_idx += 1
    return out


def _decrypt_movy(cipher_b64: str, seed: str, tmdb_id: int) -> Optional[str]:
    try:
        normalized = cipher_b64.replace('-', '+').replace('_', '/')
        while len(normalized) % 4 != 0:
            normalized += '='
        cipher_bytes = bytearray(base64.b64decode(normalized))
        if len(cipher_bytes) <= len(MAGIC):
            return None
        ks = _generate_keystream(seed, tmdb_id, len(cipher_bytes))
        for i in range(len(cipher_bytes)):
            cipher_bytes[i] ^= ks[i]
        if list(cipher_bytes[:len(MAGIC)]) != MAGIC:
            return None
        return cipher_bytes[len(MAGIC):].decode('utf-8')
    except Exception:
        return None


def _get_seed(tmdb_id: int) -> Optional[str]:
    """Acquire dynamic ephemeral seed for media ID."""
    try:
        req = urllib.request.Request(
            f'{API_BASE}/seed?mediaId={tmdb_id}',
            headers={'User-Agent': UA, 'Referer': REFERER, 'Origin': ORIGIN}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('seed')
    except Exception as e:
        logger.debug(f"Failed to fetch Movy seed for TMDB {tmdb_id}: {e}")
        return None


class MovyProvider(BaseProvider):
    """Movy streaming provider featuring 14 global city servers and multi-language HLS."""

    name = 'Movy'
    base_url = 'https://www.movy.bz'

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        seed = _get_seed(tmdb_id)
        if not seed:
            return None

        is_tv = (season is not None and episode is not None)
        media_type = 'tv' if is_tv else 'movie'

        params = {
            'mediaType': media_type,
            'tmdbId': str(tmdb_id),
            'enc': '2',
            'seed': seed,
        }
        if is_tv:
            params['seasonId'] = str(season)
            params['episodeId'] = str(episode)

        base_query = urllib.parse.urlencode(params)

        for srv in SERVERS:
            endpoint = srv['endpoint']
            srv_name = srv['name']
            extra = srv.get('extra', '')
            full_url = f'{API_BASE}/{endpoint}/sources?{base_query}'
            if extra:
                full_url += f'&{extra}'

            try:
                req = urllib.request.Request(
                    full_url,
                    headers={'User-Agent': UA, 'Referer': REFERER, 'Origin': ORIGIN}
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    enc_text = resp.read().decode('utf-8').strip()
                    if not enc_text or enc_text.startswith('<'):
                        continue

                    dec = _decrypt_movy(enc_text, seed, tmdb_id)
                    if not dec:
                        continue

                    parsed = json.loads(dec)
                    sources = parsed.get('sources', [])
                    for src in sources:
                        if not isinstance(src, dict):
                            continue
                        stream_url = src.get('url')
                        if not stream_url:
                            continue

                        quality = src.get('quality', '1080p')
                        logger.info(f"Resolved Movy stream from {srv_name} ({quality})")
                        return StreamResult(
                            url=stream_url,
                            referer=REFERER,
                            origin=ORIGIN,
                            quality=quality,
                            format='hls',
                            headers={'User-Agent': UA, 'Referer': REFERER},
                            provider_name=self.name,
                        )
            except Exception as e:
                logger.debug(f"Movy server {endpoint} failed: {e}")
                continue

        return None

    def fetch_stream_choices(self, tmdb_id: int, season: int = None, episode: int = None) -> List[Dict[str, Any]]:
        seed = _get_seed(tmdb_id)
        if not seed:
            return []

        is_tv = (season is not None and episode is not None)
        media_type = 'tv' if is_tv else 'movie'

        params = {
            'mediaType': media_type,
            'tmdbId': str(tmdb_id),
            'enc': '2',
            'seed': seed,
        }
        if is_tv:
            params['seasonId'] = str(season)
            params['episodeId'] = str(episode)

        base_query = urllib.parse.urlencode(params)
        choices = []

        for srv in SERVERS:
            endpoint = srv['endpoint']
            srv_name = srv['name']
            note = srv.get('note', '')
            extra = srv.get('extra', '')
            full_url = f'{API_BASE}/{endpoint}/sources?{base_query}'
            if extra:
                full_url += f'&{extra}'

            try:
                req = urllib.request.Request(
                    full_url,
                    headers={'User-Agent': UA, 'Referer': REFERER, 'Origin': ORIGIN}
                )
                with urllib.request.urlopen(req, timeout=4) as resp:
                    enc_text = resp.read().decode('utf-8').strip()
                    if not enc_text or enc_text.startswith('<'):
                        continue
                    dec = _decrypt_movy(enc_text, seed, tmdb_id)
                    if not dec:
                        continue
                    parsed = json.loads(dec)
                    for src in parsed.get('sources', []):
                        if isinstance(src, dict) and src.get('url'):
                            q = src.get('quality', '1080p')
                            choices.append({
                                'title': f'[Movy - {srv_name}] {q} ({note})',
                                'url': src['url'],
                                'quality': q,
                                'server': srv_name,
                                'provider': self.name,
                                'headers': {'User-Agent': UA, 'Referer': REFERER},
                            })
            except Exception:
                continue

        return choices
