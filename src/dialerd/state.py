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
