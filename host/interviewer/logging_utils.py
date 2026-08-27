"""Small JSON Lines session logger with sensitive-field redaction."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "resumption",
    "raw_audio",
    "audio_bytes",
    "environment",
    "env_vars",
)


def local_timestamp() -> str:
    """Return the current machine-local time with its UTC offset included."""

    return datetime.now().astimezone().isoformat()


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact_sensitive(value: Any) -> Any:
    """Recursively redact fields that must not enter normal session logs."""

    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(str(key)) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item) for item in value]
    return value


class SessionJsonLogger:
    """Write one append-only JSONL file for an interview session."""

    def __init__(self, logs_dir: str | Path, *, clock=time.monotonic) -> None:
        self.logs_dir = Path(logs_dir)
        self.clock = clock
        self.started_at_monotonic: float | None = None
        self.path: Path | None = None

    def start(self, *, now: float | None = None) -> Path:
        if self.path is not None:
            return self.path
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        self.path = self.logs_dir / f"interview-{timestamp}-{uuid.uuid4().hex[:8]}.jsonl"
        self.started_at_monotonic = self.clock() if now is None else float(now)
        return self.path

    def log(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        elapsed_seconds: float | None = None,
    ) -> None:
        if self.path is None:
            self.start()
        assert self.path is not None
        if elapsed_seconds is None and self.started_at_monotonic is not None:
            elapsed_seconds = max(0.0, self.clock() - self.started_at_monotonic)
        record = {
            "timestamp": local_timestamp(),
            "elapsedSeconds": round(float(elapsed_seconds or 0.0), 3),
            "event": event_type,
            "payload": redact_sensitive(dict(payload or {})),
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
