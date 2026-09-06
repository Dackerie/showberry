"""CineSrc streaming provider with PoW challenge solving."""

import base64
import hashlib
import json
import logging
from typing import Optional

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    import requests as curl_requests
import requests

from kinema.providers.base import BaseProvider, StreamResult

logger = logging.getLogger(__name__)


def u32(x):
    return x & 0xffffffff


def rotl(x, n):
    n &= 31
    if n == 0:
        return u32(x)
    return u32((x << n) | (x >> (32 - n)))


def imul(a, b):
    return ((a & 0xffffffff) * (b & 0xffffffff)) & 0xffffffff


def read_le32(b, p):
    return u32(
        b[p]
        | (b[p + 1] << 8)
        | (b[p + 2] << 16)
        | (b[p + 3] << 24)
    )


def write_le32(b, p, x):
    x = u32(x)
    b[p] = x & 0xff
    b[p + 1] = (x >> 8) & 0xff
    b[p + 2] = (x >> 16) & 0xff
    b[p + 3] = (x >> 24) & 0xff


def b64(s):
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return bytearray(base64.b64decode(s))


def build(w, m):
    s = [0] * 4096
    x = u32(w[m & 3] ^ u32(imul(m, 0x9e3779b1) - 0x61c8864f) ^ 0xa5a5a5a5)
    y = 0x85ebca6b

    for i in range(4096):
        x = u32(x + y + w[i & 3])
        x = u32(x ^ (x << 13))
        x = u32(x ^ (x >> 17))
        x = u32(x ^ (x << 5))
        s[i] = u32(x + imul(i ^ m, 0xc2b2ae35) + rotl(w[(i + m) & 3], i + m))
        y = u32(y - 0x7a143595)

    return s


def mix(w, s, m, n):
    lo = n & 0xffffffff
    hi = (n >> 32) & 0xffffffff
    a = u32(w[0] ^ imul(m + 1, 0x27d4eb2d) ^ lo)
    b = u32(w[2] ^ rotl(lo, m + 5))
    c = u32(hi ^ (w[1] ^ 0x165667b1))
    d = u32(w[3] ^ rotl(u32(lo ^ hi), m + 11))
    y = 2667

    for r in range(1, 9):
        v = s[(imul(c, 2481) ^ rotl(b, r) ^ y ^ a) & 4095]
        op = ((r + m - 1) & 7) - 1

        if op == -1:
            a = rotl(u32(a + d + v), 5)
            c = u32(imul(a ^ c, 0x9e3779b1) + b)
        elif op == 0:
            b = rotl(u32(b ^ c ^ v), 11)
            d = u32(imul(b ^ a, 0x85ebca6b) + d)
        elif op == 1:
            c = rotl(u32(b + c + v), 17)
            a = u32(imul(c ^ d, 0xc2b2ae35) ^ a)
        elif op == 2:
            d = rotl(u32(a ^ d ^ v), 23)
            b = u32(imul(d ^ c, 0x27d4eb2d) + b)
        elif op == 3:
            a = u32(imul(a ^ v, 0x165667b1) + rotl(b, 7))
            d = u32(rotl(u32(a + c), 13) ^ d)
        elif op == 4:
            c = u32(imul(u32(v + c), 0xd3a2646c) ^ rotl(d, 9))
            b = u32(rotl(c ^ a, 19) + b)
        elif op == 5:
            b = u32(imul(b ^ v, 0xfd7046c5) + rotl(a, 3))
            c = u32(rotl(u32(b + d), 15) ^ c)
        else:
            d = u32(imul(u32(d + v), 0xb55a4f09) ^ rotl(c, 21))
            a = u32(rotl(d ^ b, 27) + a)
        y += 2667

    return lo, hi, a, c, b, d


def diff(h, d):
    q = d >> 3
    r = d & 7
    for i in range(q):
        if h[i]:
            return False
    return r == 0 or (h[q] >> (8 - r)) == 0


def solve_stage1(data):
    b = b64(data["w"])
    d = b[5]
    m = b[6]
    w = [
        read_le32(b, 8),
        read_le32(b, 12),
        read_le32(b, 16),
        read_le32(b, 20),
    ]
    s = build(w, m)
    msg = bytearray(42)
    msg[0:16] = b[8:24]
    msg[40] = 2
    msg[41] = m
    n = 0
    while True:
        lo, hi, a, c, b2, d2 = mix(w, s, m, n)
        write_le32(msg, 16, lo)
        write_le32(msg, 20, hi)
        write_le32(msg, 24, a)
        write_le32(msg, 28, c)
        write_le32(msg, 32, b2)
        write_le32(msg, 36, d2)
        h = hashlib.sha256(msg).digest()
        if diff(h, d):
            return f"m2.{n:x}"
        n += 1


def solve_stage2(data):
    target = data["pack"][0][::-1]
    salt = data["pack"][3][::-1]
    r = data["pack"][4][::-1]

    decode = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()

    body = decode(r.split(".")[1])
    payload = decode(body.split(".", 1)[1])
    difficulty = json.loads(payload)["d"]
    width = (difficulty + 3) // 4

    for counter in range(1 << difficulty):
        key = format(counter, "x").zfill(width)
        digest = hashlib.sha256((salt + key).encode()).hexdigest()
        if digest == target:
            return key
    raise RuntimeError("Stage 2 solution not found")


