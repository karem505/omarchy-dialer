#!/usr/bin/env python3
"""Replay a canned event sequence on the dialer socket for UI work."""
from __future__ import annotations

import os
import socket
import sys

SCRIPTS = {
    "idle": [
        '{"ev":"gateway","connected":true,"address":"AA:BB:CC:DD:EE:FF","name":"Example Phone"}',
        '{"ev":"transport","state":"idle","codec":0}',
    ],
    "incoming": [
        '{"ev":"gateway","connected":true,"name":"Example Phone"}',
        '{"ev":"call","id":"call1","state":"incoming","line":"+201000000001"}',
    ],
    "active": [
        '{"ev":"gateway","connected":true,"name":"Example Phone"}',
        '{"ev":"call","id":"call1","state":"active","line":"+201000000001"}',
        '{"ev":"transport","state":"active","codec":2}',
    ],
    "incoming-known": [
        '{"ev":"gateway","connected":true,"name":"Example Phone"}',
        '{"ev":"contacts","available":true,"count":1,"items":[{"name":"\u0623\u062d\u0645\u062f","number":"+201000000001"}]}',
        '{"ev":"call","id":"call1","state":"incoming","line":"+201000000001"}',
    ],
    "demo": [
        '{"ev":"gateway","connected":true,"address":"AA:BB:CC:DD:EE:FF","name":"Example Phone"}',
        '{"ev":"transport","state":"idle","codec":0}',
        '{"ev":"contacts","available":true,"count":4,"items":['
        '{"name":"Alex Rivera","number":"+15550100"},'
        '{"name":"Dana Brooks","number":"+15550142"},'
        '{"name":"Sam Okafor","number":"+15550177"},'
        '{"name":"Priya Nair","number":"+15550188"}]}',
    ],
    "demo-active": [
        '{"ev":"gateway","connected":true,"address":"AA:BB:CC:DD:EE:FF","name":"Example Phone"}',
        '{"ev":"contacts","available":true,"count":4,"items":['
        '{"name":"Alex Rivera","number":"+15550100"},'
        '{"name":"Dana Brooks","number":"+15550142"},'
        '{"name":"Sam Okafor","number":"+15550177"},'
        '{"name":"Priya Nair","number":"+15550188"}]}',
        '{"ev":"call","id":"call1","state":"active","line":"+15550100","name":"Alex Rivera"}',
        '{"ev":"transport","state":"active","codec":2}',
    ],
    "demo-incoming": [
        '{"ev":"gateway","connected":true,"address":"AA:BB:CC:DD:EE:FF","name":"Example Phone"}',
        '{"ev":"contacts","available":true,"count":4,"items":['
        '{"name":"Alex Rivera","number":"+15550100"},'
        '{"name":"Dana Brooks","number":"+15550142"}]}',
        '{"ev":"call","id":"call1","state":"incoming","line":"+15550142","name":"Dana Brooks"}',
    ],
    "offline": ['{"ev":"gateway","connected":false}'],
}


def main() -> int:
    script = SCRIPTS[sys.argv[1] if len(sys.argv) > 1 else "idle"]
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "omarchy-dialer.sock")
    if os.path.exists(path):
        os.unlink(path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    os.chmod(path, 0o600)
    srv.listen(4)
    print(f"fake daemon on {path} -> {sys.argv[1:] or ['idle']}", flush=True)
    try:
        while True:
            conn, _ = srv.accept()
            for line in script:
                conn.sendall((line + "\n").encode())
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                print("<-", data.decode().strip(), flush=True)
    except KeyboardInterrupt:
        return 0
    finally:
        srv.close()
        if os.path.exists(path):
            os.unlink(path)


if __name__ == "__main__":
    sys.exit(main())
