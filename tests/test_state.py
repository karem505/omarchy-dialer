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


def test_set_gateway_is_idempotent():
    # _rescan fires on every InterfacesAdded/Removed and on the name watch,
    # so an unchanged gateway must not spam identical events at clients.
    st = DialerState()
    st.set_gateway("/org/pipewire/Telephony/ag1", "AA:BB:CC:DD:EE:FF", "Example Phone")
    assert st.set_gateway("/org/pipewire/Telephony/ag1", "AA:BB:CC:DD:EE:FF", "Example Phone") == []


def test_set_gateway_still_emits_on_change():
    st = DialerState()
    st.set_gateway("/org/pipewire/Telephony/ag1", "AA:BB", "one")
    assert st.set_gateway("/org/pipewire/Telephony/ag1", "CC:DD", "two") != []


def test_repeated_disconnect_emits_once():
    st = DialerState()
    st.set_gateway(None, None, None)
    assert st.set_gateway(None, None, None) == []


def test_contacts_event_carries_items_and_availability():
    from dialerd.protocol import encode_event
    line = encode_event("contacts", available=True, count=2,
                        items=[{"name": "Ahmed", "number": "+20"}])
    ev = json.loads(line)
    assert ev["ev"] == "contacts" and ev["count"] == 2
    assert ev["items"][0]["name"] == "Ahmed"


def test_call_event_takes_a_resolved_name():
    st = DialerState()
    out = events(st.upsert_call("/org/pipewire/Telephony/ag1/call1",
                                {"State": "incoming", "LineIdentification": "+201000000001",
                                 "Name": "Ahmed"}))
    assert out[0]["name"] == "Ahmed"
