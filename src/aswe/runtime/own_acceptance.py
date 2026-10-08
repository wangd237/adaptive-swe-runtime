"""Narrow Runtime-owned *own* AcceptanceFailure repair / stale recheck.

An AcceptanceFailure must be a real attested canonical check bound to the
Writer attempt; model text and a mere completed backend are never authority.
This path intentionally does not implement dirty-WRITE own repair (R101).
"""
from __future__ import annotations

import asyncio

from pydantic import model_validator

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts import (
    AttemptEvidenceKind, EvidenceRef, ReceiptRef, WorkspaceAccess, WorkKind,
    WorkspaceRevision, NodeAttemptKind,
)
from aswe.core.fingerprint import fingerprint
from aswe.runtime.feedback import RepairFeedback, RepairTriggerKind
from aswe.runtime.dispatch import TaskDispatchGateState, NodeDispatchTicketState, DispatchRevoked
from aswe.runtime.state import NodeLogicalStatus, NodeAttemptStatus, NodeBlockReason


class CanonicalAcceptanceVerdict(FrozenModel):
    source_node_id: str
    source_execution_id: str
    source_attempt: int
    observed_workspace_revision: WorkspaceRevision
    check_id: str
    command_policy_fingerprint: str
    canonical_proof: EvidenceRef
    status: str
    fingerprint: str

    @model_validator(mode="after")
    def validate_verdict(self):
        if self.status not in ("failed", "holds", "unverified"):
            raise ValueError("unknown acceptance status")
        if self.canonical_proof.kind is not AttemptEvidenceKind.TOOL_RECEIPT_LEDGER:
            raise ValueError("acceptance must refer to Runtime-owned tool receipt")
        if (self.canonical_proof.source_node_id != self.source_node_id
                or self.canonical_proof.source_execution_id != self.source_execution_id
                or self.canonical_proof.source_attempt != self.source_attempt
                or self.canonical_proof.workspace_revision_generation !=
                   self.observed_workspace_revision.generation
                or self.canonical_proof.workspace_state_fingerprint !=
                   self.observed_workspace_revision.repository_state_fingerprint):
            raise ValueError("acceptance provenance mismatch")
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("acceptance verdict digest mismatch")
        return self


def build_acceptance_verdict(*, node_id, execution_id, attempt, revision,
                             policy, receipt_ref, status):
    body = dict(
        source_node_id=node_id, source_execution_id=execution_id,
        source_attempt=attempt, observed_workspace_revision=revision,
        check_id=policy.check_id, command_policy_fingerprint=policy.fingerprint,
        canonical_proof=receipt_ref, status=status,
    )
    return CanonicalAcceptanceVerdict(**body, fingerprint=fingerprint(body))


def _feedback(*, verdict, verdict_ref, target):
    rev = verdict.observed_workspace_revision
    receipt = ReceiptRef(
        source_execution_id=verdict.source_execution_id,
        ledger_evidence=verdict.canonical_proof, ledger_index=0,
        display_receipt_id=None, tool_call_id=None, tool_name="canonical_acceptance",
        args_freshness_stamp=rev.repository_state_fingerprint,
        output_freshness_stamp=rev.repository_state_fingerprint,
    )
    body = dict(
        trigger_kind=RepairTriggerKind.NODE_ACCEPTANCE,
        feedback_source_node_id=verdict.source_node_id,
        feedback_source_execution_id=verdict.source_execution_id,
        feedback_source_attempt=verdict.source_attempt,
        target_write_node_id=target, target_write_attempt=verdict.source_attempt,
        observed_workspace_revision=rev,
        failed_check_ids=(verdict.check_id,), verification_result=None,
        acceptance_verdict=verdict_ref, repair_attribution=None,
        receipt_refs=(receipt,),
        deterministic_failure_summaries=("Runtime canonical acceptance failed",),
        verifier_report=None,
    )
    return RepairFeedback(**body, fingerprint=fingerprint(body))


