"""Resolve the user's actual desktop directory for first-run configuration."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
from typing import Callable


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


_FOLDERID_DESKTOP = _GUID(
    0xB4BFCC3A,
    0xDB2C,
    0x424C,
    (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41),
)
DesktopProvider = Callable[[], Path | str | None]


def windows_known_folder_desktop() -> Path | None:
    """Return the Windows Known Folder desktop path when the API is available."""
    if os.name != "nt":
        return None
    allocated = ctypes.c_void_p()
    try:
        shell32 = ctypes.windll.shell32
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        result = shell32.SHGetKnownFolderPath(
            ctypes.byref(_FOLDERID_DESKTOP), 0, None, ctypes.byref(allocated)
        )
        if result != 0 or not allocated.value:
            return None
        return Path(ctypes.wstring_at(allocated.value))
    except (AttributeError, OSError):
        return None
    finally:
        if allocated.value:
            ole32 = ctypes.windll.ole32
            ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ole32.CoTaskMemFree(allocated)


def _is_accessible_directory(path: Path) -> bool:
    try:
        return path.is_dir() and os.access(path, os.R_OK)
    except OSError:
        return False


def _fallback_candidates(home: Path) -> list[Path]:
    candidates = [home / "Desktop", home / "\u684c\u9762"]
    one_drive_roots = [home / "OneDrive"]
    for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        value = os.environ.get(key)
        if value:
            one_drive_roots.append(Path(value))
    for root in one_drive_roots:
        candidates.extend((root / "Desktop", root / "\u684c\u9762"))
    return candidates


def resolve_desktop_path(
    *, known_folder_provider: DesktopProvider | None = None, home: Path | None = None
) -> Path:
    """Select the configured desktop path without persisting machine-specific data."""
    provider = known_folder_provider or windows_known_folder_desktop
    try:
        known_folder = provider()
    except OSError:
        known_folder = None
    if known_folder:
        return Path(known_folder)

    resolved_home = Path.home() if home is None else Path(home)
    for candidate in _fallback_candidates(resolved_home):
        if _is_accessible_directory(candidate):
            return candidate
    return resolved_home / "Desktop"
