"""Filter and Sort popover for Movies and Series pages."""

from typing import Dict, Any, Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, GLib

from showberry.services.tmdb import (
    MOVIE_GENRES,
    TV_GENRES,
    LANGUAGES,
    YEAR_OPTIONS,
    SORT_OPTIONS,
)


class FilterSortPopover(Gtk.Popover):
    """Sleek Adwaita popover menu for filtering and sorting movies or TV series."""

    __gsignals__ = {
        'filter-changed': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, is_tv: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._is_tv = is_tv
        self._genres = TV_GENRES if is_tv else MOVIE_GENRES
        self._updating = False
        self._leave_timer_id = None

        self._setup_ui()

    def _setup_ui(self):
        self.set_autohide(True)
        self.add_css_class('filter-sort-popover')

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        main_box.set_margin_top(14)
        main_box.set_margin_bottom(14)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)
        main_box.set_size_request(260, -1)

        # ── Header: Title + Reset Button ────────────────────────────────────
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        title_lbl = Gtk.Label(label="Filter & Sort")
        title_lbl.add_css_class('title-4')
        title_lbl.set_hexpand(True)
        title_lbl.set_xalign(0.0)
        header_box.append(title_lbl)

        self._reset_btn = Gtk.Button(label="Reset")
        self._reset_btn.add_css_class('flat')
        self._reset_btn.add_css_class('caption')
        self._reset_btn.connect('clicked', self._on_reset_clicked)
        header_box.append(self._reset_btn)

        self._close_btn = Gtk.Button.new_from_icon_name('window-close-symbolic')
        self._close_btn.add_css_class('flat')
        self._close_btn.set_tooltip_text("Close (Esc)")
        self._close_btn.connect('clicked', lambda b: self.popdown())
        header_box.append(self._close_btn)

        main_box.append(header_box)
        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── 1. Sort By Dropdown ─────────────────────────────────────────────
        sort_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sort_lbl = Gtk.Label(label="Sort By")
        sort_lbl.add_css_class('caption')
        sort_lbl.add_css_class('dim-label')
        sort_lbl.set_xalign(0.0)
        sort_box.append(sort_lbl)

        self._sort_dropdown = Gtk.DropDown.new_from_strings([label for _, label in SORT_OPTIONS])
        self._sort_dropdown.set_selected(0)
        self._sort_dropdown.connect('notify::selected', self._on_selection_changed)
        sort_box.append(self._sort_dropdown)
        main_box.append(sort_box)

        # ── 2. Genre Dropdown ───────────────────────────────────────────────
        genre_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        genre_lbl = Gtk.Label(label="Genre")
        genre_lbl.add_css_class('caption')
        genre_lbl.add_css_class('dim-label')
        genre_lbl.set_xalign(0.0)
        genre_box.append(genre_lbl)

        self._genre_dropdown = Gtk.DropDown.new_from_strings([name for _, name in self._genres])
        self._genre_dropdown.set_selected(0)
        self._genre_dropdown.connect('notify::selected', self._on_selection_changed)
        genre_box.append(self._genre_dropdown)
        main_box.append(genre_box)

        # ── 3. Year Dropdown ────────────────────────────────────────────────
        year_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        year_lbl = Gtk.Label(label="Release Year")
        year_lbl.add_css_class('caption')
        year_lbl.add_css_class('dim-label')
        year_lbl.set_xalign(0.0)
        year_box.append(year_lbl)

        self._year_dropdown = Gtk.DropDown.new_from_strings(YEAR_OPTIONS)
        self._year_dropdown.set_selected(0)
        self._year_dropdown.connect('notify::selected', self._on_selection_changed)
        year_box.append(self._year_dropdown)
        main_box.append(year_box)

        # ── 4. Language Dropdown ────────────────────────────────────────────
        lang_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        lang_lbl = Gtk.Label(label="Original Language")
        lang_lbl.add_css_class('caption')
        lang_lbl.add_css_class('dim-label')
        lang_lbl.set_xalign(0.0)
        lang_box.append(lang_lbl)

        self._lang_dropdown = Gtk.DropDown.new_from_strings([name for _, name in LANGUAGES])
        self._lang_dropdown.set_selected(0)
        self._lang_dropdown.connect('notify::selected', self._on_selection_changed)
        lang_box.append(self._lang_dropdown)
        main_box.append(lang_box)

        # ── 5. Only Released Titles Toggle ──────────────────────────────────
        released_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        released_box.set_valign(Gtk.Align.CENTER)
        released_lbl = Gtk.Label(label="Only Released")
        released_lbl.add_css_class('body')
        released_lbl.set_hexpand(True)
        released_lbl.set_xalign(0.0)
        released_box.append(released_lbl)

        self._released_switch = Gtk.Switch()
        self._released_switch.set_active(False)
        self._released_switch.set_valign(Gtk.Align.CENTER)
        self._released_switch.connect('notify::active', self._on_selection_changed)
        released_box.append(self._released_switch)
        main_box.append(released_box)

        # ── Mouse Leave Auto-Dismissal Controller ───────────────────────────
        motion_ctrl = Gtk.EventControllerMotion.new()
        motion_ctrl.connect('enter', self._on_motion_enter)
        motion_ctrl.connect('leave', self._on_motion_leave)
        self.add_controller(motion_ctrl)

        self.set_child(main_box)

    def get_filter_params(self) -> Dict[str, Any]:
        """Get the active filter parameters dictionary."""
        sort_idx = self._sort_dropdown.get_selected()
        genre_idx = self._genre_dropdown.get_selected()
        year_idx = self._year_dropdown.get_selected()
        lang_idx = self._lang_dropdown.get_selected()
        only_released = self._released_switch.get_active()

        sort_by = SORT_OPTIONS[sort_idx][0] if 0 <= sort_idx < len(SORT_OPTIONS) else 'popularity.desc'
        genre_id = self._genres[genre_idx][0] if 0 <= genre_idx < len(self._genres) else 0
        year = YEAR_OPTIONS[year_idx] if 0 <= year_idx < len(YEAR_OPTIONS) else 'All Years'
        language = LANGUAGES[lang_idx][0] if 0 <= lang_idx < len(LANGUAGES) else ''

        is_active = (sort_idx != 0 or genre_idx != 0 or year_idx != 0 or lang_idx != 0 or only_released)

        return {
            'sort_by': sort_by,
            'genre_id': genre_id,
            'year': year,
            'language': language,
            'only_released': only_released,
            'is_active': is_active,
        }

    def is_active(self) -> bool:
        """Check if any non-default filter is currently active."""
        return self.get_filter_params()['is_active']

    def update_button_style(self, button: Gtk.Widget):
        """Add or remove suggested-action styling on the filter button based on filter status."""
        if self.is_active():
            button.add_css_class('suggested-action')
        else:
            button.remove_css_class('suggested-action')

    def reset(self):
        """Reset all filter selections to default."""
        self._updating = True
        self._sort_dropdown.set_selected(0)
        self._genre_dropdown.set_selected(0)
        self._year_dropdown.set_selected(0)
        self._lang_dropdown.set_selected(0)
        self._released_switch.set_active(False)
        self._updating = False
        self.emit('filter-changed', self.get_filter_params())

    def _on_reset_clicked(self, button):
        self.reset()

    def _on_selection_changed(self, widget, pspec):
        if not self._updating:
            self.emit('filter-changed', self.get_filter_params())

    def _on_motion_enter(self, controller, x, y):
        if self._leave_timer_id:
            GLib.source_remove(self._leave_timer_id)
            self._leave_timer_id = None

    def _on_motion_leave(self, controller):
        if self._leave_timer_id:
            GLib.source_remove(self._leave_timer_id)
        self._leave_timer_id = GLib.timeout_add(350, self._auto_popdown)

    def _is_any_dropdown_open(self) -> bool:
        for dd in (self._sort_dropdown, self._genre_dropdown, self._year_dropdown, self._lang_dropdown):
            child = dd.get_first_child()
            while child:
                if isinstance(child, Gtk.Popover) and child.get_visible():
                    return True
                child = child.get_next_sibling()
        return False

    def _auto_popdown(self):
        self._leave_timer_id = None
        if not self.get_visible():
            return GLib.SOURCE_REMOVE
        if self._is_any_dropdown_open():
            return GLib.SOURCE_REMOVE
        self.popdown()
        return GLib.SOURCE_REMOVE
