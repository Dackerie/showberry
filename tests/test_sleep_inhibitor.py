"""Tests for cross-platform SleepInhibitor service and video playback integration."""

import sys
from unittest.mock import MagicMock, patch
import pytest

from showberry.services.sleep_inhibitor import SleepInhibitor
from showberry.ui.player_page import MpvWidget, PlayerPage


class TestSleepInhibitorService:
    """Unit tests for SleepInhibitor cross-platform behavior."""

    def test_initial_state(self):
        inhibitor = SleepInhibitor()
        assert not inhibitor.is_inhibited
        assert inhibitor._inhibit_cookie is None
        assert inhibitor._win_heartbeat_id is None
        assert inhibitor._caffeinate_proc is None

    def test_uninhibit_when_not_inhibited_is_safe(self):
        inhibitor = SleepInhibitor()
        # Should be a no-op and not raise any exception
        inhibitor.uninhibit()
        assert not inhibitor.is_inhibited

    def test_windows_inhibit_and_uninhibit(self):
        inhibitor = SleepInhibitor()

        mock_kernel32 = MagicMock()
        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32 = mock_kernel32

        with patch.dict(sys.modules, {'ctypes': mock_ctypes}), \
             patch('sys.platform', 'win32'):
            # Inhibit
            inhibitor.inhibit()
            assert inhibitor.is_inhibited
            assert mock_kernel32.SetThreadExecutionState.called

            # Check that calling inhibit again is idempotent
            mock_kernel32.SetThreadExecutionState.reset_mock()
            inhibitor.inhibit()
            assert not mock_kernel32.SetThreadExecutionState.called

            # Uninhibit
            inhibitor.uninhibit()
            assert not inhibitor.is_inhibited
            assert mock_kernel32.SetThreadExecutionState.called

    def test_macos_inhibit_and_uninhibit(self):
        inhibitor = SleepInhibitor()
        mock_proc = MagicMock()
        mock_proc.pid = 12345

        with patch('sys.platform', 'darwin'), \
             patch('subprocess.Popen', return_value=mock_proc) as mock_popen:
            # Inhibit
            inhibitor.inhibit()
            assert inhibitor.is_inhibited
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert 'caffeinate' in args[0]
            assert '-d' in args

            # Calling inhibit again should be idempotent
            mock_popen.reset_mock()
            inhibitor.inhibit()
            assert not mock_popen.called

            # Uninhibit
            inhibitor.uninhibit()
            assert not inhibitor.is_inhibited
            assert mock_proc.terminate.called

    def test_linux_gtk_application_inhibit_and_uninhibit(self):
        mock_window = MagicMock()
        inhibitor = SleepInhibitor(window_getter=lambda: mock_window)

        mock_app = MagicMock()
        mock_app.get_is_registered.return_value = True
        mock_app.inhibit.return_value = 42

        with patch('sys.platform', 'linux'), \
             patch('gi.repository.Gio.Application.get_default', return_value=mock_app):
            # Inhibit
            inhibitor.inhibit()
            assert inhibitor.is_inhibited
            assert inhibitor._inhibit_cookie == 42
            mock_app.inhibit.assert_called_once()

            # Uninhibit
            inhibitor.uninhibit()
            assert not inhibitor.is_inhibited
            assert inhibitor._inhibit_cookie is None
            mock_app.uninhibit.assert_called_once_with(42)

    def test_linux_unregistered_app_does_not_crash(self):
        inhibitor = SleepInhibitor()

        mock_app = MagicMock()
        mock_app.get_is_registered.return_value = False

        with patch('sys.platform', 'linux'), \
             patch('gi.repository.Gio.Application.get_default', return_value=mock_app):
            # Should not crash or call inhibit on unregistered GApplication
            inhibitor.inhibit()
            assert inhibitor.is_inhibited
            assert not mock_app.inhibit.called

            inhibitor.uninhibit()
            assert not inhibitor.is_inhibited


class TestPlayerSleepInhibitorIntegration:
    """Integration tests for PlayerPage and MpvWidget with SleepInhibitor."""

    def test_mpv_widget_signals_include_pause_changed(self):
        from gi.repository import GObject
        signals = GObject.signal_list_names(MpvWidget)
        assert 'pause-changed' in signals
        assert 'stream-ready' in signals
        assert 'playback-ended' in signals

    def test_player_page_has_sleep_inhibitor(self):
        player_page = PlayerPage()
        assert hasattr(player_page, '_sleep_inhibitor')
        assert isinstance(player_page._sleep_inhibitor, SleepInhibitor)
        assert not player_page._sleep_inhibitor.is_inhibited

    def test_player_page_pause_changed_handler(self):
        player_page = PlayerPage()
        inhibitor = player_page._sleep_inhibitor

        # Mock inhibitor inhibit/uninhibit methods to test handler behavior
        with patch.object(inhibitor, 'inhibit') as mock_inhibit, \
             patch.object(inhibitor, 'uninhibit') as mock_uninhibit:
            # Paused -> should uninhibit
            player_page._on_pause_changed(player_page._mpv_widget, True)
            mock_uninhibit.assert_called_once()
            assert not mock_inhibit.called

            mock_uninhibit.reset_mock()
            mock_inhibit.reset_mock()

            # Unpaused / Playing -> should inhibit
            player_page._on_pause_changed(player_page._mpv_widget, False)
            mock_inhibit.assert_called_once()
            assert not mock_uninhibit.called

    def test_player_page_teardown_uninhibits(self):
        player_page = PlayerPage()
        inhibitor = player_page._sleep_inhibitor

        with patch.object(inhibitor, 'uninhibit') as mock_uninhibit:
            player_page._on_playback_ended()
            mock_uninhibit.assert_called_once()

        with patch.object(inhibitor, 'uninhibit') as mock_uninhibit:
            player_page._on_stream_error("Test error")
            mock_uninhibit.assert_called_once()
