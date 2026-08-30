# Omarchy Dialer (Calls) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Place, answer and end phone calls from the PC over the paired phone's cellular radio, with call audio on the PC's own microphone and speakers.

**Architecture:** A Python daemon (`omarchy-dialerd`) owns all D-Bus traffic with `org.pipewire.Telephony` and republishes it as newline-delimited JSON on a Unix socket. A standalone Quickshell QML application consumes that socket and renders the dialer. The socket is the only contract between them, so the UI is testable against a recorded transcript with no Bluetooth present.

**Tech Stack:** Python 3.14 + PyGObject (`gi.repository.Gio`/`GLib`) for D-Bus and the main loop; pytest for tests; Quickshell 0.3.1 (`Quickshell.Io` — `Socket`, `SplitParser`, `FileView`) for the UI.

**Spec:** `docs/superpowers/specs/2026-08-30-omarchy-dialer-design.md`

## Global Constraints

- **Scope is calls only.** Contacts and messaging are out of scope for this plan — spec phases 3 and 4 get their own plans. Do not add a contacts pane.
- **No new runtime dependencies.** `gi.repository` (PyGObject 3.56.3) is already installed and is the D-Bus binding. Do not add `dasbus`, `pydbus`, or `dbus-next`.
- **Bus name:** `org.pipewire.Telephony`. **Manager path:** `/org/pipewire/Telephony`.
- **Gateway interface:** `org.pipewire.Telephony.AudioGateway1`. **Transport:** `org.pipewire.Telephony.AudioGatewayTransport1`. **Call:** `org.pipewire.Telephony.Call1`.
- **Lifecycle signals** `CallAdded(oa{sv})` / `CallRemoved(o)` are emitted on interface `org.ofono.VoiceCallManager` at the *gateway* path, not the manager path. This is verified behaviour, not a guess.
- **Socket path:** `$XDG_RUNTIME_DIR/omarchy-dialer.sock`, mode `0600`.
- **Theme source:** `~/.local/state/omarchy/current/theme/colors.toml`. `current` is a symlink Omarchy repoints on theme change.
- **Target hardware for manual verification:** Example Phone, `AA:BB:CC:DD:EE:FF`.
- Every Python file starts with `from __future__ import annotations`.
- Commit after every task. Never commit with failing tests.

---

### Task 1: Project scaffold and protocol codec

The wire format between daemon and UI. Pure functions, no I/O, no D-Bus — this is the foundation every later task encodes against.

**Files:**
- Create: `pyproject.toml`
- Create: `src/dialerd/__init__.py`
- Create: `src/dialerd/protocol.py`
- Test: `tests/test_protocol.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `encode_event(kind: str, **fields) -> str` returning one NDJSON line ending in `\n`; `decode_command(line: str) -> dict` returning a parsed command dict; `ProtocolError(Exception)` raised on malformed input.

- [ ] **Step 1: Create the test environment**

A venv with `--system-site-packages` keeps the system PyGObject visible while
adding pytest, so no root access is needed.

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install pytest
```

All later `python3 -m pytest` commands in this plan run as
`.venv/bin/python -m pytest`.

- [ ] **Step 2: Create the project scaffold**

`pyproject.toml`:

```toml
[project]
name = "omarchy-dialerd"
version = "0.1.0"
requires-python = ">=3.12"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

Create empty `src/dialerd/__init__.py`.

- [ ] **Step 3: Write the failing test**

`tests/test_protocol.py`:

```python
from __future__ import annotations

import json

import pytest

from dialerd.protocol import ProtocolError, decode_command, encode_event


def test_encode_event_is_one_ndjson_line():
    line = encode_event("call", id="call1", state="active")
    assert line.endswith("\n")
    assert line.count("\n") == 1
    assert json.loads(line) == {"ev": "call", "id": "call1", "state": "active"}


def test_encode_event_drops_none_fields():
    line = encode_event("call", id="call1", name=None)
    assert json.loads(line) == {"ev": "call", "id": "call1"}


def test_decode_command_returns_dict():
    assert decode_command('{"cmd":"dial","number":"+201000000001"}') == {
        "cmd": "dial",
        "number": "+201000000001",
    }


def test_decode_command_rejects_malformed_json():
    with pytest.raises(ProtocolError):
        decode_command("not json")


def test_decode_command_requires_cmd_key():
    with pytest.raises(ProtocolError):
        decode_command('{"number":"+20"}')
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python3 -m pytest tests/test_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dialerd.protocol'`

- [ ] **Step 5: Write minimal implementation**

`src/dialerd/protocol.py`:

```python
from __future__ import annotations

import json
from typing import Any


class ProtocolError(Exception):
    """Raised when a peer sends something we cannot parse."""


def encode_event(kind: str, **fields: Any) -> str:
    payload = {"ev": kind}
    payload.update({k: v for k, v in fields.items() if v is not None})
    return json.dumps(payload, separators=(",", ":")) + "\n"


def decode_command(line: str) -> dict[str, Any]:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"malformed json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ProtocolError("command must be a json object")
    if "cmd" not in parsed:
        raise ProtocolError("command missing 'cmd' key")
    return parsed
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python3 -m pytest tests/test_protocol.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/dialerd/__init__.py src/dialerd/protocol.py tests/test_protocol.py
git commit -m "feat: add NDJSON protocol codec for the dialer socket"
```

---

### Task 2: Gateway and call state model

Turns raw D-Bus property dictionaries into the events the UI consumes, and answers "what is true right now" for a late-joining client. Pure — no bus, no socket.

**Files:**
- Create: `src/dialerd/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `encode_event` from Task 1.
- Produces: `DialerState` with `set_gateway(path: str | None, address: str | None, name: str | None) -> list[str]`, `set_transport(state: str, codec: int) -> list[str]`, `upsert_call(path: str, props: dict) -> list[str]`, `remove_call(path: str) -> list[str]`, and `snapshot() -> list[str]`. Every method returns already-encoded NDJSON lines. `call_id(path: str) -> str` returns the trailing segment (`/org/pipewire/Telephony/ag1/call1` -> `call1`).

- [ ] **Step 1: Write the failing test**

`tests/test_state.py`:

```python
from __future__ import annotations

import json

from dialerd.state import DialerState, call_id


def events(lines):
    return [json.loads(line) for line in lines]


def test_call_id_takes_trailing_segment():
    assert call_id("/org/pipewire/Telephony/ag1/call1") == "call1"


