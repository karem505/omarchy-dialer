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

    def device_name(self, address: str) -> str | None:
        """BlueZ friendly name for a MAC, or None. Lives on the system bus."""
        path = "/org/bluez/hci0/dev_" + address.replace(":", "_")
        try:
            system = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            reply = system.call_sync(
                "org.bluez", path, "org.freedesktop.DBus.Properties", "Get",
                GLib.Variant("(ss)", ("org.bluez.Device1", "Alias")), None,
                Gio.DBusCallFlags.NONE, 3000, None)
            return reply.unpack()[0] or None
        except GLib.GError:
            return None

    def watch_name(self, name: str, on_appeared: Callable[[], None]) -> None:
        """Re-scan when the telephony service shows up or comes back."""
        Gio.bus_watch_name(
            Gio.BusType.SESSION, name, Gio.BusNameWatcherFlags.NONE,
            lambda *_: on_appeared(), lambda *_: on_appeared(),
        )

    def get_managed_objects(self, name: str, path: str) -> dict[str, Any]:
        reply = self._conn.call_sync(name, path, "org.freedesktop.DBus.ObjectManager",
                                     "GetManagedObjects", None, None,
                                     Gio.DBusCallFlags.NONE, 5000, None)
        return reply.unpack()[0]
