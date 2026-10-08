"""Single-process fsynced append-only trace, kept separate from EvidenceStore."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import RLock

from pydantic import Field

from aswe.core.contracts._base import FrozenModel
from aswe.core.fingerprint import canonical_json_bytes
from aswe.core.ids import validate_safe_id


class RuntimeEvent(FrozenModel):
    task_id: str
    seq: int = Field(ge=1)
    event_type: str
    timestamp: datetime
    source: str
    node_id: str | None = None
    payload: dict


class LocalRuntimeEventSink:
    """Append-only event sink; events are informational, not evidence authority."""

    def __init__(self, runtime_data_dir: str | Path, task_id: str,
                 *, workspace_root: str | Path | None = None):
        validate_safe_id(task_id)
        self.task_id = task_id
        self.path = Path(runtime_data_dir).resolve() / "tasks" / task_id / "events.jsonl"
        if workspace_root is not None:
            workspace = Path(workspace_root).resolve()
            if self.path.is_relative_to(workspace):
                raise ValueError("trace must be outside workspace")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._next_seq = len(self.read_all()) + 1

    def read_all(self) -> tuple[RuntimeEvent, ...]:
        if not self.path.exists():
            return ()
        events = []
        for line in self.path.read_bytes().splitlines():
            if not line:
                raise ValueError("malformed empty runtime event")
            event = RuntimeEvent.model_validate(json.loads(line))
            if event.task_id != self.task_id or event.seq != len(events) + 1:
                raise ValueError("trace provenance or sequence invalid")
            events.append(event)
        return tuple(events)

    def emit(self, event_type: str, *, source: str = "aswe-runtime",
             node_id: str | None = None, payload: dict | None = None) -> RuntimeEvent:
        if not event_type:
            raise ValueError("event_type required")
        data = payload if payload is not None else {}
        encoded = canonical_json_bytes(data)
        if len(encoded) > 16 * 1024:
            raise ValueError("trace payload too large; use EvidenceStore")
        with self._lock:
            event = RuntimeEvent(
                task_id=self.task_id, seq=self._next_seq, event_type=event_type,
                timestamp=datetime.now(timezone.utc), source=source, node_id=node_id,
                payload=json.loads(encoded),
            )
            raw = canonical_json_bytes(event) + b"\n"
            with open(self.path, "ab") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self._next_seq += 1
            return event