def test_set_gateway_emits_connected_event():
    st = DialerState()
    out = events(st.set_gateway("/org/pipewire/Telephony/ag1", "AA:BB:CC:DD:EE:FF", "Example Phone"))
    assert out == [{
        "ev": "gateway", "connected": True,
        "address": "AA:BB:CC:DD:EE:FF", "name": "Example Phone",
    }]


def test_clearing_gateway_emits_disconnected_and_drops_calls():
    st = DialerState()
    st.set_gateway("/org/pipewire/Telephony/ag1", "AA:BB:CC:DD:EE:FF", "Example Phone")
    st.upsert_call("/org/pipewire/Telephony/ag1/call1", {"State": "active", "LineIdentification": "+20"})
    out = events(st.set_gateway(None, None, None))
    assert {"ev": "call_removed", "id": "call1"} in out
    assert {"ev": "gateway", "connected": False} in out


def test_upsert_call_emits_call_event():
    st = DialerState()
    out = events(st.upsert_call(
        "/org/pipewire/Telephony/ag1/call1",
        {"State": "incoming", "LineIdentification": "+201000000001", "Name": ""},
    ))
    assert out == [{
        "ev": "call", "id": "call1",
        "state": "incoming", "line": "+201000000001",
    }]


def test_upsert_call_twice_emits_only_on_change():
    st = DialerState()
    props = {"State": "active", "LineIdentification": "+20"}
    st.upsert_call("/org/pipewire/Telephony/ag1/call1", props)
    assert st.upsert_call("/org/pipewire/Telephony/ag1/call1", props) == []


def test_partial_property_update_merges():
    st = DialerState()
    st.upsert_call("/org/pipewire/Telephony/ag1/call1", {"State": "dialing", "LineIdentification": "+20"})
    out = events(st.upsert_call("/org/pipewire/Telephony/ag1/call1", {"State": "active"}))
    assert out == [{"ev": "call", "id": "call1", "state": "active", "line": "+20"}]


def test_snapshot_replays_full_state():
    st = DialerState()
    st.set_gateway("/org/pipewire/Telephony/ag1", "AA:BB:CC:DD:EE:FF", "Example Phone")
    st.set_transport("active", 2)
    st.upsert_call("/org/pipewire/Telephony/ag1/call1", {"State": "active", "LineIdentification": "+20"})
    out = events(st.snapshot())
    assert {"ev": "gateway", "connected": True, "address": "AA:BB:CC:DD:EE:FF", "name": "Example Phone"} in out
    assert {"ev": "transport", "state": "active", "codec": 2} in out
    assert {"ev": "call", "id": "call1", "state": "active", "line": "+20"} in out


