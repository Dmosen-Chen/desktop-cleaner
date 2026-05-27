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


if __name__ == "__main__":
    unittest.main()
