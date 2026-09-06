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

    def test_provider_ranking_order(self):
        providers = get_all_providers()
        names = [p.name for p in providers]
        expected_ranking = [
            'VidEasy',
            'Vidy',
            'VidKing',
            'VidLink',
            'VixSrc',
            'VidFast',
            'VidZee',
            'CineSrc',
            'SuperEmbed',
            'VidRift',
            'VidNest',
            'PrimeWire',
        ]
        for i, exp in enumerate(expected_ranking):
            self.assertEqual(names[i], exp, f"Expected {exp} at index {i}, got {names[i]}")

    def test_vidy_cipher_decryption(self):
        from kinema.providers.vidy import _decrypt_vidy
        # Known test vector from Node.js/Python cross-validation
        # Seed: 'test_seed_123', media_id: 550
        # Keystream begins with [61, 173, 199, 215, 139, 235, 236, 197, 189, 186, 125, 65, 102, 102, 226, 54]
        # Magic: [109, 118, 109, 49]
        # Payload: '{"test":true}'
        magic = [109, 118, 109, 49]
        payload = b'{"test":true}'
        plain = bytes(magic) + payload
        import base64
        from kinema.providers.vidy import _imul, _p_fn, _g_fn
        # Create encrypted ciphertext using the cipher keystream
        seed = 'test_seed_123'
        media_id = 550
        t_fnv = 2166136261
        for ch in seed:
            t_fnv = _imul(t_fnv ^ ord(ch), 16777619)
        fnv_res = _p_fn(t_fnv)
        n = _p_fn(fnv_res ^ _p_fn((media_id & 0xFFFFFFFF) ^ 2654435769))
        a = {}
        for e in range(8):
            t = n % 61
            n = _g_fn((n + 2654435769) & 0xFFFFFFFF, 7 + (7 & e))
            a[t] = (n ^ _p_fn(n)) & 0xFFFFFFFF
            n = _p_fn((n + t) & 0xFFFFFFFF)
        state = {'S': a, 'acc': _p_fn(2779096485 ^ n)}
        raw_ct = bytearray(plain)
        s_cnt = 0
        e_idx = 0
        while e_idx < len(raw_ct):
            r = state['S']
            s = state['acc']
            o = s % 61
            i = -1 if (o in r) else 0
            d = r.get(o, 0)
            n_term = (d ^ _imul(2654435769, s_cnt + 1)) & 0xFFFFFFFF
            s_cnt += 1
            a_term = s
            l_val = ((a_term ^ n_term) | (a_term & n_term & i)) & 0xFFFFFFFF
            term1 = _g_fn((l_val + s) & 0xFFFFFFFF, 31 & o)
            term2 = _g_fn(s, 31 & _imul(o, 7))
            l_val = (term1 ^ term2) & 0xFFFFFFFF
            s = _p_fn((l_val + 2654435769) & 0xFFFFFFFF)
            r[o] = s
            state['acc'] = s
            t_val = s
            raw_ct[e_idx] ^= (t_val & 0xFF)
            e_idx += 1
            if e_idx < len(raw_ct):
                raw_ct[e_idx] ^= ((t_val >> 8) & 0xFF)
                e_idx += 1
            if e_idx < len(raw_ct):
                raw_ct[e_idx] ^= ((t_val >> 16) & 0xFF)
                e_idx += 1
            if e_idx < len(raw_ct):
                raw_ct[e_idx] ^= ((t_val >> 24) & 0xFF)
                e_idx += 1
        ct_b64 = base64.b64encode(raw_ct).decode('ascii')
        decrypted = _decrypt_vidy(ct_b64, seed, media_id)
        self.assertEqual(decrypted, '{"test":true}')

    def test_vidrift_provider_properties(self):
        from kinema.providers.vidrift import VidRiftProvider
        p = VidRiftProvider()
        self.assertEqual(p.name, 'VidRift')
        self.assertEqual(p.base_url, 'https://embed.vidrift.in')

    def test_vidking_provider_properties(self):
        from kinema.providers.vidking import VidKingProvider
        p = VidKingProvider()
        self.assertEqual(p.name, 'VidKing')
        self.assertEqual(p.base_url, 'https://vidking.net')


if __name__ == '__main__':
    unittest.main()
