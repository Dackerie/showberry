"""Cross-platform auto-updater service for Showberry.

Provides GitHub release checking, checksum verification, background streaming
download with progress reporting, and platform-specific in-place upgrade execution.
"""

from __future__ import annotations

import os
import sys
import re
import json
import time
import shutil
import hashlib
import logging
import tempfile
import threading
import subprocess
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable, Tuple
from pathlib import Path

from gi.repository import GLib

from showberry import __version__
from showberry.services.settings import SettingsService

logger = logging.getLogger(__name__)

GITHUB_REPO = "Dackerie/showberry"
GITHUB_LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
UPDATE_CHECK_INTERVAL_SECONDS = 86400  # 24 hours


def parse_version(version_str: str) -> tuple:
    """Parse version string like 'v0.4.0' or '0.3.3.2' into a comparable tuple of integers."""
    if not version_str:
        return (0, 0, 0)
    clean = re.sub(r'^[vV]', '', str(version_str).strip())
    parts = []
    # Split by '.' or '-'
    tokens = re.split(r'[.\-_]', clean)
    for token in tokens:
        match = re.match(r'(\d+)', token)
        if match:
            parts.append(int(match.group(1)))
        elif token:
            # Alpha/beta/rc tags - negative rank
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer_version(latest_tag: str, current_version: str) -> bool:
    """Return True if latest_tag represents a strictly newer version than current_version."""
    return parse_version(latest_tag) > parse_version(current_version)


class InstallationType(Enum):
    """Detected distribution and packaging format of the currently running application."""
    WINDOWS_INSTALLED = auto()
    WINDOWS_PORTABLE = auto()
    MACOS_BUNDLE = auto()
    LINUX_APPIMAGE = auto()
    LINUX_FLATPAK = auto()
    LINUX_PACKAGE = auto()
    DEVELOPMENT = auto()


def get_macos_app_bundle_path() -> Optional[str]:
    """Find the path to the enclosing .app bundle when running on macOS."""
    if sys.platform != 'darwin':
        return None
    for cand in (sys.executable, getattr(sys, '_MEIPASS', ''), __file__):
        p = os.path.abspath(cand)
        while p and p != '/' and p != os.path.dirname(p):
            if p.endswith('.app'):
                return p
            p = os.path.dirname(p)
    if os.path.isdir('/Applications/Showberry.app'):
        return '/Applications/Showberry.app'
    return None


def detect_installation_type() -> InstallationType:
    """Detect how Showberry was packaged and launched on the current host."""
    if sys.platform == 'win32':
        exe_dir = os.path.dirname(sys.executable)
        if os.path.exists(os.path.join(exe_dir, 'unins000.exe')):
            return InstallationType.WINDOWS_INSTALLED
        if 'Program Files' in exe_dir or 'AppData' in exe_dir:
            return InstallationType.WINDOWS_INSTALLED
        if getattr(sys, 'frozen', False):
            return InstallationType.WINDOWS_PORTABLE
        return InstallationType.DEVELOPMENT

    if sys.platform == 'darwin':
        bundle = get_macos_app_bundle_path()
        if bundle or getattr(sys, 'frozen', False):
            return InstallationType.MACOS_BUNDLE
        return InstallationType.DEVELOPMENT

    # Linux / BSD
    if os.environ.get('APPIMAGE'):
        return InstallationType.LINUX_APPIMAGE

    if os.path.exists('/.flatpak-info') or os.environ.get('FLATPAK_ID'):
        return InstallationType.LINUX_FLATPAK

    if getattr(sys, 'frozen', False):
        return InstallationType.LINUX_PACKAGE

    # Check if running from git/source checkout
    here = Path(__file__).resolve().parent.parent.parent
    if (here / '.git').exists() or (here / 'pyproject.toml').exists():
        return InstallationType.DEVELOPMENT

    return InstallationType.LINUX_PACKAGE


