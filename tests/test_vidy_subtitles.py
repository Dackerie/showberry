"""Unit tests for Vidy-style subtitles implementation."""

import unittest
from unittest.mock import MagicMock
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from showberry.ui.player_page import SubtitlePopover, MpvWidget
from showberry.services.subtitles import SubtitleService


class TestVidySubtitles(unittest.TestCase):
    """Test Vidy-style popover navigation, upload, search, and appearance controls."""

    def test_subtitle_popover_structure(self):
        popover = SubtitlePopover()
        self.assertIsInstance(popover._stack, Gtk.Stack)
        self.assertIsNotNone(popover._stack.get_child_by_name('main'))
        self.assertIsNotNone(popover._stack.get_child_by_name('search'))
        self.assertIsNotNone(popover._stack.get_child_by_name('appearance'))

    def test_upload_button_callback(self):
        called = False

        def _on_upload():
            nonlocal called
            called = True

        popover = SubtitlePopover(on_upload_requested=_on_upload)
        popover._on_upload_clicked(None)
        self.assertTrue(called)

    def test_search_filtering(self):
        popover = SubtitlePopover()
        subs = [
            {'id': '1', 'url': 'https://subs.org/1.srt', 'lang': 'eng', 'lang_name': 'English', 'release_name': '1080p.WEBRip', 'flag': '🇺🇸', 'label': 'English [SDH]'},
            {'id': '2', 'url': 'https://subs.org/2.srt', 'lang': 'spa', 'lang_name': 'Spanish', 'release_name': '720p.HDTV', 'flag': '🇪🇸', 'label': 'Spanish [Latin]'},
            {'id': '3', 'url': 'https://subs.org/3.srt', 'lang': 'fra', 'lang_name': 'French', 'release_name': 'BluRay', 'flag': '🇫🇷', 'label': 'French'},
        ]
        popover.set_available_subtitles(subs)
        self.assertEqual(len(popover._available_subtitles), 3)

        # Filter service
        service = SubtitleService()
        res_spa = service.filter_subtitles(subs, 'spanish')
        self.assertEqual(len(res_spa), 1)
        self.assertEqual(res_spa[0]['lang'], 'spa')

        res_bluray = service.filter_subtitles(subs, 'bluray')
        self.assertEqual(len(res_bluray), 1)
        self.assertEqual(res_bluray[0]['lang'], 'fra')

    def test_searching_state_with_spinner(self):
        popover = SubtitlePopover()
        popover.set_searching(True)
        self.assertTrue(popover._is_searching)

        # Ensure a spinner exists in search results box while searching
        child = popover._search_results_box.get_first_child()
        self.assertIsNotNone(child)
        spinner = child.get_first_child()
        self.assertIsInstance(spinner, Gtk.Spinner)

    def test_search_error_state(self):
        popover = SubtitlePopover()
        popover.set_search_error("Failed to connect to OpenSubtitles")
        self.assertFalse(popover._is_searching)
        self.assertEqual(popover._search_error, "Failed to connect to OpenSubtitles")

        # Ensure error message is displayed
        child = popover._search_results_box.get_first_child()
        self.assertIsNotNone(child)
        label = child.get_first_child()
        self.assertIsInstance(label, Gtk.Label)
        self.assertIn("Failed to connect", label.get_text())

    def test_search_empty_state_and_reload(self):
        reloaded = False

        def _on_reload():
            nonlocal reloaded
            reloaded = True

        popover = SubtitlePopover(on_refresh_requested=_on_reload)
        popover.set_available_subtitles([])
        self.assertFalse(popover._is_searching)

        # Check empty label
        child = popover._search_results_box.get_first_child()
        self.assertIsNotNone(child)
        label = child.get_first_child()
        self.assertIsInstance(label, Gtk.Label)
        self.assertIn("No subtitles found", label.get_text())

        # Trigger reload search
        popover._on_reload_search()
        self.assertTrue(reloaded)
        self.assertTrue(popover._is_searching)

    def test_appearance_reset(self):
        widget = MpvWidget()
        mock_mpv = MagicMock()
        mock_mpv.sub_delay = 1.5
        mock_mpv.sub_pos = 80
        mock_mpv.sub_font_size = 50
        widget._mpv = mock_mpv

        popover = SubtitlePopover(player=widget)
        popover._reset_appearance()

        self.assertEqual(mock_mpv.sub_delay, 0.0)
        self.assertEqual(mock_mpv.sub_pos, 96)
        self.assertEqual(mock_mpv.sub_font_size, 28)

    def test_score_subtitle_release_prioritizes_web_dl_over_cam(self):
        from showberry.services.subtitles import score_subtitle_release
        cam_sub = {
            'movieReleaseName': 'Inception.2010.CAM.Xvid-LKRG',
            'releaseFormat': 'Cam',
            'fpsMilli': 25000,
        }
        web_sub = {
            'movieReleaseName': 'Inception.2010.1080p.HMAX.WEB-DL.DDP5.1.x264',
            'releaseFormat': 'WEBRip',
            'fpsMilli': 23976,
        }
        bluray_sub = {
            'movieReleaseName': 'Inception.2010.BluRay.1080p.x264-YTS',
            'releaseFormat': 'Blu-ray',
            'fpsMilli': 23976,
        }
        cam_score = score_subtitle_release(cam_sub)
        web_score = score_subtitle_release(web_sub)
        bluray_score = score_subtitle_release(bluray_sub)

        self.assertLess(cam_score, -500)
        self.assertGreater(web_score, 200)
        self.assertGreater(bluray_score, 200)
        self.assertGreater(web_score, cam_score)

    def test_mpv_widget_queues_subtitles_when_video_not_loaded(self):
        widget = MpvWidget()
        mock_mpv = MagicMock()
        mock_mpv.filename = None
        widget._mpv = mock_mpv

        # Add subtitle while file is not yet loaded
        widget._add_local_subtitle("/tmp/test.srt", label="English WEBRip", lang="eng", select=True)
        self.assertEqual(len(widget._pending_local_subs), 1)
        self.assertEqual(widget._pending_local_subs[0][0], "/tmp/test.srt")
        self.assertEqual(widget._pending_local_subs[0][1], "English WEBRip")
        mock_mpv.command.assert_not_called()

        # Simulate file loaded
        mock_mpv.filename = "https://cdn.example.com/video.mp4"
        mock_mpv.track_list = [{'id': 1, 'type': 'sub', 'selected': False, 'title': 'English WEBRip'}]
        widget._flush_pending_local_subs()

        self.assertEqual(len(widget._pending_local_subs), 0)
        mock_mpv.command.assert_called_once_with('sub-add', '/tmp/test.srt', 'select', 'English WEBRip', 'eng')
        mock_mpv.__setitem__.assert_called_with('sid', 1)

    def test_subtitle_popover_tracks_active_state(self):
        widget = MpvWidget()
        mock_mpv = MagicMock()
        mock_mpv.filename = "/video.mp4"
        mock_mpv.track_list = [
            {'id': 1, 'type': 'sub', 'selected': True, 'title': 'English (1080p.WEBRip)', 'lang': 'eng'}
        ]
        mock_mpv.__getitem__.side_effect = lambda k: 1 if k == 'sid' else None
        widget._mpv = mock_mpv

        popover = SubtitlePopover(player=widget)
        popover.refresh_tracks()

        # Find buttons in tracks box
        children = []
        child = popover._tracks_box.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()

        self.assertEqual(len(children), 2)  # "Off" and "English (1080p.WEBRip)"
        off_btn = children[0]
        track_btn = children[1]

        self.assertEqual(off_btn.get_label(), "Off")
        self.assertFalse(off_btn.get_active())
        self.assertTrue(track_btn.get_active())

    def test_sync_subtitle_with_reference_pure_python(self):
        import tempfile
        import os
        from showberry.services.subtitles import parse_subtitle_cues, write_srt_cues, format_srt_timestamp
        service = SubtitleService()

        with tempfile.TemporaryDirectory() as tmpdir:
            ref_path = os.path.join(tmpdir, 'ref.vtt')
            target_path = os.path.join(tmpdir, 'target_spa.srt')

            # Create a WebVTT reference file with MM:SS.mmm timestamps (like Vidy's built-in English track)
            ref_lines = ["WEBVTT\n"]
            target_cues = []
            # True offset: reference is +13.50s later than target
            true_offset = 13.50
            for i in range(40):
                r_start = 120.0 + i * 15.0
                r_end = r_start + 2.5
                r_mm = int(r_start) // 60
                r_ss = r_start - r_mm * 60
                re_mm = int(r_end) // 60
                re_ss = r_end - re_mm * 60
                ref_lines.append(f"{r_mm:02d}:{r_ss:06.3f} --> {re_mm:02d}:{re_ss:06.3f}\nReference line {i + 1}\n")
                target_cues.append((r_start - true_offset, r_end - true_offset, f"Línea en español {i + 1}"))

            with open(ref_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(ref_lines))
            write_srt_cues(target_cues, target_path)

            synced_path = service.sync_subtitle_with_reference(ref_path, target_path)
            self.assertIsNotNone(synced_path)
            self.assertTrue(synced_path.endswith('_synced.srt'))
            self.assertTrue(os.path.exists(synced_path))

            synced_cues = parse_subtitle_cues(open(synced_path, 'r', encoding='utf-8').read())
            self.assertEqual(len(synced_cues), 40)
            # First cue should now be aligned to ~120.0s (within 0.15s of reference)
            self.assertAlmostEqual(synced_cues[0][0], 120.0, delta=0.15)
            self.assertEqual(synced_cues[0][2], "Línea en español 1")

    def test_score_subtitle_release_penalizes_cd1_and_txt(self):
        from showberry.services.subtitles import score_subtitle_release
        cd1_sub = {
            'subtitleFileName': 'The_Shawshank_Redemption_(1994).CD1.aFLDp.srt',
            'fpsMilli': 23976,
        }
        txt_sub = {
            'subtitleFileName': 'THE SHAWSHANK REDEMPTION.txt',
            'fpsMilli': 23976,
        }
        full_sub = {
            'subtitleFileName': 'sawshank_redemption_esp.srt',
            'fpsMilli': 23980,
        }
        self.assertLess(score_subtitle_release(cd1_sub), -500)
        self.assertLess(score_subtitle_release(txt_sub), -500)
        self.assertGreater(score_subtitle_release(full_sub), 50)

    def test_no_duplicate_or_unnamed_tracks_in_popover(self):
        widget = MpvWidget()
        mock_mpv = MagicMock()
        mock_mpv.filename = "/video.mp4"
        # Simulate MPV having an unnamed Track 2 alongside duplicate Spanish tracks
        mock_mpv.track_list = [
            {'id': 1, 'type': 'sub', 'selected': False, 'title': '🇺🇸 English', 'lang': 'eng'},
            {'id': 2, 'type': 'sub', 'selected': False, 'title': 'Track 2', 'lang': ''},
            {'id': 3, 'type': 'sub', 'selected': False, 'title': '🇪🇸 Spanish', 'lang': 'spa'},
            {'id': 4, 'type': 'sub', 'selected': True, 'title': '🇪🇸 Spanish', 'lang': 'spa'},
        ]
        mock_mpv.__getitem__.side_effect = lambda k: 4 if k == 'sid' else None
        widget._mpv = mock_mpv

        popover = SubtitlePopover(player=widget)
        popover.refresh_tracks()

        labels = []
        child = popover._tracks_box.get_first_child()
        while child:
            labels.append(child.get_label())
            child = child.get_next_sibling()

        # Must only contain Off, English, and ONE Spanish (no Track 2, no duplicate Spanish)
        self.assertEqual(labels, ["Off", "🇺🇸 English", "🇪🇸 Spanish"])

    def test_vidlink_provider_subtitles_extraction(self):
        from showberry.providers.vidlink import VidLinkProvider
        from unittest.mock import patch, MagicMock
        provider = VidLinkProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'stream': {'playlist': 'https://filmboom.top/playlist.m3u8'},
            'captions': [
                {'url': 'https://filmboom.top/sub/en.vtt', 'language': 'en', 'label': 'English'},
                {'url': 'https://filmboom.top/sub/es.vtt', 'language': 'es', 'label': 'Spanish'}
            ]
        }
        with patch('requests.get', return_value=mock_resp):
            res = provider.get_stream_url(12345)
            self.assertIsNotNone(res)
            self.assertEqual(len(res.subtitles), 2)
            self.assertEqual(res.subtitles[0]['lang'], 'en')
            self.assertEqual(res.subtitles[0]['label'], 'English')
            self.assertEqual(res.subtitles[0]['referer'], 'https://filmboom.top/')

    def test_vidrift_provider_subtitles_extraction(self):
        from showberry.providers.vidrift import VidRiftProvider
        from unittest.mock import patch, MagicMock
        provider = VidRiftProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '''
        <html>
        <script>
        var embedMeta = {"selfhostUrl": "https://vidrift.com/video.m3u8"};
        var subtitleTracks = [
            {"code": "en", "label": "English", "url": "https://vidrift.com/en.vtt"},
            {"code": "fr", "label": "French", "url": "https://vidrift.com/fr.vtt"}
        ];
        </script>
        </html>
        '''
        with patch('requests.get', return_value=mock_resp):
            res = provider.get_stream_url(12345)
            self.assertIsNotNone(res)
            self.assertEqual(len(res.subtitles), 2)
            self.assertEqual(res.subtitles[0]['lang'], 'en')
            self.assertEqual(res.subtitles[0]['label'], 'English')

    def test_provider_subtitles_in_main_view(self):
        popover = SubtitlePopover()
        provider_subs = [
            {'url': 'https://moon.example/subs/spa.vtt', 'lang': 'spa', 'lang_name': 'Spanish', 'flag': '🇪🇸', 'label': '🇪🇸 Spanish'},
            {'url': 'https://moon.example/subs/fre.vtt', 'lang': 'fre', 'lang_name': 'French', 'flag': '🇫🇷', 'label': '🇫🇷 French'},
            {'url': 'https://moon.example/subs/hin.vtt', 'lang': 'hin', 'lang_name': 'Hindi', 'flag': '🇮🇳', 'label': '🇮🇳 Hindi'},
        ]
        popover.set_provider_subtitles(provider_subs)

        children = []
        child = popover._tracks_box.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()

        # Should contain "Off" (no symbol) + 3 clean language tracks (no "(Built-in)")
        self.assertEqual(len(children), 4)
        labels = [c.get_label() for c in children]
        self.assertIn("Off", labels)
        self.assertIn("🇪🇸 Spanish", labels)
        self.assertIn("🇫🇷 French", labels)
        self.assertIn("🇮🇳 Hindi", labels)
        for lbl in labels:
            self.assertNotIn("Built-in", lbl)
            self.assertNotIn("⊘", lbl)

    def test_builtin_track_selection_callback(self):
        selected_sub = None
        def _on_select(sub):
            nonlocal selected_sub
            selected_sub = sub

        popover = SubtitlePopover()
        provider_subs = [
            {'url': 'https://moon.example/subs/hin.vtt', 'lang': 'hin', 'lang_name': 'Hindi', 'flag': '🇮🇳', 'label': '🇮🇳 Hindi'},
        ]
        popover.set_provider_subtitles(provider_subs, on_select_builtin=_on_select)

        children = []
        child = popover._tracks_box.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()

        # Children: [0] Off, [1] Hindi
        hin_btn = children[1]
        hin_btn.set_active(True)
        self.assertIsNotNone(selected_sub)
        self.assertEqual(selected_sub['lang'], 'hin')

    def test_language_subtitles_in_main_view_and_selection(self):
        selected_ext = None
        def _on_select_ext(sub):
            nonlocal selected_ext
            selected_ext = sub

        popover = SubtitlePopover()
        ext_subs = [
            {'url': 'https://subs.org/spa.srt', 'lang': 'spa', 'lang_name': 'Spanish', 'flag': '🇪🇸'},
            {'url': 'https://subs.org/hin.srt', 'lang': 'hin', 'lang_name': 'Hindi', 'flag': '🇮🇳'},
        ]
        popover.set_language_subtitles(ext_subs, on_select_external=_on_select_ext)

        children = []
        child = popover._tracks_box.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()

        self.assertEqual(len(children), 3)  # Off, Spanish, Hindi
        labels = [c.get_label() for c in children]
        self.assertEqual(labels, ["Off", "🇪🇸 Spanish", "🇮🇳 Hindi"])

        # Click Hindi
        children[2].set_active(True)
        self.assertIsNotNone(selected_ext)
        self.assertEqual(selected_ext['lang'], 'hin')

    def test_torrent_disabled_inhibits_torrent_resolution(self):
        from showberry.services.settings import SettingsService
        from showberry.providers.torrent import TorrentProvider
        from showberry.providers.base import ProviderManager, get_all_providers

        orig_torrent = SettingsService().torrent_enabled
        SettingsService().torrent_enabled = False
        try:
            # Direct provider returns None
            tp = TorrentProvider()
            self.assertIsNone(tp.get_stream_url(12345))

            # Not included in provider lists
            providers = get_all_providers()
            self.assertFalse(any('torrent' in p.name.lower() for p in providers))
        finally:
            SettingsService().torrent_enabled = orig_torrent

    def test_language_mappings_for_gre_and_rum(self):
        from showberry.services.subtitles import LANG_NAMES, LANG_FLAGS
        self.assertEqual(LANG_NAMES.get('gre'), 'Greek')
        self.assertEqual(LANG_FLAGS.get('gre'), '🇬🇷')
        self.assertEqual(LANG_NAMES.get('rum'), 'Romanian')
        self.assertEqual(LANG_FLAGS.get('rum'), '🇷🇴')

    def test_popover_no_negative_space_and_stream_resolved_preserves_languages(self):
        from showberry.ui.player_page import PlayerPage
        from showberry.providers.base import StreamResult
        from unittest.mock import patch

        popover = SubtitlePopover()
        # Stack must not force vhomogeneous height across views (prevents bottom negative space)
        self.assertFalse(popover._stack.get_vhomogeneous())
        self.assertTrue(popover._stack.get_interpolate_size())

        pp = PlayerPage()
        pp._session_id = 10
        # Simulate OpenSubtitles finishing BEFORE _on_stream_resolved
        pp._opensubtitles_results = [
            {'url': 'https://subs.org/eng.srt', 'lang': 'eng', 'lang_name': 'English', 'flag': '🇺🇸', 'label': 'English'},
            {'url': 'https://subs.org/spa.srt', 'lang': 'spa', 'lang_name': 'Spanish', 'flag': '🇪🇸', 'label': 'Spanish'},
            {'url': 'https://subs.org/fre.srt', 'lang': 'fre', 'lang_name': 'French', 'flag': '🇫🇷', 'label': 'French'},
            {'url': 'https://subs.org/hin.srt', 'lang': 'hin', 'lang_name': 'Hindi', 'flag': '🇮🇳', 'label': 'Hindi'},
        ]
        pp._opensubtitles_done = True
        pp._sync_subtitle_popover_lists(10)

        # Now _on_stream_resolved runs with built-in English
        res = StreamResult(
            url='https://cdn.example/master.m3u8',
            provider_name='Vidy',
            subtitles=[{'url': 'https://cdn.example/eng.vtt', 'lang': 'eng', 'label': 'English'}]
        )
        with patch.object(pp._mpv_widget, 'play'), patch('threading.Thread'):
            pp._on_stream_resolved(res, [], session_id=10)

        # Verify start_update_timer did NOT wipe out the language options!
        sub_pop = pp._controls._sub_popover
        labels = []
        child = sub_pop._tracks_box.get_first_child()
        while child:
            labels.append(child.get_label())
            child = child.get_next_sibling()

        self.assertEqual(labels, ["Off", "🇺🇸 English", "🇪🇸 Spanish", "🇫🇷 French", "🇮🇳 Hindi"])
        self.assertEqual(len(sub_pop._available_subtitles), 5)
        pp._controls.stop_update_timer()
        pp._stop_progress_timer()


