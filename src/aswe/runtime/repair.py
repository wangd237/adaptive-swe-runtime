"""Deterministic verification-to-writer repair ownership (Specs 03 §9.10).

This resolver establishes *legal remediation ownership*, not causal blame.
The verification evidence must already have been persisted and attached to
the matching attempt by the Runtime; model prose has no authority here.
"""
from __future__ import annotations

from enum import Enum
from typing import Mapping

from pydantic import Field, model_validator

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts import (
    AttemptEvidenceKind, EvidenceRef, TaskDAG, WorkKind, WorkspaceAccess,
    WorkspaceRevision,
)
from aswe.core.fingerprint import fingerprint
from aswe.evidence import LocalEvidenceStore
from aswe.runtime.state import NodeAttemptRecord, NodeAttemptStatus, NodeRuntimeState, NodeLogicalStatus


class VerificationCheckStatus(str, Enum):
    HOLDS = "holds"
    FAILED = "failed"
    UNVERIFIED = "unverified"


class VerificationCheckResult(FrozenModel):
    check_id: str
    status: VerificationCheckStatus
    deterministic: bool
    evidence_refs: tuple[EvidenceRef, ...] = ()


def _seal(values: dict) -> str:
    return fingerprint(values)


class VerificationResult(FrozenModel):
    verification_node_id: str
    verification_execution_id: str
    verification_attempt: int = Field(ge=1)
    observed_workspace_revision: WorkspaceRevision
    observed_repository_state_fingerprint: str
    checks: tuple[VerificationCheckResult, ...]
    repository_state_unchanged: bool
    fingerprint: str

    @model_validator(mode="after")
    def verify_fingerprint(self) -> "VerificationResult":
        body = self.model_dump(mode="json", exclude={"fingerprint"})
        if self.fingerprint != _seal(body):
            raise ValueError("verification result fingerprint invalid")
        if len({check.check_id for check in self.checks}) != len(self.checks):
            raise ValueError("duplicate verification check identifiers")
        return self


class RepairAttributionKind(str, Enum):
    UNIQUE_WRITER = "unique_writer"
    NO_OWNER = "no_owner"
    MULTI_WRITER = "multi_writer"
    SOURCE_INELIGIBLE = "source_ineligible"
    SCOPE_INVALIDATED = "scope_invalidated"