def test_snapshot_when_empty_reports_disconnected():
    assert events(DialerState().snapshot()) == [{"ev": "gateway", "connected": False}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dialerd.state'`

- [ ] **Step 3: Write minimal implementation**

`src/dialerd/state.py`:

```python
from __future__ import annotations

from typing import Any

from dialerd.protocol import encode_event


def call_id(path: str) -> str:
    return path.rsplit("/", 1)[-1]


class DialerState:
    """Authoritative view of the gateway and its calls.

    Every mutator returns the NDJSON lines describing what changed, so the
    server can broadcast without re-deriving anything.
    """

    def __init__(self) -> None:
        self._gateway_path: str | None = None
        self._address: str | None = None
        self._name: str | None = None
        self._transport: tuple[str, int] | None = None
        self._calls: dict[str, dict[str, Any]] = {}

    def set_gateway(self, path: str | None, address: str | None, name: str | None) -> list[str]:
        lines: list[str] = []
        if path is None:
            for call_path in list(self._calls):
                lines.extend(self.remove_call(call_path))
            self._transport = None
            self._gateway_path = self._address = self._name = None
            return lines + [encode_event("gateway", connected=False)]
        self._gateway_path, self._address, self._name = path, address, name
        return [encode_event("gateway", connected=True, address=address, name=name)]

    def set_transport(self, state: str, codec: int) -> list[str]:
        if self._transport == (state, codec):
            return []
        self._transport = (state, codec)
        return [encode_event("transport", state=state, codec=codec)]

    def upsert_call(self, path: str, props: dict[str, Any]) -> list[str]:
        merged = dict(self._calls.get(path, {}))
        merged.update(props)
        if merged == self._calls.get(path):
            return []
        self._calls[path] = merged
        return [self._call_event(path, merged)]

    def remove_call(self, path: str) -> list[str]:
        if self._calls.pop(path, None) is None:
            return []
        return [encode_event("call_removed", id=call_id(path))]

    def snapshot(self) -> list[str]:
        if self._gateway_path is None:
            return [encode_event("gateway", connected=False)]
        lines = [encode_event("gateway", connected=True, address=self._address, name=self._name)]
        if self._transport is not None:
            lines.append(encode_event("transport", state=self._transport[0], codec=self._transport[1]))
        lines.extend(self._call_event(p, props) for p, props in self._calls.items())
        return lines

    @staticmethod
    def _call_event(path: str, props: dict[str, Any]) -> str:
        return encode_event(
            "call",
            id=call_id(path),
            state=props.get("State"),
            line=props.get("LineIdentification") or None,
            name=props.get("Name") or None,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_state.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/dialerd/state.py tests/test_state.py
git commit -m "feat: add gateway and call state model"
```

---

### Task 3: PipeWire Telephony D-Bus adapter

Wraps `org.pipewire.Telephony` behind a narrow interface, with the bus injected so tests never touch a real one.

**Files:**
- Create: `src/dialerd/telephony.py`
- Test: `tests/test_telephony.py`

**Interfaces:**
- Consumes: `DialerState` from Task 2.
- Produces: `TelephonyAdapter(bus, state, emit)` where `bus` satisfies the `Bus` protocol below and `emit(lines: list[str]) -> None` publishes events. Methods: `start() -> None`, `dial(number: str) -> None`, `answer(call: str) -> None`, `hangup(call: str) -> None`, `send_tones(digits: str) -> None`, `set_volume(which: str, value: int) -> None`. `Bus` protocol: `call(name, path, iface, method, args) -> tuple`, `subscribe(iface, member, path, handler) -> None`, `get_managed_objects(name, path) -> dict`.

- [ ] **Step 1: Write the failing test**

`tests/test_telephony.py`:

```python
from __future__ import annotations

import json

import pytest

from dialerd.state import DialerState
from dialerd.telephony import GATEWAY_IFACE, TelephonyAdapter

AG = "/org/pipewire/Telephony/ag1"


class FakeBus:
    """Records calls and lets tests fire signals by hand."""

    def __init__(self, managed=None):
        self.calls: list[tuple] = []
        self.handlers: dict[tuple[str, str], list] = {}
        self._managed = managed or {}

    def call(self, name, path, iface, method, args):
        self.calls.append((path, iface, method, args))
        return ()

    def subscribe(self, iface, member, path, handler):
        self.handlers.setdefault((iface, member), []).append(handler)

    def get_managed_objects(self, name, path):
        return self._managed

    def fire(self, iface, member, *args):
        for h in self.handlers.get((iface, member), []):
            h(*args)


def managed_with_gateway():
    return {
        AG: {
            GATEWAY_IFACE: {"Address": "AA:BB:CC:DD:EE:FF"},
            "org.pipewire.Telephony.AudioGatewayTransport1": {"State": "idle", "Codec": 0},
        }
    }


def collect():
    out: list[dict] = []
    return out, lambda lines: out.extend(json.loads(l) for l in lines)


def test_start_discovers_existing_gateway():
    out, emit = collect()
    bus = FakeBus(managed_with_gateway())
    TelephonyAdapter(bus, DialerState(), emit).start()
    # _device_name returns the address, so "name" is always present too.
    assert {"ev": "gateway", "connected": True, "address": "AA:BB:CC:DD:EE:FF",
            "name": "AA:BB:CC:DD:EE:FF"} in out


def test_start_with_no_gateway_reports_disconnected():
    out, emit = collect()
    TelephonyAdapter(FakeBus({}), DialerState(), emit).start()
    assert {"ev": "gateway", "connected": False} in out


def test_dial_invokes_gateway_method():
    bus = FakeBus(managed_with_gateway())
    out, emit = collect()
    a = TelephonyAdapter(bus, DialerState(), emit)
    a.start()
    a.dial("+201000000001")
    assert (AG, GATEWAY_IFACE, "Dial", ("+201000000001",)) in bus.calls


def test_dial_without_gateway_emits_error():
    out, emit = collect()
    a = TelephonyAdapter(FakeBus({}), DialerState(), emit)
    a.start()
    a.dial("+20")
    assert {"ev": "error", "cmd": "dial", "message": "no gateway"} in out


def test_hangup_targets_the_call_object():
    bus = FakeBus(managed_with_gateway())
    out, emit = collect()
    a = TelephonyAdapter(bus, DialerState(), emit)
    a.start()
    a.hangup("call1")
    assert (f"{AG}/call1", "org.pipewire.Telephony.Call1", "Hangup", ()) in bus.calls


def test_call_added_signal_emits_call_event():
    bus = FakeBus(managed_with_gateway())
    out, emit = collect()
    TelephonyAdapter(bus, DialerState(), emit).start()
    bus.fire("org.ofono.VoiceCallManager", "CallAdded",
             f"{AG}/call1", {"State": "incoming", "LineIdentification": "+201000000001"})
    assert {"ev": "call", "id": "call1", "state": "incoming", "line": "+201000000001"} in out


def test_call_removed_signal_emits_removal():
    bus = FakeBus(managed_with_gateway())
    out, emit = collect()
    TelephonyAdapter(bus, DialerState(), emit).start()
    bus.fire("org.ofono.VoiceCallManager", "CallAdded", f"{AG}/call1", {"State": "active"})
    bus.fire("org.ofono.VoiceCallManager", "CallRemoved", f"{AG}/call1")
    assert {"ev": "call_removed", "id": "call1"} in out


def test_send_tones_and_volume():
    bus = FakeBus(managed_with_gateway())
    out, emit = collect()
    a = TelephonyAdapter(bus, DialerState(), emit)
    a.start()
    a.send_tones("123")
    a.set_volume("mic", 12)
    assert (AG, GATEWAY_IFACE, "SendTones", ("123",)) in bus.calls
    assert any(c[2] == "Set" for c in bus.calls)


def test_set_volume_rejects_unknown_target():
    bus = FakeBus(managed_with_gateway())
    out, emit = collect()
    a = TelephonyAdapter(bus, DialerState(), emit)
    a.start()
    a.set_volume("nose", 3)
    assert {"ev": "error", "cmd": "set_volume", "message": "unknown target 'nose'"} in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_telephony.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dialerd.telephony'`

- [ ] **Step 3: Write minimal implementation**

`src/dialerd/telephony.py`:

```python
from __future__ import annotations

from typing import Any, Callable, Protocol

from dialerd.protocol import encode_event
from dialerd.state import DialerState

BUS_NAME = "org.pipewire.Telephony"
MANAGER_PATH = "/org/pipewire/Telephony"
GATEWAY_IFACE = "org.pipewire.Telephony.AudioGateway1"
TRANSPORT_IFACE = "org.pipewire.Telephony.AudioGatewayTransport1"
CALL_IFACE = "org.pipewire.Telephony.Call1"
# Call lifecycle is published on the oFono compatibility interface, at the
# gateway path rather than the manager path. Verified on hardware.
VCM_IFACE = "org.ofono.VoiceCallManager"

VOLUME_PROPS = {"mic": "MicrophoneVolume", "speaker": "SpeakerVolume"}


class Bus(Protocol):
    def call(self, name: str, path: str, iface: str, method: str, args: tuple) -> tuple: ...
    def subscribe(self, iface: str, member: str, path: str | None, handler: Callable) -> None: ...
    def get_managed_objects(self, name: str, path: str) -> dict[str, dict[str, dict[str, Any]]]: ...


class TelephonyAdapter:
    def __init__(self, bus: Bus, state: DialerState, emit: Callable[[list[str]], None]) -> None:
        self._bus = bus
        self._state = state
        self._emit = emit
        self._gateway: str | None = None

    def start(self) -> None:
        self._bus.subscribe(VCM_IFACE, "CallAdded", None, self._on_call_added)
        self._bus.subscribe(VCM_IFACE, "CallRemoved", None, self._on_call_removed)
        self._bus.subscribe("org.freedesktop.DBus.Properties", "PropertiesChanged", None, self._on_props)
        self._bus.subscribe("org.freedesktop.DBus.ObjectManager", "InterfacesAdded", None, self._rescan)
        self._bus.subscribe("org.freedesktop.DBus.ObjectManager", "InterfacesRemoved", None, self._rescan)
        self._rescan()

    def _rescan(self, *_: Any) -> None:
        objects = self._bus.get_managed_objects(BUS_NAME, MANAGER_PATH)
        gateways = [p for p, ifaces in objects.items() if GATEWAY_IFACE in ifaces]
        if not gateways:
            self._gateway = None
            self._emit(self._state.set_gateway(None, None, None))
            return
        path = gateways[0]
        self._gateway = path
        address = objects[path][GATEWAY_IFACE].get("Address")
        self._emit(self._state.set_gateway(path, address, self._device_name(address)))
        transport = objects[path].get(TRANSPORT_IFACE)
        if transport:
            self._emit(self._state.set_transport(transport.get("State", "idle"), transport.get("Codec", 0)))

    @staticmethod
    def _device_name(address: str | None) -> str | None:
        """Returns the address as the display name.

        Friendly-name resolution needs a system-bus lookup against
        org.bluez, which this session-bus adapter deliberately does not do.
        The UI falls back to the address.
        """
        return address

    def _on_call_added(self, path: str, props: dict[str, Any]) -> None:
        self._emit(self._state.upsert_call(path, props))

    def _on_call_removed(self, path: str) -> None:
        self._emit(self._state.remove_call(path))

    def _on_props(self, path: str, iface: str, changed: dict[str, Any]) -> None:
        if iface == CALL_IFACE:
            self._emit(self._state.upsert_call(path, changed))
        elif iface == TRANSPORT_IFACE and self._gateway:
            self._emit(self._state.set_transport(changed.get("State", "idle"), changed.get("Codec", 0)))

    def _fail(self, cmd: str, message: str) -> None:
        self._emit([encode_event("error", cmd=cmd, message=message)])

    def dial(self, number: str) -> None:
        if not self._gateway:
            return self._fail("dial", "no gateway")
        self._bus.call(BUS_NAME, self._gateway, GATEWAY_IFACE, "Dial", (number,))

    def send_tones(self, digits: str) -> None:
        if not self._gateway:
            return self._fail("tones", "no gateway")
        self._bus.call(BUS_NAME, self._gateway, GATEWAY_IFACE, "SendTones", (digits,))

    def answer(self, call: str) -> None:
        self._call_method(call, "Answer", "answer")

    def hangup(self, call: str) -> None:
        self._call_method(call, "Hangup", "hangup")

    def _call_method(self, call: str, method: str, cmd: str) -> None:
        if not self._gateway:
            return self._fail(cmd, "no gateway")
        self._bus.call(BUS_NAME, f"{self._gateway}/{call}", CALL_IFACE, method, ())

    def set_volume(self, which: str, value: int) -> None:
        prop = VOLUME_PROPS.get(which)
        if prop is None:
            return self._fail("set_volume", f"unknown target '{which}'")
        if not self._gateway:
            return self._fail("set_volume", "no gateway")
        self._bus.call(BUS_NAME, self._gateway, "org.freedesktop.DBus.Properties",
                       "Set", (GATEWAY_IFACE, prop, value))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_telephony.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/dialerd/telephony.py tests/test_telephony.py
git commit -m "feat: add PipeWire Telephony d-bus adapter with injectable bus"
```

---

### Task 4: Unix socket server

Accepts multiple clients, replays a snapshot to each new one, broadcasts events to all, and routes commands back to a handler.

**Files:**
- Create: `src/dialerd/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `decode_command`, `ProtocolError` from Task 1; `DialerState.snapshot` from Task 2.
- Produces: `SocketServer(path: str, state: DialerState, on_command: Callable[[dict], None])` with `start() -> None`, `broadcast(lines: list[str]) -> None`, `stop() -> None`. Uses a background `selectors` loop on its own thread so it composes with GLib's main loop in Task 5.

- [ ] **Step 1: Write the failing test**

`tests/test_server.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dialerd.server'`

- [ ] **Step 3: Write minimal implementation**

`src/dialerd/server.py`:

```python
from __future__ import annotations

import os
import selectors
import socket
import threading
from typing import Callable

from dialerd.protocol import ProtocolError, decode_command, encode_event
from dialerd.state import DialerState


class SocketServer:
    def __init__(self, path: str, state: DialerState, on_command: Callable[[dict], None]) -> None:
        self._path = path
        self._state = state
        self._on_command = on_command
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
        self._send(conn, self._state.snapshot())

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_server.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/dialerd/server.py tests/test_server.py
git commit -m "feat: add unix socket server with snapshot replay and broadcast"
```

---

### Task 5: Gio bus binding and daemon entrypoint

The only code that touches a real bus. Verified against hardware rather than unit tests, because the value here is precisely that it talks to the real thing.

**Files:**
- Create: `src/dialerd/giobus.py`
- Create: `src/dialerd/__main__.py`
- Create: `systemd/omarchy-dialerd.service`
- Test: manual, against the paired phone

**Interfaces:**
- Consumes: `Bus` protocol shape from Task 3; `TelephonyAdapter`, `DialerState`, `SocketServer`.
- Produces: `GioBus()` implementing `call`/`subscribe`/`get_managed_objects`; `main() -> int` entrypoint.

- [ ] **Step 1: Write the Gio bus binding**

`src/dialerd/giobus.py`:

```python
from __future__ import annotations

from typing import Any, Callable

from gi.repository import Gio, GLib


def _pack(args: tuple) -> GLib.Variant | None:
    if not args:
        return None
    parts = []
    for a in args:
        if isinstance(a, str):
            parts.append(GLib.Variant("s", a))
        elif isinstance(a, bool):
            parts.append(GLib.Variant("b", a))
        elif isinstance(a, int):
            parts.append(GLib.Variant("y", a))
        else:
            raise TypeError(f"unsupported argument type {type(a)!r}")
    return GLib.Variant.new_tuple(*parts)


class GioBus:
    """Session-bus binding built on the already-installed PyGObject."""

    def __init__(self) -> None:
        self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def call(self, name: str, path: str, iface: str, method: str, args: tuple) -> tuple:
        # Properties.Set needs an explicit variant for its value argument.
        if method == "Set" and len(args) == 3:
            body = GLib.Variant("(ssv)", (args[0], args[1], GLib.Variant("y", args[2])))
        else:
            body = _pack(args)
        reply = self._conn.call_sync(name, path, iface, method, body, None,
                                     Gio.DBusCallFlags.NONE, 5000, None)
        return reply.unpack() if reply else ()

    def subscribe(self, iface: str, member: str, path: str | None, handler: Callable) -> None:
        def _cb(_conn, _sender, obj_path, _iface, _member, params):
            handler(*self._normalise(member, obj_path, params.unpack()))

        self._conn.signal_subscribe(None, iface, member, path, None,
                                    Gio.DBusSignalFlags.NONE, _cb)

    @staticmethod
    def _normalise(member: str, obj_path: str, body: tuple) -> tuple:
        if member == "PropertiesChanged":
            return (obj_path, body[0], body[1])
        if member in ("InterfacesAdded", "InterfacesRemoved"):
            return ()
        # CallAdded -> (path, props); CallRemoved -> (path,)
        return body

    def get_managed_objects(self, name: str, path: str) -> dict[str, Any]:
        reply = self._conn.call_sync(name, path, "org.freedesktop.DBus.ObjectManager",
                                     "GetManagedObjects", None, None,
                                     Gio.DBusCallFlags.NONE, 5000, None)
        return reply.unpack()[0]
```

- [ ] **Step 2: Write the entrypoint**

`src/dialerd/__main__.py`:

```python
from __future__ import annotations

import os
import signal
import sys

from gi.repository import GLib

from dialerd.giobus import GioBus
from dialerd.server import SocketServer
from dialerd.state import DialerState
from dialerd.telephony import TelephonyAdapter


def socket_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, "omarchy-dialer.sock")


def main() -> int:
    state = DialerState()
    server: SocketServer | None = None

    def emit(lines: list[str]) -> None:
        if server is not None:
            server.broadcast(lines)

    adapter = TelephonyAdapter(GioBus(), state, emit)

    def on_command(cmd: dict) -> None:
        name = cmd.get("cmd")
        if name == "dial":
            adapter.dial(cmd.get("number", ""))
        elif name == "answer":
            adapter.answer(cmd.get("call", ""))
        elif name == "hangup":
            adapter.hangup(cmd.get("call", ""))
        elif name == "tones":
            adapter.send_tones(cmd.get("digits", ""))
        elif name == "set_volume":
            adapter.set_volume(cmd.get("which", ""), int(cmd.get("value", 0)))
        elif name == "refresh":
            adapter.start()

    server = SocketServer(socket_path(), state, on_command)
    server.start()
    adapter.start()

    loop = GLib.MainLoop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (loop.quit(), False)[1])
    try:
        loop.run()
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify the whole suite still passes**

Run: `python3 -m pytest -v`
Expected: 29 passed

- [ ] **Step 4: Manual hardware verification — gateway discovery**

Ensure the phone is connected: `bluetoothctl connect AA:BB:CC:DD:EE:FF`

Terminal A: `PYTHONPATH=src .venv/bin/python -m dialerd`
(the `PYTHONPATH` is required for a direct run; the systemd unit sets it itself)

Terminal B: a direct client, because `socat` buffers through a pipe and can
appear to show nothing:

```bash
.venv/bin/python -c '
import os, socket
c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); c.settimeout(5)
c.connect(os.path.join(os.environ["XDG_RUNTIME_DIR"], "omarchy-dialer.sock"))
while True:
    d = c.recv(4096)
    if not d: break
    print(d.decode(), end="")'
