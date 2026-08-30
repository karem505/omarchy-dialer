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
    assert {"ev": "gateway", "connected": True, "address": "AA:BB:CC:DD:EE:FF", "name": "AA:BB:CC:DD:EE:FF"} in out


def test_start_with_no_gateway_reports_disconnected():
    # No broadcast fires: state never changed from its empty initial value,
    # and there are no clients at startup anyway. The contract is that a
    # client which connects learns the truth, which it does via snapshot().
    out, emit = collect()
    st = DialerState()
    TelephonyAdapter(FakeBus({}), st, emit).start()
    assert [json.loads(l) for l in st.snapshot()] == [{"ev": "gateway", "connected": False}]


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


class ExplodingBus(FakeBus):
    """Bus whose GetManagedObjects fails, as when the service is not yet up."""

    def get_managed_objects(self, name, path):
        raise RuntimeError("GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown")


def test_start_survives_telephony_service_being_absent():
    # Boot-order race: wireplumber restarting means org.pipewire.Telephony is
    # briefly unavailable. The daemon must degrade, not die.
    out, emit = collect()
    st = DialerState()
    a = TelephonyAdapter(ExplodingBus(), st, emit)
    a.start()  # must not raise
    assert [json.loads(l) for l in st.snapshot()] == [{"ev": "gateway", "connected": False}]


def test_dial_after_failed_start_reports_no_gateway():
    out, emit = collect()
    a = TelephonyAdapter(ExplodingBus(), DialerState(), emit)
    a.start()
    a.dial("+20")
    assert {"ev": "error", "cmd": "dial", "message": "no gateway"} in out


class NamingBus(FakeBus):
    """Bus that can resolve a BlueZ friendly name, as GioBus does."""

    def device_name(self, address):
        return "Example Phone" if address == "AA:BB:CC:DD:EE:FF" else None


def test_gateway_uses_bluez_friendly_name_when_available():
    out, emit = collect()
    TelephonyAdapter(NamingBus(managed_with_gateway()), DialerState(), emit).start()
    assert {"ev": "gateway", "connected": True, "address": "AA:BB:CC:DD:EE:FF",
            "name": "Example Phone"} in out


def test_gateway_falls_back_to_address_without_name_resolution():
    # FakeBus has no device_name(), mirroring a bus that cannot resolve it.
    out, emit = collect()
    TelephonyAdapter(FakeBus(managed_with_gateway()), DialerState(), emit).start()
    assert {"ev": "gateway", "connected": True, "address": "AA:BB:CC:DD:EE:FF",
            "name": "AA:BB:CC:DD:EE:FF"} in out


class StubContacts:
    def name_for(self, number):
        return "Ahmed" if "1000000001" in number else None


def test_incoming_call_gets_name_from_contact_book():
    bus = FakeBus(managed_with_gateway())
    out, emit = collect()
    TelephonyAdapter(bus, DialerState(), emit, contacts=StubContacts()).start()
    bus.fire("org.ofono.VoiceCallManager", "CallAdded",
             "/org/pipewire/Telephony/ag1/call1",
             {"State": "incoming", "LineIdentification": "+201000000001"})
    assert {"ev": "call", "id": "call1", "state": "incoming",
            "line": "+201000000001", "name": "Ahmed"} in out


def test_network_supplied_name_wins_over_contact_book():
    bus = FakeBus(managed_with_gateway())
    out, emit = collect()
    TelephonyAdapter(bus, DialerState(), emit, contacts=StubContacts()).start()
    bus.fire("org.ofono.VoiceCallManager", "CallAdded",
             "/org/pipewire/Telephony/ag1/call1",
             {"State": "incoming", "LineIdentification": "+201000000001", "Name": "Carrier CNAM"})
    assert any(e.get("name") == "Carrier CNAM" for e in out)


def test_unknown_caller_keeps_no_name():
    bus = FakeBus(managed_with_gateway())
    out, emit = collect()
    TelephonyAdapter(bus, DialerState(), emit, contacts=StubContacts()).start()
    bus.fire("org.ofono.VoiceCallManager", "CallAdded",
             "/org/pipewire/Telephony/ag1/call1",
             {"State": "incoming", "LineIdentification": "+9990000"})
    assert {"ev": "call", "id": "call1", "state": "incoming", "line": "+9990000"} in out


def test_partial_transport_update_keeps_the_other_field():
    # PropertiesChanged carries only what changed. A State-only update must
    # not reset Codec to 0, and a Codec-only update must not claim "idle"
    # in the middle of a live call.
    bus = FakeBus(managed_with_gateway())
    out, emit = collect()
    TelephonyAdapter(bus, DialerState(), emit).start()

    bus.fire("org.freedesktop.DBus.Properties", "PropertiesChanged",
             "/org/pipewire/Telephony/ag1",
             "org.pipewire.Telephony.AudioGatewayTransport1",
             {"State": "active", "Codec": 2})
    assert {"ev": "transport", "state": "active", "codec": 2} in out

    out.clear()
    bus.fire("org.freedesktop.DBus.Properties", "PropertiesChanged",
             "/org/pipewire/Telephony/ag1",
             "org.pipewire.Telephony.AudioGatewayTransport1",
             {"State": "active"})           # codec absent
    assert not any(e.get("codec") == 0 for e in out), "codec was wiped to 0"

    out.clear()
    bus.fire("org.freedesktop.DBus.Properties", "PropertiesChanged",
             "/org/pipewire/Telephony/ag1",
             "org.pipewire.Telephony.AudioGatewayTransport1",
             {"Codec": 1})                  # state absent
    assert not any(e.get("state") == "idle" for e in out), "state falsely idle"
    assert {"ev": "transport", "state": "active", "codec": 1} in out


class BusWithExistingCall(FakeBus):
    """Gateway with a call already in progress, as after a daemon restart.

    Mirrors the real bus: GetManagedObjects lists only the gateway, while
    VoiceCallManager.GetCalls is what actually reports live calls.
    """

    def call(self, name, path, iface, method, args):
        super().call(name, path, iface, method, args)
        if method == "GetCalls":
            return ({f"{AG}/call1": {"LineIdentification": "01000000002",
                                     "State": "active"}},)
        return ()


def test_restart_during_a_call_recovers_the_call():
    out, emit = collect()
    TelephonyAdapter(BusWithExistingCall(managed_with_gateway()),
                     DialerState(), emit).start()
    assert {"ev": "call", "id": "call1", "state": "active",
            "line": "01000000002"} in out


def test_start_tolerates_getcalls_being_unsupported():
    class NoGetCalls(FakeBus):
        def call(self, name, path, iface, method, args):
            if method == "GetCalls":
                raise RuntimeError("not supported")
            return super().call(name, path, iface, method, args)

    out, emit = collect()
    TelephonyAdapter(NoGetCalls(managed_with_gateway()), DialerState(), emit).start()
    assert {"ev": "gateway", "connected": True, "address": "AA:BB:CC:DD:EE:FF",
            "name": "AA:BB:CC:DD:EE:FF"} in out
