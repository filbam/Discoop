"""Anonymized protocol trace for `discoop login --trace`.

It records message shapes (op names, field names, value types and lengths), timings and
close codes. Values are kept only for the non-secret keys in SAFE_VALUE_KEYS, so keys,
nonces, fingerprints, tickets and tokens never reach the file.
"""

import json
import time
from pathlib import Path
from typing import Any

SAFE_VALUE_KEYS = {
    "op",
    "heartbeat_interval",
    "timeout_ms",
    "captcha_service",
    "code",
    "message",
    "retry_after",
    "global",
}
_MAX_SAFE_LEN = 200


def shape(value: Any) -> Any:
    """Describe a JSON value without its content."""
    if isinstance(value, dict):
        return {key: _field(key, item) for key, item in value.items()}
    if isinstance(value, list):
        return {"type": "list", "len": len(value), "item": shape(value[0]) if value else None}
    if isinstance(value, str):
        return {"type": "str", "len": len(value)}
    if value is None:
        return None
    return {"type": type(value).__name__}


def _field(key: str, value: Any) -> Any:
    if key in SAFE_VALUE_KEYS and (value is None or isinstance(value, bool | int | float)):
        return value
    if key in SAFE_VALUE_KEYS and isinstance(value, str):
        return value[:_MAX_SAFE_LEN]
    return shape(value)


class Trace:
    """Writes JSON lines to `path`; does nothing when `path` is None."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._start = time.monotonic()
        self._file = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("w", encoding="utf-8")

    def __enter__(self) -> "Trace":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close_file()

    def close_file(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def frame(self, direction: str, payload: dict[str, Any]) -> None:
        self._write({"kind": "ws", "dir": direction, "frame": shape(payload)})

    def close(self, code: int | None, reason: str | None) -> None:
        self._write({"kind": "ws_close", "code": code, "reason": (reason or "")[:_MAX_SAFE_LEN]})

    def http(self, method: str, path: str, status: int, body: Any) -> None:
        self._write({"kind": "http", "method": method, "path": path, "status": status, "body": shape(body)})

    def event(self, name: str, **details: str | int | float | None) -> None:
        """Free-form marker. Callers pass only non-secret details."""
        self._write({"kind": "event", "name": name, **details})

    def _write(self, record: dict[str, Any]) -> None:
        if self._file is None:
            return
        record = {"t_ms": round((time.monotonic() - self._start) * 1000), **record}
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()
