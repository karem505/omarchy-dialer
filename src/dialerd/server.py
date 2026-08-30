from __future__ import annotations

import os
import selectors
import socket
import threading
from typing import Callable

from dialerd.protocol import ProtocolError, decode_command, encode_event
from dialerd.state import DialerState


class SocketServer:
    def __init__(self, path: str, state: DialerState, on_command: Callable[[dict], None],
                 extra_snapshot: Callable[[], list[str]] | None = None) -> None:
        self._path = path
        self._state = state
        self._on_command = on_command
        # Lets the daemon append state it owns (the contact book) to the
        # opening snapshot without the server knowing what it is.
        self._extra_snapshot = extra_snapshot
        self._clients: dict[socket.socket, bytes] = {}
        self._lock = threading.Lock()
        self._sel = selectors.DefaultSelector()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._listener: socket.socket | None = None

    def start(self) -> None:
        if os.path.exists(self._path):
            os.unlink(self._path)
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(self._path)
        os.chmod(self._path, 0o600)
        self._listener.listen(8)
        self._listener.setblocking(False)
        self._sel.register(self._listener, selectors.EVENT_READ, self._accept)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            for key, _ in self._sel.select(timeout=0.2):
                key.data(key.fileobj)

    def _accept(self, listener: socket.socket) -> None:
        conn, _ = listener.accept()
        conn.setblocking(False)
        with self._lock:
            self._clients[conn] = b""
        self._sel.register(conn, selectors.EVENT_READ, self._read)
        lines = self._state.snapshot()
        if self._extra_snapshot is not None:
            lines = lines + self._extra_snapshot()
        self._send(conn, lines)

    def _read(self, conn: socket.socket) -> None:
        try:
            chunk = conn.recv(4096)
        except OSError:
            chunk = b""
        if not chunk:
            return self._drop(conn)
        with self._lock:
            buffered = self._clients.get(conn, b"") + chunk
            lines = buffered.split(b"\n")
            self._clients[conn] = lines.pop()
        for raw in lines:
            if not raw.strip():
                continue
            try:
                self._on_command(decode_command(raw.decode()))
            except ProtocolError as exc:
                self._send(conn, [encode_event("error", cmd=None, message=str(exc))])

    def _send(self, conn: socket.socket, lines: list[str]) -> None:
        try:
            conn.sendall("".join(lines).encode())
        except OSError:
            self._drop(conn)

    def broadcast(self, lines: list[str]) -> None:
        if not lines:
            return
        with self._lock:
            targets = list(self._clients)
        for conn in targets:
            self._send(conn, lines)

    def _drop(self, conn: socket.socket) -> None:
        with self._lock:
            if conn not in self._clients:
                return
            del self._clients[conn]
        try:
            self._sel.unregister(conn)
        except (KeyError, ValueError):
            pass
        conn.close()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        for conn in list(self._clients):
            self._drop(conn)
        if self._listener:
            self._sel.unregister(self._listener)
            self._listener.close()
        if os.path.exists(self._path):
            os.unlink(self._path)
