"""Main application window for Showberry using Komikku-style Adw.NavigationView."""

import time
import warnings
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio, GLib, Gdk

from showberry.ui.library_page import LibraryPage
from showberry.ui.movies_page import MoviesPage
from showberry.ui.series_page import SeriesPage
from showberry.ui.movie_page import MoviePage
from showberry.ui.person_page import PersonPage
from showberry.ui.settings_page import SettingsPage
from showberry.ui.player_page import PlayerPage


class ShowberryWindow(Adw.ApplicationWindow):
    """The main application window using Adw.NavigationView."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.set_title('Showberry')
        self.set_default_size(1200, 720)
        self._last_tab_cycle_time = 0.0
        self._pending_tab_focus_id = None

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
        self._nav_view.connect('notify::visible-page', self._on_nav_page_changed)
        self._toast_overlay.set_child(self._nav_view)

        # Global key controller (e.g. quick search via '/')
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect('key-pressed', self._on_window_key_pressed)
        self.add_controller(key_ctrl)

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
        self._library_page.connect('focus-tabs', lambda p: self.focus_tabs())
        p_library = self._view_stack.add_titled(self._library_page, 'library', 'Library')
        p_library.set_icon_name('emblem-favorite-symbolic')
        self._view_stack.connect(
            'notify::visible-child-name',
            lambda s, p: self._library_page.schedule_refresh() if s.get_visible_child_name() == 'library' and hasattr(self, '_library_page') else None
        )

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

        switcher_key = Gtk.EventControllerKey.new()
        switcher_key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        switcher_key.connect('key-pressed', self._on_switcher_key_pressed)
        self._switcher.add_controller(switcher_key)

        # Bottom ViewSwitcherBar for narrow/mobile screens
        self._switcher_bar = Adw.ViewSwitcherBar()
        self._switcher_bar.set_stack(self._view_stack)
        self._switcher_bar.set_reveal(False)
        toolbar_view.add_bottom_bar(self._switcher_bar)

        switcher_bar_key = Gtk.EventControllerKey.new()
        switcher_bar_key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        switcher_bar_key.connect('key-pressed', self._on_switcher_key_pressed)
        self._switcher_bar.add_controller(switcher_bar_key)

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
        menu.append("Keyboard Shortcuts", "win.shortcuts")
        menu.append("Clear Watch History", "win.clear_history")
        menu.append("About Showberry", "win.about")
        menu_button.set_menu_model(menu)
        header_bar.pack_end(menu_button)

        toolbar_view.add_top_bar(header_bar)
        toolbar_view.set_content(self._view_stack)

        main_page = Adw.NavigationPage.new(toolbar_view, 'Showberry')
        main_page.set_tag('main')
        return main_page

    def _on_switcher_key_pressed(self, controller, keyval, keycode, state):
        if keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            self.focus_active_page()
            return True
        return False

    def focus_tabs(self) -> bool:
        """Focus the active tab in the ViewSwitcher."""
        switcher = self._switcher if self._switcher.get_visible() else self._switcher_bar
        child = switcher.get_first_child()
        active_btn = None
        first_btn = child
        while child:
            if hasattr(child, 'get_property') and child.get_property('active'):
                active_btn = child
                break
            child = child.get_next_sibling()
        target = active_btn or first_btn
        if target and hasattr(target, 'grab_focus'):
            target.grab_focus()
            return True
        return False

    def focus_active_page(self) -> bool:
        """Focus the primary entry element in the active page."""
        curr = self._view_stack.get_visible_child_name()
        if curr == 'library' and hasattr(self, '_library_page'):
            self._library_page.focus_first()
        elif curr == 'movies' and hasattr(self, '_movies_page'):
            self._movies_page._search_entry.grab_focus()
        elif curr == 'series' and hasattr(self, '_series_page'):
            self._series_page._search_entry.grab_focus()
        return False

    def _on_nav_page_changed(self, nav_view, pspec):
        vis = nav_view.get_visible_page()
        if vis and vis.get_tag() == 'main' and hasattr(self, '_library_page'):
            if getattr(self, '_nav_initialized', False):
                self._library_page.schedule_refresh(100)
            self._nav_initialized = True

    def _on_window_key_pressed(self, controller, keyval, keycode, state):
        focus = self.get_focus()
        if focus and isinstance(focus, (Gtk.Editable, Gtk.Entry)):
            return False
        if keyval == Gdk.KEY_slash:
            self._on_search_action(None, None)
            return True
        return False

    def _on_movie_selected(self, page, movie_data):
        """Push movie detail page onto navigation view."""
        movie_page = MoviePage(movie=movie_data)
        movie_page.connect('play-movie', self._on_play_movie)
        movie_page.connect('movie-selected', self._on_movie_selected)
        movie_page.connect('person-selected', self._on_person_selected)
        movie_page.connect('watchlist-toggled', lambda p, m, a: self._library_page.refresh() if hasattr(self, '_library_page') else None)
        self._nav_view.push(movie_page)

    def _on_person_selected(self, page, person_data):
        """Push person filmography page onto navigation view."""
        person_page = PersonPage(person_data=person_data)
        person_page.connect('movie-selected', self._on_movie_selected)
        person_page.connect('play-movie', self._on_play_movie)
        self._nav_view.push(person_page)

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

        shortcuts_action = Gio.SimpleAction.new('shortcuts', None)
        shortcuts_action.connect('activate', self._on_shortcuts_action)
        self.add_action(shortcuts_action)

        search_action = Gio.SimpleAction.new('search', None)
        search_action.connect('activate', self._on_search_action)
        self.add_action(search_action)

        tab_lib_action = Gio.SimpleAction.new('tab_library', None)
        tab_lib_action.connect('activate', lambda a, p: self._switch_tab('library'))
        self.add_action(tab_lib_action)

        tab_mov_action = Gio.SimpleAction.new('tab_movies', None)
        tab_mov_action.connect('activate', lambda a, p: self._switch_tab('movies'))
        self.add_action(tab_mov_action)

        tab_ser_action = Gio.SimpleAction.new('tab_series', None)
        tab_ser_action.connect('activate', lambda a, p: self._switch_tab('series'))
        self.add_action(tab_ser_action)

        tab_next_action = Gio.SimpleAction.new('tab_next', None)
        tab_next_action.connect('activate', lambda a, p: self._cycle_tab(1))
        self.add_action(tab_next_action)

        tab_prev_action = Gio.SimpleAction.new('tab_prev', None)
        tab_prev_action.connect('activate', lambda a, p: self._cycle_tab(-1))
        self.add_action(tab_prev_action)

    def _switch_tab(self, tab_name: str):
        visible = self._nav_view.get_visible_page()
        if visible and visible.get_tag() == 'player':
            return
        while self._nav_view.get_visible_page() and self._nav_view.get_visible_page().get_tag() != 'main':
            self._nav_view.pop()
        self._view_stack.set_visible_child_name(tab_name)

        if self._pending_tab_focus_id:
            GLib.source_remove(self._pending_tab_focus_id)
            self._pending_tab_focus_id = None

        def _do_focus():
            self._pending_tab_focus_id = None
            if tab_name == 'library' and hasattr(self, '_library_page'):
                self._library_page.focus_first()
            elif tab_name == 'movies' and hasattr(self, '_movies_page'):
                self._movies_page._search_entry.grab_focus()
            elif tab_name == 'series' and hasattr(self, '_series_page'):
                self._series_page._search_entry.grab_focus()
            return False

        self._pending_tab_focus_id = GLib.timeout_add(50, _do_focus)

    def _cycle_tab(self, step: int):
        visible = self._nav_view.get_visible_page()
        if visible and visible.get_tag() == 'player':
            return
        tabs = ['library', 'movies', 'series']
        curr = self._view_stack.get_visible_child_name()
        if curr in tabs:
            idx = (tabs.index(curr) + step) % len(tabs)
            self._switch_tab(tabs[idx])

    def _on_search_action(self, action, param):
        visible = self._nav_view.get_visible_page()
        if visible and visible.get_tag() == 'player':
            return
        curr = self._view_stack.get_visible_child_name()
        if curr == 'movies':
            self._movies_page._search_entry.grab_focus()
        elif curr == 'series':
            self._series_page._search_entry.grab_focus()
        else:
            self._switch_tab('movies')
            self._movies_page._search_entry.grab_focus()

    def _on_shortcuts_action(self, action, param):
        self._show_shortcuts_window()

    def _show_shortcuts_window(self):
        win = Gtk.ShortcutsWindow()
        win.set_transient_for(self)
        win.set_modal(True)
        win.set_default_size(680, 480)

        # ── Section 1: App & Navigation ────────────────────────────────────
        sec_app = Gtk.ShortcutsSection(title="App & Navigation", section_name="app", max_height=10)

        g_gen = Gtk.ShortcutsGroup(title="General")
        g_gen.append(Gtk.ShortcutsShortcut(title="Search", accelerator="<Ctrl>F"))
        g_gen.append(Gtk.ShortcutsShortcut(title="Quick Search", accelerator="slash"))
        g_gen.append(Gtk.ShortcutsShortcut(title="Keyboard Shortcuts", accelerator="<Ctrl>question"))
        g_gen.append(Gtk.ShortcutsShortcut(title="Preferences", accelerator="<Ctrl>comma"))
        g_gen.append(Gtk.ShortcutsShortcut(title="Toggle Fullscreen", accelerator="F11"))
        g_gen.append(Gtk.ShortcutsShortcut(title="Go Back / Exit Player", accelerator="Escape"))
        sec_app.append(g_gen)

        g_nav = Gtk.ShortcutsGroup(title="Navigation")
        g_nav.append(Gtk.ShortcutsShortcut(title="Switch to Library", accelerator="<Ctrl>1"))
        g_nav.append(Gtk.ShortcutsShortcut(title="Switch to Movies", accelerator="<Ctrl>2"))
        g_nav.append(Gtk.ShortcutsShortcut(title="Switch to Series", accelerator="<Ctrl>3"))
        g_nav.append(Gtk.ShortcutsShortcut(title="Next Tab", accelerator="<Ctrl>Tab"))
        g_nav.append(Gtk.ShortcutsShortcut(title="Previous Tab", accelerator="<Ctrl><Shift>Tab"))
        g_nav.append(Gtk.ShortcutsShortcut(title="Open Details", accelerator="Return"))
        g_nav.append(Gtk.ShortcutsShortcut(title="Play Directly", accelerator="space"))
        g_nav.append(Gtk.ShortcutsShortcut(title="Toggle Watchlist", accelerator="w"))
        sec_app.append(g_nav)

        # ── Section 2: Player Controls ─────────────────────────────────────
        sec_player = Gtk.ShortcutsSection(title="Player Controls", section_name="playback", max_height=10)

        g_play = Gtk.ShortcutsGroup(title="Playback")
        g_play.append(Gtk.ShortcutsShortcut(title="Play / Pause", accelerator="space"))
        g_play.append(Gtk.ShortcutsShortcut(title="Seek Backward 10s", accelerator="Left"))
        g_play.append(Gtk.ShortcutsShortcut(title="Seek Forward 10s", accelerator="Right"))
        g_play.append(Gtk.ShortcutsShortcut(title="Seek Backward 1m", accelerator="<Shift>Left"))
        g_play.append(Gtk.ShortcutsShortcut(title="Seek Forward 1m", accelerator="<Shift>Right"))
        g_play.append(Gtk.ShortcutsShortcut(title="Volume Up", accelerator="Up"))
        g_play.append(Gtk.ShortcutsShortcut(title="Volume Down", accelerator="Down"))
        g_play.append(Gtk.ShortcutsShortcut(title="Mute / Unmute", accelerator="m"))
        g_play.append(Gtk.ShortcutsShortcut(title="Decrease Subtitle Delay", accelerator="z"))
        g_play.append(Gtk.ShortcutsShortcut(title="Increase Subtitle Delay", accelerator="x"))
        g_play.append(Gtk.ShortcutsShortcut(title="Toggle Captions (Default English)", accelerator="c"))
        g_play.append(Gtk.ShortcutsShortcut(title="Subtitles Menu", accelerator="s"))
        g_play.append(Gtk.ShortcutsShortcut(title="Choose Torrent Stream", accelerator="t"))
        g_play.append(Gtk.ShortcutsShortcut(title="Next Episode (TV)", accelerator="<Shift>n"))
        g_play.append(Gtk.ShortcutsShortcut(title="Cycle Audio Track", accelerator="a"))
        g_play.append(Gtk.ShortcutsShortcut(title="Decrease Playback Speed", accelerator="bracketleft"))
        g_play.append(Gtk.ShortcutsShortcut(title="Increase Playback Speed", accelerator="bracketright"))
        g_play.append(Gtk.ShortcutsShortcut(title="Reset Playback Speed", accelerator="r"))
        g_play.append(Gtk.ShortcutsShortcut(title="Cycle Video Fit / Aspect Ratio", accelerator="w"))
        g_play.append(Gtk.ShortcutsShortcut(title="Toggle Fullscreen", accelerator="f"))
        sec_player.append(g_play)

        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            win.add_section(sec_app)
            win.add_section(sec_player)

        win.present()

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
        from showberry.services.database import DatabaseService
        db = DatabaseService()
        with db._get_connection() as conn:
            conn.execute("DELETE FROM watch_history")
            conn.commit()
        if hasattr(self, '_library_page'):
            self._library_page.refresh()
        self.show_toast("Watch history cleared", timeout=3)

    def _on_about_action(self, action, param):
        """Show About Showberry dialog."""
        dialog = Adw.AboutDialog.new()
        dialog.set_application_name("Showberry")
        dialog.set_version("0.2.2")
        dialog.set_developer_name("Showberry Contributors")
        dialog.set_comments("An elegant, modern movie and TV series streaming application for GNOME.")
        dialog.set_website("https://github.com/Dackerie/showberry")
        dialog.set_application_icon("io.github.Dackerie.Showberry")
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
                if settings:
                    schema = settings.get_property('settings-schema')
                    keys = schema.list_keys() if schema else []
                    width, height = self.get_default_size()
                    if 'window-width' in keys:
                        settings.set_int('window-width', width)
                    if 'window-height' in keys:
                        settings.set_int('window-height', height)
                    if 'is-maximized' in keys:
                        settings.set_boolean('is-maximized', self.is_maximized())
        except Exception:
            pass
        return False

# Backwards compatibility alias
KinemaWindow = ShowberryWindow
