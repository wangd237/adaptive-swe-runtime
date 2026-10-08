"""Workspace lifecycle: terminal quiescence is not a business success verdict."""
from __future__ import annotations
from enum import Enum
from pathlib import Path
from threading import RLock
from pydantic import model_validator

from aswe.core.contracts._base import FrozenModel
from aswe.core.ids import validate_safe_id
from aswe.repository import RepositoryBinding


class WorkspaceSessionStatus(str, Enum):
    BOOTSTRAPPING = "bootstrapping"
    READY = "ready"
    ACTIVE = "active"
    FROZEN = "frozen"
    QUARANTINED = "quarantined"
    CLOSED = "closed"


class WorkspaceSession(FrozenModel):
    task_id: str
    thread_id: str
    user_id: str
    workspace_root: str
    repository: RepositoryBinding | None = None
    status: WorkspaceSessionStatus

    @model_validator(mode="after")
    def validate_identity(self) -> "WorkspaceSession":
        for identity in (self.task_id, self.thread_id, self.user_id):
            validate_safe_id(identity)
        if not Path(self.workspace_root).is_absolute():
            raise ValueError("workspace root must be an absolute path")
        if self.repository is not None and (
            Path(self.repository.repository_root).resolve() != Path(self.workspace_root).resolve()
        ):
            raise ValueError("RepositoryBinding must point to shared workspace root")
        return self


class WorkspaceLifecycle:
    """Publishes immutable session snapshots; Scheduler/lock manager own transitions."""

    _allowed = {
        WorkspaceSessionStatus.BOOTSTRAPPING: {WorkspaceSessionStatus.READY,
                                                WorkspaceSessionStatus.QUARANTINED},
        WorkspaceSessionStatus.READY: {WorkspaceSessionStatus.ACTIVE,
                                       WorkspaceSessionStatus.FROZEN,
                                       WorkspaceSessionStatus.QUARANTINED},
        WorkspaceSessionStatus.ACTIVE: {WorkspaceSessionStatus.FROZEN,
                                        WorkspaceSessionStatus.QUARANTINED},
        WorkspaceSessionStatus.FROZEN: {WorkspaceSessionStatus.CLOSED},
        WorkspaceSessionStatus.QUARANTINED: {WorkspaceSessionStatus.CLOSED},
        WorkspaceSessionStatus.CLOSED: set(),
    }

    def __init__(self, session: WorkspaceSession):
        self._current = session
        self._lock = RLock()

    @property
    def current(self) -> WorkspaceSession:
        with self._lock:
            return self._current

    def transition(self, target: WorkspaceSessionStatus) -> WorkspaceSession:
        with self._lock:
            if target not in self._allowed[self._current.status]:
                raise ValueError(f"invalid WorkspaceSession transition: {self._current.status} -> {target}")
            self._current = self._current.model_copy(update={"status": target})
            return self._current

    def mark_ready(self, binding: RepositoryBinding | None = None) -> WorkspaceSession:
        with self._lock:
            if self._current.status is not WorkspaceSessionStatus.BOOTSTRAPPING:
                raise ValueError("workspace not bootstrapping")
            updated = self._current.model_copy(update={"repository": binding, "status": WorkspaceSessionStatus.READY})
            self._current = updated
            return updated

    def assert_can_finalize(self) -> None:
        if self.current.status is not WorkspaceSessionStatus.FROZEN:
            raise RuntimeError("workspace-touching finalization requires proven FROZEN workspace")
