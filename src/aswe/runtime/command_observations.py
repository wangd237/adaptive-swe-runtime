"""Provider-neutral trusted command observation interfaces.

Adapters implement the runtime boundary; Core never imports DeerFlow.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from aswe.core.contracts import WorkspaceRevision


@dataclass(frozen=True)
class ForegroundReceipt:
    task_id: str
    node_id: str
    execution_id: str
    attempt: int
    command_id: str
    command_fingerprint: str
    policy_fingerprint: str
    command_policy_fingerprint: str
    argv_fingerprint: str
    returncode: int | None
    timed_out: bool
    completion_observed: bool
    process_group_drained: bool
    pre_repository_fingerprint: str
    post_repository_fingerprint: str
    status: str
    stdout_sha256: str
    stderr_sha256: str
    observed_revision: WorkspaceRevision
    authority: str = "runtime-foreground-command-observation"


class IsolatedPythonCommandBackend(ABC):
    """Nominal host-owned backend contract; no structural duck-type spoofing."""

    @property
    @abstractmethod
    def workspace_root(self) -> Path: ...

    @abstractmethod
    async def run(self, command: str, *, timeout: float, max_output: int): ...
