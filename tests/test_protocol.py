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
