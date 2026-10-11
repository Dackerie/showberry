"""Unit tests for Showberry cross-platform auto-updater."""

import os
import sys
import errno
import json
import time
import unittest
from unittest.mock import MagicMock, patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

Adw.init()

from showberry.services.updater import (
    parse_version,
    is_newer_version,
    detect_installation_type,
    InstallationType,
    UpdateInfo,
    UpdateService,
)
from showberry.ui.update_dialog import UpdateDialog
from showberry.ui.settings_page import SettingsPage
from showberry.window import ShowberryWindow


class TestUpdaterService(unittest.TestCase):

    def test_parse_version(self):
        self.assertEqual(parse_version("0.3.4"), (0, 3, 4))
        self.assertEqual(parse_version("v0.4.0"), (0, 4, 0))
        self.assertEqual(parse_version("V1.2.3.4"), (1, 2, 3, 4))
        self.assertEqual(parse_version(""), (0, 0, 0))
        self.assertEqual(parse_version("0.4"), (0, 4, 0))

    def test_is_newer_version(self):
        self.assertTrue(is_newer_version("v0.4.0", "0.3.4"))
        self.assertTrue(is_newer_version("0.4.1", "0.4.0"))
        self.assertTrue(is_newer_version("1.0.0", "0.4.0"))
        self.assertFalse(is_newer_version("0.3.4", "0.3.4"))
        self.assertFalse(is_newer_version("v0.3.4", "0.4.0"))
        self.assertFalse(is_newer_version("0.3.3.2", "0.3.4"))

    def test_detect_installation_type(self):
        with patch.dict(os.environ, {'APPIMAGE': '/path/to/Showberry-x86_64.AppImage'}):
            self.assertEqual(detect_installation_type(), InstallationType.LINUX_APPIMAGE)

        with patch.dict(os.environ, {'FLATPAK_ID': 'io.github.Dackerie.Showberry'}, clear=True):
            self.assertEqual(detect_installation_type(), InstallationType.LINUX_FLATPAK)

    def test_get_best_asset_matching(self):
        updater = UpdateService.get_instance()
        sample_assets = [
            {'name': 'Showberry-Windows-Setup-x86_64.exe', 'browser_download_url': 'https://example.com/setup.exe', 'size': 50000000},
            {'name': 'Showberry-Windows-Portable-x86_64.zip', 'browser_download_url': 'https://example.com/win.zip', 'size': 45000000},
            {'name': 'Showberry-macOS-arm64.dmg', 'browser_download_url': 'https://example.com/mac.dmg', 'size': 60000000},
            {'name': 'Showberry-macOS-arm64.zip', 'browser_download_url': 'https://example.com/mac.zip', 'size': 58000000},
            {'name': 'Showberry-x86_64.AppImage', 'browser_download_url': 'https://example.com/appimage', 'size': 70000000},
            {'name': 'io.github.Dackerie.Showberry.flatpak', 'browser_download_url': 'https://example.com/flatpak', 'size': 65000000},
            {'name': 'SHA256SUMS.txt', 'browser_download_url': 'https://example.com/sums.txt', 'size': 1000},
        ]

        # Windows installer
        name, url, size = updater.get_best_asset(sample_assets, InstallationType.WINDOWS_INSTALLED)
        self.assertEqual(name, 'Showberry-Windows-Setup-x86_64.exe')
        self.assertEqual(url, 'https://example.com/setup.exe')
        self.assertEqual(size, 50000000)

        # macOS bundle (prefer zip for auto-update)
        name, url, size = updater.get_best_asset(sample_assets, InstallationType.MACOS_BUNDLE)
        self.assertEqual(name, 'Showberry-macOS-arm64.zip')

        # Linux AppImage
        name, url, size = updater.get_best_asset(sample_assets, InstallationType.LINUX_APPIMAGE)
        self.assertEqual(name, 'Showberry-x86_64.AppImage')

        # Flatpak
        name, url, size = updater.get_best_asset(sample_assets, InstallationType.LINUX_FLATPAK)
        self.assertEqual(name, 'io.github.Dackerie.Showberry.flatpak')

    def test_update_info_dataclass(self):
        info = UpdateInfo(
            version="0.4.0",
            tag_name="v0.4.0",
            name="Showberry v0.4.0",
            body="New features and fixes",
            html_url="https://github.com/Dackerie/showberry/releases/tag/v0.4.0",
            published_at="2026-10-01T00:00:00Z",
            installation_type=InstallationType.LINUX_APPIMAGE,
            asset_name="Showberry-x86_64.AppImage",
            download_url="https://github.com/Dackerie/showberry/releases/download/v0.4.0/Showberry-x86_64.AppImage",
            asset_size=75000000,
            sha256="abcdef1234567890",
        )
        self.assertEqual(info.version, "0.4.0")
        self.assertEqual(info.asset_name, "Showberry-x86_64.AppImage")
        self.assertEqual(info.sha256, "abcdef1234567890")

    def test_update_dialog_instantiation(self):
        parent = Gtk.Window()
        info = UpdateInfo(
            version="0.4.0",
            tag_name="v0.4.0",
            name="Showberry v0.4.0",
            body="* Added auto-update system\n* Added player window repositioning",
            html_url="https://github.com/Dackerie/showberry/releases/tag/v0.4.0",
            published_at="2026-10-01T00:00:00Z",
            installation_type=InstallationType.LINUX_APPIMAGE,
            asset_name="Showberry-x86_64.AppImage",
            download_url="https://github.com/Dackerie/showberry/releases/download/v0.4.0/Showberry-x86_64.AppImage",
            asset_size=75000000,
        )
        dialog = UpdateDialog(parent, info)
        self.assertIn("v0.4.0", dialog.get_title())
        self.assertIsNotNone(dialog._action_btn)
        self.assertEqual(dialog._action_btn.get_label(), "Update & Restart")

    def test_settings_page_update_controls(self):
        page = SettingsPage()
        self.assertTrue(hasattr(page, '_update_row'))
        self.assertTrue(hasattr(page, '_check_update_btn'))
        # Auto-check updates toggle
        page._settings.auto_check_updates = True
        self.assertTrue(page._settings.auto_check_updates)
        page._settings.auto_check_updates = False
        self.assertFalse(page._settings.auto_check_updates)
        page._settings.auto_check_updates = True

    def test_window_update_action_and_banner(self):
        win = ShowberryWindow()
        self.assertTrue(hasattr(win, '_update_banner'))
        self.assertFalse(win._update_banner.get_revealed())
        self.assertIsNotNone(win.lookup_action('check_updates'))

        # Test simulating update found
        info = UpdateInfo(
            version="0.4.0",
            tag_name="v0.4.0",
            name="Showberry v0.4.0",
            body="Release notes",
            html_url="https://example.com",
            published_at="",
            installation_type=InstallationType.LINUX_APPIMAGE,
        )
        win._on_background_update_check_finished(info, None)
        self.assertTrue(win._update_banner.get_revealed())
        self.assertIn("0.4.0", win._update_banner.get_title())

    def test_update_debounce_interval(self):
        from showberry.services.updater import UPDATE_CHECK_INTERVAL_SECONDS
        self.assertEqual(UPDATE_CHECK_INTERVAL_SECONDS, 1800)

    def test_cached_update_info_lifecycle(self):
        updater = UpdateService.get_instance()
        info = UpdateInfo(
            version="99.0.0",
            tag_name="v99.0.0",
            name="Showberry v99.0.0",
            body="Future version",
            html_url="https://example.com",
            published_at="",
            installation_type=InstallationType.WINDOWS_INSTALLED,
            asset_name="Showberry-Windows-Setup-x86_64.exe",
            download_url="https://example.com/setup.exe",
            asset_size=50000000,
        )
        # Cache it
        updater._cache_update_info(info)
        cached = updater.get_cached_update_info()
        self.assertIsNotNone(cached)
        self.assertEqual(cached.version, "99.0.0")

        # Clear it
        updater._clear_cached_update()
        self.assertIsNone(updater.get_cached_update_info())

    def test_windows_apply_update_silent_flags(self):
        updater = UpdateService.get_instance()
        updater._installation_type = InstallationType.WINDOWS_INSTALLED

        with patch('os.path.exists', return_value=True), \
             patch('subprocess.Popen') as mock_popen, \
             patch('sys.platform', 'win32'):
            success, err = updater.apply_update(
                UpdateInfo(
                    version="0.4.1",
                    tag_name="v0.4.1",
                    name="Showberry v0.4.1",
                    body="",
                    html_url="",
                    published_at="",
                    installation_type=InstallationType.WINDOWS_INSTALLED,
                ),
                "C:\\temp\\Showberry-Windows-Setup-x86_64.exe"
            )
            self.assertTrue(success)
            self.assertIsNone(err)

    def test_background_check_shows_toast_and_banner(self):
        win = ShowberryWindow()
        info = UpdateInfo(
            version="0.4.2",
            tag_name="v0.4.2",
            name="Showberry v0.4.2",
            body="Notes",
            html_url="",
            published_at="",
            installation_type=InstallationType.LINUX_APPIMAGE,
        )
        with patch.object(win, 'show_toast') as mock_show_toast:
            win._on_background_update_check_finished(info, None)
            self.assertTrue(win._update_banner.get_revealed())
            self.assertIn("0.4.2", win._update_banner.get_title())
            mock_show_toast.assert_called_once()
            self.assertIn("0.4.2", mock_show_toast.call_args[0][0])

    def test_appimage_apply_update_normal(self):
        updater = UpdateService.get_instance()
        updater._installation_type = InstallationType.LINUX_APPIMAGE

        with patch.dict(os.environ, {'APPIMAGE': '/home/user/Showberry-x86_64.AppImage'}), \
             patch('os.path.exists', return_value=True), \
             patch('os.chmod') as mock_chmod, \
             patch('os.replace') as mock_replace, \
             patch('subprocess.Popen') as mock_popen:
            info = UpdateInfo(
                version="0.4.2",
                tag_name="v0.4.2",
                name="Showberry v0.4.2",
                body="",
                html_url="",
                published_at="",
                installation_type=InstallationType.LINUX_APPIMAGE,
            )
            success, err = updater.apply_update(info, "/tmp/showberry_download.AppImage")
            self.assertTrue(success)
            self.assertIsNone(err)
            mock_chmod.assert_called_with("/tmp/showberry_download.AppImage", 0o755)
            mock_replace.assert_called_once_with("/tmp/showberry_download.AppImage", "/home/user/Showberry-x86_64.AppImage")
            mock_popen.assert_called_once_with(["/home/user/Showberry-x86_64.AppImage"], start_new_session=True)

    def test_appimage_apply_update_exdev_fallback(self):
        updater = UpdateService.get_instance()
        updater._installation_type = InstallationType.LINUX_APPIMAGE

        # First os.replace raises EXDEV, second os.replace succeeds
        replace_calls = []
        def fake_replace(src, dst):
            replace_calls.append((src, dst))
            if len(replace_calls) == 1:
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return None

        with patch.dict(os.environ, {'APPIMAGE': '/home/user/Showberry-x86_64.AppImage'}), \
             patch('os.path.exists', return_value=True), \
             patch('os.chmod') as mock_chmod, \
             patch('os.replace', side_effect=fake_replace), \
             patch('shutil.copy2') as mock_copy2, \
             patch('os.unlink') as mock_unlink, \
             patch('subprocess.Popen') as mock_popen:
            info = UpdateInfo(
                version="0.4.2",
                tag_name="v0.4.2",
                name="Showberry v0.4.2",
                body="",
                html_url="",
                published_at="",
                installation_type=InstallationType.LINUX_APPIMAGE,
            )
            success, err = updater.apply_update(info, "/tmp/showberry_download.AppImage")
            self.assertTrue(success)
            self.assertIsNone(err)
            # Verify staging copy happened on target dir
            mock_copy2.assert_called_once_with("/tmp/showberry_download.AppImage", "/home/user/.Showberry-x86_64.AppImage.update_tmp")
            # Verify second replace was from staging file to target
            self.assertEqual(len(replace_calls), 2)
            self.assertEqual(replace_calls[1], ("/home/user/.Showberry-x86_64.AppImage.update_tmp", "/home/user/Showberry-x86_64.AppImage"))
            # Verify unlinks cleaned up local temp file and temp staged
            mock_unlink.assert_any_call("/tmp/showberry_download.AppImage")
            mock_popen.assert_called_once_with(["/home/user/Showberry-x86_64.AppImage"], start_new_session=True)

    def test_appimage_apply_update_missing_env(self):
        updater = UpdateService.get_instance()
        updater._installation_type = InstallationType.LINUX_APPIMAGE

        with patch.dict(os.environ, {}, clear=True), \
             patch('os.path.exists', side_effect=lambda p: p == "/tmp/test.AppImage"):
            info = UpdateInfo(
                version="0.4.2",
                tag_name="v0.4.2",
                name="Showberry v0.4.2",
                body="",
                html_url="",
                published_at="",
                installation_type=InstallationType.LINUX_APPIMAGE,
            )
            success, err = updater.apply_update(info, "/tmp/test.AppImage")
            self.assertFalse(success)
            self.assertIn("Could not determine host AppImage location", err)


if __name__ == '__main__':
    unittest.main()