```

Expected in B on connect: a `{"ev":"gateway","connected":true,"address":"AA:BB:CC:DD:EE:FF"}` line, followed by a `transport` line.

- [ ] **Step 5: Manual hardware verification — a real call**

In terminal B, type a dial command against a number you control:

```
{"cmd":"dial","number":"+201000000001"}
```

Expected: a `call` event with `state` progressing toward `active` and `line` matching the number; a `transport` event with `state":"active"` and `codec":2`; audio on the PC's speakers and microphone. Then hang up:

```
{"cmd":"hangup","call":"call1"}
```

Expected: `{"ev":"call_removed","id":"call1"}` and transport returning to `idle`.

- [ ] **Step 6: Write the systemd user unit**

`systemd/omarchy-dialerd.service`:

```ini
[Unit]
Description=Omarchy Dialer daemon
After=pipewire.service wireplumber.service
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m dialerd
Environment=PYTHONPATH=%h/.local/share/omarchy-dialer/src
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
```

- [ ] **Step 7: Commit**

```bash
git add src/dialerd/giobus.py src/dialerd/__main__.py systemd/omarchy-dialerd.service
git commit -m "feat: add gio bus binding, daemon entrypoint and systemd unit"
```

---

### Task 6: Theme singleton

Loads Omarchy's palette and restyles a running app when the user switches themes.

**Files:**
- Create: `ui/Theme.qml`
- Test: manual, via a scratch harness

**Interfaces:**
- Consumes: nothing.
- Produces: singleton `Theme` with string properties `background`, `surface`, `foreground`, `dim`, `accent`, `selection`, `danger`, `success`, and bool `isDark`. Hot-reloads on theme change.

- [ ] **Step 1: Write the theme singleton**

`ui/Theme.qml`:

```qml
pragma Singleton

