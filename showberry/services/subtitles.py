"""Subtitle service for discovering and downloading subtitles."""

import json
import logging
import os
import re
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from gi.repository import GLib

logger = logging.getLogger(__name__)

STREMIO_SUBTITLES_URL = "https://opensubtitles-v3.strem.io/subtitles"

_SPLIT_RELEASE_RE = re.compile(
    r'(?:^|[\s._\-\(\[])(cd\s*[1234]|disc\s*[1234]|disk\s*[1234]|part\s*[1234]|[123]cd)(?:$|[\s._\-\)\]])',
    re.IGNORECASE
)

_TIMESTAMP_CUE_RE = re.compile(
    r'(?:(\d{1,2}):)?(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(?:(\d{1,2}):)?(\d{2}):(\d{2})[,.](\d{3})'
)

_MICRODVD_CUE_RE = re.compile(r'^\{(\d+)\}\{(\d+)\}(.+)$')

# Common language code mappings
LANG_NAMES = {
    'eng': 'English',
    'en': 'English',
    'spa': 'Spanish',
    'es': 'Spanish',
    'fre': 'French',
    'fra': 'French',
    'fr': 'French',
    'ger': 'German',
    'deu': 'German',
    'de': 'German',
    'ita': 'Italian',
    'it': 'Italian',
    'por': 'Portuguese',
    'pt': 'Portuguese',
    'pob': 'Portuguese (Brazil)',
    'rus': 'Russian',
    'ru': 'Russian',
    'ara': 'Arabic',
    'ar': 'Arabic',
    'chi': 'Chinese',
    'zho': 'Chinese',
    'zh': 'Chinese',
    'jpn': 'Japanese',
    'ja': 'Japanese',
    'kor': 'Korean',
    'ko': 'Korean',
    'hin': 'Hindi',
    'hi': 'Hindi',
    'pol': 'Polish',
    'pl': 'Polish',
    'tur': 'Turkish',
    'tr': 'Turkish',
    'dut': 'Dutch',
    'nld': 'Dutch',
    'nl': 'Dutch',
    'swe': 'Swedish',
    'sv': 'Swedish',
    'nor': 'Norwegian',
    'no': 'Norwegian',
    'dan': 'Danish',
    'da': 'Danish',
    'fin': 'Finnish',
    'fi': 'Finnish',
    'ell': 'Greek',
    'gre': 'Greek',
    'el': 'Greek',
    'heb': 'Hebrew',
    'he': 'Hebrew',
    'tha': 'Thai',
    'th': 'Thai',
    'vie': 'Vietnamese',
    'vi': 'Vietnamese',
    'ind': 'Indonesian',
    'id': 'Indonesian',
    'ces': 'Czech',
    'cze': 'Czech',
    'cs': 'Czech',
    'hun': 'Hungarian',
    'hu': 'Hungarian',
    'ron': 'Romanian',
    'rum': 'Romanian',
    'ro': 'Romanian',
    'ukr': 'Ukrainian',
    'uk': 'Ukrainian',
}

# Country flag emojis by language code
LANG_FLAGS = {
    'eng': '🇺🇸', 'en': '🇺🇸',
    'spa': '🇪🇸', 'es': '🇪🇸',
    'fre': '🇫🇷', 'fra': '🇫🇷', 'fr': '🇫🇷',
    'ara': '🇸🇦', 'ar': '🇸🇦',
    'ger': '🇩🇪', 'deu': '🇩🇪', 'de': '🇩🇪',
    'ita': '🇮🇹', 'it': '🇮🇹',
    'por': '🇵🇹', 'pt': '🇵🇹',
    'pob': '🇧🇷',
    'rus': '🇷🇺', 'ru': '🇷🇺',
    'chi': '🇨🇳', 'zho': '🇨🇳', 'zh': '🇨🇳',
    'jpn': '🇯🇵', 'ja': '🇯🇵',
    'kor': '🇰🇷', 'ko': '🇰🇷',
    'hin': '🇮🇳', 'hi': '🇮🇳',
    'pol': '🇵🇱', 'pl': '🇵🇱',
    'tur': '🇹🇷', 'tr': '🇹🇷',
    'dut': '🇳🇱', 'nld': '🇳🇱', 'nl': '🇳🇱',
    'swe': '🇸🇪', 'sv': '🇸🇪',
    'nor': '🇳🇴', 'no': '🇳🇴',
    'dan': '🇩🇰', 'da': '🇩🇰',
    'fin': '🇫🇮', 'fi': '🇫🇮',
    'ell': '🇬🇷', 'gre': '🇬🇷', 'el': '🇬🇷',
    'heb': '🇮🇱', 'he': '🇮🇱',
    'tha': '🇹🇭', 'th': '🇹🇭',
    'vie': '🇻🇳', 'vi': '🇻🇳',
    'ind': '🇮🇩', 'id': '🇮🇩',
    'ces': '🇨🇿', 'cze': '🇨🇿', 'cs': '🇨🇿',
    'hun': '🇭🇺', 'hu': '🇭🇺',
    'ron': '🇷🇴', 'rum': '🇷🇴', 'ro': '🇷🇴',
    'ukr': '🇺🇦', 'uk': '🇺🇦',
}


