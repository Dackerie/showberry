"""Persistent logging service for Showberry across macOS, Windows, and Linux."""

import os
import sys
import subprocess
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler


def get_log_dir() -> Path:
    """Return platform-specific log directory."""
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Logs' / 'Showberry'
    elif sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA', str(Path.home()))
        return Path(base) / 'Showberry' / 'logs'
    else:
        base = os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local' / 'state'))
        return Path(base) / 'showberry'


def get_log_file() -> Path:
    """Return platform-specific log file path."""
    return get_log_dir() / 'showberry.log'


def open_log_folder() -> bool:
    """Open the log folder in the native file manager (Finder / Explorer / Files)."""
    p = get_log_dir()
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    try:
        if sys.platform == 'darwin':
            subprocess.run(['open', str(p)], check=False)
            return True
        elif sys.platform == 'win32':
            os.startfile(str(p))
            return True
        else:
            subprocess.run(['xdg-open', str(p)], check=False)
            return True
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to open log folder: %s", e)
        return False


def setup_logging():
    """Initialize persistent rotating file logger and console output."""
    log_dir = get_log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = get_log_file()
    except Exception:
        log_file = None

    root_logger = logging.getLogger()
    if root_logger.handlers:
        # Avoid duplicate handlers if setup_logging is invoked multiple times
        return

    is_debug = ('--debug' in sys.argv or '--verbose' in sys.argv or os.environ.get('SHOWBERRY_DEBUG'))
    log_level = logging.DEBUG if is_debug else logging.INFO
    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (5 MB max, 3 backups)
    if log_file:
        try:
            file_handler = RotatingFileHandler(
                str(log_file),
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            print(f"Warning: Failed to setup file logger: {e}", file=sys.stderr)

    # Global uncaught exception handler
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        root_logger.error("Uncaught exception:", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception
    root_logger.info("Showberry starting (platform: %s, python: %s)", sys.platform, sys.version.split()[0])
    if log_file:
        root_logger.info("Persistent log file: %s", log_file)