async def arm_own_acceptance_repair(core, *, node_id, acceptance_ref, evidence_store):
    """Authorize bounded repair only for a clean failed Writer and attested fail."""
    verifier = core._canonical_verifier
    if verifier is None or verifier.store is not evidence_store:
        raise ValueError("Runtime acceptance verifier/store required")
    if acceptance_ref.kind is not AttemptEvidenceKind.ACCEPTANCE_VERDICT:
        raise ValueError("acceptance verdict evidence kind required")
    verdict = CanonicalAcceptanceVerdict.model_validate(evidence_store.get(acceptance_ref))
    policy = core._canonical_check_policies.get(verdict.check_id)
    if policy is None or policy.fingerprint != verdict.command_policy_fingerprint:
        raise ValueError("acceptance policy not compiler-authorized")
    proof = verifier.validate(
        verdict.canonical_proof, node_id=node_id,
        execution_id=verdict.source_execution_id, attempt=verdict.source_attempt,
        revision=verdict.observed_workspace_revision, check_id=verdict.check_id,
    )
    if proof.status != "failed" or verdict.status != "failed":
        raise ValueError("only attested deterministic failure may trigger repair")
    async with core.state_mutex:
        if node_id not in core.states:
            raise KeyError(node_id)
        state = core.states[node_id]
        source = state.attempts[-1] if state.attempts else None
        if (core.gate.state is not TaskDispatchGateState.OPEN
                or core.nodes[node_id].work_kind is not WorkKind.IMPLEMENTATION
                or core.nodes[node_id].workspace_access is not WorkspaceAccess.WRITE
                or state.logical_status is not NodeLogicalStatus.FAILED
                or source is None or source.status is not NodeAttemptStatus.FAILED
                or source.failure_kind != "ACCEPTANCE_OR_EXECUTION_FAILED"
                or source.post_workspace_revision != core.revision
                or verdict.observed_workspace_revision != core.revision
                or source.execution_id != verdict.source_execution_id
                or source.attempt != verdict.source_attempt
                or acceptance_ref not in source.evidence_refs
                or state.repair_count >= core.budget.max_repairs_per_write):
            raise DispatchRevoked("own acceptance failure not legal for repair")
        fb = _feedback(verdict=verdict, verdict_ref=acceptance_ref, target=node_id)
        core.states[node_id] = state.model_copy(update={
            "logical_status": NodeLogicalStatus.REMEDIATION_PENDING,
            "terminal_failure_kind": None,
            "repair_count": state.repair_count + 1,
        })
        core._pending_attempt_kinds[node_id] = NodeAttemptKind.REPAIR
        core._typed_repair_feedback[node_id] = fb
        core._repair_feedback_revision[node_id] = core.revision
        core._repair_feedback_text[node_id] = fb.bounded_projection()
        for descendant_id in core._descendants_locked(node_id):
            downstream = core.states[descendant_id]
            if (downstream.logical_status is NodeLogicalStatus.BLOCKED
                    and downstream.block_reason is NodeBlockReason.UPSTREAM_FAILURE):
                core.states[descendant_id] = downstream.model_copy(update={
                    "logical_status": NodeLogicalStatus.PENDING,
                    "block_reason": None, "blocked_by": (),
                })
        core._recompute_locked()
    return fb


