from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.services.updates import (
    UpdateError,
    UpdateInfo,
    UpdateService,
    is_newer_version,
)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class FakeOpener:
    def __init__(self, responses: list[bytes]) -> None:
        self._responses = list(responses)
        self.requests: list[str] = []

    def __call__(self, request: object, timeout: float = 0) -> FakeResponse:
        url = getattr(request, "full_url", str(request))
        self.requests.append(url)
        if not self._responses:
            raise AssertionError(f"Unexpected request: {url}")
        return FakeResponse(self._responses.pop(0))


def release_payload(version: str, *, assets: list[dict[str, str]]) -> bytes:
    return json.dumps(
        {
            "tag_name": version,
            "html_url": f"https://example.test/releases/{version}",
            "body": "notes",
            "assets": assets,
        }
    ).encode("utf-8")


class UpdateServiceTests(unittest.TestCase):
    def test_version_comparison_accepts_v_prefix(self) -> None:
        self.assertTrue(is_newer_version("v1.0.13", "1.0.12"))
        self.assertFalse(is_newer_version("1.0.12", "v1.0.12"))
        self.assertFalse(is_newer_version("v1.0.11", "1.0.12"))

    def test_check_latest_requires_desktop_cleaner_asset(self) -> None:
        opener = FakeOpener(
            [
                release_payload(
                    "v1.0.13",
                    assets=[{"name": "not-the-app.zip", "browser_download_url": "https://asset"}],
                )
            ]
        )
        service = UpdateService(current_version="1.0.12", opener=opener)

        with self.assertRaisesRegex(UpdateError, "DesktopCleaner.exe"):
            service.check_latest()

    def test_check_latest_reports_available_only_for_newer_release(self) -> None:
        opener = FakeOpener(
            [
                release_payload(
                    "v1.0.13",
                    assets=[
                        {
                            "name": "DesktopCleaner.exe",
                            "browser_download_url": "https://asset/app.exe",
                        }
                    ],
                )
            ]
        )
        service = UpdateService(current_version="1.0.12", opener=opener)

        update = service.check_latest()

        self.assertTrue(update.available)
        self.assertEqual(update.latest_version, "1.0.13")
        self.assertEqual(update.asset_url, "https://asset/app.exe")

    def test_download_writes_temp_then_renames_versioned_exe(self) -> None:
        with TemporaryDirectory() as tmp:
            opener = FakeOpener([b"new-exe"])
            service = UpdateService(
                current_version="1.0.12",
                updates_dir=Path(tmp),
                opener=opener,
            )
            update = UpdateInfo(
                current_version="1.0.12",
                latest_version="1.0.13",
                release_url="https://release",
                asset_url="https://asset/app.exe",
                available=True,
            )

            result = service.download(update)

            self.assertEqual(result.path, Path(tmp) / "DesktopCleaner-v1.0.13.exe")
            self.assertEqual(result.path.read_bytes(), b"new-exe")
            self.assertFalse(result.path.with_suffix(".exe.tmp").exists())

    def test_prepare_replace_script_waits_copies_and_restarts(self) -> None:
        with TemporaryDirectory() as tmp:
            service = UpdateService(current_version="1.0.12", updates_dir=Path(tmp))
            downloaded = Path(tmp) / "DesktopCleaner-v1.0.13.exe"
            current = Path(tmp) / "DesktopCleaner.exe"

            script = service.prepare_replace(downloaded, current)
            text = script.read_text(encoding="utf-8")

            self.assertIn("tasklist", text)
            self.assertIn("copy /Y", text)
            self.assertIn(str(downloaded), text)
            self.assertIn(str(current), text)
            self.assertIn('start ""', text)


if __name__ == "__main__":
    unittest.main()
