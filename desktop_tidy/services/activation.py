"""Local activation channel used by duplicate launches."""

from __future__ import annotations

import time

from PySide6.QtCore import QIODevice, QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


ACTIVATION_SERVER_NAME = "DesktopCleanerActivation"
SHOW_COMMAND = b"show\n"


def notify_existing_instance(
    *,
    server_name: str = ACTIVATION_SERVER_NAME,
    timeout_ms: int = 1500,
) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while True:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        socket = QLocalSocket()
        socket.connectToServer(server_name, QIODevice.OpenModeFlag.WriteOnly)
        if socket.waitForConnected(min(100, remaining_ms)):
            queued = socket.write(SHOW_COMMAND)
            socket.flush()
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socket.waitForBytesWritten(remaining_ms)
            socket.disconnectFromServer()
            return queued == len(SHOW_COMMAND)
        socket.abort()
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


class ActivationServer(QObject):
    activated = Signal()

    def __init__(
        self,
        *,
        server_name: str = ACTIVATION_SERVER_NAME,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._server_name = server_name
        self._server = QLocalServer(self)
        self._sockets: list[QLocalSocket] = []
        QLocalServer.removeServer(server_name)
        self._server.newConnection.connect(self._on_new_connection)
        self._server.listen(server_name)

    def close(self) -> None:
        self._server.close()
        QLocalServer.removeServer(self._server_name)

    def is_listening(self) -> bool:
        return self._server.isListening()

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            self._sockets.append(socket)
            self.activated.emit()
            socket.readyRead.connect(lambda socket=socket: self._read_command(socket))
            socket.disconnected.connect(lambda socket=socket: self._read_if_available(socket))
            socket.disconnected.connect(lambda socket=socket: self._forget_socket(socket))
            socket.disconnected.connect(socket.deleteLater)
            if not socket.bytesAvailable():
                socket.waitForReadyRead(50)
            if socket.bytesAvailable():
                self._read_command(socket)
            else:
                QTimer.singleShot(25, lambda socket=socket: self._read_if_available(socket))

    def _read_command(self, socket: QLocalSocket) -> None:
        command = bytes(socket.readAll())
        socket.disconnectFromServer()

    def _read_if_available(self, socket: QLocalSocket) -> None:
        try:
            if socket.bytesAvailable():
                self._read_command(socket)
        except RuntimeError:
            return

    def _forget_socket(self, socket: QLocalSocket) -> None:
        if socket in self._sockets:
            self._sockets.remove(socket)