def score_subtitle_release(item: Dict[str, Any]) -> int:
    """
    Score a subtitle item based on release quality, source match, and framerate.
    Prioritizes full-movie WEB-DL, WEBRip, 1080p, BluRay, and standard 23.976 fps.
    Heavily penalizes multi-disc splits (CD1/CD2/Part1), non-SRT (.txt/.sub), and CAM/TS releases.
    """
    name = (item.get('movieReleaseName') or item.get('subtitleFileName') or item.get('release_name') or '').lower()
    fname = (item.get('subtitleFileName') or '').lower()
    fmt = (item.get('releaseFormat') or item.get('format') or '').lower()
    fps = item.get('fpsMilli', 0) or 0
    score = 0

    # Severe penalty for multi-CD / split-disc releases (CD1, CD2, Disc 1, Part 1, etc.)
    if _SPLIT_RELEASE_RE.search(name) or _SPLIT_RELEASE_RE.search(fname):
        score -= 1000

    # Penalize raw .txt / .sub / .smi files and prefer .srt / .vtt
    if fname.endswith(('.txt', '.sub', '.idx', '.smi')):
        score -= 800
    elif fname.endswith(('.srt', '.vtt')):
        score += 50

    if (item.get('SubEncoding') or '').upper() == 'UTF-8':
        score += 20

    # Severe penalty for CAM / Telesync / Workprint / Screener
    if any(k in name for k in ('cam', 'telesync', 'hdcam', 'hd-ts', 'ts.', '.ts', '-ts', 'tc', 'workprint', 'scr', 'screener', 'dvdscr')):
        score -= 500
    if fmt in ('cam', 'telesync', 'screener', 'ts', 'tc'):
        score -= 500

    # High quality web & bluray releases
    if any(k in name for k in ('web-dl', 'webrip', 'web.', 'web-', 'hmax', 'amzn', 'nf', 'netflix', 'atvp', 'dsnp')):
        score += 150
    elif any(k in name for k in ('bluray', 'bdrip', 'brrip', 'blu-ray')):
        score += 130
    elif 'dvd' in name or 'dvdrip' in name:
        score += 60

    if fmt in ('web-dl', 'webrip', 'blu-ray', 'bdrip'):
        score += 80

    # Resolution
    if any(k in name for k in ('1080p', '720p', '2160p', '4k')):
        score += 50

    # Popular trusted scene groups
    if any(k in name for k in ('yts', 'yify', 'evo', 'sparks', 'geckos', 'rarbg', 'deflate', 'flux', 'ntb')):
        score += 30

    # Framerate matching (23.976 / 23.980 / 24.0 fps is industry standard for film & streaming)
    if 23970 <= fps <= 24000:
        score += 40
    elif fps == 25000:
        score -= 10
    elif fps == 30000:
        score -= 20

    return score