import Quickshell
import Quickshell.Io

Singleton {
    id: root

    // Omarchy repoints ~/.local/state/omarchy/current on theme change.
    readonly property string themeFile: Quickshell.env("HOME")
        + "/.local/state/omarchy/current/theme/colors.toml"

    property string background: "#060B1E"
    property string surface:    "#131a3a"
    property string foreground: "#ffcead"
    property string dim:        "#6d7db6"
    property string accent:     "#7d82d9"
    property string selection:  "#252e56"
    property string danger:     "#ED5B5A"
    property string success:    "#92a593"
    property bool   isDark:     true

    // colors.toml is flat `key = "value"` lines; a full TOML parser is overkill.
    function parse(text) {
        const out = {};
        for (const line of text.split("\n")) {
            const m = line.match(/^\s*([a-z_]+)\s*=\s*"([^"]*)"/);
            if (m) out[m[1]] = m[2];
        }
        return out;
    }

    function apply(text) {
        const c = parse(text);
        if (c.background)        root.background = c.background;
        if (c.lighter_background) root.surface   = c.lighter_background;
        if (c.foreground)        root.foreground = c.foreground;
        if (c.dark_foreground)   root.dim        = c.dark_foreground;
        if (c.accent)            root.accent     = c.accent;
        if (c.selection)         root.selection  = c.selection;
        if (c.red)               root.danger     = c.red;
        if (c.green)             root.success    = c.green;
        root.isDark = (c.mode || "dark") === "dark";
    }

    FileView {
        id: file
        path: root.themeFile
        watchChanges: true
        onLoaded: root.apply(file.text())
        onFileChanged: file.reload()
    }
}
```

- [ ] **Step 2: Register the singleton**

`ui/qmldir`:

```
singleton Theme 1.0 Theme.qml
Bridge 1.0 Bridge.qml
```

Once a `qmldir` exists, a directory import exports **only** what the file
lists. Every type added directly under `ui/` must be declared here or it
fails with "X is not a type". Subdirectories (`views/`, `components/`) have
no `qmldir`, so implicit directory import still works there.

- [ ] **Step 3: Verify it parses the live theme**

Create `/tmp/themecheck.qml`:

```qml
import Quickshell
import "."

