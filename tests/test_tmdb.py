"""Tests for TMDBClient."""

import unittest
from kinema.services.tmdb import TMDBClient


class TestTMDBClient(unittest.TestCase):

    def setUp(self):
        self.client = TMDBClient()

    def test_trending(self):
        trending = self.client.get_trending()
        self.assertIsInstance(trending, list)
        self.assertGreater(len(trending), 0)
        self.assertIn('title', trending[0])
        self.assertIn('id', trending[0])

    def test_movie_details_with_imdb(self):
        details = self.client.get_movie_details(550)
        self.assertIsNotNone(details)
        self.assertEqual(details['id'], 550)
        self.assertEqual(details.get('imdb_id'), 'tt0137523')

    def test_search_multi(self):
        results = self.client.search_multi('Breaking Bad')
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)


if __name__ == '__main__':
    unittest.main()
