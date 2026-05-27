"""Diagnostics and safe recovery helpers for the desktop cleaner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import zipfile

from desktop_tidy.domain.models import Configuration
from desktop_tidy.services.desktop_takeover import TakeoverResult
from desktop_tidy.services.logging_setup import log_exception


@dataclass(frozen=True)
class RecoveryResult:
    success: bool
    message: str
    details: str = ""


@dataclass(frozen=True)
class DiagnosticsSnapshot:
    desktop_path: str
    config_path: str
    history_path: str
    log_path: str
    executable_path: str
    takeover_enabled: bool
    restore_required: bool
    explorer_icons_hidden: bool
    explorer_icons_visible: bool | None
    group_count: int
    tab_count: int
    panel_window_count: int
    primary_screen_id: str
    process_id: int
    frozen: bool
    recent_errors: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DiagnosticsService:
    """Collect local status, logs, export bundles, and run safe recovery actions."""

    def __init__(
        self,
        config: Configuration,
        *,
        config_path: Path,
        history_path: Path,
        takeover_service: object,
        executable_path_provider: Callable[[], Path] | None = None,
        panel_handles_provider: Callable[[], list[int]] | None = None,
        panel_window_count_provider: Callable[[], int] | None = None,
        config_saver: Callable[[], None] | None = None,
    ) -> None:
        self.config = config
        self.config_path = Path(config_path)
        self.history_path = Path(history_path)
        self.log_dir = self.config_path.parent / "logs"
        self.log_path = self.log_dir / "desktop-cleaner.log"
        self.takeover_service = takeover_service
        self._executable_path_provider = executable_path_provider or self._default_executable_path
        self._panel_handles_provider = panel_handles_provider or (lambda: [])
        self._panel_window_count_provider = panel_window_count_provider or (
            lambda: len(self._panel_handles_provider())
        )
        self._config_saver = config_saver or (lambda: None)

    def collect_snapshot(self) -> DiagnosticsSnapshot:
        recent_logs = self.read_recent_logs(200)
        recent_errors = [
            line
            for line in recent_logs
            if " ERROR " in line or "Traceback" in line or "Exception" in line
        ][-8:]
        return DiagnosticsSnapshot(
            desktop_path=self.config.desktop.path,
            config_path=str(self.config_path),
            history_path=str(self.history_path),
            log_path=str(self.log_path),
            executable_path=str(self._safe_executable_path()),
            takeover_enabled=self.config.desktop.takeover_enabled,
            restore_required=self.config.desktop.restore_required,
            explorer_icons_hidden=self.config.desktop.explorer_icons_hidden,
            explorer_icons_visible=self._explorer_icons_visible(),
            group_count=len(self.config.panel_groups),
            tab_count=len(self.config.panel_tabs),
            panel_window_count=self._safe_panel_window_count(),
            primary_screen_id=self.config.desktop.primary_screen_id,
            process_id=os.getpid(),
            frozen=bool(getattr(sys, "frozen", False)),
            recent_errors=recent_errors,
        )

    def read_recent_logs(self, max_lines: int) -> list[str]:
        if max_lines <= 0 or not self.log_path.is_file():
            return []
        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            log_exception("read diagnostics log", exc)
            return []
        return lines[-max_lines:]

    def export_bundle(self, target_dir: Path) -> Path:
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        bundle = target_dir / f"desktop-cleaner-diagnostics-{timestamp}.zip"
        snapshot = self.collect_snapshot()
        try:
            with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "diagnostics.json",
                    json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
                )
                self._write_file_if_exists(archive, self.config_path, "config.json")
                self._write_file_if_exists(archive, self.history_path, "layout-history.json")
                for log_file in sorted(self.log_dir.glob("desktop-cleaner.log*")):
                    self._write_file_if_exists(archive, log_file, f"logs/{log_file.name}")
        except Exception as exc:
            log_exception("export diagnostics bundle", exc)
            raise
        return bundle

    def restore_desktop_icons(self) -> RecoveryResult:
        restored = bool(self.takeover_service.restore_explorer_icons())
        if restored:
            self.config.desktop.restore_required = False
            self.config.desktop.explorer_icons_hidden = False
            self._safe_save()
            return RecoveryResult(True, "已恢复 Explorer 桌面图标")
        self.config.desktop.restore_required = True
        self._safe_save()
        return RecoveryResult(False, "恢复 Explorer 桌面图标失败", "下次启动会继续尝试恢复")

    def refresh_takeover_if_enabled(self) -> RecoveryResult:
        if not self.config.desktop.takeover_enabled:
            return RecoveryResult(False, "桌面接管未启用")
        restored = bool(self.takeover_service.restore_explorer_icons())
        self.takeover_service.detach_panels()
        if not restored:
            self.config.desktop.restore_required = True
            self._safe_save()
            return RecoveryResult(False, "刷新桌面接管失败", "恢复 Explorer 图标失败")
        self.config.desktop.restore_required = False
        self.config.desktop.explorer_icons_hidden = False
        result = self.takeover_service.attach_panels(self._panel_handles_provider())
        if not getattr(result, "success", False):
            self._safe_save()
            return RecoveryResult(
                False,
                "刷新桌面接管失败",
                str(getattr(result, "message", "")),
            )
        self.config.desktop.restore_required = True
        self.config.desktop.explorer_icons_hidden = False
        self._safe_save()
        if not self.takeover_service.hide_explorer_icons():
            self.takeover_service.restore_explorer_icons()
            self.takeover_service.detach_panels()
            self.config.desktop.restore_required = True
            self.config.desktop.explorer_icons_hidden = False
            self._safe_save()
            return RecoveryResult(False, "刷新桌面接管失败", "隐藏 Explorer 图标失败")
        self.config.desktop.explorer_icons_hidden = True
        self._safe_save()
        return RecoveryResult(True, "已刷新桌面接管")

    def _explorer_icons_visible(self) -> bool | None:
        visible = getattr(self.takeover_service, "explorer_icons_visible", None)
        if visible is None:
            return None
        try:
            return visible()
        except Exception as exc:
            log_exception("read explorer icon visibility", exc)
            return None

    def _safe_executable_path(self) -> Path:
        try:
            return Path(self._executable_path_provider()).resolve()
        except Exception as exc:
            log_exception("read executable path for diagnostics", exc)
            return Path(sys.executable)

    def _safe_panel_window_count(self) -> int:
        try:
            return int(self._panel_window_count_provider())
        except Exception as exc:
            log_exception("read panel window count for diagnostics", exc)
            return 0

    def _safe_save(self) -> None:
        try:
            self._config_saver()
        except Exception as exc:
            log_exception("save diagnostics recovery state", exc)

    @staticmethod
    def _default_executable_path() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable)
        return Path(sys.argv[0] or sys.executable)

    @staticmethod
    def _write_file_if_exists(
        archive: zipfile.ZipFile,
        path: Path,
        arcname: str,
    ) -> None:
        if path.is_file():
            archive.write(path, arcname)
