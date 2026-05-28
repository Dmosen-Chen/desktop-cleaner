"""Manual update checks backed by GitHub Releases."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from desktop_tidy.version import APP_NAME, APP_VERSION, GITHUB_REPOSITORY

_ASSET_NAME = "DesktopCleaner.exe"


class UpdateError(RuntimeError):
    """Raised when checking, downloading, or preparing an update fails."""


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    asset_url: str
    available: bool
    asset_name: str = _ASSET_NAME
    notes: str = ""


@dataclass(frozen=True)
class DownloadResult:
    version: str
    path: Path


def _version_parts(value: str) -> tuple[int, ...]:
    normalized = value.strip()
    if normalized.lower().startswith("v"):
        normalized = normalized[1:]
    parts = re.split(r"[.\-+]", normalized)
    numeric: list[int] = []
    for part in parts:
        if not part:
            continue
        match = re.match(r"(\d+)", part)
        if match is None:
            numeric.append(0)
            continue
        numeric.append(int(match.group(1)))
    return tuple(numeric or [0])


def normalize_version(value: str) -> str:
    parts = _version_parts(value)
    return ".".join(str(part) for part in parts)


def is_newer_version(remote: str, current: str) -> bool:
    remote_parts = list(_version_parts(remote))
    current_parts = list(_version_parts(current))
    width = max(len(remote_parts), len(current_parts))
    remote_parts.extend([0] * (width - len(remote_parts)))
    current_parts.extend([0] * (width - len(current_parts)))
    return tuple(remote_parts) > tuple(current_parts)


def default_updates_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME
    return base / "updates"


class UpdateService:
    def __init__(
        self,
        *,
        repo: str = GITHUB_REPOSITORY,
        current_version: str = APP_VERSION,
        updates_dir: Path | None = None,
        opener: Callable[[object, float], object] | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.repo = repo
        self.current_version = current_version
        self.updates_dir = updates_dir or default_updates_dir()
        self._opener = opener or urlopen
        self.timeout = timeout

    def check_latest(self) -> UpdateInfo:
        url = f"https://api.github.com/repos/{self.repo}/releases/latest"
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"{APP_NAME}/{self.current_version}",
            },
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise UpdateError(f"检查更新失败：{exc}") from exc

        latest_version = normalize_version(str(payload.get("tag_name", "")))
        if not latest_version or latest_version == "0":
            raise UpdateError("最新发布没有有效版本号。")

        asset_url = ""
        for asset in payload.get("assets", []):
            if asset.get("name") == _ASSET_NAME:
                asset_url = str(asset.get("browser_download_url") or "")
                break
        if not asset_url:
            raise UpdateError(f"最新发布中没有 {_ASSET_NAME} 附件。")

        return UpdateInfo(
            current_version=normalize_version(self.current_version),
            latest_version=latest_version,
            release_url=str(payload.get("html_url") or ""),
            asset_url=asset_url,
            available=is_newer_version(latest_version, self.current_version),
            notes=str(payload.get("body") or ""),
        )

    def download(self, update: UpdateInfo) -> DownloadResult:
        if not update.asset_url:
            raise UpdateError("没有可下载的更新附件。")
        self.updates_dir.mkdir(parents=True, exist_ok=True)
        final_path = self.updates_dir / f"DesktopCleaner-v{update.latest_version}.exe"
        temp_path = final_path.with_suffix(final_path.suffix + ".tmp")
        request = Request(
            update.asset_url,
            headers={"User-Agent": f"{APP_NAME}/{self.current_version}"},
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                with temp_path.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            temp_path.replace(final_path)
        except Exception as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise UpdateError(f"下载更新失败：{exc}") from exc
        return DownloadResult(version=update.latest_version, path=final_path)

    def prepare_replace(self, downloaded_exe: Path, current_exe: Path) -> Path:
        self.updates_dir.mkdir(parents=True, exist_ok=True)
        script_path = self.updates_dir / "replace-and-restart.cmd"
        pid = os.getpid()
        script = "\n".join(
            [
                "@echo off",
                "setlocal",
                f'set "SOURCE={downloaded_exe}"',
                f'set "TARGET={current_exe}"',
                f'set "PID={pid}"',
                ":wait",
                'tasklist /FI "PID eq %PID%" | find "%PID%" >nul',
                "if not errorlevel 1 (",
                "  timeout /t 1 /nobreak >nul",
                "  goto wait",
                ")",
                'copy /Y "%SOURCE%" "%TARGET%"',
                "if errorlevel 1 exit /b 1",
                'start "" "%TARGET%"',
                "exit /b 0",
                "",
            ]
        )
        script_path.write_text(script, encoding="utf-8")
        return script_path

