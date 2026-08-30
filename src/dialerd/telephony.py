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
    def __init__(self, bus: Bus, state: DialerState, emit: Callable[[list[str]], None],
                 contacts: Any = None) -> None:
        self._bus = bus
        self._state = state
        self._emit = emit
        self._contacts = contacts
        self._gateway: str | None = None
        # Last known transport values. PropertiesChanged is a delta, so we
        # merge against these rather than defaulting the absent field.
        self._transport: dict[str, Any] = {"State": "idle", "Codec": 0}

    def start(self) -> None:
        self._bus.subscribe(VCM_IFACE, "CallAdded", None, self._on_call_added)
        self._bus.subscribe(VCM_IFACE, "CallRemoved", None, self._on_call_removed)
        self._bus.subscribe("org.freedesktop.DBus.Properties", "PropertiesChanged", None, self._on_props)
        self._bus.subscribe("org.freedesktop.DBus.ObjectManager", "InterfacesAdded", None, self._rescan)
        self._bus.subscribe("org.freedesktop.DBus.ObjectManager", "InterfacesRemoved", None, self._rescan)
        self._rescan()

    def _rescan(self, *_: Any) -> None:
        try:
            objects = self._bus.get_managed_objects(BUS_NAME, MANAGER_PATH)
        except Exception:
            # org.pipewire.Telephony is not on the bus yet -- typically a boot
            # race while wireplumber restarts. Degrade to "no gateway" rather
            # than dying; the name watch will re-scan when it appears.
            objects = {}
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
            self._emit(self._apply_transport(transport))
        self._adopt_existing_calls(path)

    def _adopt_existing_calls(self, gateway: str) -> None:
        """Pick up calls already in progress.

        GetManagedObjects lists only the gateway -- call objects are not
        under the ObjectManager -- so a daemon that started mid-call would
        otherwise never know about it, leaving an active call invisible and
        impossible to hang up from here.
        """
        try:
            reply = self._bus.call(BUS_NAME, gateway, VCM_IFACE, "GetCalls", ())
        except Exception:
            return
        if not reply:
            return
        calls = reply[0] if isinstance(reply, tuple) else reply
        if not isinstance(calls, dict):
            return
        for call_path, props in calls.items():
            self._emit(self._state.upsert_call(call_path,
                                               self._with_contact_name(props)))

    def _device_name(self, address: str | None) -> str | None:
        """Resolve a friendly name via the bus, falling back to the address.

        Name resolution lives on the system bus (org.bluez), so it is an
        optional capability of the bus rather than a required one; buses
        without it simply yield the address.
        """
        resolve = getattr(self._bus, "device_name", None)
        if resolve is not None and address:
            try:
                return resolve(address) or address
            except Exception:
                return address
        return address

    def _on_call_added(self, path: str, props: dict[str, Any]) -> None:
        self._emit(self._state.upsert_call(path, self._with_contact_name(props)))

    def _with_contact_name(self, props: dict[str, Any]) -> dict[str, Any]:
        """Fill in Name from the contact book when the network supplies none."""
        if self._contacts is None or props.get("Name"):
            return props
        line = props.get("LineIdentification")
        if not line:
            return props
        name = self._contacts.name_for(line)
        if not name:
            return props
        merged = dict(props)
        merged["Name"] = name
        return merged

    def _on_call_removed(self, path: str) -> None:
        self._emit(self._state.remove_call(path))

    def _on_props(self, path: str, iface: str, changed: dict[str, Any]) -> None:
        if iface == CALL_IFACE:
            self._emit(self._state.upsert_call(path, changed))
        elif iface == TRANSPORT_IFACE and self._gateway:
            self._emit(self._apply_transport(changed))

    def _apply_transport(self, changed: dict[str, Any]) -> list[str]:
        """Merge a partial transport update into the cached values."""
        for key in ("State", "Codec"):
            if key in changed:
                self._transport[key] = changed[key]
        return self._state.set_transport(self._transport["State"],
                                         self._transport["Codec"])

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