class RepairAttributionEvidence(FrozenModel):
    source_verification_node_id: str
    source_verification_execution_id: str
    source_verification_attempt: int = Field(ge=1)
    failed_check_ids: tuple[str, ...]
    candidate_write_node_ids: tuple[str, ...]
    target_write_node_id: str | None = None
    target_write_attempt: int | None = None
    observed_workspace_revision: WorkspaceRevision
    kind: RepairAttributionKind
    reason_codes: tuple[str, ...]
    task_dag_fingerprint: str
    fingerprint: str

    @model_validator(mode="after")
    def verify_fingerprint(self) -> "RepairAttributionEvidence":
        if self.fingerprint != _seal(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("repair attribution fingerprint invalid")
        if self.kind is RepairAttributionKind.UNIQUE_WRITER:
            if self.target_write_node_id is None or self.target_write_attempt is None:
                raise ValueError("UNIQUE_WRITER must contain its target")
        elif self.target_write_node_id is not None or self.target_write_attempt is not None:
            raise ValueError("non-unique attribution must not authorize a target")
        return self


def make_verification_result(**fields) -> VerificationResult:
    return VerificationResult(**fields, fingerprint=_seal({
        key: value.model_dump(mode="json") if isinstance(value, WorkspaceRevision)
        else [c.model_dump(mode="json") for c in value] if key == "checks"
        else value
        for key, value in fields.items()
    }))


def _attribution(
    source: VerificationResult, dag: TaskDAG,
    kind: RepairAttributionKind, *, failures: tuple[str, ...],
    candidates: tuple[str, ...] = (), reason: str,
    target: str | None = None, target_attempt: int | None = None,
) -> RepairAttributionEvidence:
    body = dict(
        source_verification_node_id=source.verification_node_id,
        source_verification_execution_id=source.verification_execution_id,
        source_verification_attempt=source.verification_attempt,
        failed_check_ids=failures, candidate_write_node_ids=candidates,
        target_write_node_id=target, target_write_attempt=target_attempt,
        observed_workspace_revision=source.observed_workspace_revision,
        kind=kind, reason_codes=(reason,), task_dag_fingerprint=dag.fingerprint,
    )
    raw = {k: v.model_dump(mode="json") if isinstance(v, WorkspaceRevision)
           else v.value if isinstance(v, Enum) else v for k, v in body.items()}
    return RepairAttributionEvidence(**body, fingerprint=_seal(raw))


def resolve_verification_repair_attribution(
    *,
    dag: TaskDAG,
    source_attempt: NodeAttemptRecord,
    verification_ref: EvidenceRef,
    node_states: Mapping[str, NodeRuntimeState],
    evidence_store: LocalEvidenceStore,
) -> RepairAttributionEvidence:
    """Resolve exactly one compiler-owned repair target; no heuristic fallback.

    A corrupt/missing EvidenceRef is a hard integrity failure and must never
    silently become an ownership decision.
    """
    if verification_ref.kind is not AttemptEvidenceKind.VERIFICATION_RESULT:
        raise ValueError("expected verification_result EvidenceRef")
    if verification_ref not in source_attempt.evidence_refs:
        raise ValueError("verification EvidenceRef not attached to source attempt")
    if (verification_ref.source_node_id != source_attempt.node_id or
            verification_ref.source_attempt != source_attempt.attempt or
            verification_ref.source_execution_id != source_attempt.execution_id):
        raise ValueError("verification evidence provenance mismatch")
    result = VerificationResult.model_validate(evidence_store.get(verification_ref))
    if (result.verification_node_id != source_attempt.node_id or
            result.verification_attempt != source_attempt.attempt or
            result.verification_execution_id != source_attempt.execution_id):
        raise ValueError("verification payload provenance mismatch")

    failed = tuple(c.check_id for c in result.checks if c.status is VerificationCheckStatus.FAILED)
    def report(kind: RepairAttributionKind, reason: str, candidates: tuple[str, ...] = (),
               target: str | None = None, attempt: int | None = None) -> RepairAttributionEvidence:
        return _attribution(result, dag, kind, failures=failed, candidates=candidates,
                            reason=reason, target=target, target_attempt=attempt)

    by_id = {node.id: node for node in dag.nodes}
    node = by_id.get(source_attempt.node_id)
    source_state = node_states.get(source_attempt.node_id)
    if (node is None or node.work_kind is not WorkKind.VERIFICATION
            or source_attempt.status is not NodeAttemptStatus.FAILED
            or source_attempt.failure_kind != "VERIFICATION_FAILED"
            or source_state is None
            or source_state.logical_status is not NodeLogicalStatus.FAILED
            or not source_state.attempts
            or source_state.attempts[-1] != source_attempt
            or not result.repository_state_unchanged
            or result.observed_repository_state_fingerprint !=
               result.observed_workspace_revision.repository_state_fingerprint
            or source_attempt.post_workspace_revision != result.observed_workspace_revision
            or not failed
            or any(not c.deterministic for c in result.checks if c.status is VerificationCheckStatus.FAILED)
    ):
        return report(RepairAttributionKind.SOURCE_INELIGIBLE, "INVALID_DETERMINISTIC_SOURCE")

    binding_map = {(b.verification_node_id, b.verification_check_id): b
                   for b in dag.verification_repair_bindings}
    sets = []
    for check_id in failed:
        binding = binding_map.get((source_attempt.node_id, check_id))
        if binding is None or binding.dag_structure_fingerprint != dag.structure_fingerprint:
            return report(RepairAttributionKind.SOURCE_INELIGIBLE, "UNBOUND_FAILED_CHECK")
        sets.append(set(binding.candidate_write_node_ids))
    candidates = tuple(sorted(set().union(*sets)))
    if any(not owners for owners in sets):
        return report(RepairAttributionKind.NO_OWNER, "NO_WRITER_FOR_CHECK", candidates)
    if any(len(owners) != 1 for owners in sets) or len(candidates) != 1:
        return report(RepairAttributionKind.MULTI_WRITER, "NON_UNIQUE_WRITER", candidates)

    writer_id = candidates[0]
    writer_node = by_id[writer_id]
    writer_state = node_states.get(writer_id)
    if (writer_node.work_kind is not WorkKind.IMPLEMENTATION
            or writer_node.workspace_access is not WorkspaceAccess.WRITE
            or writer_state is None
            or writer_state.logical_status is not NodeLogicalStatus.SUCCEEDED
            or writer_state.accepted_attempt is None
            or writer_state.accepted_handoff is None):
        return report(RepairAttributionKind.SOURCE_INELIGIBLE, "WRITER_NOT_CURRENTLY_ACCEPTED", candidates)
    accepted = next((a for a in writer_state.attempts
                     if a.attempt == writer_state.accepted_attempt), None)
    if accepted is None or accepted.post_workspace_revision is None:
        return report(RepairAttributionKind.SOURCE_INELIGIBLE, "NO_TRUSTED_WRITER_REVISION", candidates)
    low = accepted.post_workspace_revision.generation
    high = result.observed_workspace_revision.generation
    if low > high:
        return report(RepairAttributionKind.SCOPE_INVALIDATED, "VERIFIER_PRECEDES_WRITER", candidates)

    # Conservative chronological defense: no later distinct business WRITE
    # may be silently treated as harmless without complete, trusted history.
    for other_id, other_node in by_id.items():
        if other_id == writer_id or other_node.work_kind is not WorkKind.IMPLEMENTATION:
            continue
        if other_node.workspace_access is not WorkspaceAccess.WRITE:
            continue
        state = node_states.get(other_id)
        if state is None:
            return report(RepairAttributionKind.SCOPE_INVALIDATED, "MISSING_WRITER_HISTORY", candidates)
        for attempt in state.attempts:
            after = attempt.post_workspace_revision
            if after is None:
                if attempt.pre_workspace_revision.generation >= low:
                    return report(RepairAttributionKind.SCOPE_INVALIDATED, "UNRESOLVED_DISTINCT_WRITER", candidates)
                continue
            if low <= after.generation <= high and (
                after.repository_state_fingerprint != attempt.pre_workspace_revision.repository_state_fingerprint
                or after.head_sha != attempt.pre_workspace_revision.head_sha
            ):
                return report(RepairAttributionKind.SCOPE_INVALIDATED, "INTERVENING_DISTINCT_WRITER", candidates)
    return report(RepairAttributionKind.UNIQUE_WRITER, "UNIQUE_COMPILED_OWNER", candidates,
                  writer_id, writer_state.accepted_attempt)
