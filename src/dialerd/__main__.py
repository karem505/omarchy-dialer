from __future__ import annotations

import os
import signal
import sys

from gi.repository import GLib

from dialerd.contacts import ContactStore
from dialerd.giobus import GioBus
from dialerd.protocol import encode_event
from dialerd.server import SocketServer
from dialerd.state import DialerState
from dialerd.telephony import BUS_NAME as TELEPHONY_BUS_NAME, TelephonyAdapter


def socket_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, "omarchy-dialer.sock")


def contacts_path() -> str:
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(data, "omarchy-dialer", "contacts.json")


def main() -> int:
    state = DialerState()
    server: SocketServer | None = None

    def emit(lines: list[str]) -> None:
        if server is not None:
            server.broadcast(lines)

    contacts = ContactStore(contacts_path())
    bus = GioBus()
    adapter = TelephonyAdapter(bus, state, emit, contacts=contacts)

    def contacts_event() -> list[str]:
        items = contacts.all()
        return [encode_event("contacts", available=bool(items),
                             count=len(items), items=items)]

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
        elif name == "contacts":
            emit(contacts_event())
        elif name in ("import_contacts", "import_csv"):
            try:
                result = contacts.import_file(cmd.get("path", ""))
            except ValueError as exc:
                emit([encode_event("error", cmd="import_contacts", message=str(exc))])
            else:
                emit([encode_event("imported", **result)])
                emit(contacts_event())
        elif name == "refresh":
            adapter.start()

    server = SocketServer(socket_path(), state, on_command,
                          extra_snapshot=contacts_event)
    server.start()
    adapter.start()
    # Recover if org.pipewire.Telephony appears or restarts after we do.
    bus.watch_name(TELEPHONY_BUS_NAME, adapter.start)

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
