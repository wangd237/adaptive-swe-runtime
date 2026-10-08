"""Immutable task-scoped terminal TaskResult persistence outside Agent Workspace."""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

from aswe.core.fingerprint import canonical_json_bytes
from aswe.core.ids import validate_safe_id
from aswe.runtime.finalization import TaskResult


class TaskResultIntegrityError(RuntimeError):
    pass


class LocalTaskResultStore:
    """Exactly one immutable terminal publication for one task in P1.

    A file exclusively created with O_EXCL cannot replace an existing result.
    A restart resolves the identical TaskResult and validates its fingerprint.
    Single-process runtime assumption; not a distributed transaction.
    """

    def __init__(self, *, runtime_data_dir: str | Path,
                 workspace_root: str | Path | None = None):
        self.root = Path(runtime_data_dir).resolve()
        if workspace_root is not None:
            workspace = Path(workspace_root).resolve()
            if self.root == workspace or self.root.is_relative_to(workspace):
                raise ValueError("TaskResult persistence must remain outside Workspace")
        self._lock = RLock()

    def _path(self, task_id: str) -> Path:
        validate_safe_id(task_id)
        return self.root / "tasks" / task_id / "task_result.json"

    def persist(self, result: TaskResult) -> None:
        path = self._path(result.task_id)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = canonical_json_bytes(result) + b"\n"
            fd = None
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    fd = None
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                if os.name != "nt":
                    directory = os.open(path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            except FileExistsError as exc:
                raise TaskResultIntegrityError("terminal TaskResult already published") from exc
            finally:
                if fd is not None:
                    os.close(fd)

    def get(self, task_id: str) -> TaskResult:
        try:
            data = json.loads(self._path(task_id).read_text(encoding="utf-8"))
            result = TaskResult.model_validate(data)
        except (OSError, ValueError) as exc:
            raise TaskResultIntegrityError("missing or corrupted TaskResult") from exc
        if result.task_id != task_id:
            raise TaskResultIntegrityError("task owner mismatch")
        return result


def finalize_and_persist_task(*, result_store: LocalTaskResultStore, **kwargs) -> TaskResult:
    from aswe.runtime.finalization import finalize_task
    outcome = finalize_task(**kwargs)
    result_store.persist(outcome)
    return outcome
