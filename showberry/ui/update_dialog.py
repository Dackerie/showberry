"""Update notification and in-place upgrade dialog."""

import os
import sys
import logging
from typing import Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib, Pango

from showberry import __version__
from showberry.services.updater import UpdateService, UpdateInfo, InstallationType

logger = logging.getLogger(__name__)


class UpdateDialog(Adw.Window):
    """Modal dialog presenting release notes, download progress, and upgrade trigger."""

    def __init__(self, parent_window: Gtk.Window, update_info: UpdateInfo):
        super().__init__()
        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_default_size(580, 500)
        self.set_title(f"Update Available • Showberry v{update_info.version}")

        self._updater = UpdateService.get_instance()
        self._update_info = update_info
        self._is_downloading = False
        self._download_completed = False
        self._downloaded_file: Optional[str] = None

        self._setup_ui()

    def _setup_ui(self):
        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        main_box.set_margin_top(16)
        main_box.set_margin_bottom(16)
        main_box.set_margin_start(24)
        main_box.set_margin_end(24)

        # Header hero section
        hero_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        app_icon = Gtk.Image.new_from_icon_name('system-software-update-symbolic')
        app_icon.set_pixel_size(48)
        hero_box.append(app_icon)

        title_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title_label = Gtk.Label(label=f"Showberry v{self._update_info.version} is available!")
        title_label.add_css_class('title-2')
        title_label.set_halign(Gtk.Align.START)
        title_vbox.append(title_label)

        sub_label = Gtk.Label(label=f"Currently running: v{__version__}  •  {self._get_install_type_label()}")
        sub_label.add_css_class('dim-label')
        sub_label.set_halign(Gtk.Align.START)
        title_vbox.append(sub_label)
        hero_box.append(title_vbox)
        main_box.append(hero_box)

        # Release Notes ScrolledWindow
        notes_frame = Gtk.Frame()
        notes_frame.set_vexpand(True)
        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        notes_tv = Gtk.TextView()
        notes_tv.set_editable(False)
        notes_tv.set_cursor_visible(False)
        notes_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        notes_tv.set_top_margin(12)
        notes_tv.set_bottom_margin(12)
        notes_tv.set_left_margin(14)
        notes_tv.set_right_margin(14)

        buf = notes_tv.get_buffer()
        buf.set_text(self._update_info.body or "No release notes available.")
        notes_scroll.set_child(notes_tv)
        notes_frame.set_child(notes_scroll)
        main_box.append(notes_frame)

        # Download Progress Area (Hidden by default)
        self._progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._progress_box.set_visible(False)

        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.set_show_text(False)
        self._progress_box.append(self._progress_bar)

        self._progress_status = Gtk.Label(label="Connecting...")
        self._progress_status.add_css_class('caption')
        self._progress_status.set_halign(Gtk.Align.START)
        self._progress_box.append(self._progress_status)
        main_box.append(self._progress_box)

        # Action Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_box.set_halign(Gtk.Align.END)

        self._github_btn = Gtk.Button(label="View on GitHub")
        self._github_btn.add_css_class('flat')
        self._github_btn.connect('clicked', self._on_github_clicked)
        btn_box.append(self._github_btn)

        self._cancel_btn = Gtk.Button(label="Later")
        self._cancel_btn.connect('clicked', self._on_cancel_clicked)
        btn_box.append(self._cancel_btn)

        self._action_btn = Gtk.Button()
        self._action_btn.add_css_class('suggested-action')
        self._configure_action_button()
        btn_box.append(self._action_btn)

        main_box.append(btn_box)
        toolbar_view.set_content(main_box)
        self.set_content(toolbar_view)

    def _get_install_type_label(self) -> str:
        itype = self._update_info.installation_type
        if itype == InstallationType.WINDOWS_INSTALLED:
            return "Windows (Installer)"
        elif itype == InstallationType.WINDOWS_PORTABLE:
            return "Windows (Portable)"
        elif itype == InstallationType.MACOS_BUNDLE:
            return "macOS Application"
        elif itype == InstallationType.LINUX_APPIMAGE:
            return "Linux AppImage"
        elif itype == InstallationType.LINUX_FLATPAK:
            return "Flatpak Package"
        return "System Package / Source"

    def _configure_action_button(self):
        itype = self._update_info.installation_type
        if itype in (InstallationType.WINDOWS_INSTALLED, InstallationType.WINDOWS_PORTABLE,
                     InstallationType.MACOS_BUNDLE, InstallationType.LINUX_APPIMAGE):
            self._action_btn.set_label("Update & Restart")
            self._action_btn.connect('clicked', self._on_update_clicked)
        elif itype == InstallationType.LINUX_FLATPAK:
            self._action_btn.set_label("Download .flatpak")
            self._action_btn.connect('clicked', self._on_update_clicked)
        else:
            self._action_btn.set_label("View Release")
            self._action_btn.connect('clicked', self._on_github_clicked)

    def _on_github_clicked(self, btn):
        try:
            Gio.AppInfo.launch_default_for_uri(self._update_info.html_url, None)
        except Exception:
            pass

    def _on_cancel_clicked(self, btn):
        if self._is_downloading:
            self._updater.cancel_download()
        self.close()

    def _on_update_clicked(self, btn):
        if self._is_downloading:
            return

        itype = self._update_info.installation_type
        if not self._update_info.download_url:
            self._on_github_clicked(None)
            return

        self._is_downloading = True
        self._action_btn.set_sensitive(False)
        self._cancel_btn.set_label("Cancel")
        self._progress_box.set_visible(True)
        self._progress_bar.set_fraction(0.0)
        self._progress_status.set_label("Starting download...")

        self._updater.download_update(
            self._update_info,
            self._on_download_progress,
            self._on_download_completed
        )

    def _on_download_progress(self, fraction: float, downloaded: int, total: int):
        self._progress_bar.set_fraction(max(0.0, min(1.0, fraction)))
        mb_down = downloaded / (1024 * 1024)
        if total > 0:
            mb_tot = total / (1024 * 1024)
            pct = int(fraction * 100)
            self._progress_status.set_label(f"Downloading: {mb_down:.1f} MB of {mb_tot:.1f} MB ({pct}%)")
        else:
            self._progress_status.set_label(f"Downloading: {mb_down:.1f} MB")

    def _on_download_completed(self, success: bool, local_path: Optional[str], error_msg: Optional[str]):
        self._is_downloading = False
        if not success or not local_path:
            self._action_btn.set_sensitive(True)
            self._action_btn.set_label("Retry Update")
            self._cancel_btn.set_label("Close")
            self._progress_status.set_label(f"Error: {error_msg or 'Download failed'}")
            return

        self._download_completed = True
        self._downloaded_file = local_path
        self._progress_bar.set_fraction(1.0)

        itype = self._update_info.installation_type
        if itype == InstallationType.LINUX_FLATPAK:
            self._progress_status.set_label(f"Downloaded bundle to: {local_path}")
            self._action_btn.set_label("Open Folder")
            self._action_btn.set_sensitive(True)
            self._action_btn.disconnect_by_func(self._on_update_clicked)
            self._action_btn.connect('clicked', lambda b: self._updater.apply_update(self._update_info, local_path))
            return

        self._progress_status.set_label("Download complete! Applying update and restarting...")
        GLib.timeout_add(800, self._trigger_restart)

    def _trigger_restart(self):
        if not self._downloaded_file:
            return False

        success, err = self._updater.apply_update(self._update_info, self._downloaded_file)
        if success:
            app = Gtk.Application.get_default()
            if app:
                app.quit()
            sys.exit(0)
        else:
            self._progress_status.set_label(f"Failed to launch update: {err}")
            self._action_btn.set_sensitive(True)
            self._action_btn.set_label("Retry")
        return False
