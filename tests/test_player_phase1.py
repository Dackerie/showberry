"""Unit tests for Phase 1 Player Experience features."""

import unittest
from unittest.mock import MagicMock, patch
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib

from showberry.ui.player_page import (
    PlayerPage,
    MpvWidget,
    PlayerControls,
    AudioPopover,
    SpeedPopover,
    ASPECT_MODES,
)


class TestPlayerPhase1(unittest.TestCase):
    """Test Phase 1 player experience additions."""

    def test_mpv_audio_tracks_and_cycling(self):
        """Test audio track retrieval, selection, and cycling."""
        widget = MpvWidget()
        mock_mpv = MagicMock()
        mock_mpv.track_list = [
            {'type': 'video', 'id': 1},
            {'type': 'audio', 'id': 2, 'title': 'English Surround', 'lang': 'eng', 'codec': 'ac3', 'audio-channels': 6, 'selected': True},
            {'type': 'audio', 'id': 3, 'title': 'Japanese Stereo', 'lang': 'jpn', 'codec': 'aac', 'audio-channels': 2, 'selected': False},
            {'type': 'sub', 'id': 4},
        ]
        prop_dict = {'aid': 2}
        mock_mpv.__getitem__.side_effect = lambda k: prop_dict.get(k)
        def set_item(k, v):
            prop_dict[k] = v
        mock_mpv.__setitem__.side_effect = set_item
        widget._mpv = mock_mpv

        tracks = widget.get_audio_tracks()
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[0]['id'], 2)
        self.assertEqual(tracks[0]['codec'], 'ac3')
        self.assertEqual(tracks[1]['id'], 3)
        self.assertEqual(tracks[1]['lang'], 'jpn')

        # Cycle to next track (should switch to track 3)
        next_track = widget.cycle_audio_track()
        self.assertIsNotNone(next_track)
        self.assertEqual(next_track['id'], 3)
        self.assertEqual(widget.get_audio_track(), 3)

        # Cycle again (should wrap back to track 2)
        next_track = widget.cycle_audio_track()
        self.assertEqual(next_track['id'], 2)
        self.assertEqual(widget.get_audio_track(), 2)

    def test_mpv_speed_control(self):
        """Test playback speed getters, setters, and clamping."""
        widget = MpvWidget()
        widget._mpv.speed = 1.0

        # Adjust up
        s = widget.adjust_speed(0.25)
        self.assertEqual(s, 1.25)
        self.assertEqual(widget.get_speed(), 1.25)

        # Adjust down
        s = widget.adjust_speed(-0.5)
        self.assertEqual(s, 0.75)
        self.assertEqual(widget.get_speed(), 0.75)

        # Clamp max
        s = widget.set_speed(4.5)
        self.assertEqual(s, 3.0)

        # Clamp min
        s = widget.set_speed(0.1)
        self.assertEqual(s, 0.25)

    def test_mpv_aspect_ratio_cycling(self):
        """Test aspect ratio / video fit mode cycling."""
        widget = MpvWidget()
        widget._mpv._property_dict = {}
        widget._mpv.__setitem__ = lambda s, k, v: widget._mpv._property_dict.update({k: v})

        # Cycle through all 5 modes
        modes = []
        for _ in range(len(ASPECT_MODES)):
            label = widget.cycle_aspect_ratio()
            modes.append(label)

        self.assertIn("Fill / Crop", modes)
        self.assertIn("Stretch 16:9", modes)
        self.assertIn("Stretch 21:9", modes)
        self.assertIn("Stretch 4:3", modes)
        self.assertIn("Fit (Original)", modes)

    def test_player_keyboard_shortcuts_phase1(self):
        """Test audio track, speed, and aspect ratio keyboard shortcuts."""
        pp = PlayerPage()
        pp._hide_controls()

        # 1. Cycle Audio Track ('a' / 'A')
        with patch.object(pp._mpv_widget, 'cycle_audio_track', return_value={'title': 'English', 'codec': 'ac3', 'id': 1}):
            handled = pp._on_key_pressed(None, Gdk.KEY_a, 0, 0)
            self.assertTrue(handled)
            self.assertIn("Audio: English (AC3)", pp._osd_pill.get_text())

        # 2. Speed Down ('[')
        with patch.object(pp._mpv_widget, 'adjust_speed', return_value=0.75):
            handled = pp._on_key_pressed(None, Gdk.KEY_bracketleft, 0, 0)
            self.assertTrue(handled)
            self.assertEqual(pp._osd_pill.get_text(), "Speed: 0.75x")
            self.assertEqual(pp._controls._speed_btn.get_label(), "0.75x")

        # 3. Speed Up (']')
        with patch.object(pp._mpv_widget, 'adjust_speed', return_value=1.25):
            handled = pp._on_key_pressed(None, Gdk.KEY_bracketright, 0, 0)
            self.assertTrue(handled)
            self.assertEqual(pp._osd_pill.get_text(), "Speed: 1.25x")
            self.assertEqual(pp._controls._speed_btn.get_label(), "1.25x")

        # 4. Speed Reset ('r')
        with patch.object(pp._mpv_widget, 'set_speed', return_value=1.0):
            handled = pp._on_key_pressed(None, Gdk.KEY_r, 0, 0)
            self.assertTrue(handled)
            self.assertEqual(pp._osd_pill.get_text(), "Speed: 1.0x (Normal)")
            self.assertEqual(pp._controls._speed_btn.get_label(), "1x")

        # 5. Aspect Ratio ('w')
        with patch.object(pp._mpv_widget, 'cycle_aspect_ratio', return_value="Fill / Crop"):
            handled = pp._on_key_pressed(None, Gdk.KEY_w, 0, 0)
            self.assertTrue(handled)
            self.assertEqual(pp._osd_pill.get_text(), "Video Fit: Fill / Crop")

        # Ensure OSC bottom bar remained hidden throughout
        self.assertFalse(pp._controls.get_visible())

    def test_next_episode_resolution_and_trigger(self):
        """Test background next episode resolution and play-next trigger."""
        pp = PlayerPage()
        pp._stream_data = {
            'movie': {'id': 100, 'title': 'Test Show'},
            'media_type': 'tv',
            'season': 1,
            'episode': 2,
            'provider': 'vidfast',
        }

        # Mock TMDB season lookup returning episodes 1, 2, 3
        mock_eps = [
            {'episode_number': 1, 'name': 'Pilot'},
            {'episode_number': 2, 'name': 'Episode 2'},
            {'episode_number': 3, 'name': 'Episode 3'},
        ]
        with patch.object(pp._tmdb, 'get_tv_season', return_value=mock_eps):
            pp._resolve_next_episode_thread(100, 1, 2, pp._session_id)
        while GLib.MainContext.default().iteration(False):
            pass

        # After resolution, next stream data should point to S1E3
        self.assertIsNotNone(pp._next_stream_data)
        self.assertEqual(pp._next_stream_data['season'], 1)
        self.assertEqual(pp._next_stream_data['episode'], 3)
        self.assertTrue(pp._controls._next_ep_btn.get_visible())
        self.assertIn("S01E03", pp._next_ep_sub_label.get_text())

        # Test countdown card appearance
        pp._show_next_episode_countdown()
        self.assertTrue(pp._next_ep_card.get_visible())
        self.assertIn("Next Episode in", pp._next_ep_title_label.get_text())

        # Test dismiss
        pp._on_dismiss_next_episode()
        self.assertFalse(pp._next_ep_card.get_visible())
        self.assertTrue(pp._next_ep_dismissed)

        # Test Shift+N shortcut to immediately trigger next episode
        with patch.object(pp, 'load_stream') as mock_load:
            pp._on_key_pressed(None, Gdk.KEY_N, 0, Gdk.ModifierType.SHIFT_MASK)
            mock_load.assert_called_once()
            call_arg = mock_load.call_args[0][0]
            self.assertEqual(call_arg['episode'], 3)

    def test_next_episode_season_rollover(self):
        """Test next episode rollover to season 2 episode 1 when season 1 ends."""
        pp = PlayerPage()
        pp._stream_data = {
            'movie': {'id': 100, 'title': 'Test Show'},
            'media_type': 'tv',
            'season': 1,
            'episode': 10,
        }

        # S1 has episodes 1-10 (no ep 11); S2 has episode 1
        def mock_season_fn(tmdb_id, s_num):
            if s_num == 1:
                return [{'episode_number': i, 'name': f'Ep {i}'} for i in range(1, 11)]
            elif s_num == 2:
                return [{'episode_number': 1, 'name': 'Season 2 Premiere'}]
            return []

        with patch.object(pp._tmdb, 'get_tv_season', side_effect=mock_season_fn):
            pp._resolve_next_episode_thread(100, 1, 10, pp._session_id)
        while GLib.MainContext.default().iteration(False):
            pass

        self.assertIsNotNone(pp._next_stream_data)
        self.assertEqual(pp._next_stream_data['season'], 2)
        self.assertEqual(pp._next_stream_data['episode'], 1)
        self.assertEqual(pp._next_stream_data['title'], 'Season 2 Premiere')

    def test_popovers_interaction(self):
        """Test AudioPopover and SpeedPopover instantiation and item selection."""
        mock_mpv = MagicMock()
        mock_mpv.get_audio_tracks.return_value = [
            {'id': 1, 'title': 'English', 'codec': 'aac', 'channels': 2, 'selected': True},
            {'id': 2, 'title': 'Japanese', 'codec': 'flac', 'channels': 6, 'selected': False},
        ]
        mock_mpv.get_audio_track.return_value = 1
        mock_mpv.get_speed.return_value = 1.0

        # Audio popover
        audio_cb = MagicMock()
        ap = AudioPopover(player=mock_mpv, on_audio_changed=audio_cb)
        ap.refresh_tracks()
        self.assertIsNotNone(ap.get_child())

        # Speed popover
        speed_cb = MagicMock()
        sp = SpeedPopover(player=mock_mpv, on_speed_changed=speed_cb)
        sp.refresh_speeds()
        sp._on_speed_toggled(MagicMock(get_active=lambda: True), 1.25)
        mock_mpv.set_speed.assert_called_with(1.25)
        speed_cb.assert_called_with(1.25)

    def test_audio_button_icon_and_tooltip(self):
        """Audio track selector button must use headphones icon and not duplicate volume icon."""
        pc = PlayerControls()
        self.assertEqual(pc._audio_btn.get_icon_name(), 'audio-headphones-symbolic')
        self.assertIn("Audio Tracks", pc._audio_btn.get_tooltip_text())

    def test_seek_bar_clean_structure(self):
        """Verify seekbar has standard clean structure without obstructing overlays."""
        pc = PlayerControls()
        self.assertIsInstance(pc._seek_bar, Gtk.Scale)
        self.assertFalse(hasattr(pc, '_hover_box'))
        self.assertFalse(hasattr(pc, '_hover_pill'))

    def test_next_episode_overlay_ordering_and_spacing(self):
        """Verify Next Episode card has bottom margin (148px) matching bottom OSC window gap and is added after controls."""
        pp = PlayerPage()
        self.assertEqual(pp._next_ep_card.get_margin_bottom(), 148)
        self.assertEqual(pp._next_ep_card.get_margin_end(), 28)

        # Verify child ordering in overlay
        children = []
        child = pp._overlay.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()

        self.assertIn(pp._controls, children)
        self.assertIn(pp._next_ep_card, children)
        # Next episode card must appear after controls in sibling chain (rendered on top)
        controls_idx = children.index(pp._controls)
        next_card_idx = children.index(pp._next_ep_card)
        self.assertGreater(next_card_idx, controls_idx)


if __name__ == '__main__':
    unittest.main()

