"""Terminal TaskResult: orthogonal task/workspace/repository/patch outcomes.

Workspace inspection happens only for FROZEN, never QUARANTINED.
A residual patch cannot be promoted to accepted success.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import model_validator

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts import EvidenceRef, TaskEvidenceKind, TaskEvidenceRef, WorkspaceRevision
from aswe.core.fingerprint import fingerprint
from aswe.core.ids import new_finalization_id
from aswe.evidence import LocalEvidenceStore
from aswe.evaluation.contracts import ContractVerdict
from aswe.repository import RepositoryBinding, capture_repository_state, materialize_repository_changeset
from aswe.runtime.state import NodeLogicalStatus
from aswe.workspace.session import WorkspaceSessionStatus


class TaskLogicalStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkspaceDisposition(str, Enum):
    STABLE = "stable"
    STABLE_WITH_UNCERTAINTY = "stable_with_uncertainty"
    QUARANTINED = "quarantined"


class RepositoryDisposition(str, Enum):
    BASELINE_CLEAN = "baseline_clean"
    PATCH_PRESENT = "patch_present"
    INVARIANT_BROKEN = "invariant_broken"
    UNKNOWN = "unknown"


class PatchDisposition(str, Enum):
    NONE = "none"
    ACCEPTED = "accepted"
    RESIDUAL_UNACCEPTED = "residual_unaccepted"
    UNAVAILABLE = "unavailable"


class RootFailureRecord(FrozenModel):
    failure_kind: str
    node_id: str | None = None
    execution_id: str | None = None
    attempt: int | None = None
    supporting_evidence_refs: tuple[EvidenceRef, ...] = ()
    diagnostics: tuple[str, ...] = ()
    fingerprint: str

    @model_validator(mode="after")
    def validate_fingerprint(self):
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("root failure fingerprint mismatch")
        return self


class TaskResult(FrozenModel):
    task_id: str
    status: TaskLogicalStatus
    workspace_disposition: WorkspaceDisposition
    repository_disposition: RepositoryDisposition
    patch_disposition: PatchDisposition
    final_workspace_revision: WorkspaceRevision | None
    final_repository_state: TaskEvidenceRef | None
    final_repository_changeset: TaskEvidenceRef | None
    final_contract_verdict: TaskEvidenceRef | None
    last_trusted_evidence_refs: tuple[EvidenceRef, ...] = ()
    root_failures: tuple[RootFailureRecord, ...] = ()
    blocked_node_ids: tuple[str, ...] = ()
    cancelled_node_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    fingerprint: str

    @model_validator(mode="after")
    def validate_terminal_semantics(self):
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("TaskResult fingerprint mismatch")
        if self.status is TaskLogicalStatus.RUNNING:
            raise ValueError("terminal TaskResult may not be RUNNING")
        if self.status is TaskLogicalStatus.SUCCEEDED:
            if self.root_failures or self.final_contract_verdict is None:
                raise ValueError("SUCCEEDED requires contract proof and zero roots")
            if self.patch_disposition not in (PatchDisposition.NONE, PatchDisposition.ACCEPTED):
                raise ValueError("SUCCEEDED requires accepted or absent patch")
            if self.workspace_disposition is WorkspaceDisposition.QUARANTINED:
                raise ValueError("SUCCEEDED cannot be quarantined")
        if self.patch_disposition is PatchDisposition.ACCEPTED and self.status is not TaskLogicalStatus.SUCCEEDED:
            raise ValueError("ACCEPTED patch requires SUCCEEDED task")
        if self.repository_disposition is RepositoryDisposition.PATCH_PRESENT:
            expected = (PatchDisposition.ACCEPTED if self.status is TaskLogicalStatus.SUCCEEDED
                        else PatchDisposition.RESIDUAL_UNACCEPTED)
            if self.patch_disposition is not expected:
                raise ValueError("patch-present disposition inconsistent with terminal status")
        if self.workspace_disposition is WorkspaceDisposition.QUARANTINED:
            if self.final_workspace_revision is not None:
                raise ValueError("QUARANTINED may not advertise current final revision")
            if self.final_repository_state is not None or self.final_repository_changeset is not None:
                raise ValueError("QUARANTINED may not materialize current-final repository evidence")
            if (self.repository_disposition is not RepositoryDisposition.UNKNOWN
                or self.patch_disposition is not PatchDisposition.UNAVAILABLE):
                raise ValueError("QUARANTINED must report unknown/unavailable current Git state")
        return self


def _root(**values) -> RootFailureRecord:
    normalized = dict(failure_kind=values["failure_kind"], node_id=None,
        execution_id=None, attempt=None, supporting_evidence_refs=(), diagnostics=())
    normalized.update(values)
    return RootFailureRecord(**normalized, fingerprint=fingerprint(normalized))


def finalize_task(
    *, scheduler, binding: RepositoryBinding,
    evidence_store: LocalEvidenceStore,
    contract_verdict: ContractVerdict | None = None,
    physical_attribution_complete: bool = True,
) -> TaskResult:
    """Synchronous Runtime-only terminal finalization. Do not call from an agent.

    No backend/LLM/tool calls and no workspace I/O on QUARANTINED.
    The caller must first perform a task-wide fail-close and committed join.
    """
    lifecycle = scheduler.workspace.lifecycle.current.status
    if lifecycle not in (WorkspaceSessionStatus.FROZEN, WorkspaceSessionStatus.QUARANTINED):
        raise RuntimeError("terminalization requires completed quiescence drain")
    if any(s.logical_status is NodeLogicalStatus.RUNNING for s in scheduler.states.values()):
        if lifecycle is not WorkspaceSessionStatus.QUARANTINED:
            raise RuntimeError("running node cannot be finalized on FROZEN workspace")
    all_success = all(s.logical_status is NodeLogicalStatus.SUCCEEDED for s in scheduler.states.values())
    cancelled = bool(getattr(scheduler, "cancelled", False))
    succeeded = (not cancelled and not scheduler.failed and all_success
                 and contract_verdict is not None and contract_verdict.all_required_satisfied
                 and lifecycle is WorkspaceSessionStatus.FROZEN)
    task_status = (TaskLogicalStatus.CANCELLED if cancelled else
                   TaskLogicalStatus.SUCCEEDED if succeeded else TaskLogicalStatus.FAILED)

    roots = []
    if task_status is TaskLogicalStatus.FAILED:
        for node_id, state in scheduler.states.items():
            if state.logical_status is NodeLogicalStatus.FAILED:
                attempt = state.attempts[-1] if state.attempts else None
                kind = state.terminal_failure_kind or (attempt.failure_kind if attempt else None) or "NODE_FAILURE"
                attrs = dict(failure_kind=kind, node_id=node_id,
                             execution_id=attempt.execution_id if attempt else None,
                             attempt=attempt.attempt if attempt else None,
                             supporting_evidence_refs=attempt.evidence_refs if attempt else (),
                             diagnostics=())
                roots.append(_root(**attrs))
        if not roots:
            roots.append(_root(failure_kind=(
                scheduler.failure_kinds[0] if scheduler.failure_kinds else
                "TASK_CONTRACT_UNVERIFIED" if contract_verdict is None else "TASK_TERMINAL_FAILURE")))
    roots = tuple(sorted(roots, key=lambda r: (r.node_id or "", r.failure_kind)))
    blocked = tuple(sorted(node_id for node_id, st in scheduler.states.items()
                           if st.logical_status is NodeLogicalStatus.BLOCKED))
    cancelled_ids = tuple(sorted(node_id for node_id, st in scheduler.states.items()
                                 if st.logical_status is NodeLogicalStatus.CANCELLED or
                                 (st.attempts and st.attempts[-1].status.value == "cancelled")))
    historical = tuple(ref for st in scheduler.states.values() for attempt in st.attempts
                       for ref in attempt.evidence_refs)
    # Preserve every already-persisted attempt evidence, never claim it is current-final.
    historical = tuple(sorted(set(historical), key=lambda ref: ref.evidence_id))

    repository_state_ref = changeset_ref = contract_ref = None
    revision = None
    warnings = []
    if lifecycle is WorkspaceSessionStatus.QUARANTINED:
        workspace_disposition = WorkspaceDisposition.QUARANTINED
        repository_disposition = RepositoryDisposition.UNKNOWN
        patch_disposition = PatchDisposition.UNAVAILABLE
    else:
        workspace_disposition = (WorkspaceDisposition.STABLE if physical_attribution_complete
            else WorkspaceDisposition.STABLE_WITH_UNCERTAINTY)
        state = capture_repository_state(binding)
        revision = WorkspaceRevision(
            generation=scheduler.revision.generation, base_sha=state.base_sha,
            head_sha=state.head_sha, head_matches_baseline=state.head_matches_baseline,
            repository_state_fingerprint=state.fingerprint, dirty=state.dirty_vs_base,
        )
        finalization_id = new_finalization_id()
        repository_state_ref = evidence_store.put_task(
            task_id=scheduler.task_id, finalization_id=finalization_id,
            kind=TaskEvidenceKind.FINAL_REPOSITORY_STATE,
            payload=state, workspace_revision=revision,
        )
        if not state.head_matches_baseline:
            repository_disposition = RepositoryDisposition.INVARIANT_BROKEN
            patch_disposition = PatchDisposition.UNAVAILABLE
            succeeded = False
            task_status = TaskLogicalStatus.CANCELLED if cancelled else TaskLogicalStatus.FAILED
            roots = roots + (_root(failure_kind="REPOSITORY_INVARIANT_FAILURE"),)
        else:
            repository_disposition = (RepositoryDisposition.PATCH_PRESENT if state.dirty_vs_base
                                      else RepositoryDisposition.BASELINE_CLEAN)
            if state.dirty_vs_base:
                try:
                    changeset = materialize_repository_changeset(binding)
                    if (changeset.working_tree_oid != state.working_tree_oid
                        or changeset.head_sha != state.head_sha):
                        raise RuntimeError("final working tree drift")
                    changeset_ref = evidence_store.put_task(
                        task_id=scheduler.task_id, finalization_id=finalization_id,
                        kind=TaskEvidenceKind.FINAL_REPOSITORY_CHANGESET,
                        payload=changeset, workspace_revision=revision,
                    )
                    patch_disposition = (PatchDisposition.ACCEPTED if succeeded
                                         else PatchDisposition.RESIDUAL_UNACCEPTED)
                except Exception:
                    patch_disposition = PatchDisposition.UNAVAILABLE
                    succeeded = False
                    task_status = TaskLogicalStatus.CANCELLED if cancelled else TaskLogicalStatus.FAILED
                    warnings.append("FINAL_CHANGESET_MATERIALIZATION_FAILED")
                    roots = roots + (_root(failure_kind="FINAL_CHANGESET_MATERIALIZATION_FAILED"),)
            else:
                patch_disposition = PatchDisposition.NONE
        if contract_verdict is not None:
            contract_ref = evidence_store.put_task(
                task_id=scheduler.task_id, finalization_id=finalization_id,
                kind=TaskEvidenceKind.FINAL_CONTRACT_VERDICT,
                payload=contract_verdict, workspace_revision=revision,
            )
        if task_status is TaskLogicalStatus.FAILED and not roots:
            roots = (_root(failure_kind="TASK_CONTRACT_UNVERIFIED" if contract_verdict is None
                           else "TASK_CONTRACT_UNSATISFIED"),)
    values = dict(
        task_id=scheduler.task_id, status=task_status,
        workspace_disposition=workspace_disposition,
        repository_disposition=repository_disposition,
        patch_disposition=patch_disposition,
        final_workspace_revision=revision,
        final_repository_state=repository_state_ref,
        final_repository_changeset=changeset_ref,
        final_contract_verdict=contract_ref if succeeded else contract_ref,
        last_trusted_evidence_refs=historical,
        root_failures=roots, blocked_node_ids=blocked,
        cancelled_node_ids=cancelled_ids, warnings=tuple(warnings),
    )
    return TaskResult(**values, fingerprint=fingerprint(values))
