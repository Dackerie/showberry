"""Tests for streaming providers and ProviderManager."""

import unittest
from kinema.providers import get_all_providers, StreamResult, ProviderManager


class TestProviders(unittest.TestCase):

    def test_provider_registration(self):
        providers = get_all_providers()
        self.assertGreater(len(providers), 5)
        names = [p.name for p in providers]
        self.assertIn('VidEasy', names)
        self.assertIn('VidLink', names)
        self.assertIn('VidFast', names)
        self.assertIn('VidZee', names)
        self.assertIn('PrimeWire', names)
        self.assertIn('Torrent (P2P)', names)

    def test_stream_result_properties(self):
        sr = StreamResult(
            url='https://example.com/video.mp4',
            quality='1080p',
            format='mp4',
            referer='https://example.com',
            subtitles=[{'lang': 'en', 'url': 'https://example.com/sub.srt'}]
        )
        self.assertEqual(sr['url'], 'https://example.com/video.mp4')
        self.assertEqual(sr.get('quality'), '1080p')
        self.assertEqual(sr.get('nonexistent', 'default'), 'default')

    def test_provider_manager_lookup(self):
        vl = ProviderManager.get_provider_by_name('VidLink')
        self.assertIsNotNone(vl)
        self.assertEqual(vl.name, 'VidLink')

        nonexistent = ProviderManager.get_provider_by_name('FakeProvider')
        self.assertIsNone(nonexistent)

    def test_videasy_cipher_structure(self):
        from kinema.providers.videasy import _init_state, _gen_keystream
        state = _init_state('test_seed_123', 278)
        self.assertIn('S', state)
        self.assertIn('acc', state)
        self.assertIsInstance(state['acc'], int)

        ks = _gen_keystream(state, 16)
        self.assertEqual(len(ks), 16)


if __name__ == '__main__':
    unittest.main()
