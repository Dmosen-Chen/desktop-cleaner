from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
import unittest
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtNetwork import QLocalServer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from desktop_tidy.services.activation import ActivationServer, notify_existing_instance


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


class ActivationServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = qt_app()

    def test_notify_existing_instance_emits_activation_signal(self) -> None:
        server_name = f"DesktopCleanerTest{uuid4().hex}"
        server = ActivationServer(server_name=server_name)
        self.addCleanup(server.close)
        spy = QSignalSpy(server.activated)
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")

        self.assertTrue(server.is_listening())
        client = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-c",
                (
                    "import sys; "
                    "from desktop_tidy.services.activation import notify_existing_instance; "
                    "sys.exit(0 if notify_existing_instance(server_name=sys.argv[1], timeout_ms=2000) else 2)"
                ),
                server_name,
            ],
            cwd=Path.cwd(),
            env=env,
        )
        deadline = time.monotonic() + 2
        while client.poll() is None and time.monotonic() < deadline:
            type(self).app.processEvents()
            QTest.qWait(10)
        if client.poll() is None:
            client.kill()
            self.fail("activation client did not exit")

        if spy.count() == 0:
            spy.wait(1000)
        self.assertEqual(client.returncode, 0)
        self.assertEqual(spy.count(), 1)

    def test_notify_existing_instance_returns_false_without_server(self) -> None:
        server_name = f"DesktopCleanerMissing{uuid4().hex}"
        QLocalServer.removeServer(server_name)

        self.assertFalse(notify_existing_instance(server_name=server_name, timeout_ms=20))


if __name__ == "__main__":
    unittest.main()
