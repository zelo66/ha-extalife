"""Recording of the traffic exchanged with EFC-01 controller.

Recordings are JSON Lines files. The first line is a header, every next line is one message:
    {"t": 1.234, "dir": "out", "msg": {...}}      - message sent to the controller
    {"t": 1.301, "dir": "in", "msg": {...}}       - message received from the controller
    {"t": 1.400, "dir": "in", "raw": "..."}       - received message which is not valid JSON
Credentials are removed before a message is stored. Recordings are used to reproduce problems and
as test data (tests/recordings).
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

RECORDING_FORMAT = "extalife-traffic"
RECORDING_VERSION = 1
REDACTED = "**REDACTED**"

# keys whose values are never stored in a recording
REDACT_KEYS = frozenset({"password", "login", "user", "username", "email", "mail", "phone", "token"})

# protection against unbounded memory usage
MAX_MESSAGES = 50_000


def redact(value: Any) -> Any:
    """Return copy of the value with credentials removed"""
    if isinstance(value, dict):
        return {
            key: REDACTED if isinstance(key, str) and key.lower() in REDACT_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class TrafficRecorder:
    """Collects messages exchanged with the controller in memory and saves them to a file"""

    def __init__(self, header: dict[str, Any] | None = None) -> None:
        self._start = time.monotonic()
        self._started_at = datetime.now().astimezone()
        self._header = header or {}
        self._records: list[dict[str, Any]] = []
        self._truncated = False

    @property
    def message_count(self) -> int:
        return len(self._records)

    @property
    def started_at(self) -> datetime:
        return self._started_at

    def record(self, direction: str, message: str) -> None:
        """Traffic callback - store single message"""
        if len(self._records) >= MAX_MESSAGES:
            self._truncated = True
            return

        entry: dict[str, Any] = {"t": round(time.monotonic() - self._start, 3), "dir": direction}
        try:
            entry["msg"] = redact(json.loads(message))
        except ValueError:
            # not a JSON message - store as is, it may be the reason of a problem
            entry["raw"] = message
        self._records.append(entry)

    def header(self) -> dict[str, Any]:
        return {
            "format": RECORDING_FORMAT,
            "version": RECORDING_VERSION,
            "created": self._started_at.isoformat(timespec="seconds"),
            "messages": len(self._records),
            "truncated": self._truncated,
            **self._header,
        }

    def save(self, path: Path) -> int:
        """Write recording to a file (blocking - run in executor). Returns number of bytes written"""
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(self.header(), ensure_ascii=False)]
        lines += [json.dumps(record, ensure_ascii=False) for record in self._records]
        content = "\n".join(lines) + "\n"
        path.write_text(content, encoding="utf-8")
        return len(content.encode("utf-8"))


def load_recording(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read recording file, returns header and list of records"""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"{path} is empty")
    header = json.loads(lines[0])
    if header.get("format") != RECORDING_FORMAT:
        raise ValueError(f"{path} is not an Exta Life traffic recording")
    return header, [json.loads(line) for line in lines[1:]]
