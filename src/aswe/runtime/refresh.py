"""Runtime-owned fresh deterministic verification before stale Repair dispatch.

This module is deliberately narrow: only attested compiler-exact canonical
verification can authorize an updated REPAIR. It never guesses check commands
from model text or revives a previously revoked Writer handoff.
"""
from __future__ import annotations

import asyncio

from aswe.core.contracts import (
    AttemptEvidenceKind, NodeAttemptKind, WorkspaceAccess,
)
from aswe.core.ids import new_execution_id
from aswe.runtime.dispatch import NodeDispatchTicketState, TaskDispatchGateState
from aswe.runtime.repair import (
    VerificationCheckResult, VerificationCheckStatus, RepairAttributionKind,
    make_verification_result, resolve_verification_repair_attribution,
)
from aswe.runtime.state import NodeAttemptRecord, NodeAttemptStatus, NodeLogicalStatus
from aswe.runtime.feedback import build_verification_repair_feedback, RepairTriggerKind


async def refresh_stale_verification(core, ticket_id: str) -> bool:
    """Return True iff new failed-check evidence authorizes this REPAIR ticket.

    Caller holds the *physical* WRITE Workspace lock, not SchedulerStateMutex.
    Fresh canonical receipts are attached to a real new logical Verification
    REVERIFY attempt; old source attempt and its evidence remain immutable.
    """
    async with core.state_mutex:
        ticket = core.tickets[ticket_id]
        writer_id = ticket.node_id
        fb = core._typed_repair_feedback.get(writer_id)
        if (fb is None or fb.trigger_kind is not RepairTriggerKind.DOWNSTREAM_VERIFICATION
                or fb.verification_result is None or core._canonical_verifier is None
                or core.gate.state is not TaskDispatchGateState.OPEN
                or ticket.state is not NodeDispatchTicketState.LOCKED_PRECOMMIT
                or not core._is_current_locked(ticket)):
            failure = "REPAIR_FEEDBACK_STALE"
        else:
            failure = None
            source_id = fb.feedback_source_node_id
            source_state = core.states[source_id]
            writer_state = core.states[writer_id]
            if (source_state.logical_status is not NodeLogicalStatus.REMEDIATION_PENDING
                    or writer_state.logical_status is not NodeLogicalStatus.REMEDIATION_PENDING
                    or fb.target_write_attempt != writer_state.accepted_attempt
                       and not any(a.attempt == fb.target_write_attempt and a.handoff is not None
                                   for a in writer_state.attempts)):
                failure = "REPAIR_FEEDBACK_STALE"
            elif core.revision == fb.observed_workspace_revision:
                return True
            else:
                revision = core.revision
                attempt_no = source_state.next_attempt
                execution_id = new_execution_id()
                # Serialize the source's internal deterministic REVERIFY with
                # all other scheduling decisions before doing any checker I/O.
                run = NodeAttemptRecord(
                    node_id=source_id, attempt=attempt_no, kind=NodeAttemptKind.REVERIFY,
                    execution_id=execution_id, pre_workspace_revision=revision,
                    post_workspace_revision=None, status=NodeAttemptStatus.RUNNING,
                    failure_kind=None,
                )
                core.states[source_id] = source_state.model_copy(update={
                    "logical_status": NodeLogicalStatus.RUNNING,
                    "next_attempt": attempt_no + 1,
                    "attempts": source_state.attempts + (run,),
                })
                snapshot_writer = writer_state
                snapshot_source = core.states[source_id]
    if failure is not None:
        await core.fail_closed(failure, root_node=writer_id)
        return False

    store = core._canonical_verifier.store
    verifier = core._canonical_verifier
    proofs = []
    result = None
    try:
        old = store.get(fb.verification_result)
        from aswe.runtime.repair import VerificationResult
        old_result = VerificationResult.model_validate(old)
        if (old_result.verification_execution_id != fb.feedback_source_execution_id
                or old_result.verification_attempt != fb.feedback_source_attempt
                or old_result.observed_workspace_revision != fb.observed_workspace_revision):
            raise ValueError("untrusted old verification provenance")
        checks = []
        if not old_result.checks:
            raise ValueError("missing original check set")
        for check in old_result.checks:
            policy = core._canonical_check_policies.get(check.check_id)
            if policy is None:
                raise ValueError("no compiler-owned refresh command for check")
            if not check.evidence_refs:
                raise ValueError("missing old canonical proof for check")
            for proof in check.evidence_refs:
                receipt = verifier.validate(
                    proof, node_id=source_id,
                    execution_id=fb.feedback_source_execution_id,
                    attempt=fb.feedback_source_attempt,
                    revision=fb.observed_workspace_revision, check_id=check.check_id,
                )
                if receipt.command_policy_fingerprint != policy.fingerprint:
                    raise ValueError("refresh command policy differs from original")
            proof, receipt = await asyncio.to_thread(
                verifier.run, node_id=source_id, execution_id=execution_id,
                attempt=attempt_no, policy=policy, revision=revision,
            )
            proofs.append(proof)
            checks.append(VerificationCheckResult(
                check_id=check.check_id, deterministic=True, evidence_refs=(proof,),
                status=VerificationCheckStatus(receipt.status),
            ))
            if receipt.status == "unverified":
                raise ValueError("refresh check is UNVERIFIED")
        result = make_verification_result(
            verification_node_id=source_id, verification_execution_id=execution_id,
            verification_attempt=attempt_no, observed_workspace_revision=revision,
            observed_repository_state_fingerprint=revision.repository_state_fingerprint,
            checks=tuple(checks), repository_state_unchanged=True,
        )
        result_ref = store.put_attempt(
            task_id=core.task_id, node_id=source_id, execution_id=execution_id,
            attempt=attempt_no, kind=AttemptEvidenceKind.VERIFICATION_RESULT,
            payload=result, workspace_revision=revision,
        )
        proofs.append(result_ref)
        failed = any(c.status is VerificationCheckStatus.FAILED for c in checks)
        if failed:
            candidate = run.model_copy(update={
                "status": NodeAttemptStatus.FAILED,
                "post_workspace_revision": revision, "failure_kind": "VERIFICATION_FAILED",
                "evidence_refs": tuple(proofs),
            })
            # Attribution has to inspect the *historical* accepted Writer
            # solely to determine legal ownership: no authority is restored.
            historical = next(a for a in snapshot_writer.attempts
                              if a.attempt == fb.target_write_attempt and a.handoff is not None)
            attribution_writer = snapshot_writer.model_copy(update={
                "logical_status": NodeLogicalStatus.SUCCEEDED,
                "accepted_attempt": historical.attempt,
                "accepted_handoff": historical.handoff,
            })
            attribution_source = snapshot_source.model_copy(update={
                "logical_status": NodeLogicalStatus.FAILED,
                "attempts": snapshot_source.attempts[:-1] + (candidate,),
            })
            async with core.state_mutex:
                observed_states = dict(core.states)
            observed_states[source_id] = attribution_source
            observed_states[writer_id] = attribution_writer
            decision = resolve_verification_repair_attribution(
                dag=core.dag, source_attempt=candidate,
                verification_ref=result_ref, node_states=observed_states,
                evidence_store=store, canonical_verifier=verifier,
            )
            if (decision.kind is not RepairAttributionKind.UNIQUE_WRITER
                    or decision.target_write_node_id != writer_id
                    or decision.target_write_attempt != fb.target_write_attempt):
                raise ValueError("fresh checks do not authorize original Writer")
            aref = store.put_attempt(
                task_id=core.task_id, node_id=source_id, execution_id=execution_id,
                attempt=attempt_no, kind=AttemptEvidenceKind.REPAIR_ATTRIBUTION,
                payload=decision, workspace_revision=revision,
            )
            proofs.append(aref)
            refreshed = build_verification_repair_feedback(
                source=result, source_ref=result_ref,
                attribution=decision, attribution_ref=aref,
            )
        else:
            refreshed = None
    except Exception:
        await _close_refresh(core, source_id, run, proofs, "REPAIR_FEEDBACK_STALE")
        return False

    async with core.state_mutex:
        if (core.gate.state is not TaskDispatchGateState.OPEN
                or core.revision != revision
                or core.states[source_id] != snapshot_source
                or core.states[writer_id] != snapshot_writer
                or core.tickets[ticket_id].state is not NodeDispatchTicketState.LOCKED_PRECOMMIT):
            invalid = True
        else:
            invalid = False
            record = run.model_copy(update={
                "status": NodeAttemptStatus.FAILED,
                "post_workspace_revision": revision,
                "failure_kind": ("VERIFICATION_FAILED" if refreshed is not None
                                 else "REPAIR_SUPERSEDED_NO_WRITER_AUTHORITY"),
                "evidence_refs": tuple(proofs),
            })
            core.states[source_id] = snapshot_source.model_copy(update={
                "logical_status": (NodeLogicalStatus.REMEDIATION_PENDING if refreshed is not None
                                   else NodeLogicalStatus.FAILED),
                "attempts": snapshot_source.attempts[:-1] + (record,),
                "terminal_failure_kind": (None if refreshed is not None
                                          else "REPAIR_SUPERSEDED_NO_WRITER_AUTHORITY"),
            })
            if refreshed is not None:
                core._typed_repair_feedback[writer_id] = refreshed
                core._repair_feedback_revision[writer_id] = revision
                core._repair_feedback_text[writer_id] = refreshed.bounded_projection()
            else:
                core._typed_repair_feedback.pop(writer_id, None)
                core._repair_feedback_revision.pop(writer_id, None)
                core._repair_feedback_text.pop(writer_id, None)
                core._pending_attempt_kinds.pop(writer_id, None)
    if invalid:
        await core.fail_closed("REPAIR_REFRESH_RACE", root_node=source_id)
        return False
    if refreshed is None:
        # The old Writer authority was already revoked by reopen. Even though
        # tests now pass, there is no legal transition that silently resurrects
        # that old handoff; stop rather than executing an unnecessary REPAIR.
        await core.fail_closed("REPAIR_SUPERSEDED_REPLAN_REQUIRED", root_node=source_id)
        return False
    return True


async def _close_refresh(core, source_id, running, proofs, reason):
    async with core.state_mutex:
        state = core.states[source_id]
        if state.logical_status is NodeLogicalStatus.RUNNING and state.attempts[-1] == running:
            finished = running.model_copy(update={
                "status": NodeAttemptStatus.FAILED, "failure_kind": reason,
                "post_workspace_revision": None,
                "evidence_refs": tuple(proofs),
            })
            core.states[source_id] = state.model_copy(update={
                "logical_status": NodeLogicalStatus.FAILED,
                "attempts": state.attempts[:-1] + (finished,),
                "terminal_failure_kind": reason,
            })
    await core.fail_closed(reason, root_node=source_id)
