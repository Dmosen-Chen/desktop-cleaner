"""Application logging setup for diagnostics and recovery support."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

LOGGER_NAME = "desktop_cleaner"


def configure_logging(app_dir: Path) -> Path:
    log_dir = Path(app_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "desktop-cleaner.log"
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) != log_path:
            handler.close()
            logger.removeHandler(handler)
    if not any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename) == log_path
        for handler in logger.handlers
    ):
        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
            delay=True,
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    return log_path


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def log_exception(context: str, exc: BaseException) -> None:
    logger = get_logger()
    logger.error(context, exc_info=(type(exc), exc, exc.__traceback__))
    for handler in logger.handlers:
        handler.flush()
        if isinstance(handler, RotatingFileHandler):
            handler.close()


def install_global_exception_hook() -> None:
    previous = sys.excepthook

    def _hook(exc_type, exc, traceback):  # type: ignore[no-untyped-def]
        logging.getLogger(LOGGER_NAME).error(
            "unhandled exception",
            exc_info=(exc_type, exc, traceback),
        )
        previous(exc_type, exc, traceback)

    sys.excepthook = _hook
