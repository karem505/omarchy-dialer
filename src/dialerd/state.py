from __future__ import annotations

import time
from typing import Any, Callable

from dialerd.protocol import encode_event

# States in which the two parties are connected and the meter is running.
# "incoming"/"dialing"/"alerting" are setup, not talk time.
CONNECTED_STATES = frozenset({"active", "held"})


def call_id(path: str) -> str:
    return path.rsplit("/", 1)[-1]


class DialerState:
    """Authoritative view of the gateway and its calls.

    Every mutator returns the NDJSON lines describing what changed, so the
    server can broadcast without re-deriving anything.
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._gateway_path: str | None = None
        self._address: str | None = None
        self._name: str | None = None
        self._transport: tuple[str, int] | None = None
        self._calls: dict[str, dict[str, Any]] = {}
        # Wall-clock epoch when each call connected. None means "we joined
        # this call in progress and genuinely do not know".
        self._started: dict[str, float | None] = {}

    def set_gateway(self, path: str | None, address: str | None, name: str | None) -> list[str]:
        # _rescan runs on every InterfacesAdded/Removed and on the bus name
        # watch, so an unchanged gateway must stay silent rather than making
        # clients rebuild bindings for nothing.
        if (path, address, name) == (self._gateway_path, self._address, self._name):
            return []
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
        previous = self._calls.get(path)
        merged = dict(previous or {})
        merged.update(props)
        if merged == previous:
            return []
        self._calls[path] = merged
        self._stamp(path, previous, merged)
        return [self._call_event(path, merged, self._started.get(path))]

    def remove_call(self, path: str) -> list[str]:
        self._started.pop(path, None)
        if self._calls.pop(path, None) is None:
            return []
        return [encode_event("call_removed", id=call_id(path))]

    def snapshot(self) -> list[str]:
        if self._gateway_path is None:
            return [encode_event("gateway", connected=False)]
        lines = [encode_event("gateway", connected=True, address=self._address, name=self._name)]
        if self._transport is not None:
            lines.append(encode_event("transport", state=self._transport[0], codec=self._transport[1]))
        lines.extend(
            self._call_event(p, props, self._started.get(p))
            for p, props in self._calls.items()
        )
        return lines

    def _stamp(self, path: str, previous: dict[str, Any] | None, merged: dict[str, Any]) -> None:
        """Record when a call connected, once, and never guess."""
        if path in self._started or merged.get("State") not in CONNECTED_STATES:
            return
        # A call that was already up the first time we saw it was adopted
        # mid-flight -- at daemon start, or after wireplumber restarted. Its
        # real start time is unrecoverable, and a duration counting from when
        # the daemon woke up would be a confident lie, so say nothing.
        self._started[path] = None if previous is None else self._clock()

    @staticmethod
    def _call_event(path: str, props: dict[str, Any], started: float | None) -> str:
        return encode_event(
            "call",
            id=call_id(path),
            state=props.get("State"),
            line=props.get("LineIdentification") or None,
            name=props.get("Name") or None,
            started=started,
        )
