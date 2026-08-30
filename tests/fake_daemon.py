#!/usr/bin/env python3
"""Replay a canned event sequence on the dialer socket for UI work."""
from __future__ import annotations

import os
import socket
import sys
import time

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

    # A ringing call the way the phone actually reports one: the number
    # arrives first and the caller's name trickles in afterwards. Every
    # update used to undo a dismissal, so "Later" had to be pressed once per
    # update before the card would stay down.
    "chatty-incoming": [
        '{"ev":"gateway","connected":true,"name":"Example Phone"}',
        '{"ev":"call","id":"call1","state":"incoming","line":"+15550142"}',
        (3, '{"ev":"call","id":"call1","state":"incoming","line":"+15550142","name":"Dana Brooks"}'),
        (6, '{"ev":"transport","state":"pending","codec":2}'),
        (9, '{"ev":"call","id":"call1","state":"waiting","line":"+15550142","name":"Dana Brooks"}'),
    ],

    # An answered call that started 90s ago, for the status bar's timer.
    "answered": [
        '{"ev":"gateway","connected":true,"address":"AA:BB:CC:DD:EE:FF","name":"Example Phone"}',
        '{"ev":"transport","state":"active","codec":2}',
        lambda: '{"ev":"call","id":"call1","state":"active","line":"+15550100",'
                '"name":"Alex Rivera","started":%.1f}' % (time.time() - 90),
    ],

    # Ring, then connect: the handover the user lost the UI on. The card
    # gives way to the status bar rather than to nothing at all.
    "answer-flow": [
        '{"ev":"gateway","connected":true,"name":"Example Phone"}',
        '{"ev":"call","id":"call1","state":"incoming","line":"+15550142","name":"Dana Brooks"}',
        (5, '{"ev":"transport","state":"active","codec":2}'),
        (5, lambda: '{"ev":"call","id":"call1","state":"active","line":"+15550142",'
                    '"name":"Dana Brooks","started":%.1f}' % time.time()),
    ],

    # The same call, adopted mid-flight: no start time, so no duration.
    "answered-adopted": [
        '{"ev":"gateway","connected":true,"name":"Example Phone"}',
        '{"ev":"transport","state":"active","codec":0}',
        '{"ev":"call","id":"call1","state":"active","line":"+15550100","name":"Alex Rivera"}',
    ],
}


def normalise(entry):
    """Entries are a line, a callable returning one, or (delay, either)."""
    delay, payload = entry if isinstance(entry, tuple) else (0, entry)
    return delay, payload


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
            start = time.monotonic()
            try:
                for entry in script:
                    delay, payload = normalise(entry)
                    remaining = delay - (time.monotonic() - start)
                    if remaining > 0:
                        time.sleep(remaining)
                    line = payload() if callable(payload) else payload
                    conn.sendall((line + "\n").encode())
                while True:
                    data = conn.recv(4096)
                    if not data:
                        break
                    print("<-", data.decode().strip(), flush=True)
            except (BrokenPipeError, ConnectionResetError):
                # A UI closing mid-script is normal here; wait for the next.
                print("-- client went away", flush=True)
            finally:
                conn.close()
    except KeyboardInterrupt:
        return 0
    finally:
        srv.close()
        if os.path.exists(path):
            os.unlink(path)


if __name__ == "__main__":
    sys.exit(main())
