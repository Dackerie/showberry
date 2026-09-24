#!/usr/bin/env python3
"""Showberry - A movie browser and player for GNOME."""

import os
import sys
import locale

# Force modern OpenGL renderer to eliminate Vulkan swapchain stalls with GLArea on Linux
if sys.platform.startswith('linux'):
    os.environ.setdefault('GSK_RENDERER', 'gl')

# Preload libcurl-impersonate with RTLD_GLOBAL on Linux to avoid symbol collision with libmpv's libcurl
if sys.platform.startswith('linux'):
    try:
        import ctypes
        for _lib in ('/usr/lib/libcurl-impersonate.so.4', '/usr/lib64/libcurl-impersonate.so.4', '/usr/local/lib/libcurl-impersonate.so.4'):
            if os.path.exists(_lib):
                ctypes.CDLL(_lib, mode=ctypes.RTLD_GLOBAL)
                break
    except Exception:
        pass
elif sys.platform == 'win32':
    # Ensure current directory and exe directory are in PATH and Windows DLL search path (Python 3.8+)
    import ctypes
    import ctypes.util

    exe_dir = os.path.dirname(sys.executable)
    bundle_dir = getattr(sys, '_MEIPASS', exe_dir)
    internal_dir = os.path.join(exe_dir, '_internal')

    # Add directories to PATH and Windows DLL search path (Python 3.8+)
    search_dirs = [exe_dir, internal_dir, bundle_dir, os.getcwd()]
    for p in search_dirs:
        if p and os.path.isdir(p):
            abs_p = os.path.abspath(p)
            if hasattr(os, 'add_dll_directory'):
                try:
                    os.add_dll_directory(abs_p)
                except Exception:
                    pass
            if abs_p not in os.environ.get('PATH', ''):
                os.environ['PATH'] = abs_p + os.pathsep + os.environ.get('PATH', '')

    # Hook ctypes.util.find_library so python-mpv receives the exact absolute path to libmpv-2.dll
    _orig_find_library = ctypes.util.find_library
    def _win_find_library(name):
        if 'mpv' in name.lower():
            for d in (exe_dir, internal_dir, bundle_dir):
                if not d or not os.path.isdir(d):
                    continue
                for candidate in ('libmpv-2.dll', 'mpv-2.dll', 'mpv-1.dll', 'mpv.dll'):
                    cand_path = os.path.join(d, candidate)
                    if os.path.isfile(cand_path):
                        return os.path.abspath(cand_path)
        return _orig_find_library(name)
    ctypes.util.find_library = _win_find_library

elif sys.platform == 'darwin':
    import ctypes
    import ctypes.util

    # On macOS, search Homebrew and bundle paths for libmpv.dylib and dependencies
    mac_paths = ['/opt/homebrew/lib', '/usr/local/lib']
    if getattr(sys, 'frozen', False):
        exe_parent = os.path.dirname(sys.executable)
        bundle_dir = getattr(sys, '_MEIPASS', exe_parent)
        internal_dir = os.path.join(exe_parent, '_internal')
        bundle_internal = os.path.join(bundle_dir, '_internal')
        for p in (internal_dir, bundle_internal, exe_parent, bundle_dir):
            if p and os.path.isdir(p) and p not in mac_paths:
                mac_paths.insert(0, os.path.abspath(p))
        mac_paths.insert(0, os.path.abspath(os.path.join(exe_parent, '..')))
        mac_paths.insert(0, os.path.abspath(os.path.join(exe_parent, '..', 'Resources')))
        mac_paths.insert(0, os.path.abspath(os.path.join(exe_parent, '..', 'Resources', 'showberry')))
        mac_paths.insert(0, os.path.abspath(os.path.join(exe_parent, '..', 'Frameworks')))
    existing_dyld = os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')
    for p in mac_paths:
        if os.path.exists(p) and p not in existing_dyld:
            existing_dyld = (p + os.pathsep + existing_dyld) if existing_dyld else p
    os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = existing_dyld
    os.environ['DYLD_LIBRARY_PATH'] = existing_dyld

    # Hook ctypes.util.find_library so python-mpv finds bundled or Homebrew libmpv.dylib
    _orig_find_library = ctypes.util.find_library
    def _mac_find_library(name):
        if 'mpv' in name.lower():
            for d in mac_paths:
                if not d or not os.path.isdir(d):
                    continue
                for candidate in ('libmpv.2.dylib', 'libmpv.dylib', 'mpv.dylib'):
                    cand_path = os.path.join(d, candidate)
                    try:
                        real_p = os.path.realpath(cand_path)
                        if os.path.isfile(real_p) and os.path.exists(real_p):
                            return os.path.abspath(real_p)
                    except Exception:
                        pass
        return _orig_find_library(name)
    ctypes.util.find_library = _mac_find_library

    # Pre-load core GLib / GObject / GTK4 / Libadwaita libraries into global namespace
    # so girepository dlopen calls succeed even under macOS SIP / restricted dyld search
    for lib_name in [
        'libglib-2.0.0.dylib',
        'libglib-2.0.dylib',
        'libgobject-2.0.0.dylib',
        'libgobject-2.0.dylib',
        'libgmodule-2.0.0.dylib',
        'libgio-2.0.0.dylib',
        'libgio-2.0.dylib',
        'libgirepository-1.0.1.dylib',
        'libgirepository-2.0.0.dylib',
        'libgtk-4.1.dylib',
        'libgtk-4.dylib',
        'libadwaita-1.0.dylib',
        'libadwaita-1.dylib',
    ]:
        for d in mac_paths:
            cand = os.path.join(d, lib_name)
            if os.path.exists(cand):
                try:
                    ctypes.CDLL(cand, mode=ctypes.RTLD_GLOBAL)
                    break
                except Exception:
                    pass

