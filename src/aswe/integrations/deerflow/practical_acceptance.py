"""Opt-in, constrained single-owner SWE handoff.

A Coder handoff attests that the source mutation was completed and sealed,
NOT that it passes tests. The independent Tester owns code correctness and
may schedule Repair. This is deliberately distinct from strict assurance.

Only host-generated artifact references can become authority. Never derive a
handoff from a model's self-report or merely 'Native completed'.
"""
from __future__ import annotations

from aswe.core.contracts import (
    AttemptEvidenceKind, ExecutionCompleteness, HandoffEvidence, NodeHandoff,
    WorkspaceRevision,
)
from aswe.core.contracts.backend import (
    BackendTerminalStatus, NodeExecutionInvocation,
)
from aswe.core.fingerprint import fingerprint
from aswe.evidence import LocalEvidenceStore
from aswe.repository import RepositoryBinding, capture_repository_state


class PracticalAcceptanceDenied(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise PracticalAcceptanceDenied(code)


def build_practical_handoff(
    *,
    result: object,
    invocation: NodeExecutionInvocation,
    post: WorkspaceRevision,
    provider_id: str,
    evidence_store: LocalEvidenceStore,
    repository: RepositoryBinding,
    probe: object,
) -> NodeHandoff:
    """Called by Scheduler's trusted accept callback while WRITE lock held."""
    _require(
        getattr(result, "terminal_status", None) is BackendTerminalStatus.COMPLETED
        and getattr(result, "native_stop_reason", None) is None,
        "PRACTICAL_NATIVE_NOT_NORMAL",
    )
    _require(getattr(result, "quiescent", None) is True,
             "PRACTICAL_RESOURCES_NOT_DRAINED")
    _require(getattr(result, "mutation_evidence", None) == "observed",
             "PRACTICAL_MUTATION_UNATTESTED")
    _require(
        getattr(result, "execution_id", None) == invocation.execution_id
        and getattr(result, "node_id", None) == invocation.node_id
        and getattr(result, "attempt", None) == invocation.attempt,
        "PRACTICAL_EXECUTION_IDENTITY_MISMATCH",
    )
    _require(
        getattr(probe, "invocation", None) is invocation
        and getattr(probe, "verification_status", None) in ("passed", "failed")
        and getattr(probe, "receipt", None) is not None
        and getattr(probe, "ref", None) is not None,
        "PRACTICAL_CANONICAL_PROOF_MISSING",
    )
    # The Coder may have a legitimate FAILED precheck. That is not a reason
    # to block a stable patch from reaching the independent DAG Tester.
    _require(post.head_matches_baseline and post.base_sha == (
        invocation.execution_workspace_revision.base_sha),
        "PRACTICAL_BASELINE_DRIFT",
    )
    current = capture_repository_state(repository)
    _require(
        current.fingerprint == post.repository_state_fingerprint
        and getattr(probe, "post_state", None) is not None
        and probe.post_state.fingerprint == current.fingerprint,
        "PRACTICAL_WORKSPACE_CHANGED_BEFORE_HANDOFF",
    )
    refs = (
        (getattr(result, "workspace_evidence_ref", None),
         AttemptEvidenceKind.WORKSPACE_CHANGESET),
        (getattr(result, "tool_receipt_ref", None),
         AttemptEvidenceKind.TOOL_RECEIPT_LEDGER),
    )
    for ref, kind in refs:
        _require(
            ref is not None and ref.kind == kind
            and ref.source_node_id == invocation.node_id
            and ref.source_execution_id == invocation.execution_id
            and ref.source_attempt == invocation.attempt
            and ref.workspace_revision_generation == post.generation
            and ref.workspace_state_fingerprint == post.repository_state_fingerprint,
            "PRACTICAL_EVIDENCE_PROVENANCE_INVALID",
        )
        # This validates persisted content hash/provenance, not just ref shape.
        evidence_store.get(ref)
    receipt = probe.receipt
    ref = probe.ref
    _require(
        receipt.status in ("holds", "failed")
        and ref.source_node_id == invocation.node_id
        and ref.source_execution_id == invocation.execution_id
        and ref.source_attempt == invocation.attempt
        and ref.workspace_revision_generation == post.generation
        and ref.workspace_state_fingerprint == post.repository_state_fingerprint,
        "PRACTICAL_CHECK_RECEIPT_PROVENANCE_INVALID",
    )
    evidence_store.get(ref)
    workspace_evidence = evidence_store.get(refs[0][0])
    delta = workspace_evidence.get("delta", {})
    _require(
        isinstance(delta, dict)
        # A truncated full-FS snapshot may yield delta UNKNOWN although the
        # persisted host collector separately attests OBSERVED Git changes.
        # Check the collector's final status, and explicitly retain the
        # incomplete whole-filesystem attribution on the Handoff.
        and workspace_evidence.get("mutation_evidence") == "observed"
        and workspace_evidence.get("quiescence_proven") is True
        and workspace_evidence.get("post_repository_fingerprint")
            == post.repository_state_fingerprint
        and delta.get("repository_changed_paths_complete") is True
        and bool(delta.get("repository_changed_paths"))
        and delta.get("execution_id") == invocation.execution_id,
        "PRACTICAL_WORKSPACE_DELTA_INCOMPLETE",
    )
    fields = dict(
        source_node_id=invocation.node_id,
        source_execution_id=invocation.execution_id,
        source_attempt=invocation.attempt,
        source_provider_id=provider_id,
        observed_workspace_revision=post,
        self_report="Host-observed completed Coder; independent Tester owns code correctness.",
        evidence=HandoffEvidence(
            # Scope is explicit: Git-visible paths, not a purported history
            # of excluded cache/build directory mutations.
            changed_paths=tuple(delta["repository_changed_paths"]),
            changed_paths_complete=not delta.get("attribution_truncated", True),
            workspace_changeset=refs[0][0],
        ),
        backend_stop_reason=None,
        execution_completeness=ExecutionCompleteness.UNCAPPED,
        warnings=(
            ("practical_single_owner_profile", "filesystem_history_incomplete")
            if delta.get("attribution_truncated", False)
            else ("practical_single_owner_profile",)
        ),
    )
    return NodeHandoff(**fields, fingerprint=fingerprint(fields))


def verify_practical_handoff(
    handoff: NodeHandoff, *, evidence_store: LocalEvidenceStore,
) -> bool:
    """Host-side dependency check; never trust a bare handoff fingerprint."""
    try:
        if handoff.fingerprint != fingerprint(
            handoff.model_dump(mode="json", exclude={"fingerprint"})
        ):
            return False
        ref = handoff.evidence.workspace_changeset
        if ref is None or ref.kind is not AttemptEvidenceKind.WORKSPACE_CHANGESET:
            return False
        if (ref.source_node_id != handoff.source_node_id
                or ref.source_execution_id != handoff.source_execution_id
                or ref.source_attempt != handoff.source_attempt
                or ref.workspace_revision_generation !=
                handoff.observed_workspace_revision.generation
                or ref.workspace_state_fingerprint !=
                handoff.observed_workspace_revision.repository_state_fingerprint):
            return False
        payload = evidence_store.get(ref)
        return (
            payload.get("quiescence_proven") is True
            and payload.get("acceptance_profile") == "practical"
            and payload.get("mutation_evidence") == "observed"
        )
    except Exception:
        # An unavailable/tampered evidence store can never grant a Handoff.
        return False
