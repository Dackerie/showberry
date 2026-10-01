"""Unit tests for Showberry cross-platform auto-updater."""

import os
import sys
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


if __name__ == '__main__':
    unittest.main()