# GTK stomps over locale settings needed by libmpv
locale.setlocale(locale.LC_NUMERIC, 'C')


def _handle_fatal_exception(exc_type, exc_val, exc_tb):
    """Global crash handler writing persistent crash report and alerting user."""
    import time
    import traceback
    err_text = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
    sys.stderr.write(f"\nShowberry Fatal Crash:\n{err_text}\n")

    crash_log = None
    try:
        from showberry.services.logger import get_log_dir
        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        crash_log = log_dir / 'showberry_crash.log'
        with open(crash_log, 'a', encoding='utf-8') as f:
            f.write(f"\n--- Crash at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            f.write(err_text)
    except Exception:
        pass

    msg = f"Showberry encountered an unexpected fatal error and had to close.\n\nError: {exc_val}"
    if crash_log:
        msg += f"\n\nA crash log was saved to:\n{crash_log}"

    try:
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "Showberry Error", 0x10)
        elif sys.platform == 'darwin':
            import subprocess
            escaped = msg.replace('\\', '\\\\').replace('"', '\\"')
            subprocess.run([
                'osascript', '-e',
                f'display alert "Showberry Error" message "{escaped}" as critical buttons {{"OK"}} default button "OK"'
            ], timeout=5)
        elif sys.platform.startswith('linux'):
            import subprocess
            for tool in ('zenity', 'kdialog'):
                if subprocess.run(['which', tool], capture_output=True).returncode == 0:
                    if tool == 'zenity':
                        subprocess.run(['zenity', '--error', '--title=Showberry Error', f'--text={msg}'], timeout=5)
                    else:
                        subprocess.run(['kdialog', '--error', msg, '--title', 'Showberry Error'], timeout=5)
                    break
    except Exception:
        pass

    sys.__excepthook__(exc_type, exc_val, exc_tb)


sys.excepthook = _handle_fatal_exception


def _activate_macos_app():
    """Ensure macOS registers the process as a foreground GUI app with Dock icon and focus."""
    if sys.platform != 'darwin':
        return
    try:
        import ctypes
        import ctypes.util
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        nsapp_class = objc.objc_getClass(b"NSApplication")
        shared_app_sel = objc.sel_registerName(b"sharedApplication")
        objc_msg_send = objc.objc_msgSend
        objc_msg_send.restype = ctypes.c_void_p
        objc_msg_send.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        app_inst = objc_msg_send(nsapp_class, shared_app_sel)

        set_policy_sel = objc.sel_registerName(b"setActivationPolicy:")
        objc_msg_send_long = objc.objc_msgSend
        objc_msg_send_long.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        objc_msg_send_long(app_inst, set_policy_sel, 0)

        activate_sel = objc.sel_registerName(b"activateIgnoringOtherApps:")
        objc_msg_send_bool = objc.objc_msgSend
        objc_msg_send_bool.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
        objc_msg_send_bool(app_inst, activate_sel, True)
    except Exception:
        pass


def main():
    try:
        _activate_macos_app()
        import gi
        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')

        from showberry.services.logger import setup_logging
        from showberry.application import ShowberryApplication

        setup_logging()
        app = ShowberryApplication()
        return app.run(sys.argv)
    except Exception as e:
        _handle_fatal_exception(*sys.exc_info())
        return 1


if __name__ == '__main__':
    sys.exit(main())