ShellRoot {
    Component.onCompleted: {
        console.log("bg=" + Theme.background + " fg=" + Theme.foreground
                    + " accent=" + Theme.accent + " dark=" + Theme.isDark);
        Qt.exit(0);
    }
}
```

Run: `cp /tmp/themecheck.qml ui/ && qs -p ui/themecheck.qml`
Expected: values matching `~/.local/state/omarchy/current/theme/colors.toml` — with the `ethereal` theme active that is `bg=#060B1E fg=#ffcead accent=#7d82d9 dark=true`. Then `rm ui/themecheck.qml`.

- [ ] **Step 4: Verify hot reload**

With the check harness still running (drop the `Qt.exit(0)` temporarily), run `omarchy-theme-set catppuccin` in another terminal and confirm the logged values change without restarting.

- [ ] **Step 5: Commit**

```bash
git add ui/Theme.qml ui/qmldir
git commit -m "feat: add omarchy theme singleton with hot reload"
```

---

### Task 7: Socket bridge

The QML app's only link to the daemon. Owns framing, reconnection, and the state model every view binds to.

**Files:**
- Create: `ui/Bridge.qml`
- Test: manual, against a scripted fake daemon

**Interfaces:**
- Consumes: the socket protocol from Tasks 1 and 4.
- Produces: `Bridge` with properties `connected` (bool), `gatewayName` (string), `transportState` (string), `codec` (int), `calls` (ListModel of `{id, state, line, name}`), and `activeCall` (the first call, or null). Methods `dial(number)`, `answer(id)`, `hangup(id)`, `tones(digits)`, `setVolume(which, value)`.

- [ ] **Step 1: Write the bridge**

`ui/Bridge.qml`:

```qml
import QtQuick
import Quickshell
import Quickshell.Io

Item {
    id: root

    readonly property string sockPath: (Quickshell.env("XDG_RUNTIME_DIR")
        || "/run/user/1000") + "/omarchy-dialer.sock"

    property bool   connected: false
    property string gatewayName: ""
    property string transportState: "idle"
    property int    codec: 0
    property ListModel calls: ListModel {}
    readonly property var activeCall: calls.count > 0 ? calls.get(0) : null

    function send(obj) { sock.write(JSON.stringify(obj) + "\n"); }

    function dial(number)            { send({cmd: "dial",   number: number}); }
    function answer(id)              { send({cmd: "answer", call: id}); }
    function hangup(id)              { send({cmd: "hangup", call: id}); }
    function tones(digits)           { send({cmd: "tones",  digits: digits}); }
    function setVolume(which, value) { send({cmd: "set_volume", which: which, value: value}); }

    function indexOfCall(id) {
        for (let i = 0; i < calls.count; i++)
            if (calls.get(i).id === id) return i;
        return -1;
    }

    function handle(ev) {
        switch (ev.ev) {
        case "gateway":
            root.connected = ev.connected;
            root.gatewayName = ev.name || ev.address || "";
            if (!ev.connected) calls.clear();
            break;
        case "transport":
            root.transportState = ev.state;
            root.codec = ev.codec || 0;
            break;
        case "call": {
            const entry = {id: ev.id, state: ev.state || "",
                           line: ev.line || "", name: ev.name || ""};
            const i = indexOfCall(ev.id);
            if (i >= 0) calls.set(i, entry); else calls.append(entry);
            break;
        }
        case "call_removed": {
            const i = indexOfCall(ev.id);
            if (i >= 0) calls.remove(i);
            break;
        }
        case "error":
            console.warn("dialerd error:", ev.message);
            break;
        }
    }

    Socket {
        id: sock
        path: root.sockPath
        connected: true
        onConnectionStateChanged: {
            if (!sock.connected) {
                root.connected = false;
                root.calls.clear();
                retry.start();
            }
        }
        parser: SplitParser {
            onRead: (line) => {
                try { root.handle(JSON.parse(line)); }
                catch (e) { console.warn("bad line from daemon:", line); }
            }
        }
    }

    Timer {
        id: retry
        interval: 1000
        repeat: false
        onTriggered: sock.connected = true
    }
}
```

- [ ] **Step 2: Build a scripted fake daemon for UI testing**

`tests/fake_daemon.py` — lets every view be exercised with no phone present:

```python
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
    print(f"fake daemon on {path} -> {sys.argv[1:] or ['idle']}")
    try:
        while True:
            conn, _ = srv.accept()
            for line in script:
                conn.sendall((line + "\n").encode())
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                print("<-", data.decode().strip())
    except KeyboardInterrupt:
        return 0
    finally:
        srv.close()
        os.unlink(path)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify the bridge against the fake daemon**

Terminal A: `python3 tests/fake_daemon.py active`

Create `/tmp/bridgecheck.qml` in `ui/`:

```qml
import Quickshell
import "."

ShellRoot {
    Bridge { id: b }
    Timer {
        interval: 500; running: true
        onTriggered: {
            console.log("connected=" + b.connected + " gw=" + b.gatewayName
                        + " calls=" + b.calls.count
                        + " line=" + (b.activeCall ? b.activeCall.line : "-"));
            Qt.exit(0);
        }
    }
}
```

Run: `qs -p ui/bridgecheck.qml`
Expected: `connected=true gw=Example Phone calls=1 line=+201000000001`. Then `rm ui/bridgecheck.qml`.

- [ ] **Step 4: Commit**

```bash
git add ui/Bridge.qml tests/fake_daemon.py
git commit -m "feat: add socket bridge and scripted fake daemon for ui work"
```

---

### Task 8: Keypad and idle view

**Files:**
- Create: `ui/components/Keypad.qml`
- Create: `ui/views/Idle.qml`
- Test: manual, against `fake_daemon.py idle`

**Interfaces:**
- Consumes: `Theme` from Task 6; `Bridge` from Task 7.
- Produces: `Keypad` with signal `digit(string d)`; `Idle` taking `property Bridge bridge` and owning its own `number` string.

- [ ] **Step 1: Write the keypad**

`ui/components/Keypad.qml`:

```qml
import QtQuick
import QtQuick.Layouts
import ".."