class CineSrcProvider(BaseProvider):
    """CineSrc.st streaming provider."""

    name = 'CineSrc'
    base_url = 'https://cinesrc.st'

    def get_stream_url(self, tmdb_id: int, season: int = None, episode: int = None) -> Optional[StreamResult]:
        """Get stream URL from CineSrc."""
        try:
            is_tv = season is not None and episode is not None
            media_type = 'tv' if is_tv else 'movie'
            embed_url = (
                f"{self.base_url}/embed/tv/{tmdb_id}?s={season}&e={episode}"
                if is_tv
                else f"{self.base_url}/embed/movie/{tmdb_id}"
            )

            headers = {
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/",
                "Content-Type": "text/plain;charset=UTF-8",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            }

            # Generate and fetch bootstrap cookie
            fields = [media_type, str(tmdb_id), season, episode]
            encoded_q = base64.urlsafe_b64encode(
                json.dumps(fields, separators=(",", ":")).encode()
            ).decode().rstrip("=")

            boot_resp = requests.post(
                f"{self.base_url}/api/c/bootstrap",
                headers={**headers, "x-cs-q": encoded_q},
                timeout=4,
            )
            if boot_resp.status_code != 200:
                return None

            boot_data = boot_resp.json()
            cookies = {
                "x-cs-q": encoded_q,
                "x-cs-r": boot_data["r"],
                "x-cs-p": boot_data["p"],
            }

            # Solve challenges
            req_headers = {**headers, **cookies}
            c1_resp = requests.get(f"{self.base_url}/api/c/issue", headers=req_headers, timeout=4)
            if c1_resp.status_code != 200:
                return None
            c1 = c1_resp.json()
            sol1 = solve_stage1(c1)

            c2_resp = requests.get(f"{self.base_url}/api/c/stage2/issue", headers=req_headers, timeout=4)
            if c2_resp.status_code != 200:
                return None
            c2 = c2_resp.json()
            sol2 = solve_stage2(c2)

            challenge_data = {
                "stage1": {"challenge": c1, "solution": sol1},
                "stage2": {"challenge": c2, "solution": sol2},
            }

            # Request decryption tokens
            enc_resp = requests.post(
                "https://enc-dec.app/api/enc-cinesrc",
                json={
                    "url": embed_url,
                    "agent": headers["User-Agent"],
                    "challenge_data": challenge_data,
                },
                timeout=5,
            )
            if enc_resp.status_code != 200:
                return None
            enc_data = enc_resp.json()
            if enc_data.get("status") != 200:
                return None

            result_data = enc_data["result"]
            token = f"{result_data['token']}::c3::{cookies['x-cs-r']}"
            key = result_data["key"]

            act_headers = result_data["headers"]
            get_providers_action = act_headers.get("getProviderList")
            get_stream_action = act_headers.get("getStream")

            if not get_providers_action or not get_stream_action:
                return None

            # Get provider list
            prov_resp = requests.post(
                embed_url,
                headers={**headers, "Next-Action": get_providers_action},
                data="[]",
                timeout=4,
            )
            if prov_resp.status_code != 200:
                return None

            lines = prov_resp.text.splitlines()
            if len(lines) < 2 or ":" not in lines[1]:
                return None
            prov_json_str = lines[1].split(":", 1)[1]
            try:
                server_list = json.loads(prov_json_str)
            except Exception:
                return None
            if not server_list:
                return None

            # Try servers
            for srv in server_list:
                srv_id = srv.get("id")
                payload = [
                    str(tmdb_id),
                    "show" if is_tv else "movie",
                    season if is_tv else "$undefined",
                    episode if is_tv else "$undefined",
                    token,
                    srv_id,
                ]
                stream_resp = requests.post(
                    embed_url,
                    headers={**headers, "Next-Action": get_stream_action},
                    data=json.dumps(payload),
                    timeout=4,
                )
                if stream_resp.status_code != 200:
                    continue

                st_lines = stream_resp.text.splitlines()
                if len(st_lines) < 2 or "," not in st_lines[1]:
                    continue
                parts = st_lines[1].split(",", 1)[1]
                encrypted_chunk = parts.split(":", 1)[0] if ":" in parts else parts

                dec_resp = requests.post(
                    "https://enc-dec.app/api/dec-cinesrc",
                    json={"text": encrypted_chunk, "key": key},
                    timeout=4,
                )
                if dec_resp.status_code != 200:
                    continue
                dec_data = dec_resp.json()
                if dec_data.get("status") == 200 and dec_data.get("result"):
                    res = dec_data["result"]
                    url = res.get("url") or (res.get("stream") and res["stream"].get("url"))
                    if url:
                        return StreamResult(
                            url=url,
                            referer=f"{self.base_url}/",
                            quality="1080p",
                            format="hls" if ".m3u8" in url else "mp4",
                            provider_name=self.name,
                        )

            return None
        except Exception as e:
            logger.error(f"CineSrc resolution error: {e}")
            return None
