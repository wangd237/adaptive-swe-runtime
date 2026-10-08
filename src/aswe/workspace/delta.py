"""Attempt-local physical and Git-visible mutation attribution."""
from __future__ import annotations

from enum import Enum
from pydantic import Field

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts import EvidenceRef, WorkspaceRevision
from aswe.core.fingerprint import fingerprint
from aswe.repository import RepositoryStateDigest, compare_repository_states
from .snapshot import FilesystemSnapshot, changed_snapshot_paths


class MutationEvidence(str, Enum):
    PROVEN_NONE = "proven_none"
    OBSERVED = "observed"
    UNKNOWN = "unknown"


class NodeWorkspaceDelta(FrozenModel):
    node_id: str
    execution_id: str
    attempt: int = Field(ge=1)
    before_revision_generation: int
    after_revision_generation: int
    changed_paths: tuple[str, ...]
    changed_paths_complete: bool
    repository_changed_paths: tuple[str, ...]
    repository_changed_paths_complete: bool
    has_observed_changes: bool
    attribution_truncated: bool
    mutating_tool_admitted: bool | None
    mutation_evidence: MutationEvidence
    summary: dict
    workspace_changeset: EvidenceRef | None = None
    fingerprint: str


def derive_node_workspace_delta(
    *, node_id: str, execution_id: str, attempt: int,
    before_revision: WorkspaceRevision,
    before_filesystem: FilesystemSnapshot, after_filesystem: FilesystemSnapshot,
    before_repository: RepositoryStateDigest, after_repository: RepositoryStateDigest,
    repository_root: str,
    mutating_tool_admitted: bool | None,
) -> tuple[NodeWorkspaceDelta, WorkspaceRevision]:
    if before_revision.repository_state_fingerprint != before_repository.fingerprint:
        raise ValueError("pre-revision repository evidence mismatch")
    if before_revision.base_sha != before_repository.base_sha:
        raise ValueError("pre-revision baseline mismatch")
    repo_paths = compare_repository_states(before_repository, after_repository, repository_root)
    physical_paths = changed_snapshot_paths(before_filesystem, after_filesystem)
    complete = before_filesystem.complete and after_filesystem.complete
    repo_observed = before_repository.fingerprint != after_repository.fingerprint
    observed = bool(repo_paths or physical_paths or repo_observed)
    if observed:
        mutation = MutationEvidence.OBSERVED
    elif mutating_tool_admitted is False and complete:
        mutation = MutationEvidence.PROVEN_NONE
    else:
        mutation = MutationEvidence.UNKNOWN
    generation = before_revision.generation + int(mutation is not MutationEvidence.PROVEN_NONE)
    revision = WorkspaceRevision(
        generation=generation, base_sha=after_repository.base_sha,
        head_sha=after_repository.head_sha,
        head_matches_baseline=after_repository.head_matches_baseline,
        repository_state_fingerprint=after_repository.fingerprint,
        dirty=after_repository.dirty_vs_base,
    )
    fields = {
        "node_id": node_id, "execution_id": execution_id, "attempt": attempt,
        "before_revision_generation": before_revision.generation,
        "after_revision_generation": generation,
        "changed_paths": physical_paths, "changed_paths_complete": complete,
        "repository_changed_paths": repo_paths, "repository_changed_paths_complete": True,
        "has_observed_changes": observed, "attribution_truncated": not complete,
        "mutating_tool_admitted": mutating_tool_admitted, "mutation_evidence": mutation,
        "summary": {"observed_scanner_paths": len(physical_paths),
                    "observed_repository_paths": len(repo_paths)},
        "workspace_changeset": None,
    }
    return NodeWorkspaceDelta(**fields, fingerprint=fingerprint(fields)), revision