GridLayout {
    id: root
    signal digit(string d)

    columns: 3
    rowSpacing: 8
    columnSpacing: 8

    Repeater {
        model: ["1","2","3","4","5","6","7","8","9","*","0","#"]
        delegate: Rectangle {
            required property string modelData
            Layout.preferredWidth: 64
            Layout.preferredHeight: 48
            radius: 8
            color: mouse.pressed ? Theme.selection : Theme.surface
            Text {
                anchors.centerIn: parent
                text: parent.modelData
                color: Theme.foreground
                font.pixelSize: 18
            }
            MouseArea {
                id: mouse
                anchors.fill: parent
                onClicked: root.digit(parent.modelData)
            }
        }
    }
}
```

- [ ] **Step 2: Write the idle view**

`ui/views/Idle.qml`:

```qml
import QtQuick
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: root
    required property var bridge
    property string number: ""

    spacing: 12

    Rectangle {
        Layout.fillWidth: true
        height: 44
        radius: 8
        color: Theme.surface
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: root.number || "Enter a number"
            color: root.number ? Theme.foreground : Theme.dim
            font.pixelSize: 20
        }
    }

    Keypad {
        Layout.alignment: Qt.AlignHCenter
        onDigit: (d) => root.number += d
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8

        Rectangle {
            Layout.preferredWidth: 80
            height: 40
            radius: 8
            color: Theme.surface
            Text {
                anchors.centerIn: parent
                text: "Delete"
                color: Theme.dim
            }
            MouseArea {
                anchors.fill: parent
                onClicked: root.number = root.number.slice(0, -1)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 40
            radius: 8
            enabled: root.number.length > 0 && root.bridge.connected
            opacity: enabled ? 1 : 0.4
            color: Theme.success
            Text {
                anchors.centerIn: parent
                text: "Call"
                color: Theme.background
                font.bold: true
            }
            MouseArea {
                anchors.fill: parent
                enabled: parent.enabled
                onClicked: root.bridge.dial(root.number)
            }
        }
    }

    Keys.onReturnPressed: if (root.number) root.bridge.dial(root.number)
    Keys.onBackPressed: root.number = root.number.slice(0, -1)
}
```

- [ ] **Step 3: Verify visually**

Terminal A: `python3 tests/fake_daemon.py idle`
Terminal B: `qs -p ui/shell.qml` (after Task 9; until then, wrap `Idle` in a scratch `ShellRoot`).

Expected: keypad renders in Omarchy theme colours; tapping digits fills the number field; Call sends `{"cmd":"dial",...}` — visible in terminal A's `<-` output.

- [ ] **Step 4: Commit**

```bash
git add ui/components/Keypad.qml ui/views/Idle.qml
git commit -m "feat: add keypad and idle dialing view"
```

---

### Task 9: Active call and incoming views

**Files:**
- Create: `ui/views/ActiveCall.qml`
- Create: `ui/views/Incoming.qml`
- Test: manual, against `fake_daemon.py active` and `fake_daemon.py incoming`

**Interfaces:**
- Consumes: `Theme`, `Bridge`, `Keypad`.
- Produces: `ActiveCall` and `Incoming`, each taking `property var bridge` and `property var call`.

- [ ] **Step 1: Write the active call view**

`ui/views/ActiveCall.qml`:

```qml
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: root
    required property var bridge
    required property var call

    property int elapsed: 0
    spacing: 16

    Timer {
        interval: 1000
        running: root.call && root.call.state === "active"
        repeat: true
        onTriggered: root.elapsed++
    }

    function clock(s) {
        const m = Math.floor(s / 60), r = s % 60;
        return m + ":" + (r < 10 ? "0" : "") + r;
    }

    Text {
        Layout.alignment: Qt.AlignHCenter
        text: root.call ? (root.call.name || root.call.line) : ""
        color: Theme.foreground
        font.pixelSize: 24
    }

    Text {
        Layout.alignment: Qt.AlignHCenter
        text: root.call && root.call.state === "active"
              ? root.clock(root.elapsed)
              : (root.call ? root.call.state : "")
        color: Theme.dim
        font.pixelSize: 16
    }

    Text {
        Layout.alignment: Qt.AlignHCenter
        // Codec 2 is mSBC; anything else is narrowband CVSD.
        text: root.bridge.codec === 2 ? "HD voice" : ""
        color: Theme.success
        font.pixelSize: 12
    }

    Keypad {
        Layout.alignment: Qt.AlignHCenter
        onDigit: (d) => root.bridge.tones(d)
    }

    // HFP volume is a 0-15 scale on the wire, not 0-100.
    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 8

        Text { text: "Mic"; color: Theme.dim; font.pixelSize: 12 }
        Slider {
            Layout.fillWidth: true
            from: 0; to: 15; stepSize: 1; value: 15
            onMoved: root.bridge.setVolume("mic", Math.round(value))
        }

        Text { text: "Speaker"; color: Theme.dim; font.pixelSize: 12 }
        Slider {
            Layout.fillWidth: true
            from: 0; to: 15; stepSize: 1; value: 15
            onMoved: root.bridge.setVolume("speaker", Math.round(value))
        }
    }

    Rectangle {
        Layout.fillWidth: true
        height: 44
        radius: 8
        color: Theme.danger
        Text {
            anchors.centerIn: parent
            text: "Hang up"
            color: Theme.background
            font.bold: true
        }
        MouseArea {
            anchors.fill: parent
            onClicked: root.bridge.hangup(root.call.id)
        }
    }
}
```

- [ ] **Step 2: Write the incoming view**

`ui/views/Incoming.qml`:

```qml
import QtQuick
import QtQuick.Layouts
import ".."

