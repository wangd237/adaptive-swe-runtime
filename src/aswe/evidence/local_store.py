"""Single-process durable, immutable evidence store outside the agent workspace."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from aswe.core.contracts import (
    AttemptEvidenceKind, EvidenceRef, TaskEvidenceKind, TaskEvidenceRef, WorkspaceRevision
)
from aswe.core.fingerprint import canonical_json_bytes
from aswe.core.ids import validate_safe_id


class EvidenceIntegrityError(RuntimeError):
    """A stored artifact or caller-provided reference violates integrity/provenance."""


class EvidencePersistenceError(RuntimeError):
    """Evidence publication could not be completed durably."""


class LocalEvidenceStore:
    """Immutable single-writer evidence; a reference is resolvable after restart.

    Evidence IDs embed a safe, runtime-owned task ID followed by an opaque random
    suffix. This enables get(ref) without a volatile in-memory locator index.
    """

    def __init__(self, runtime_data_dir: str | Path, *, workspace_root: str | Path | None = None):
        self.root = Path(runtime_data_dir).resolve()
        if workspace_root is not None:
            workspace = Path(workspace_root).resolve()
            if self.root == workspace or self.root.is_relative_to(workspace):
                raise ValueError("evidence store must live outside repository workspace")
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    @staticmethod
    def _new_id(task_id: str) -> str:
        validate_safe_id(task_id)
        return validate_safe_id(f"{task_id}__{uuid4().hex}")

    def _artifact_path(self, evidence_id: str) -> Path:
        validate_safe_id(evidence_id)
        if "__" not in evidence_id:
            raise EvidenceIntegrityError("evidence id missing task-scoped namespace")
        task_id, suffix = evidence_id.rsplit("__", 1)
        if not task_id or len(suffix) != 32 or any(c not in "0123456789abcdef" for c in suffix):
            raise EvidenceIntegrityError("invalid evidence id format")
        validate_safe_id(task_id)
        return self.root / "tasks" / task_id / "evidence" / (evidence_id + ".json")

    @staticmethod
    def _revision_fields(revision: WorkspaceRevision | None) -> dict[str, Any]:
        return {
            "workspace_revision_generation": revision.generation if revision else None,
            "workspace_state_fingerprint": revision.repository_state_fingerprint if revision else None,
        }

    @staticmethod
    def _canonical_payload(payload: BaseModel | dict) -> tuple[Any, bytes]:
        if not isinstance(payload, (BaseModel, dict)):
            raise TypeError("evidence payload must be Pydantic model or dict")
        content = canonical_json_bytes(payload)
        return json.loads(content), content

    def _publish(self, ref: EvidenceRef | TaskEvidenceRef, task_id: str, payload: Any) -> None:
        path = self._artifact_path(ref.evidence_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"scope": "attempt" if isinstance(ref, EvidenceRef) else "task",
                  "task_id": task_id, "ref": ref.model_dump(mode="json"), "payload": payload}
        data = canonical_json_bytes(record) + b"\n"
        tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with open(tmp, "xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Single-process writer: a collision is never silently overwritten.
            if path.exists():
                raise EvidencePersistenceError("evidence id collision")
            os.replace(tmp, path)
            if os.name != "nt":
                fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except Exception as exc:
            if tmp.exists():
                tmp.unlink()
            if isinstance(exc, EvidencePersistenceError):
                raise
            raise EvidencePersistenceError("evidence publication failed") from exc

    def put_attempt(
        self, *, task_id: str, node_id: str, execution_id: str, attempt: int,
        kind: AttemptEvidenceKind, payload: BaseModel | dict,
        workspace_revision: WorkspaceRevision | None,
    ) -> EvidenceRef:
        validate_safe_id(task_id)
        if not node_id or not execution_id or attempt < 1:
            raise ValueError("attempt provenance required")
        parsed, raw = self._canonical_payload(payload)
        with self._lock:
            ref = EvidenceRef(
                evidence_id=self._new_id(task_id), kind=kind, source_node_id=node_id,
                source_execution_id=execution_id, source_attempt=attempt,
                content_sha256=hashlib.sha256(raw).hexdigest(),
                **self._revision_fields(workspace_revision),
            )
            self._publish(ref, task_id, parsed)
        return ref

    def put_task(
        self, *, task_id: str, finalization_id: str, kind: TaskEvidenceKind,
        payload: BaseModel | dict, workspace_revision: WorkspaceRevision | None,
    ) -> TaskEvidenceRef:
        validate_safe_id(task_id)
        validate_safe_id(finalization_id)
        parsed, raw = self._canonical_payload(payload)
        with self._lock:
            ref = TaskEvidenceRef(
                evidence_id=self._new_id(task_id), kind=kind, task_id=task_id,
                finalization_id=finalization_id,
                content_sha256=hashlib.sha256(raw).hexdigest(),
                **self._revision_fields(workspace_revision),
            )
            self._publish(ref, task_id, parsed)
        return ref

    def get(self, ref: EvidenceRef | TaskEvidenceRef) -> dict:
        if not isinstance(ref, (EvidenceRef, TaskEvidenceRef)):
            raise TypeError("get requires EvidenceRef or TaskEvidenceRef")
        with self._lock:
            path = self._artifact_path(ref.evidence_id)
            try:
                data = json.loads(path.read_bytes())
            except (OSError, ValueError) as exc:
                raise EvidenceIntegrityError("evidence missing or malformed") from exc
            if not isinstance(data, dict):
                raise EvidenceIntegrityError("evidence record must be an object")
            expected_scope = "attempt" if isinstance(ref, EvidenceRef) else "task"
            if data.get("scope") != expected_scope or data.get("ref") != ref.model_dump(mode="json"):
                raise EvidenceIntegrityError("evidence provenance mismatch")
            task_id = ref.task_id if isinstance(ref, TaskEvidenceRef) else ref.evidence_id.rsplit("__", 1)[0]
            if data.get("task_id") != task_id:
                raise EvidenceIntegrityError("evidence task owner mismatch")
            payload = data.get("payload")
            if not isinstance(payload, dict):
                raise EvidenceIntegrityError("invalid evidence payload")
            digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
            if digest != ref.content_sha256:
                raise EvidenceIntegrityError("evidence content integrity failure")
            return payload
