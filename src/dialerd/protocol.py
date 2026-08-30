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