ColumnLayout {
    id: root
    required property var bridge
    required property var call

    spacing: 20

    Text {
        Layout.alignment: Qt.AlignHCenter
        text: "Incoming call"
        color: Theme.dim
        font.pixelSize: 14
    }

    Text {
        Layout.alignment: Qt.AlignHCenter
        text: root.call ? (root.call.name || root.call.line) : ""
        color: Theme.foreground
        font.pixelSize: 26
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 12

        Rectangle {
            Layout.fillWidth: true
            height: 48
            radius: 8
            color: Theme.danger
            Text {
                anchors.centerIn: parent
                text: "Reject"
                color: Theme.background
                font.bold: true
            }
            MouseArea {
                anchors.fill: parent
                onClicked: root.bridge.hangup(root.call.id)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 48
            radius: 8
            color: Theme.success
            Text {
                anchors.centerIn: parent
                text: "Answer"
                color: Theme.background
                font.bold: true
            }
            MouseArea {
                anchors.fill: parent
                onClicked: root.bridge.answer(root.call.id)
            }
        }
    }
}
```

- [ ] **Step 3: Verify both states**

Run `python3 tests/fake_daemon.py incoming`, then `qs -p ui/shell.qml` (Task 9 wiring). Expected: Answer/Reject against `+201000000001`, and clicking Answer prints `{"cmd":"answer","call":"call1"}` in the fake daemon terminal. Repeat with `fake_daemon.py active` and confirm the timer counts, "HD voice" shows for `codec=2`, and dragging either volume slider prints `{"cmd":"set_volume",...}` with a value in 0-15.

- [ ] **Step 4: Commit**

```bash
git add ui/views/ActiveCall.qml ui/views/Incoming.qml
git commit -m "feat: add active call and incoming call views"
```

---

### Task 10: Application shell, install and boot path

Wires the views together, installs everything, and makes the HFP link survive a reboot.

**Files:**
- Create: `ui/shell.qml`
- Create: `desktop/omarchy-dialer.desktop`
- Create: `install.sh`
- Create: `README.md`
- Modify: `~/.config/wireplumber/wireplumber.conf.d/bluetooth-a2dp-autoconnect.conf`

**Interfaces:**
- Consumes: everything from Tasks 6 through 9.
- Produces: a launchable application.

- [ ] **Step 1: Write the shell**

`ui/shell.qml`:

```qml
import QtQuick
import QtQuick.Layouts
import Quickshell
import "."
import "views"

ShellRoot {
    // NOTE: the id must NOT be `bridge`. The views declare their own
    // `property var bridge`, which shadows an outer id of the same name
    // inside the Component blocks below, silently making `call:` undefined.
    Bridge { id: dialer }

    FloatingWindow {
        id: win
        title: "Dialer"
        implicitWidth: 380
        implicitHeight: 560
        color: Theme.background
        visible: true

        // Surface an incoming call even if the window was left in the background.
        Connections {
            target: dialer.calls
            function onCountChanged() {
                if (dialer.activeCall && dialer.activeCall.state === "incoming")
                    win.visible = true;
            }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "Dialer"
                    color: Theme.foreground
                    font.pixelSize: 18
                    font.bold: true
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: dialer.connected ? dialer.gatewayName : "No phone connected"
                    color: dialer.connected ? Theme.dim : Theme.danger
                    font.pixelSize: 12
                }
            }

            Loader {
                Layout.fillWidth: true
                Layout.fillHeight: true
                sourceComponent: {
                    const c = dialer.activeCall;
                    if (!c) return idleView;
                    return c.state === "incoming" ? incomingView : activeView;
                }
            }

            Component { id: idleView;     Idle       { bridge: dialer } }
            Component { id: activeView;   ActiveCall { bridge: dialer; call: dialer.activeCall } }
            Component { id: incomingView; Incoming   { bridge: dialer; call: dialer.activeCall } }
        }
    }
}
```

- [ ] **Step 2: Write the desktop entry**

`desktop/omarchy-dialer.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Dialer
Comment=Place calls through your connected phone
Exec=qs -p %h/.local/share/omarchy-dialer/ui/shell.qml
Icon=call-start
Terminal=false
Categories=Network;Telephony;
```

- [ ] **Step 3: Write the installer**

`install.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

PREFIX="${HOME}/.local/share/omarchy-dialer"
WP_CONF="${HOME}/.config/wireplumber/wireplumber.conf.d/bluetooth-a2dp-autoconnect.conf"

echo "==> Installing to ${PREFIX}"
mkdir -p "${PREFIX}"
cp -r src ui "${PREFIX}/"

echo "==> Installing desktop entry"
mkdir -p "${HOME}/.local/share/applications"
cp desktop/omarchy-dialer.desktop "${HOME}/.local/share/applications/"

echo "==> Installing user service"
mkdir -p "${HOME}/.config/systemd/user"
cp systemd/omarchy-dialerd.service "${HOME}/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now omarchy-dialerd.service

echo "==> Ensuring hfp_hf auto-connects"
if [[ -f "${WP_CONF}" ]] && ! grep -q "hfp_hf" "${WP_CONF}"; then
  cp "${WP_CONF}" "${WP_CONF}.bak"
  sed -i 's/bluez5\.auto-connect = \[ a2dp_sink a2dp_source \]/bluez5.auto-connect = [ hfp_hf a2dp_sink a2dp_source ]/' "${WP_CONF}"
  echo "    patched (backup at ${WP_CONF}.bak) - restarting wireplumber"
  systemctl --user restart wireplumber
else
  echo "    already present or config missing, skipping"
fi

echo "==> Done. Launch 'Dialer' from your app grid."
```

Make it executable: `chmod +x install.sh`

- [ ] **Step 4: Verify the auto-connect patch**

Run: `./install.sh`
Then: `grep auto-connect ~/.config/wireplumber/wireplumber.conf.d/bluetooth-a2dp-autoconnect.conf`
Expected: `bluez5.auto-connect = [ hfp_hf a2dp_sink a2dp_source ]`

- [ ] **Step 4b: Note the Hyprland limitation**

Omarchy uses Hyprland's Lua config parser, which rejects `hyprctl keyword
windowrule` at runtime ("keyword can't work with non-legacy parsers"). The
float rule must be added to `~/.config/hypr/looknfeel.lua` by the user; the
installer prints it rather than editing their config. Without it the window
is tiled and the layout stretches, but every control still works.

- [ ] **Step 5: Boot regression test**

Reboot. Then, without running `bluetoothctl connect`:

Run: `busctl --user call org.pipewire.Telephony /org/pipewire/Telephony org.freedesktop.DBus.ObjectManager GetManagedObjects`
Expected: a `/org/pipewire/Telephony/ag1` entry present once the phone is in range.

- [ ] **Step 6: Full end-to-end acceptance**

Launch Dialer from the app grid. Confirm, in order:
1. Header shows `Example Phone`.
2. Dial a number you control; the view switches to the call card and audio is on PC speakers and mic.
3. Press keypad digits mid-call and confirm the far end hears DTMF.
4. Hang up from the PC; the view returns to the keypad.
5. Call the phone from another line; the window raises showing Answer/Reject; answer from the PC.
6. Switch Omarchy themes and confirm the dialer restyles without restarting.

- [ ] **Step 7: Write the README**

`README.md` covering: what it does, the hardware requirement (a phone supporting HFP Audio Gateway, `0000111f`), install instructions, the socket protocol as a table, and a troubleshooting section noting that `Codec 0` means narrowband CVSD and that a missing gateway usually means the phone is not connected in the `audio-gateway` profile.

- [ ] **Step 8: Commit**

```bash
git add ui/shell.qml desktop/omarchy-dialer.desktop install.sh README.md
git commit -m "feat: add application shell, installer and boot path"
```

---

## Deferred to their own plans

- **Contacts** (spec phase 3) — blocked on ColorOS granting OBEX/PBAP or the KDE Connect Android app receiving the Contacts permission. Neither is currently true.
- **Messaging** (spec phase 4) — blocked on the same permissions plus a KDE Connect `sms` D-Bus path that does not presently exist for this device.

Neither should block release of the calling app.
