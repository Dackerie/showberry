"""VidFast streaming provider."""

import json
import logging
import re
from typing import Optional

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    import requests as curl_requests
import requests

from kinema.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)


class VidFastProvider(BaseProvider):
    """VidFast.pro streaming provider."""

    name = 'VidFast'
    base_url = 'https://vidfast.pro'
    alt_url = 'https://vidfast.vc'

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Get stream URL from VidFast."""
        for base in [self.base_url, self.alt_url]:
            try:
                if season is not None and episode is not None:
                    path = f'/tv/{tmdb_id}/{season}/{episode}'
                else:
                    path = f'/movie/{tmdb_id}'

                url = f'{base}{path}'

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
                    'Referer': f'{base}/',
                    'Origin': base,
                    'X-Requested-With': 'XMLHttpRequest',
                }

                if hasattr(curl_requests, 'get') and 'impersonate' in curl_requests.get.__code__.co_varnames:
                    resp = curl_requests.get(url, headers=headers, impersonate='chrome124', timeout=12)
                else:
                    resp = curl_requests.get(url, headers=headers, timeout=12)

                if resp.status_code != 200:
                    continue

                html = resp.text
                match = re.search(r'\\"(?:en|token)\\":\\"(.*?)\\"', html)
                if not match:
                    continue

                token_text = match.group(1)

                # Query decrypter endpoint
                enc_resp = requests.get(f"https://enc-dec.app/api/enc-vidfast?text={token_text}", timeout=8)
                if enc_resp.status_code != 200:
                    continue
                enc_data = enc_resp.json()
                if enc_data.get('status') != 200:
                    continue

                res = enc_data['result']
                servers_url = res.get('servers')
                stream_base = res.get('stream')
                csrf_token = res.get('token')

                req_headers = {**headers, 'X-CSRF-Token': csrf_token}

                # Fetch servers list
                srv_resp = requests.post(servers_url, headers=req_headers, timeout=8)
                if srv_resp.status_code != 200:
                    continue

                dec_srv = requests.post('https://enc-dec.app/api/dec-vidfast', json={'text': srv_resp.text}, timeout=8)
                if dec_srv.status_code != 200:
                    continue
                dec_srv_data = dec_srv.json()
                if dec_srv_data.get('status') != 200:
                    continue

                server_entries = dec_srv_data.get('result', [])
                for srv in server_entries:
                    data_token = srv.get('data')
                    if not data_token:
                        continue

                    stream_req_url = f"{stream_base}/{data_token}"
                    stream_post = requests.post(stream_req_url, headers=req_headers, timeout=8)
                    if stream_post.status_code != 200:
                        continue

                    dec_stream = requests.post(
                        'https://enc-dec.app/api/dec-vidfast',
                        json={'text': stream_post.text},
                        timeout=8
                    )
                    if dec_stream.status_code != 200:
                        continue
                    dec_stream_data = dec_stream.json()
                    if dec_stream_data.get('status') == 200 and dec_stream_data.get('result'):
                        stream_obj = dec_stream_data['result']
                        stream_url = stream_obj.get('url')
                        if stream_url:
                            fmt = 'dash' if '.mpd' in stream_url else 'hls'
                            return StreamResult(
                                url=stream_url,
                                referer=f'{base}/',
                                origin=base,
                                quality='1080p',
                                format=fmt,
                                provider_name=self.name,
                            )
            except Exception as e:
                logger.error(f"VidFast resolution error on {base}: {e}")
                continue

        return None

