"""Windows startup registration for Desktop Cleaner."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DesktopCleaner"


@dataclass(frozen=True)
class StartupResult:
    success: bool
    message: str = ""

    def __bool__(self) -> bool:
        return self.success


class StartupService:
    def __init__(
        self,
        *,
        platform_name: str | None = None,
        registry: object | None = None,
    ) -> None:
        self._platform = platform_name or sys.platform
        self._registry = registry

    def set_enabled(self, enabled: bool, exe_path: Path) -> StartupResult:
        if self._platform != "win32":
            return StartupResult(False, "startup registration is unsupported on this platform")
        if enabled and exe_path.suffix.lower() != ".exe":
            return StartupResult(False, "startup executable must be a .exe file")
        registry = self._registry
        if registry is None:
            import winreg as registry  # type: ignore[no-redef]

        try:
            with registry.OpenKey(
                registry.HKEY_CURRENT_USER,
                RUN_KEY,
                0,
                registry.KEY_SET_VALUE,
            ) as key:
                if enabled:
                    registry.SetValueEx(
                        key,
                        VALUE_NAME,
                        0,
                        registry.REG_SZ,
                        f'"{exe_path}"',
                    )
                else:
                    try:
                        registry.DeleteValue(key, VALUE_NAME)
                    except FileNotFoundError:
                        pass
        except OSError as exc:
            return StartupResult(False, str(exc))
        return StartupResult(True, "")
