"""Main application window for Kinema using Komikku-style Adw.NavigationView."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio

from kinema.ui.library_page import LibraryPage
from kinema.ui.movies_page import MoviesPage
from kinema.ui.series_page import SeriesPage
from kinema.ui.movie_page import MoviePage
from kinema.ui.settings_page import SettingsPage
from kinema.ui.player_page import PlayerPage


class KinemaWindow(Adw.ApplicationWindow):
    """The main application window using Adw.NavigationView."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.set_title('Kinema')
        self.set_default_size(1200, 720)

        self._setup_ui()
        self._setup_actions()

        self.connect('close-request', self._on_close_request)

    @property
    def _watchlist_page(self):
        return self._library_page

    @property
    def _browse_page(self):
        return self._movies_page

    def _setup_ui(self):
        # Toast overlay for notifications
        self._toast_overlay = Adw.ToastOverlay()

        # Root Navigation View (Komikku pattern)
        self._nav_view = Adw.NavigationView()
        self._toast_overlay.set_child(self._nav_view)

        # 1. Main navigation page (tag="main")
        main_page = self._create_main_page()
        self._nav_view.push(main_page)

        # 2. Player page (reusable Adw.NavigationPage, tag="player")
        self._player_page = PlayerPage()
        self._player_page.connect('close-player', self._on_close_player)
        self._player_page.connect('stream-failed', self._on_stream_failed)

        self.set_content(self._toast_overlay)

    def _create_main_page(self) -> Adw.NavigationPage:
        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()

        # Center ViewSwitcher linked to ViewStack
        self._view_stack = Adw.ViewStack()

        # 1. Library Page (Home Tab: Continue Watching + Watchlist)
        self._library_page = LibraryPage()
        self._library_page.connect('movie-selected', self._on_movie_selected)
        self._library_page.connect('play-movie', self._on_play_movie)
        p_library = self._view_stack.add_titled(self._library_page, 'library', 'Library')
        p_library.set_icon_name('emblem-favorite-symbolic')

        # 2. Movies Page (Trending/Popular Movies + integrated search)
        self._movies_page = MoviesPage()
        self._movies_page.connect('movie-selected', self._on_movie_selected)
        self._movies_page.connect('play-movie', self._on_play_movie)
        p_movies = self._view_stack.add_titled(self._movies_page, 'movies', 'Movies')
        p_movies.set_icon_name('media-optical-symbolic')

        # 3. Series Page (Trending/Popular TV Series + integrated search)
        self._series_page = SeriesPage()
        self._series_page.connect('movie-selected', self._on_movie_selected)
        self._series_page.connect('play-movie', self._on_play_movie)
        p_series = self._view_stack.add_titled(self._series_page, 'series', 'Series')
        p_series.set_icon_name('tv-symbolic')

        self._switcher = Adw.ViewSwitcher()
        self._switcher.set_stack(self._view_stack)
        self._switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header_bar.set_title_widget(self._switcher)

        # Bottom ViewSwitcherBar for narrow/mobile screens
        self._switcher_bar = Adw.ViewSwitcherBar()
        self._switcher_bar.set_stack(self._view_stack)
        self._switcher_bar.set_reveal(False)
        toolbar_view.add_bottom_bar(self._switcher_bar)

        # Breakpoint for narrow/mobile screens (< 600px)
        mobile_bp = Adw.Breakpoint.new(Adw.breakpoint_condition_parse("max-width: 600px"))
        mobile_bp.add_setter(self._switcher, "visible", False)
        mobile_bp.add_setter(self._switcher_bar, "reveal", True)
        self.add_breakpoint(mobile_bp)

        # Hamburger Menu Button on top-right
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name('open-menu-symbolic')
        menu_button.set_tooltip_text("Main Menu")

        menu = Gio.Menu()
        menu.append("Preferences", "win.preferences")
        menu.append("Clear Watch History", "win.clear_history")
        menu.append("About Kinema", "win.about")
        menu_button.set_menu_model(menu)
        header_bar.pack_end(menu_button)

        toolbar_view.add_top_bar(header_bar)
        toolbar_view.set_content(self._view_stack)

        main_page = Adw.NavigationPage.new(toolbar_view, 'Kinema')
        main_page.set_tag('main')
        return main_page

    def _on_movie_selected(self, page, movie_data):
        """Push movie detail page onto navigation view."""
        movie_page = MoviePage(movie=movie_data)
        movie_page.connect('play-movie', self._on_play_movie)
        movie_page.connect('movie-selected', self._on_movie_selected)
        self._nav_view.push(movie_page)

    def _on_play_movie(self, page, stream_data):
        """Start playback and push player page (occupies 100% of the window)."""
        self._player_page.load_stream(stream_data)
        visible = self._nav_view.get_visible_page()
        if not visible or visible.get_tag() != 'player':
            self._nav_view.push(self._player_page)

    def _on_close_player(self, page):
        """Safely exit player mode and return to previous view."""
        if self.is_fullscreen():
            self.unfullscreen()

        try:
            self.set_cursor_from_name('default')
        except Exception:
            pass

        visible = self._nav_view.get_visible_page()
        if visible and visible.get_tag() == 'player':
            self._nav_view.pop()

        # Refresh library page
        if hasattr(self, '_library_page'):
            self._library_page.refresh()

    def _on_stream_failed(self, player, error_msg):
        self.show_toast(error_msg, timeout=5)
        visible = self._nav_view.get_visible_page()
        if visible and visible.get_tag() == 'player':
            self._nav_view.pop()

    def show_toast(self, message: str, timeout: int = 3, button_label: str = None, action_name: str = None):
        """Display non-blocking toast notification."""
        toast = Adw.Toast.new(message)
        toast.set_timeout(timeout)
        if button_label and action_name:
            toast.set_button_label(button_label)
            toast.set_action_name(action_name)
        self._toast_overlay.add_toast(toast)

    def _setup_actions(self):
        back_action = Gio.SimpleAction.new('back', None)
        back_action.connect('activate', self._on_back_action)
        self.add_action(back_action)

        fullscreen_action = Gio.SimpleAction.new('fullscreen', None)
        fullscreen_action.connect('activate', self._on_fullscreen_action)
        self.add_action(fullscreen_action)

        pref_action = Gio.SimpleAction.new('preferences', None)
        pref_action.connect('activate', self._on_preferences_action)
        self.add_action(pref_action)

        clear_action = Gio.SimpleAction.new('clear_history', None)
        clear_action.connect('activate', self._on_clear_history_action)
        self.add_action(clear_action)

        about_action = Gio.SimpleAction.new('about', None)
        about_action.connect('activate', self._on_about_action)
        self.add_action(about_action)

    def _on_preferences_action(self, action, param):
        """Open settings page within the navigation view."""
        toolbar = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        toolbar.add_top_bar(header_bar)
        settings_box = SettingsPage()
        toolbar.set_content(settings_box)
        page = Adw.NavigationPage.new(toolbar, 'Preferences')
        page.set_tag('preferences')
        self._nav_view.push(page)

    def _on_clear_history_action(self, action, param):
        """Clear watch history and refresh Library."""
        from kinema.services.database import DatabaseService
        db = DatabaseService()
        with db._get_connection() as conn:
            conn.execute("DELETE FROM watch_history")
            conn.commit()
        if hasattr(self, '_library_page'):
            self._library_page.refresh()
        self.show_toast("Watch history cleared", timeout=3)

    def _on_about_action(self, action, param):
        """Show About Kinema dialog."""
        dialog = Adw.AboutDialog.new()
        dialog.set_application_name("Kinema")
        dialog.set_version("0.1.0")
        dialog.set_developer_name("Kinema Contributors")
        dialog.set_comments("An elegant, modern movie and TV series streaming application for GNOME.")
        dialog.set_website("https://codeberg.org/valos/Komikku")
        dialog.set_license_type(Gtk.License.GPL_3_0)
        dialog.present(self)

    def _on_back_action(self, action, param):
        visible = self._nav_view.get_visible_page()
        if visible and visible.get_tag() == 'player':
            self._player_page._on_close(None)
        elif visible and visible.get_tag() != 'main':
            self._nav_view.pop()

    def _on_fullscreen_action(self, action, param):
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    def _on_close_request(self, window):
        try:
            self._player_page._on_close(None)
        except Exception:
            pass
        try:
            app = self.get_application()
            if app:
                settings = app.get_settings()
                width, height = self.get_default_size()
                settings.set_int('window-width', width)
                settings.set_int('window-height', height)
                settings.set_boolean('is-maximized', self.is_maximized())
        except Exception:
            pass
        return False
