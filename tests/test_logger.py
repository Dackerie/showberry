"""Tests for persistent logging and diagnostic utilities."""

import unittest
import tempfile
import logging
from pathlib import Path
from unittest.mock import patch

from showberry.services.logger import get_log_dir, get_log_file, setup_logging


class TestLogger(unittest.TestCase):
    def test_log_paths(self):
        log_dir = get_log_dir()
        log_file = get_log_file()
        self.assertIsInstance(log_dir, Path)
        self.assertIsInstance(log_file, Path)
        self.assertTrue(str(log_file).endswith('showberry.log'))

    def test_setup_logging_and_file_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)
            test_file = test_dir / 'showberry.log'

            with patch('showberry.services.logger.get_log_dir', return_value=test_dir), \
                 patch('showberry.services.logger.get_log_file', return_value=test_file):
                root = logging.getLogger()
                old_handlers = list(root.handlers)
                root.handlers.clear()
                try:
                    setup_logging()
                    test_msg = "Unique test diagnostic entry 12345"
                    logging.getLogger("test").info(test_msg)
                    for h in root.handlers:
                        h.flush()

                    self.assertTrue(test_file.exists())
                    content = test_file.read_text(encoding='utf-8')
                    self.assertIn(test_msg, content)
                finally:
                    for h in list(root.handlers):
                        h.close()
                    root.handlers = old_handlers


if __name__ == '__main__':
    unittest.main()
