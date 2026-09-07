"""Tests for SubtitleService."""

import unittest
from showberry.services.subtitles import SubtitleService


class TestSubtitleService(unittest.TestCase):

    def setUp(self):
        self.service = SubtitleService()

    def test_get_subtitles(self):
        # Fight club IMDB ID
        subs = self.service.get_subtitles("tt0137523")
        self.assertIsInstance(subs, list)
        self.assertGreater(len(subs), 0)
        first = subs[0]
        self.assertIn('url', first)
        self.assertIn('lang', first)
        self.assertIn('label', first)

    def test_invalid_imdb_id(self):
        subs = self.service.get_subtitles("invalid_id")
        self.assertEqual(subs, [])


if __name__ == '__main__':
    unittest.main()