@dataclass
class UpdateInfo:
    """Metadata describing an available upstream software release."""
    version: str
    tag_name: str
    name: str
    body: str
    html_url: str
    published_at: str
    installation_type: InstallationType
    asset_name: Optional[str] = None
    download_url: Optional[str] = None
    asset_size: int = 0
    sha256: Optional[str] = None
    all_assets: Dict[str, str] = field(default_factory=dict)


class UpdateService:
    """Singleton service for update checking, background downloads, and execution."""
    _instance: Optional[UpdateService] = None

    @classmethod
    def get_instance(cls) -> UpdateService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._settings = SettingsService()
        self._installation_type = detect_installation_type()
        self._active_download_thread: Optional[threading.Thread] = None
        self._cancel_download_flag = threading.Event()
        self._is_checking = False

    @property
    def installation_type(self) -> InstallationType:
        return self._installation_type

    def get_best_asset(self, assets: List[Dict[str, Any]], install_type: InstallationType) -> Tuple[Optional[str], Optional[str], int]:
        """Return (asset_name, download_url, asset_size) matching current platform and installation."""
        if not assets:
            return None, None, 0

        asset_map = {a.get('name', ''): a for a in assets if 'name' in a and 'browser_download_url' in a}

        target_name = None
        if install_type in (InstallationType.WINDOWS_INSTALLED, InstallationType.WINDOWS_PORTABLE):
            # Prefer full installer .exe
            candidates = [n for n in asset_map if n.endswith('.exe') and 'setup' in n.lower()]
            if candidates:
                target_name = candidates[0]
            elif install_type == InstallationType.WINDOWS_PORTABLE:
                zips = [n for n in asset_map if n.endswith('.zip') and 'portable' in n.lower()]
                if zips:
                    target_name = zips[0]

        elif install_type == InstallationType.MACOS_BUNDLE:
            # Prefer zip for direct unzipping if available, fallback to dmg
            zips = [n for n in asset_map if n.endswith('.zip') and 'macos' in n.lower()]
            dmgs = [n for n in asset_map if n.endswith('.dmg')]
            if zips:
                target_name = zips[0]
            elif dmgs:
                target_name = dmgs[0]

        elif install_type == InstallationType.LINUX_APPIMAGE:
            appimages = [n for n in asset_map if n.endswith('.AppImage')]
            if appimages:
                target_name = appimages[0]

        elif install_type == InstallationType.LINUX_FLATPAK:
            flatpaks = [n for n in asset_map if n.endswith('.flatpak')]
            if flatpaks:
                target_name = flatpaks[0]

        # Fallback if no specific match
        if not target_name:
            if sys.platform == 'win32':
                cand = [n for n in asset_map if n.endswith('.exe')]
                target_name = cand[0] if cand else None
            elif sys.platform == 'darwin':
                cand = [n for n in asset_map if n.endswith('.dmg') or n.endswith('.zip')]
                target_name = cand[0] if cand else None
            elif sys.platform.startswith('linux'):
                cand = [n for n in asset_map if n.endswith('.AppImage') or n.endswith('.flatpak')]
                target_name = cand[0] if cand else None

        if target_name and target_name in asset_map:
            a = asset_map[target_name]
            return target_name, a.get('browser_download_url'), int(a.get('size', 0))

        return None, None, 0

    def check_for_updates(
        self,
        force: bool = False,
        callback: Optional[Callable[[Optional[UpdateInfo], Optional[str]], None]] = None
    ):
        """Asynchronously check GitHub for a newer release."""
        if self._is_checking:
            return

        if not force and not self._settings.auto_check_updates:
            if callback:
                GLib.idle_add(callback, None, None)
            return

        # Check debounce (once per 24h unless force=True)
        if not force:
            last_checked = self._settings.last_update_check
            if time.time() - last_checked < UPDATE_CHECK_INTERVAL_SECONDS:
                logger.debug("Skipping update check; checked %d seconds ago", time.time() - last_checked)
                if callback:
                    GLib.idle_add(callback, None, None)
                return

        self._is_checking = True

        def _worker():
            try:
                import urllib.request
                req = urllib.request.Request(
                    GITHUB_LATEST_RELEASE_URL,
                    headers={
                        'User-Agent': f'Showberry/{__version__} ({sys.platform})',
                        'Accept': 'application/vnd.github.v3+json',
                    }
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"GitHub returned HTTP status {resp.status}")
                    data = json.loads(resp.read().decode('utf-8'))

                tag_name = data.get('tag_name', '')
                version = re.sub(r'^[vV]', '', tag_name)

                # Update timestamp
                self._settings.last_update_check = int(time.time())

                if not is_newer_version(tag_name, __version__):
                    logger.info("Showberry is up-to-date (installed: %s, latest: %s)", __version__, version)
                    if callback:
                        GLib.idle_add(callback, None, None)
                    return

                # Found newer version
                raw_assets = data.get('assets', [])
                all_assets = {a.get('name', ''): a.get('browser_download_url', '') for a in raw_assets if 'name' in a}

                # Try to parse SHA256SUMS.txt if present
                sha256_map = {}
                sha_url = all_assets.get('SHA256SUMS.txt')
                if sha_url:
                    try:
                        sha_req = urllib.request.Request(
                            sha_url,
                            headers={'User-Agent': f'Showberry/{__version__}'}
                        )
                        with urllib.request.urlopen(sha_req, timeout=5) as sha_resp:
                            for line in sha_resp.read().decode('utf-8').splitlines():
                                parts = line.strip().split()
                                if len(parts) >= 2:
                                    sha256_map[parts[1].lstrip('*')] = parts[0]
                    except Exception as e:
                        logger.debug("Could not fetch SHA256SUMS.txt: %s", e)

                asset_name, download_url, asset_size = self.get_best_asset(raw_assets, self._installation_type)
                sha256_val = sha256_map.get(asset_name) if asset_name else None

                info = UpdateInfo(
                    version=version,
                    tag_name=tag_name,
                    name=data.get('name') or f"Showberry v{version}",
                    body=data.get('body') or "No release notes provided.",
                    html_url=data.get('html_url') or f"https://github.com/{GITHUB_REPO}/releases/tag/{tag_name}",
                    published_at=data.get('published_at') or "",
                    installation_type=self._installation_type,
                    asset_name=asset_name,
                    download_url=download_url,
                    asset_size=asset_size,
                    sha256=sha256_val,
                    all_assets=all_assets,
                )

                logger.info("New version available: %s (Asset: %s)", version, asset_name)
                if callback:
                    GLib.idle_add(callback, info, None)

            except Exception as e:
                logger.warning("Failed checking for updates: %s", e)
                if callback:
                    GLib.idle_add(callback, None, str(e))
            finally:
                self._is_checking = False

        t = threading.Thread(target=_worker, name="Showberry-UpdateChecker", daemon=True)
        t.start()

    def download_update(
        self,
        update_info: UpdateInfo,
        progress_callback: Callable[[float, int, int], None],
        completion_callback: Callable[[bool, Optional[str], Optional[str]], None]
    ):
        """Stream update asset to disk with download progress and checksum verification."""
        if not update_info.download_url:
            GLib.idle_add(completion_callback, False, None, "No download URL available for this platform.")
            return

        self._cancel_download_flag.clear()

        def _download_worker():
            local_path = None
            try:
                import urllib.request
                req = urllib.request.Request(
                    update_info.download_url,
                    headers={'User-Agent': f'Showberry/{__version__}'}
                )

                # Determine local temp target file
                suffix = ""
                if update_info.asset_name:
                    _, suffix = os.path.splitext(update_info.asset_name)

                temp_dir = tempfile.gettempdir()
                prefix = f"showberry_update_{update_info.version}_"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix=prefix, dir=temp_dir) as f:
                    local_path = f.name

                hasher = hashlib.sha256() if update_info.sha256 else None
                downloaded = 0
                total = update_info.asset_size

                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp_total = resp.headers.get('Content-Length')
                    if resp_total:
                        total = int(resp_total)

                    with open(local_path, 'wb') as out_f:
                        while True:
                            if self._cancel_download_flag.is_set():
                                out_f.close()
                                if os.path.exists(local_path):
                                    os.unlink(local_path)
                                GLib.idle_add(completion_callback, False, None, "Download cancelled.")
                                return

                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            out_f.write(chunk)
                            downloaded += len(chunk)
                            if hasher:
                                hasher.update(chunk)

                            fraction = (downloaded / total) if total > 0 else 0.0
                            GLib.idle_add(progress_callback, fraction, downloaded, total)

                # Checksum verification
                if hasher and update_info.sha256:
                    computed_sha = hasher.hexdigest().lower()
                    if computed_sha != update_info.sha256.lower():
                        if os.path.exists(local_path):
                            os.unlink(local_path)
                        raise ValueError(f"SHA256 checksum mismatch (expected {update_info.sha256}, got {computed_sha})")

                # If AppImage, ensure executable permissions
                if local_path.endswith('.AppImage'):
                    os.chmod(local_path, 0o755)

                logger.info("Downloaded update asset to %s (%d bytes)", local_path, downloaded)
                GLib.idle_add(completion_callback, True, local_path, None)

            except Exception as e:
                logger.error("Download failed: %s", e)
                if local_path and os.path.exists(local_path):
                    try:
                        os.unlink(local_path)
                    except Exception:
                        pass
                GLib.idle_add(completion_callback, False, None, str(e))

        t = threading.Thread(target=_download_worker, name="Showberry-UpdateDownloader", daemon=True)
        self._active_download_thread = t
        t.start()

    def cancel_download(self):
        """Signal active download worker to abort and clean up."""
        self._cancel_download_flag.set()

    def apply_update(self, update_info: UpdateInfo, local_file: str) -> Tuple[bool, Optional[str]]:
        """Apply the downloaded update and initiate application restart."""
        if not local_file or not os.path.exists(local_file):
            return False, "Downloaded update package file does not exist."

        install_type = self._installation_type

        try:
            # 1. Windows Installer Upgrade
            if install_type in (InstallationType.WINDOWS_INSTALLED, InstallationType.WINDOWS_PORTABLE):
                if local_file.endswith('.exe'):
                    # Launch Inno Setup with silent close & restart flags
                    cmd = [
                        local_file,
                        "/CLOSEAPPLICATIONS",
                        "/RESTARTAPPLICATIONS",
                        "/SP-",
                    ]
                    logger.info("Spawning Windows Inno Setup installer: %s", cmd)
                    subprocess.Popen(cmd, shell=False)
                    return True, None
                elif local_file.endswith('.zip'):
                    # Open folder containing the zip
                    subprocess.Popen(['explorer.exe', f'/select,{os.path.abspath(local_file)}'])
                    return True, None

            # 2. Linux AppImage In-Place Replace
            elif install_type == InstallationType.LINUX_APPIMAGE:
                current_appimage = os.environ.get('APPIMAGE')
                if not current_appimage or not os.path.exists(current_appimage):
                    return False, "Could not determine host AppImage location from $APPIMAGE environment variable."

                os.chmod(local_file, 0o755)
                # Atomically replace running binary path
                os.replace(local_file, current_appimage)
                logger.info("Replaced AppImage binary at %s", current_appimage)

                # Spawn new AppImage process and exit
                subprocess.Popen([current_appimage], start_new_session=True)
                return True, None

            # 3. macOS App Bundle Swap
            elif install_type == InstallationType.MACOS_BUNDLE:
                target_bundle = get_macos_app_bundle_path()
                if not target_bundle or not os.path.isdir(target_bundle):
                    # Fallback to opening DMG in Finder
                    if local_file.endswith('.dmg'):
                        subprocess.Popen(['open', local_file])
                        return True, None
                    return False, "Could not determine active macOS .app bundle directory."

                staging_dir = tempfile.mkdtemp(prefix="showberry_mac_staging_")
                staging_app = os.path.join(staging_dir, "Showberry.app")

                # Extract zip or mount dmg
                if local_file.endswith('.zip'):
                    extract_cmd = ['ditto', '-xk', local_file, staging_dir]
                    res = subprocess.run(extract_cmd, capture_output=True, text=True)
                    if res.returncode != 0:
                        return False, f"Failed to extract update zip: {res.stderr}"
                elif local_file.endswith('.dmg'):
                    mount_dir = tempfile.mkdtemp(prefix="showberry_dmg_mnt_")
                    mount_cmd = ['hdiutil', 'attach', '-nobrowse', '-mountpoint', mount_dir, local_file]
                    res = subprocess.run(mount_cmd, capture_output=True, text=True)
                    if res.returncode != 0:
                        # Fallback: open DMG directly in Finder
                        subprocess.Popen(['open', local_file])
                        return True, None
                    try:
                        dmg_app = os.path.join(mount_dir, "Showberry.app")
                        if not os.path.exists(dmg_app):
                            return False, "Showberry.app not found inside DMG."
                        shutil.copytree(dmg_app, staging_app, symlinks=True)
                    finally:
                        subprocess.run(['hdiutil', 'detach', mount_dir], capture_output=True)
                        shutil.rmtree(mount_dir, ignore_errors=True)

                if not os.path.isdir(staging_app):
                    return False, "Failed to prepare extracted Showberry.app for update."

                # Create detached bash helper script
                script_path = os.path.join(tempfile.gettempdir(), 'showberry_updater.sh')
                script_content = f"""#!/bin/bash
TARGET_APP="{target_bundle}"
STAGING_APP="{staging_app}"
OLD_PID="{os.getpid()}"

# 1. Wait for current process to terminate
while kill -0 "$OLD_PID" 2>/dev/null; do
    sleep 0.2
done

if [ ! -d "$STAGING_APP" ]; then
    exit 1
fi

BACKUP_APP="${{TARGET_APP}}.bak"
rm -rf "$BACKUP_APP" 2>/dev/null

if mv "$TARGET_APP" "$BACKUP_APP" 2>/dev/null; then
    if mv "$STAGING_APP" "$TARGET_APP" 2>/dev/null; then
        rm -rf "$BACKUP_APP" 2>/dev/null
    else
        mv "$BACKUP_APP" "$TARGET_APP" 2>/dev/null
        exit 1
    fi
else
    rm -rf "$TARGET_APP" 2>/dev/null
    cp -R "$STAGING_APP" "$TARGET_APP" 2>/dev/null
fi

xattr -dr com.apple.quarantine "$TARGET_APP" 2>/dev/null || true
rm -rf "$(dirname "$STAGING_APP")" 2>/dev/null || true
open -a "$TARGET_APP"
"""
                with open(script_path, 'w') as sf:
                    sf.write(script_content)
                os.chmod(script_path, 0o755)

                logger.info("Executing detached macOS updater script: %s", script_path)
                subprocess.Popen(['/bin/bash', script_path], start_new_session=True, close_fds=True)
                return True, None

            # 4. Flatpak / Linux Package Managers
            elif install_type == InstallationType.LINUX_FLATPAK:
                # Save to user Downloads folder and open with default software handler
                downloads_dir = Path.home() / "Downloads"
                downloads_dir.mkdir(parents=True, exist_ok=True)
                dest = downloads_dir / (update_info.asset_name or "io.github.Dackerie.Showberry.flatpak")
                shutil.copy2(local_file, dest)
                subprocess.Popen(['xdg-open', str(dest)])
                return True, None

            return False, f"Direct in-place update not supported for installation type {install_type.name}"

        except Exception as e:
            logger.error("Failed applying update: %s", e)
            return False, str(e)
