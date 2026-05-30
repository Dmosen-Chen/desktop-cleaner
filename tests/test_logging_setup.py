from __future__ import annotations

import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.services.logging_setup import configure_logging, log_exception


class LoggingSetupTests(unittest.TestCase):
    def test_configure_logging_writes_to_local_log_file(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = configure_logging(Path(tmp) / "DesktopCleaner")

            log_exception("probe", RuntimeError("boom"))

            self.assertEqual(log_path.name, "desktop-cleaner.log")
            text = log_path.read_text(encoding="utf-8")
            self.assertIn("probe", text)
            self.assertIn("boom", text)
            logger = logging.getLogger("desktop_cleaner")
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)

    def test_repeated_log_exception_keeps_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = configure_logging(Path(tmp) / "DesktopCleaner")

            log_exception("first", RuntimeError("boom-1"))
            log_exception("second", RuntimeError("boom-2"))

            text = log_path.read_text(encoding="utf-8")
            self.assertIn("first", text)
            self.assertIn("boom-1", text)
            self.assertIn("second", text)
            self.assertIn("boom-2", text)
            logger = logging.getLogger("desktop_cleaner")
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)

    def tearDown(self) -> None:
        logger = logging.getLogger("desktop_cleaner")
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
