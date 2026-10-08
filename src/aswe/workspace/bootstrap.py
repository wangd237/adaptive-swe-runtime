"""Deterministic task workspace bootstrap; no Agent or Scheduler involvement."""
from __future__ import annotations

from pathlib import Path

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts import WorkspaceRevision
from aswe.core.ids import validate_safe_id
from aswe.repository import bootstrap_repository, capture_repository_state, RepositoryStateDigest
from .session import WorkspaceLifecycle, WorkspaceSession, WorkspaceSessionStatus
from .snapshot import FilesystemSnapshot, capture_filesystem_snapshot


class WorkspaceBootstrapResult(FrozenModel):
    session: WorkspaceSession
    initial_revision: WorkspaceRevision
    baseline_repository_state: RepositoryStateDigest
    baseline_filesystem_snapshot: FilesystemSnapshot


def bootstrap_task_workspace(
    *, task_id: str, thread_id: str, user_id: str,
    source: str | Path, workspace_root: str | Path,
    requested_ref: str = "HEAD",
) -> WorkspaceBootstrapResult:
    """Clone → checkout exact commit → prove clean → snapshot → READY.

    The scanner's baseline is captured AFTER checkout. Repository files are not
    falsely attributed to the first Agent attempt.
    """
    for identity in (task_id, thread_id, user_id):
        validate_safe_id(identity)
    root = Path(workspace_root).resolve()
    lifecycle = WorkspaceLifecycle(WorkspaceSession(
        task_id=task_id, thread_id=thread_id, user_id=user_id,
        workspace_root=str(root), status=WorkspaceSessionStatus.BOOTSTRAPPING,
    ))
    binding = bootstrap_repository(source, root, requested_ref=requested_ref)
    digest = capture_repository_state(binding)
    if digest.dirty_vs_base or not digest.head_matches_baseline:
        raise RuntimeError("WORKSPACE_BOOTSTRAP_BASELINE_INVALID")
    snapshot = capture_filesystem_snapshot(root)
    revision = WorkspaceRevision(
        generation=0, base_sha=digest.base_sha, head_sha=digest.head_sha,
        head_matches_baseline=True, repository_state_fingerprint=digest.fingerprint,
        dirty=False,
    )
    ready = lifecycle.mark_ready(binding)
    return WorkspaceBootstrapResult(
        session=ready, initial_revision=revision,
        baseline_repository_state=digest, baseline_filesystem_snapshot=snapshot,
    )
