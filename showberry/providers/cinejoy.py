"""Cinejoy streaming provider with pure Python ECDH on P-256 and AES-256-GCM."""

import os
import json
import logging
import urllib.request
from typing import Optional, Dict, Any, List

try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

from showberry.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)

API_BASE = 'https://api.shegu.st'
ORIGIN = 'https://cinejoy.to'
REFERER = 'https://cinejoy.to/watch'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

SERVER_PUB_HEX = (
    '0483c7a82132b8516e3eb4061b82e9c881cc585593a4709001131bff7443eabc'
    '1701c1f0d50e23ac02b0b9a5979903dbd7e9055aab5e4a5532132d1d200707f5f2'
)

SERVERS = [
    {'name': 'Lisbon', '4k': True},
    {'name': 'Solara', '4k': False},
    {'name': 'Athens', '4k': False},
    {'name': 'Castle', '4k': False},
    {'name': 'Canaias', '4k': False},
]


def _execute_query(path: str, payload: Dict[str, Any], timeout: float = 6.0) -> Optional[Dict[str, Any]]:
    """Encrypt request using ECDH + AES-GCM and decrypt server response."""
    if not HAS_CRYPTOGRAPHY:
        logger.debug("cryptography package is not available; Cinejoy request skipped.")
        return None
    try:
        server_pub = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), bytes.fromhex(SERVER_PUB_HEX)
        )
        client_priv = ec.generate_private_key(ec.SECP256R1())
        client_pub_bytes = client_priv.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )
        shared_secret = client_priv.exchange(ec.ECDH(), server_pub)

        def derive_key(info: bytes) -> bytes:
            hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=client_pub_bytes, info=info)
            return hkdf.derive(shared_secret)

        req_key = derive_key(b'lumen-gate-v2|c2s')
        res_key = derive_key(b'lumen-gate-v2|s2c')

        req_json = json.dumps({'path': path, 'payload': payload}).encode('utf-8')
        iv = os.urandom(12)
        prefix = b'lumen-gate-v2'
        req_aad = prefix + bytes([0, 1, 1]) + client_pub_bytes
        res_aad = prefix + bytes([0, 2, 1]) + client_pub_bytes

        aesgcm = AESGCM(req_key)
        ciphertext = aesgcm.encrypt(iv, req_json, req_aad)
        body = bytes([2, 1]) + client_pub_bytes + iv + ciphertext

        req = urllib.request.Request(
            f'{API_BASE}/g',
            data=body,
            headers={
                'User-Agent': UA,
                'Origin': ORIGIN,
                'Referer': REFERER,
                'Content-Type': 'application/octet-stream',
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_bytes = resp.read()
            if len(resp_bytes) <= 28:
                return None
            res_iv = resp_bytes[:12]
            res_cipher = resp_bytes[12:]
            res_aes = AESGCM(res_key)
            plain = res_aes.decrypt(res_iv, res_cipher, res_aad)
            return json.loads(plain.decode('utf-8'))
    except Exception as e:
        logger.debug(f"Cinejoy query failed for {path}: {e}")
        return None


class CinejoyProvider(BaseProvider):
    """Cinejoy streaming provider featuring 4K & multi-server HLS streams."""

    name = 'Cinejoy'
    base_url = 'https://cinejoy.to'

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        if not HAS_CRYPTOGRAPHY:
            return None
        for srv in SERVERS:
            srv_name = srv['name']
            is_4k = srv.get('4k', False)
            is_tv = (season is not None and episode is not None)

            if is_tv:
                target_path = f'/{srv_name}/series'
                payload = {'tmdb': str(tmdb_id), 'season': str(season), 'episode': str(episode)}
            else:
                target_path = f'/{srv_name}/movie'
                payload = {'tmdb': str(tmdb_id)}

            data = _execute_query(target_path, payload)
            if not data or data.get('status') != 200:
                continue

            stream_data = data.get('data', {}).get('stream', [])
            if not isinstance(stream_data, list) or not stream_data:
                continue

            for st in stream_data:
                if not isinstance(st, dict):
                    continue
                if st.get('type') == 'hls' and st.get('playlist'):
                    playlist = st['playlist'].strip()
                    quality = '4K / 1080p' if is_4k else '1080p'
                    logger.info(f"Resolved Cinejoy stream from {srv_name} ({quality})")
                    return StreamResult(
                        url=playlist,
                        referer='https://cinejoy.to/',
                        origin='https://cinejoy.to',
                        quality=quality,
                        format='hls',
                        headers={'User-Agent': UA, 'Referer': 'https://cinejoy.to/'},
                        provider_name=self.name,
                    )
        return None

    def fetch_stream_choices(self, tmdb_id: int, season: int = None, episode: int = None) -> List[Dict[str, Any]]:
        """Fetch stream choices across all available Cinejoy servers."""
        if not HAS_CRYPTOGRAPHY:
            return []
        choices = []
        is_tv = (season is not None and episode is not None)

        for srv in SERVERS:
            srv_name = srv['name']
            is_4k = srv.get('4k', False)
            if is_tv:
                target_path = f'/{srv_name}/series'
                payload = {'tmdb': str(tmdb_id), 'season': str(season), 'episode': str(episode)}
            else:
                target_path = f'/{srv_name}/movie'
                payload = {'tmdb': str(tmdb_id)}

            data = _execute_query(target_path, payload, timeout=4.0)
            if not data or data.get('status') != 200:
                continue

            stream_data = data.get('data', {}).get('stream', [])
            if not isinstance(stream_data, list):
                continue

            for st in stream_data:
                if isinstance(st, dict) and st.get('type') == 'hls' and st.get('playlist'):
                    quality = '4K / 1080p' if is_4k else '1080p'
                    choices.append({
                        'title': f'[Cinejoy - {srv_name}] {quality}',
                        'url': st['playlist'].strip(),
                        'quality': quality,
                        'server': srv_name,
                        'provider': self.name,
                        'headers': {'User-Agent': UA, 'Referer': 'https://cinejoy.to/'},
                    })
        return choices