def decode_subtitle_bytes(raw: bytes) -> str:
    """Decode raw subtitle bytes reliably across UTF-8, UTF-8-SIG, UTF-16, CP1252, and Latin-1."""
    for enc in ('utf-8-sig', 'utf-8', 'utf-16', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def parse_subtitle_cues(text: str, default_fps: float = 23.976) -> List[Tuple[float, float, str]]:
    """
    Parse SRT, WebVTT (both HH:MM:SS.mmm and MM:SS.mmm), or MicroDVD ({start}{end}text)
    into a sorted list of (start_sec, end_sec, payload_text) tuples.
    """
    text = text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    cues: List[Tuple[float, float, str]] = []

    blocks = re.split(r'\n\s*\n', text.strip())
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines:
            continue
        header_upper = lines[0].upper()
        if header_upper.startswith(('WEBVTT', 'STYLE', 'NOTE', 'REGION')):
            # If the first block has a cue embedded after WEBVTT header, scan remaining lines
            pass
        for idx, line in enumerate(lines):
            m = _TIMESTAMP_CUE_RE.search(line)
            if m:
                h1, m1, s1, ms1, h2, m2, s2, ms2 = m.groups()
                st = int(h1 or 0) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000.0
                et = int(h2 or 0) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000.0
                payload = '\n'.join(lines[idx + 1:]).strip()
                if payload and et > st:
                    cues.append((st, et, payload))
                break

    if not cues:
        # Fallback for MicroDVD {start_frame}{end_frame}Line1|Line2 format
        fps = default_fps if default_fps > 0 else 23.976
        for line in text.split('\n'):
            line = line.strip()
            m = _MICRODVD_CUE_RE.match(line)
            if m:
                f_start, f_end, raw_txt = int(m.group(1)), int(m.group(2)), m.group(3)
                if f_start == 1 and f_end == 1:
                    try:
                        val = float(raw_txt.strip())
                        if 15.0 <= val <= 60.0:
                            fps = val
                            continue
                    except ValueError:
                        pass
                st = f_start / fps
                et = f_end / fps
                payload = raw_txt.replace('|', '\n').strip()
                if payload and et > st:
                    cues.append((st, et, payload))

    cues.sort(key=lambda c: c[0])
    return cues


def format_srt_timestamp(seconds: float) -> str:
    """Format seconds as standard SRT timestamp HH:MM:SS,mmm."""
    seconds = max(0.0, seconds)
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt_cues(cues: List[Tuple[float, float, str]], out_path: str) -> None:
    """Write parsed subtitle cues to a clean, standard UTF-8 SRT file."""
    out_lines: List[str] = []
    idx = 1
    for st, et, payload in cues:
        if et <= 0 or et <= st or not payload.strip():
            continue
        st_clamped = max(0.0, st)
        if et <= st_clamped:
            continue
        out_lines.append(f"{idx}\n{format_srt_timestamp(st_clamped)} --> {format_srt_timestamp(et)}\n{payload}\n")
        idx += 1
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out_lines))


def _is_sdh_or_music(text: str) -> bool:
    """Return True if a subtitle cue is purely a music note or SDH sound effect."""
    clean = re.sub(r'<[^>]+>', '', text).strip()
    if not clean:
        return True
    if '♪' in clean or '♫' in clean:
        return True
    if (clean.startswith('[') and clean.endswith(']')) or (clean.startswith('(') and clean.endswith(')')):
        return True
    return False


