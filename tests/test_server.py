from __future__ import annotations

import json
import os
import socket
import time

import pytest

from dialerd.state import DialerState
from dialerd.server import SocketServer


@pytest.fixture
def server(tmp_path):
    received: list[dict] = []
    path = str(tmp_path / "d.sock")
    state = DialerState()
    state.set_gateway("/org/pipewire/Telephony/ag1", "AA:BB:CC:DD:EE:FF", "Example Phone")
    srv = SocketServer(path, state, received.append)
    srv.start()
    yield srv, path, received
    srv.stop()


def connect(path):
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    c.connect(path)
    c.settimeout(3)
    return c


def readline(sock):
    buf = b""
    while not buf.endswith(b"\n"):
        buf += sock.recv(1)
    return json.loads(buf)


def test_socket_file_is_created_with_owner_only_mode(server):
    _, path, _ = server
    assert os.path.exists(path)
    assert oct(os.stat(path).st_mode)[-3:] == "600"


def test_new_client_receives_snapshot(server):
    _, path, _ = server
    c = connect(path)
    assert readline(c)["ev"] == "gateway"
    c.close()


def test_broadcast_reaches_all_clients(server):
    srv, path, _ = server
    a, b = connect(path), connect(path)
    readline(a); readline(b)  # drain snapshots
    srv.broadcast(['{"ev":"transport","state":"active"}\n'])
    assert readline(a)["state"] == "active"
    assert readline(b)["state"] == "active"
    a.close(); b.close()


def test_command_is_routed_to_handler(server):
    _, path, received = server
    c = connect(path)
    readline(c)
    c.sendall(b'{"cmd":"dial","number":"+20"}\n')
    deadline = time.time() + 3
    while not received and time.time() < deadline:
        time.sleep(0.01)
    assert received == [{"cmd": "dial", "number": "+20"}]
    c.close()


def test_malformed_command_returns_error_and_keeps_connection(server):
    _, path, received = server
    c = connect(path)
    readline(c)
    c.sendall(b"garbage\n")
    assert readline(c)["ev"] == "error"
    assert received == []
    c.close()


def test_client_disconnect_does_not_kill_server(server):
    srv, path, _ = server
    a = connect(path)
    readline(a)
    a.close()
    time.sleep(0.1)
    b = connect(path)
    assert readline(b)["ev"] == "gateway"
    b.close()


def test_stale_socket_file_is_replaced(tmp_path):
    path = str(tmp_path / "d.sock")
    open(path, "w").close()
    srv = SocketServer(path, DialerState(), lambda _: None)
    srv.start()
    try:
        c = connect(path)
        assert readline(c)["ev"] == "gateway"
        c.close()
    finally:
        srv.stop()


def test_extra_snapshot_is_sent_to_new_clients(tmp_path):
    path = str(tmp_path / "d.sock")
    srv = SocketServer(path, DialerState(), lambda _: None,
                       extra_snapshot=lambda: ['{"ev":"contacts","count":3}\n'])
    srv.start()
    try:
        c = connect(path)
        readline(c)  # gateway
        assert readline(c) == {"ev": "contacts", "count": 3}
        c.close()
    finally:
        srv.stop()
