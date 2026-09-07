"""TMDB API client for movie metadata."""

import os
import time
import requests
from gi.repository import Gio, GLib


TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
DEFAULT_TMDB_API_KEY = "8476a7ab80ad76f0936744df0430e67c"


class TMDBClient:
    """Client for The Movie Database API."""

    def __init__(self, api_key=None):
        self._api_key = api_key or os.environ.get('TMDB_API_KEY') or DEFAULT_TMDB_API_KEY
        self._session = requests.Session()
        self._session.headers.update({
            'Accept': 'application/json',
        })
        self._details_cache = {}

    def set_api_key(self, api_key):
        self._api_key = api_key or os.environ.get('TMDB_API_KEY') or DEFAULT_TMDB_API_KEY

    def _get_headers(self):
        return {'Authorization': f'Bearer {self._api_key}'}

    def _request(self, endpoint, params=None):
        if not self._api_key:
            return None

        url = f"{TMDB_BASE_URL}{endpoint}"
        query_params = dict(params or {})
        headers = {'Accept': 'application/json'}

        # TMDB v3 keys are 32 hex chars; v4 tokens are longer JWT-like strings
        if len(self._api_key.strip()) == 32:
            query_params['api_key'] = self._api_key.strip()
        else:
            headers['Authorization'] = f'Bearer {self._api_key.strip()}'

        for attempt in range(2):
            try:
                response = self._session.get(
                    url,
                    headers=headers,
                    params=query_params,
                    timeout=10,
                )
                if response.status_code == 429 and attempt == 0:
                    time.sleep(1.0)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.RequestException:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                return None
        return None

    def search_movies(self, query, page=1):
        """Search for movies by title."""
        data = self._request('/search/movie', {
            'query': query,
            'page': page,
            'include_adult': False,
        })
        if data is None:
            return []
        return [self._parse_movie(m) for m in data.get('results', [])]

    def search_tv(self, query, page=1):
        """Search for TV series by title."""
        data = self._request('/search/tv', {
            'query': query,
            'page': page,
            'include_adult': False,
        })
        if data is None:
            return []
        return [self._parse_tv(m) for m in data.get('results', [])]

    def search_multi(self, query, page=1):
        """Search for both movies and TV series."""
        data = self._request('/search/multi', {
            'query': query,
            'page': page,
            'include_adult': False,
        })
        if data is None:
            return []
        items = []
        for item in data.get('results', []):
            mtype = item.get('media_type')
            if mtype == 'movie':
                items.append(self._parse_movie(item))
            elif mtype == 'tv':
                items.append(self._parse_tv(item))
        return items

    def get_trending(self, page=1):
        """Get trending movies for the week."""
        data = self._request('/trending/movie/week', {'page': page})
        if data is None:
            return []
        return [self._parse_movie(m) for m in data.get('results', [])]

    def get_trending_tv(self, page=1):
        """Get trending TV shows for the week."""
        data = self._request('/trending/tv/week', {'page': page})
        if data is None:
            return []
        return [self._parse_tv(m) for m in data.get('results', [])]

    def get_popular(self, page=1):
        """Get popular movies."""
        data = self._request('/movie/popular', {'page': page})
        if data is None:
            return []
        return [self._parse_movie(m) for m in data.get('results', [])]

    def get_popular_tv(self, page=1):
        """Get popular TV series."""
        data = self._request('/tv/popular', {'page': page})
        if data is None:
            return []
        return [self._parse_tv(m) for m in data.get('results', [])]

    def get_top_rated(self, page=1):
        """Get top rated movies."""
        data = self._request('/movie/top_rated', {'page': page})
        if data is None:
            return []
        return [self._parse_movie(m) for m in data.get('results', [])]

    def get_now_playing(self, page=1):
        """Get movies currently in theaters."""
        data = self._request('/movie/now_playing', {'page': page})
        if data is None:
            return []
        return [self._parse_movie(m) for m in data.get('results', [])]

    def get_movie_details(self, movie_id):
        """Get detailed information about a movie including directors, cast, and recommendations."""
        cache_key = f"movie_{movie_id}"
        if cache_key in self._details_cache:
            return self._details_cache[cache_key]

        data = self._request(f'/movie/{movie_id}', {'append_to_response': 'external_ids,credits,recommendations'})
        if data is None:
            return None
        parsed = self._parse_movie(data, detailed=True)
        ext_ids = data.get('external_ids') or {}
        parsed['imdb_id'] = data.get('imdb_id') or ext_ids.get('imdb_id')

        # Parse credits (directors & top cast)
        credits_data = data.get('credits') or {}
        cast = []
        for c in credits_data.get('cast', [])[:12]:
            cast.append({
                'name': c.get('name', ''),
                'character': c.get('character', ''),
                'profile_path': c.get('profile_path'),
            })
        directors = [
            c['name'] for c in credits_data.get('crew', [])
            if c.get('job') == 'Director'
        ]
        parsed['cast'] = cast
        parsed['directors'] = directors

        # Parse recommendations
        recs = data.get('recommendations', {}).get('results', [])
        parsed['recommendations'] = [self._parse_movie(m) for m in recs[:12]]

        self._details_cache[cache_key] = parsed
        return parsed

    def get_tv_details(self, tv_id):
        """Get detailed information about a TV show including seasons, cast, and recommendations."""
        cache_key = f"tv_{tv_id}"
        if cache_key in self._details_cache:
            return self._details_cache[cache_key]

        data = self._request(f'/tv/{tv_id}', {'append_to_response': 'external_ids,credits,recommendations'})
        if data is None:
            return None
        parsed = self._parse_tv(data, detailed=True)
        ext_ids = data.get('external_ids') or {}
        parsed['imdb_id'] = ext_ids.get('imdb_id')

        # Parse credits (top cast)
        credits_data = data.get('credits') or {}
        cast = []
        for c in credits_data.get('cast', [])[:12]:
            cast.append({
                'name': c.get('name', ''),
                'character': c.get('character', ''),
                'profile_path': c.get('profile_path'),
            })
        parsed['cast'] = cast

        # Parse recommendations
        recs = data.get('recommendations', {}).get('results', [])
        parsed['recommendations'] = [self._parse_tv(m) for m in recs[:12]]

        self._details_cache[cache_key] = parsed
        return parsed

    def get_imdb_id(self, tmdb_id: int, is_tv: bool = False):
        """Get IMDB ID for a movie or TV show."""
        endpoint = f'/tv/{tmdb_id}/external_ids' if is_tv else f'/movie/{tmdb_id}/external_ids'
        data = self._request(endpoint)
        if data:
            return data.get('imdb_id')
        return None

    def get_tv_season(self, tv_id, season_number):
        """Get episodes for a specific TV show season."""
        data = self._request(f'/tv/{tv_id}/season/{season_number}')
        if data is None:
            return []
        episodes = []
        for ep in data.get('episodes', []):
            ep_item = {
                'id': ep.get('id'),
                'episode_number': ep.get('episode_number'),
                'season_number': ep.get('season_number'),
                'name': ep.get('name', f'Episode {ep.get("episode_number")}'),
                'overview': ep.get('overview', ''),
                'still_path': ep.get('still_path'),
                'still_url': f"{TMDB_IMAGE_BASE}/w300{ep.get('still_path')}" if ep.get('still_path') else None,
                'vote_average': ep.get('vote_average', 0),
                'runtime': ep.get('runtime'),
            }
            episodes.append(ep_item)
        return episodes

    def get_movie_credits(self, movie_id):
        """Get cast and crew for a movie."""
        data = self._request(f'/movie/{movie_id}/credits')
        if data is None:
            return {'cast': [], 'crew': []}

        cast = []
        for c in data.get('cast', [])[:10]:
            cast.append({
                'name': c.get('name', ''),
                'character': c.get('character', ''),
            })

        directors = [
            c['name'] for c in data.get('crew', [])
            if c.get('job') == 'Director'
        ]

        return {'cast': cast, 'directors': directors}

    def _parse_movie(self, data, detailed=False):
        """Parse movie data from TMDB response."""
        movie = {
            'id': data.get('id'),
            'media_type': 'movie',
            'title': data.get('title', ''),
            'original_title': data.get('original_title', ''),
            'overview': data.get('overview', ''),
            'release_date': data.get('release_date', ''),
            'vote_average': data.get('vote_average', 0),
            'vote_count': data.get('vote_count', 0),
            'poster_path': data.get('poster_path'),
            'backdrop_path': data.get('backdrop_path'),
            'genre_ids': data.get('genre_ids', []),
            'genre_names': [g['name'] for g in data.get('genres', [])],
            'runtime': data.get('runtime'),
            'status': data.get('status', ''),
            'tagline': data.get('tagline', ''),
            'imdb_id': data.get('imdb_id') or (data.get('external_ids') or {}).get('imdb_id'),
        }

        # Build image URLs
        if movie['poster_path']:
            movie['poster_url'] = f"{TMDB_IMAGE_BASE}/w500{movie['poster_path']}"
            movie['poster_url_small'] = f"{TMDB_IMAGE_BASE}/w342{movie['poster_path']}"
        else:
            movie['poster_url'] = None
            movie['poster_url_small'] = None

        if movie['backdrop_path']:
            movie['backdrop_url'] = f"{TMDB_IMAGE_BASE}/w1280{movie['backdrop_path']}"
        else:
            movie['backdrop_url'] = None

        return movie

    def _parse_tv(self, data, detailed=False):
        """Parse TV show data from TMDB response."""
        show = {
            'id': data.get('id'),
            'media_type': 'tv',
            'title': data.get('name', ''),
            'original_title': data.get('original_name', ''),
            'overview': data.get('overview', ''),
            'release_date': data.get('first_air_date', ''),
            'vote_average': data.get('vote_average', 0),
            'vote_count': data.get('vote_count', 0),
            'poster_path': data.get('poster_path'),
            'backdrop_path': data.get('backdrop_path'),
            'genre_ids': data.get('genre_ids', []),
            'genre_names': [g['name'] for g in data.get('genres', [])],
            'status': data.get('status', ''),
            'tagline': data.get('tagline', ''),
            'number_of_seasons': data.get('number_of_seasons', 1),
            'number_of_episodes': data.get('number_of_episodes', 1),
            'seasons': data.get('seasons', []),
            'imdb_id': (data.get('external_ids') or {}).get('imdb_id'),
            'network': (data.get('networks') or [{}])[-1].get('name', ''),
            'runtime': (data.get('episode_run_time') or [None])[0] if data.get('episode_run_time') else None,
        }

        if show['poster_path']:
            show['poster_url'] = f"{TMDB_IMAGE_BASE}/w500{show['poster_path']}"
            show['poster_url_small'] = f"{TMDB_IMAGE_BASE}/w342{show['poster_path']}"
        else:
            show['poster_url'] = None
            show['poster_url_small'] = None

        if show['backdrop_path']:
            show['backdrop_url'] = f"{TMDB_IMAGE_BASE}/w1280{show['backdrop_path']}"
        else:
            show['backdrop_url'] = None

        return show




def genre_id_to_name(genre_id):
    """Convert TMDB genre ID to name."""
    genres = {
        28: 'Action', 12: 'Adventure', 16: 'Animation', 35: 'Comedy',
        80: 'Crime', 99: 'Documentary', 18: 'Drama', 10751: 'Family',
        14: 'Fantasy', 36: 'History', 27: 'Horror', 10402: 'Music',
        9648: 'Mystery', 10749: 'Romance', 878: 'Sci-Fi', 10770: 'TV Movie',
        53: 'Thriller', 10752: 'War', 37: 'Western',
    }
    return genres.get(genre_id, 'Unknown')