class SubtitleService:
    """Service to discover and download subtitles for movies and TV series."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return

        cache_dir = Path(GLib.get_user_cache_dir()) / 'showberry' / 'subtitles'
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir = cache_dir
        self._initialized = True

    def get_subtitles(
        self,
        imdb_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        language_filter: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch available subtitles for a movie or TV episode using OpenSubtitles.

        Args:
            imdb_id: IMDB ID (e.g. 'tt0137523')
            season: Season number (for TV series)
            episode: Episode number (for TV series)
            language_filter: Optional list of language codes to prioritize or filter

        Returns:
            List of subtitle dictionaries with 'id', 'url', 'lang', 'label'
        """
        if not imdb_id or not imdb_id.startswith('tt'):
            return []

        try:
            if season is not None and episode is not None:
                url = f"{STREMIO_SUBTITLES_URL}/series/{imdb_id}:{season}:{episode}.json"
            else:
                url = f"{STREMIO_SUBTITLES_URL}/movie/{imdb_id}.json"

            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )

            data = None
            last_err = None
            for attempt in range(2):
                try:
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        if resp.status != 200:
                            return []
                        data = json.loads(resp.read().decode('utf-8', errors='replace'))
                        break
                except Exception as e:
                    last_err = e
                    if attempt == 0:
                        time.sleep(0.5)
                        continue

            if data is None:
                if last_err:
                    logger.warning(f"Failed to fetch subtitles from OpenSubtitles ({url}): {last_err}")
                return []

            subtitles = []
            for item in data.get('subtitles', []):
                sub_url = item.get('url')
                if not sub_url:
                    continue

                lang_code = item.get('lang', 'eng').lower()
                lang_label = LANG_NAMES.get(lang_code, lang_code.upper())
                flag = LANG_FLAGS.get(lang_code, '🌐')
                file_name = item.get('subtitleFileName') or item.get('movieReleaseName') or ''
                clean_name = file_name.removesuffix('.srt').removesuffix('.vtt')
                if clean_name and len(clean_name) < 45:
                    label = f"{lang_label} ({clean_name})"
                else:
                    label = f"{lang_label}"

                sub_score = score_subtitle_release(item)

                subtitles.append({
                    'id': str(item.get('id', '')),
                    'url': sub_url,
                    'lang': lang_code,
                    'lang_name': lang_label,
                    'flag': flag,
                    'release_name': clean_name or lang_label,
                    'label': label,
                    'format': 'srt',
                    'score': sub_score,
                })

            # Sort so English / preferred languages come first, and within each language group, highest score first
            if language_filter:
                filter_set = set(l.lower() for l in language_filter)
                subtitles.sort(key=lambda s: (0 if s['lang'] in filter_set else 1, -s.get('score', 0)))
            else:
                subtitles.sort(key=lambda s: (0 if s['lang'] in ('eng', 'en') else 1, -s.get('score', 0)))

            return subtitles

        except Exception as e:
            logger.warning(f"Failed to fetch subtitles from OpenSubtitles: {e}")
            return []

    def filter_subtitles(self, subtitles: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """Filter list of subtitles by language or release query."""
        if not query or not query.strip():
            return subtitles
        q = query.strip().lower()
        return [
            s for s in subtitles
            if q in s.get('lang', '').lower()
            or q in s.get('lang_name', '').lower()
            or q in s.get('release_name', '').lower()
            or q in s.get('label', '').lower()
        ]

    def download_subtitle(
        self,
        sub_url: str,
        filename_hint: str = "subtitle.srt",
        headers: Optional[Dict[str, str]] = None,
        referer: Optional[str] = None
    ) -> Optional[str]:
        """
        Download subtitle to local cache, normalize to clean UTF-8 SRT, and return the local path.
        Accepts optional referer and headers to authenticate against protected provider CDNs.
        """
        try:
            url_hash = hex(abs(hash(sub_url)))[2:]
            base_hint = os.path.basename(filename_hint)
            base_stem = Path(base_hint).stem or "subtitle"
            safe_filename = f"{url_hash}_{base_stem}.srt"

            local_path = self._cache_dir / safe_filename
            if local_path.exists() and local_path.stat().st_size > 0:
                try:
                    raw_existing = local_path.read_bytes()
                    if raw_existing.lstrip().startswith(b'WEBVTT'):
                        cues = parse_subtitle_cues(decode_subtitle_bytes(raw_existing))
                        if cues:
                            write_srt_cues(cues, str(local_path))
                except Exception:
                    pass
                return str(local_path)

            req_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            if referer:
                req_headers['Referer'] = referer
                req_headers['Origin'] = referer.rstrip('/')
            if headers:
                for k, v in headers.items():
                    if k.lower() in ('referer', 'origin', 'user-agent', 'accept'):
                        req_headers[k] = v

            req = urllib.request.Request(sub_url, headers=req_headers)

            with urllib.request.urlopen(req, timeout=6) as resp:
                content = resp.read()

            decoded = decode_subtitle_bytes(content)
            cues = parse_subtitle_cues(decoded)
            if cues:
                write_srt_cues(cues, str(local_path))
            else:
                with open(local_path, 'w', encoding='utf-8') as f:
                    f.write(decoded)

            return str(local_path)
        except Exception as e:
            logger.warning(f"Error downloading subtitle {sub_url}: {e}")
            return None

    @staticmethod
    def is_autosync_available() -> bool:
        """Pure-Python subtitle-to-subtitle synchronizer is always available."""
        return True

    def is_partial_subtitle(self, ref_path: str, target_path: str) -> bool:
        """
        Return True if target_path appears to be an incomplete / single-CD split (e.g. CD1)
        covering less than 65% of the reference subtitle's time span.
        """
        try:
            if not os.path.exists(ref_path) or not os.path.exists(target_path):
                return False
            ref_cues = parse_subtitle_cues(decode_subtitle_bytes(Path(ref_path).read_bytes()))
            target_cues = parse_subtitle_cues(decode_subtitle_bytes(Path(target_path).read_bytes()))
            if not ref_cues or not target_cues:
                return True
            ref_end = ref_cues[-1][1]
            target_end = target_cues[-1][1]
            # Only apply partial check on full-length episodes/movies (> 25 mins)
            if ref_end > 1500.0 and target_end < (ref_end * 0.65):
                logger.warning(
                    f"Detected partial/split subtitle ({target_path}): ends at {target_end:.0f}s vs reference {ref_end:.0f}s"
                )
                return True
            return False
        except Exception:
            return False

    def sync_subtitle_with_audio(self, video_path: str, sub_path: str) -> Optional[str]:
        """Synchronize subtitle file with video audio speech using ffsubsync if installed."""
        import shutil
        import subprocess

        ffsubsync_bin = shutil.which('ffsubsync')
        if not ffsubsync_bin:
            user_bin = Path.home() / '.local' / 'bin' / 'ffsubsync'
            if user_bin.exists() and os.access(user_bin, os.X_OK):
                ffsubsync_bin = str(user_bin)

        if not ffsubsync_bin:
            logger.warning("ffsubsync executable not found.")
            return None

        if not os.path.exists(sub_path):
            logger.warning(f"Input subtitle file does not exist: {sub_path}")
            return None

        out_path = Path(sub_path).with_name(f"{Path(sub_path).stem}_synced.srt")

        cmd = [
            ffsubsync_bin,
            video_path,
            '-i', sub_path,
            '-o', str(out_path),
            '--max-duration-seconds', '600',
            '--extract-audio-first',
        ]
        logger.info(f"Running ffsubsync: {' '.join(cmd)}")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if res.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
                logger.info(f"Successfully synchronized subtitle to {out_path}")
                return str(out_path)
            else:
                logger.warning(f"ffsubsync failed (code {res.returncode}): {res.stderr}")
                return None
        except Exception as e:
            logger.warning(f"Error executing ffsubsync: {e}")
            return None

    def sync_subtitle_with_reference(self, ref_path: str, target_path: str) -> Optional[str]:
        """
        Synchronize a target subtitle file with a reference subtitle file in pure Python.
        Aligns speech cue intervals across both constant intro/recap offsets (-180s to +180s)
        and PAL/NTSC framerate ratios (1.0, 25/23.976, 23.976/25, 24/23.976, 23.976/24)
        in ~150ms without external binary dependencies.
        """
        if not os.path.exists(ref_path) or not os.path.exists(target_path):
            logger.warning(f"Reference or target subtitle file missing: {ref_path}, {target_path}")
            return None

        try:
            t0 = time.time()
            ref_text = decode_subtitle_bytes(Path(ref_path).read_bytes())
            target_text = decode_subtitle_bytes(Path(target_path).read_bytes())

            ref_cues = parse_subtitle_cues(ref_text)
            target_cues = parse_subtitle_cues(target_text)

            if not ref_cues or not target_cues:
                logger.warning(f"Could not parse cues for sync (ref={len(ref_cues)}, target={len(target_cues)})")
                return None

            r_speech = [(s, e) for s, e, txt in ref_cues if not _is_sdh_or_music(txt)]
            t_speech = [(s, e) for s, e, txt in target_cues if not _is_sdh_or_music(txt)]
            if len(r_speech) < 15:
                r_speech = [(s, e) for s, e, _ in ref_cues]
            if len(t_speech) < 15:
                t_speech = [(s, e) for s, e, _ in target_cues]

            candidate_ratios = [
                1.0,
                25.0 / 23.976,
                23.976 / 25.0,
                24.0 / 23.976,
                23.976 / 24.0,
                25.0 / 24.0,
                24.0 / 25.0,
            ]

            max_time = max(r_speech[-1][1], t_speech[-1][1]) * 1.1 + 600.0
            fine_res = 20  # 50ms precision grid
            fine_size = int(max_time * fine_res) + 1000
            fine_grid = bytearray(fine_size)
            onset_grid = bytearray(fine_size)
            for s, e in r_speech:
                i_s = max(0, int((s - 0.05) * fine_res))
                i_e = min(fine_size - 1, int((e + 0.05) * fine_res))
                if i_e >= i_s:
                    fine_grid[i_s:i_e + 1] = b'\x01' * (i_e - i_s + 1)
                c_idx = int(round(s * fine_res))
                for d_i, w_val in ((-2, 1), (-1, 2), (0, 3), (1, 2), (2, 1)):
                    pos_i = c_idx + d_i
                    if 0 <= pos_i < fine_size and w_val > onset_grid[pos_i]:
                        onset_grid[pos_i] = w_val

            t_starts = [s for s, _ in t_speech]
            t_mids = [(s + e) * 0.5 for s, e in t_speech]
            t_pairs = list(zip(t_starts, t_mids))
            sample_step = max(1, len(t_speech) // 350)
            t_sample = t_speech[::sample_step]
            r_starts = [s for s, _ in r_speech]
            n_r = len(r_starts)

            best_offset = 0.0
            best_ratio = 1.0
            best_score = -1.0

            for ratio in candidate_ratios:
                # Hough-transform pairwise offset voting (-180s to +180s in 0.2s bins)
                votes = [0] * 1805
                r_idx = 0
                for ts, _ in t_sample:
                    ts_scaled = ts * ratio
                    low = ts_scaled - 180.0
                    high = ts_scaled + 180.0
                    while r_idx < n_r and r_starts[r_idx] < low:
                        r_idx += 1
                    k = r_idx
                    while k < n_r:
                        rs = r_starts[k]
                        if rs > high:
                            break
                        b = int(round((rs - ts_scaled) * 5.0)) + 900
                        if 1 <= b < 1804:
                            votes[b] += 2
                            votes[b - 1] += 1
                            votes[b + 1] += 1
                        k += 1

                max_v = max(votes)
                if max_v == 0:
                    continue

                # Evaluate top 2 peak bins on the 50ms fine grid
                peak_bins = [votes.index(max_v) - 900]
                second_v = 0
                second_b = None
                first_idx = peak_bins[0] + 900
                for bi, val in enumerate(votes):
                    if abs(bi - first_idx) > 10 and val > second_v:
                        second_v = val
                        second_b = bi - 900
                if second_b is not None and second_v >= max_v * 0.7:
                    peak_bins.append(second_b)

                for cand_bin in peak_bins:
                    center_off = cand_bin / 5.0
                    r_scaled = ratio * fine_res
                    for step in range(-20, 21):
                        off = center_off + step * 0.05
                        off_scaled = off * fine_res
                        hits = 0
                        for ts, tm in t_pairs:
                            idx_m = int(tm * r_scaled + off_scaled)
                            if 0 <= idx_m < fine_size and fine_grid[idx_m]:
                                hits += 1
                                idx_s = int(round(ts * r_scaled + off_scaled))
                                if 0 <= idx_s < fine_size:
                                    hits += onset_grid[idx_s]
                        # Slight preference for 1.0 ratio and near-zero offset when tied
                        score = float(hits) + (2.0 if ratio == 1.0 else 0.0) - (0.01 if abs(off) > 0.1 else 0.0)
                        if score > best_score:
                            best_score = score
                            best_offset = off
                            best_ratio = ratio

            match_ratio = min(1.0, (best_score / 3.0) / max(1, len(t_mids)))
            elapsed_ms = (time.time() - t0) * 1000.0
            logger.info(
                f"Pure-Python subtitle sync completed in {elapsed_ms:.0f}ms: "
                f"offset={best_offset:+.2f}s, ratio={best_ratio:.5f}, match={match_ratio * 100:.1f}%"
            )

            out_path = Path(target_path).with_name(f"{Path(target_path).stem}_synced.srt")
            synced_cues = [
                (st * best_ratio + best_offset, et * best_ratio + best_offset, payload)
                for st, et, payload in target_cues
                if (et * best_ratio + best_offset) > 0.0
            ]
            write_srt_cues(synced_cues, str(out_path))
            return str(out_path)
        except Exception as e:
            logger.warning(f"Error in pure-Python subtitle sync: {e}")
            return None
