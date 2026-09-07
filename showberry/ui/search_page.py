"""Search page - search for movies."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, GObject

from showberry.services.tmdb import TMDBClient
from showberry.ui.browse_page import MovieCard


class SearchPage(Gtk.Box):
    """Search page with search bar and results grid."""

    __gsignals__ = {
        'movie-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._tmdb = TMDBClient()
        self._search_timeout = None
        self._setup_ui()

    def _setup_ui(self):
        # Header with search bar
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        header.set_margin_top(12)
        header.set_margin_bottom(12)
        header.set_margin_start(12)
        header.set_margin_end(12)

        # Search entry
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text('Search movies...')
        self._search_entry.connect('search-changed', self._on_search_changed)
        self._search_entry.connect('activate', self._on_search_activate)
        header.append(self._search_entry)

        self.append(header)

        # Separator
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Content area
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.set_vexpand(True)

        # Search results
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_vexpand(True)
        self._scroll.set_visible(False)

        self._clamp = Adw.Clamp()
        self._clamp.set_maximum_size(1400)
        self._clamp.set_tightening_threshold(800)

        # Results grid
        self._results_flow = Gtk.FlowBox()
        self._results_flow.set_homogeneous(True)
        self._results_flow.set_column_spacing(12)
        self._results_flow.set_row_spacing(12)
        self._results_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self._results_flow.set_margin_start(12)
        self._results_flow.set_margin_end(12)
        self._results_flow.set_margin_top(12)
        self._results_flow.set_margin_bottom(12)

        self._clamp.set_child(self._results_flow)
        self._scroll.set_child(self._clamp)
        content_box.append(self._scroll)

        # Loading spinner
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(48, 48)
        self._spinner.set_halign(Gtk.Align.CENTER)
        self._spinner.set_valign(Gtk.Align.CENTER)
        self._spinner.set_vexpand(True)
        self._spinner.set_visible(False)
        content_box.append(self._spinner)

        # Empty state
        self._empty_state = Adw.StatusPage()
        self._empty_state.set_icon_name('edit-find-symbolic')
        self._empty_state.set_title('Search Showberry')
        self._empty_state.set_description('Search for movies and TV series to watch')
        self._empty_state.set_vexpand(True)
        self._empty_state.set_visible(True)
        content_box.append(self._empty_state)

        # No results state
        self._no_results = Adw.StatusPage()
        self._no_results.set_icon_name('system-search-symbolic')
        self._no_results.set_title('No Results Found')
        self._no_results.set_description('Try searching with different keywords')
        self._no_results.set_vexpand(True)
        self._no_results.set_visible(False)
        content_box.append(self._no_results)

        self.append(content_box)

    def _on_search_changed(self, entry):
        """Handle search text changes with debouncing."""
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
        self._search_timeout = GLib.timeout_add(300, self._do_search)

    def _on_search_activate(self, entry):
        """Handle Enter key press."""
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
        self._do_search()

    def _do_search(self):
        """Perform the search."""
        self._search_timeout = None
        query = self._search_entry.get_text().strip()

        if not query:
            self._show_empty_state()
            return False

        self._show_loading()

        import threading
        threading.Thread(target=self._perform_search, args=(query,), daemon=True).start()
        return False

    def _perform_search(self, query):
        """Actually perform the search in background worker thread."""
        from showberry.services.settings import SettingsService
        settings = SettingsService()
        api_key = settings.tmdb_api_key

        self._tmdb.set_api_key(api_key)
        results = self._tmdb.search_multi(query)
        GLib.idle_add(self._display_search_results, results)

    def _display_search_results(self, results):
        """Render results on UI main thread."""
        while True:
            child = self._results_flow.get_first_child()
            if child is None:
                break
            self._results_flow.remove(child)

        if not results:
            self._show_no_results()
        else:
            self._show_results(results)


    def _show_loading(self):
        self._scroll.set_visible(False)
        self._empty_state.set_visible(False)
        self._no_results.set_visible(False)
        self._spinner.set_visible(True)
        self._spinner.start()

    def _show_empty_state(self):
        self._spinner.stop()
        self._spinner.set_visible(False)
        self._scroll.set_visible(False)
        self._no_results.set_visible(False)
        self._empty_state.set_visible(True)

    def _show_no_results(self):
        self._spinner.stop()
        self._spinner.set_visible(False)
        self._scroll.set_visible(False)
        self._empty_state.set_visible(False)
        self._no_results.set_visible(True)

    def _show_results(self, results):
        self._spinner.stop()
        self._spinner.set_visible(False)
        self._empty_state.set_visible(False)
        self._no_results.set_visible(False)
        self._scroll.set_visible(True)

        for movie in results:
            card = MovieCard(movie)
            card.connect('clicked-movie', self._on_movie_clicked)
            self._results_flow.append(card)

    def _show_error(self, message):
        self._spinner.stop()
        self._spinner.set_visible(False)
        self._scroll.set_visible(False)
        self._empty_state.set_visible(False)
        self._no_results.set_description(message)
        self._no_results.set_visible(True)

    def _on_movie_clicked(self, card, movie_data):
        self.emit('movie-selected', movie_data)
