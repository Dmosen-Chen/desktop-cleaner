"""Shared pytest hooks for desktop_tidy."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_active_desktop_applications() -> None:
    yield
    from desktop_tidy.application import _active_desktop_apps

    _active_desktop_apps.clear()
