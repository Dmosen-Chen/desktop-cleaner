"""Read-only desktop item icons for the Qt item grid."""

from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QFileInfo, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from desktop_tidy.services.logging_setup import log_exception

IMAGE_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
        ".svg",
    }
)


class WindowsShellIconProvider:
    """Best-effort Windows shell icon extraction for shortcuts and file types."""

    def icon_for(self, path: Path, size: int = 64) -> QIcon | None:
        if sys.platform != "win32":
            return None
        try:
            if path.suffix.casefold() == ".lnk":
                shortcut_icon = self._shortcut_icon(path, size)
                if shortcut_icon is not None and not shortcut_icon.isNull():
                    return shortcut_icon
            shell_icon = self._shell_icon(path, size)
            if shell_icon is not None and not shell_icon.isNull():
                return shell_icon
        except Exception as exc:  # pragma: no cover - depends on local shell state.
            log_exception(f"extract shell icon for {path}", exc)
        return None

    def _shortcut_icon(self, path: Path, size: int) -> QIcon | None:
        try:
            import win32com.client  # type: ignore[import-not-found]
        except Exception:
            return None
        shortcut = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(path))
        raw_icon = str(getattr(shortcut, "IconLocation", "") or "").strip()
        candidates: list[tuple[Path, int]] = []
        if raw_icon:
            icon_path, _, raw_index = raw_icon.partition(",")
            try:
                index = int(raw_index.strip() or "0")
            except ValueError:
                index = 0
            candidates.append((Path(icon_path.strip().strip('"')), index))
        target = str(getattr(shortcut, "TargetPath", "") or "").strip()
        if target:
            candidates.append((Path(target), 0))
        for candidate, index in candidates:
            icon = self._extract_icon(candidate, index, size)
            if icon is not None and not icon.isNull():
                return icon
        return None

    def _shell_icon(self, path: Path, size: int) -> QIcon | None:
        try:
            import win32com.shell.shell as shell  # type: ignore[import-not-found]
            import win32gui  # type: ignore[import-not-found]
        except Exception:
            return None
        flags = 0x000000100  # SHGFI_ICON
        flags |= 0 if size >= 32 else 0x000000001  # SHGFI_SMALLICON
        hicon = 0
        try:
            hicon, *_ = shell.SHGetFileInfo(str(path), 0, flags)
            return self._icon_from_hicon(hicon, size)
        finally:
            if hicon:
                try:
                    win32gui.DestroyIcon(hicon)
                except Exception:
                    pass

    def _extract_icon(self, path: Path, index: int, size: int) -> QIcon | None:
        if not str(path):
            return None
        try:
            import win32gui  # type: ignore[import-not-found]
        except Exception:
            return None
        large_icons: list[int] = []
        small_icons: list[int] = []
        try:
            large_icons, small_icons = win32gui.ExtractIconEx(str(path), index, 1)
            handles = large_icons if size >= 32 else small_icons
            if not handles:
                handles = small_icons or large_icons
            if not handles:
                return None
            return self._icon_from_hicon(handles[0], size)
        finally:
            for handle in list(large_icons) + list(small_icons):
                try:
                    win32gui.DestroyIcon(handle)
                except Exception:
                    pass

    def _icon_from_hicon(self, hicon: int, size: int) -> QIcon | None:
        if not hicon:
            return None
        from_hicon = getattr(QImage, "fromHICON", None)
        if from_hicon is None:
            return None
        image = from_hicon(hicon)
        if image.isNull():
            return None
        pixmap = QPixmap.fromImage(image).scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return QIcon(pixmap) if not pixmap.isNull() else None


class ItemVisualProvider:
    """Loads native or thumbnail icons without mutating source files."""

    def __init__(self, shell_provider: object | None = None) -> None:
        self.icons = QFileIconProvider()
        self.shell_provider = shell_provider if shell_provider is not None else WindowsShellIconProvider()
        self._cache: dict[tuple[str, int, int, int], QIcon] = {}

    def icon_for(self, path: Path, size: int = 64) -> QIcon:
        key = self._cache_key(path, size)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        icon = self._load_icon(path, size)
        self._cache[key] = icon
        return icon

    def _load_icon(self, path: Path, size: int) -> QIcon:
        if path.suffix.casefold() in IMAGE_EXTENSIONS:
            pixmap = QPixmap(str(path)).scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            if not pixmap.isNull():
                return QIcon(pixmap)
        shell_icon = self._shell_icon(path, size)
        if shell_icon is not None and not shell_icon.isNull():
            return shell_icon
        qt_icon = self.icons.icon(QFileInfo(str(path)))
        if not qt_icon.isNull():
            return qt_icon
        return self._fallback_icon(path, size)

    def _shell_icon(self, path: Path, size: int) -> QIcon | None:
        icon_for = getattr(self.shell_provider, "icon_for", None)
        if icon_for is None:
            return None
        try:
            return icon_for(path, size)
        except Exception as exc:
            log_exception(f"extract visual icon for {path}", exc)
            return None

    def _fallback_icon(self, path: Path, size: int) -> QIcon:
        pixmap = QPixmap(size, size)
        color = QColor("#4a6fa5")
        suffix = path.suffix.casefold()
        if path.is_dir():
            color = QColor("#c99a42")
            label = "DIR"
        elif suffix in {".lnk", ".url", ".exe", ".msi"}:
            color = QColor("#6b67d8")
            label = "APP"
        elif suffix in {".zip", ".rar", ".7z"}:
            color = QColor("#b46a42")
            label = "ZIP"
        elif suffix in {".pdf"}:
            color = QColor("#d93737")
            label = "PDF"
        else:
            label = (suffix[1:4] if suffix else "FILE").upper()
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(2, 2, size - 4, size - 4, 8, 8)
        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(max(10, int(size * 0.22)))
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, label)
        painter.end()
        return QIcon(pixmap)

    def _cache_key(self, path: Path, size: int) -> tuple[str, int, int, int]:
        try:
            stat = path.stat()
            mtime = int(stat.st_mtime_ns)
            file_size = int(stat.st_size)
        except OSError:
            mtime = 0
            file_size = 0
        return (str(path), mtime, file_size, int(size))