async def refresh_stale_own_acceptance(core, ticket_id, fb):
    """Exact policy recheck at current revision under caller's physical WRITE lock."""
    node_id = fb.target_write_node_id
    verifier = core._canonical_verifier
    if verifier is None or fb.acceptance_verdict is None:
        await core.fail_closed("REPAIR_FEEDBACK_STALE", root_node=node_id)
        return False
    try:
        initial = CanonicalAcceptanceVerdict.model_validate(
            verifier.store.get(fb.acceptance_verdict)
        )
        policy = core._canonical_check_policies.get(initial.check_id)
        if policy is None or policy.fingerprint != initial.command_policy_fingerprint:
            raise ValueError("no authoritative acceptance recheck command")
        old_receipt = verifier.validate(
            initial.canonical_proof, node_id=node_id,
            execution_id=fb.feedback_source_execution_id,
            attempt=fb.feedback_source_attempt, revision=fb.observed_workspace_revision,
            check_id=initial.check_id,
        )
        if old_receipt.status != "failed":
            raise ValueError("old acceptance did not fail")
        async with core.state_mutex:
            t = core.tickets[ticket_id]
            state = core.states[node_id]
            if (not core._is_current_locked(t)
                    or t.state is not NodeDispatchTicketState.LOCKED_PRECOMMIT
                    or state.logical_status is not NodeLogicalStatus.REMEDIATION_PENDING
                    or core._typed_repair_feedback.get(node_id) != fb
                    or core.revision == fb.observed_workspace_revision):
                raise ValueError("own acceptance refresh authority unavailable")
            revision = core.revision
            state_snapshot = state
        command = asyncio.create_task(asyncio.to_thread(
            verifier.run, node_id=node_id,
            execution_id=fb.feedback_source_execution_id,
            attempt=fb.feedback_source_attempt,
            policy=policy, revision=revision,
        ))
        try:
            fresh_proof, fresh_receipt = await asyncio.shield(command)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(command)
            finally:
                core._quiescence_unknown = True
                raise
        if fresh_receipt.status == "unverified":
            core._quiescence_unknown = True
            raise ValueError("acceptance recheck unverified")
        from aswe.repository import capture_repository_state
        physical = await asyncio.to_thread(capture_repository_state, verifier.binding)
        if (physical.fingerprint != revision.repository_state_fingerprint
                or physical.head_sha != revision.head_sha):
            core._quiescence_unknown = True
            raise ValueError("acceptance recheck post-state drift")
        verdict = build_acceptance_verdict(
            node_id=node_id, execution_id=fb.feedback_source_execution_id,
            attempt=fb.feedback_source_attempt, revision=revision,
            policy=policy, receipt_ref=fresh_proof, status=fresh_receipt.status,
        )
        new_ref = verifier.store.put_attempt(
            task_id=core.task_id, node_id=node_id,
            execution_id=fb.feedback_source_execution_id,
            attempt=fb.feedback_source_attempt,
            kind=AttemptEvidenceKind.ACCEPTANCE_VERDICT,
            payload=verdict, workspace_revision=revision,
        )
        fresh_fb = (_feedback(verdict=verdict, verdict_ref=new_ref, target=node_id)
                    if fresh_receipt.status == "failed" else None)
        async with core.state_mutex:
            if (core.gate.state is not TaskDispatchGateState.OPEN
                    or core.revision != revision
                    or core.states[node_id] != state_snapshot
                    or core.tickets[ticket_id].state is not NodeDispatchTicketState.LOCKED_PRECOMMIT):
                raise ValueError("acceptance refresh state race")
            current = core.states[node_id]
            source = current.attempts[-1]
            core.states[node_id] = current.model_copy(update={
                "attempts": current.attempts[:-1] + (source.model_copy(update={
                    "evidence_refs": source.evidence_refs + (fresh_proof, new_ref),
                }),),
            })
            if fresh_fb is not None:
                core._typed_repair_feedback[node_id] = fresh_fb
                core._repair_feedback_revision[node_id] = revision
                core._repair_feedback_text[node_id] = fresh_fb.bounded_projection()
            else:
                core._typed_repair_feedback.pop(node_id, None)
                core._repair_feedback_revision.pop(node_id, None)
                core._repair_feedback_text.pop(node_id, None)
                core._pending_attempt_kinds.pop(node_id, None)
        if fresh_fb is None:
            await core.fail_closed("REPAIR_SUPERSEDED_REPLAN_REQUIRED", root_node=node_id)
            return False
        return True
    except asyncio.CancelledError:
        core._quiescence_unknown = True
        await core.fail_closed("REPAIR_REFRESH_CANCELLED", root_node=node_id)
        raise
    except Exception:
        await core.fail_closed("REPAIR_FEEDBACK_STALE", root_node=node_id)
        return False
