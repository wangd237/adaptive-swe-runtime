"""Deterministic repair-attribution/reopen gates; no model-based attribution."""
from __future__ import annotations

import asyncio
import pytest

from aswe.core.contracts import (
    AttemptEvidenceKind, BackendTerminalStatus, WorkKind, WorkspaceAccess,
    VerificationRepairBinding,
)
from aswe.core.dag_fingerprint import build_task_dag, structure_fingerprint
from aswe.evidence import LocalEvidenceStore
from aswe.runtime.dispatch import DispatchRevoked, RepairScopeInvalidated, NodeDispatchTicketState
from aswe.runtime.repair import (
    RepairAttributionKind, VerificationCheckResult, VerificationCheckStatus,
    make_verification_result, resolve_verification_repair_attribution,
)
from aswe.runtime.state import NodeLogicalStatus
from aswe.workspace.session import WorkspaceSessionStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario, MutationEvidence
from tests.unit.test_scheduler_foundation import accept, node, scheduler


async def fixture(tmp_path, *, consumer: bool = False, candidates=("writer",)):
    writer = node("writer", access=WorkspaceAccess.WRITE)
    verifier = node("verify", deps=("writer",), ordinal=1,
                    kind=WorkKind.VERIFICATION, access=WorkspaceAccess.WRITE)
    nodes = [writer, verifier]
    if consumer:
        nodes.append(node("reviewer", deps=("writer",), ordinal=2,
                          kind=WorkKind.REVIEW, access=WorkspaceAccess.READ))
    core, manager = scheduler(tmp_path, *nodes)
    sfp = structure_fingerprint(nodes)
    b = VerificationRepairBinding(
        verification_node_id="verify", verification_check_id="unit-tests",
        candidate_write_node_ids=tuple(candidates),
        derivation="dag_business_writer_ancestors",
        dag_structure_fingerprint=sfp, fingerprint="compiler-binding",
    )
    core.dag = build_task_dag(nodes, (b,))
    store = LocalEvidenceStore(tmp_path / "evidence")
    await core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario()]), accept=accept,
    )
    assert core.states["writer"].acceptance_epoch == 1
    await core.run_claim(
        await core.claim("verify"),
        FakeExecutionBackend([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.FAILED,
            mutation_evidence=MutationEvidence.PROVEN_NONE,
            failure_kind="VERIFICATION_FAILED",
        )]),
    )
    source = core.states["verify"].attempts[-1]
    check_proof = store.put_attempt(
        task_id=core.task_id, node_id="verify",
        execution_id=source.execution_id, attempt=source.attempt,
        kind=AttemptEvidenceKind.TOOL_RECEIPT_LEDGER,
        payload={"check_id": "unit-tests", "exit_code": 1, "checker": "fixture"},
        workspace_revision=source.post_workspace_revision,
    )
    result = make_verification_result(
        verification_node_id="verify",
        verification_execution_id=source.execution_id,
        verification_attempt=source.attempt,
        observed_workspace_revision=source.post_workspace_revision,
        observed_repository_state_fingerprint=source.post_workspace_revision.repository_state_fingerprint,
        checks=(VerificationCheckResult(
            check_id="unit-tests", status=VerificationCheckStatus.FAILED,
            deterministic=True, evidence_refs=(check_proof,),
        ),),
        repository_state_unchanged=True,
    )
    ref = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.VERIFICATION_RESULT,
        payload=result, workspace_revision=result.observed_workspace_revision,
    )
    await core.attach_attempt_evidence(node_id="verify", evidence_ref=ref, evidence_store=store)
    source = core.states["verify"].attempts[-1]
    decision = resolve_verification_repair_attribution(
        dag=core.dag, source_attempt=source, verification_ref=ref,
        node_states=core.states, evidence_store=store,
    )
    attribution_ref = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.REPAIR_ATTRIBUTION,
        payload=decision, workspace_revision=decision.observed_workspace_revision,
    )
    await core.attach_attempt_evidence(
        node_id="verify", evidence_ref=attribution_ref, evidence_store=store,
    )
    return core, manager, store, ref, decision, attribution_ref


@pytest.mark.asyncio
async def test_unique_writer_attribution_is_persisted_and_reopen_revokes_authority(tmp_path):
    core, _, store, ref, decision, attribution_ref = await fixture(tmp_path, consumer=True)
    assert decision.kind is RepairAttributionKind.UNIQUE_WRITER
    assert decision.target_write_node_id == "writer" and decision.target_write_attempt == 1
    assert store.get(attribution_ref)["kind"] == "unique_writer"
    reviewer_ticket = await core.claim("reviewer")
    await core.reopen_writer_from_verification(
        verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
    )
    writer = core.states["writer"]
    assert writer.logical_status is NodeLogicalStatus.REMEDIATION_PENDING
    assert writer.acceptance_epoch == 2 and writer.accepted_handoff is None
    assert writer.attempts[0].handoff is not None
    assert core.states["verify"].logical_status is NodeLogicalStatus.REMEDIATION_PENDING
    assert core.tickets[reviewer_ticket.ticket_id].state is NodeDispatchTicketState.REVOKED
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.PENDING
    assert core.states["reviewer"].attempts == ()
    assert core.revision.generation == 0  # old H1 must be fenced even with same revision


@pytest.mark.asyncio
async def test_full_single_writer_repair_and_fresh_reverify(tmp_path):
    core, _, store, ref, _, attribution_ref = await fixture(tmp_path, consumer=True)
    await core.reopen_writer_from_verification(
        verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
    )
    writer_invocation = await core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario(
            mutation_evidence=MutationEvidence.OBSERVED,
        )]), accept=accept,
    )
    assert writer_invocation.attempt_kind.value == "repair"
    assert writer_invocation.repair_feedback_text is not None
    assert core.states["writer"].acceptance_epoch == 3
    assert core.states["writer"].accepted_handoff.fingerprint == "h-writer-2"
    assert core.states["verify"].logical_status is NodeLogicalStatus.REMEDIATION_PENDING
    verify_invocation = await core.run_claim(
        await core.claim("verify"),
        FakeExecutionBackend([FakeExecutionScenario()]), accept=accept,
    )
    assert verify_invocation.attempt_kind.value == "reverify"
    assert core.states["verify"].accepted_attempt == 2
    assert core.states["verify"].attempts[0].status.value == "failed"
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.READY


@pytest.mark.asyncio
async def test_no_owner_does_not_guess_last_writer(tmp_path):
    core, _, store, ref, decision, attribution_ref = await fixture(tmp_path, candidates=())
    assert decision.kind is RepairAttributionKind.NO_OWNER
    assert decision.target_write_node_id is None
    with pytest.raises(RepairScopeInvalidated, match="no unique"):
        await core.reopen_writer_from_verification(
            verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
        )
    assert core.states["writer"].logical_status is NodeLogicalStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_preparing_ticket_is_revoked_without_precommit_attempt(tmp_path):
    core, _, store, ref, _, attribution_ref = await fixture(tmp_path, consumer=True)
    ticket = await core.claim("reviewer")
    await core.reopen_writer_from_verification(
        verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
    )
    backend = FakeExecutionBackend([FakeExecutionScenario()])
    assert await core.run_claim(ticket, backend, accept=accept) is None
    assert backend.records == []
    assert core.states["reviewer"].attempts == ()


@pytest.mark.asyncio
async def test_consumer_commit_wins_then_reopen_fails_closed_even_prestart(tmp_path):
    core, manager, store, ref, _, attribution_ref = await fixture(tmp_path, consumer=True)
    event = asyncio.Event()
    from aswe.core.contracts import BackendExecutionPhase
    backend = FakeExecutionBackend([FakeExecutionScenario(
        release_event=event, execution_phase=BackendExecutionPhase.PRE_START,
    )])
    ticket = await core.claim("reviewer")
    running = asyncio.create_task(core.run_claim(ticket, backend, accept=accept))
    for _ in range(50):
        if core.states["reviewer"].logical_status is NodeLogicalStatus.RUNNING:
            break
        await asyncio.sleep(0)
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.RUNNING
    with pytest.raises(RepairScopeInvalidated, match="ACTIVE_DOWNSTREAM_DISPATCH"):
        await core.reopen_writer_from_verification(
            verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
        )
    assert core.failed and manager.dispatch_closed
    assert core.states["writer"].logical_status is NodeLogicalStatus.SUCCEEDED
    assert core.states["writer"].acceptance_epoch == 1
    # Reopen fail-close now automatically cancels and JOINs the COMMITTED
    # consumer; PRE_START does not make it revocable as a precommit ticket.
    assert core.states["reviewer"].attempts[0].status.value == "cancelled"
    await running
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.FAILED
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
    assert backend.records[-1].terminal_status is BackendTerminalStatus.CANCELLED


@pytest.mark.asyncio
async def test_forged_stored_attribution_is_rejected_before_reopen(tmp_path):
    core, _, store, ref, decision, _ = await fixture(tmp_path)
    # Internally valid seal but inconsistent with deterministic resolver: tests
    # the actual provenance/ownership gate rather than frozen-model validation.
    from aswe.core.fingerprint import fingerprint
    from aswe.runtime.repair import RepairAttributionEvidence
    forged_body = decision.model_dump(mode="json", exclude={"fingerprint"})
    forged_body["reason_codes"] = ["trust-the-model"]
    forged = RepairAttributionEvidence(
        **forged_body, fingerprint=fingerprint(forged_body)
    )
    forged_ref = store.put_attempt(
        task_id=core.task_id, node_id="verify",
        execution_id=core.states["verify"].attempts[-1].execution_id,
        attempt=1, kind=AttemptEvidenceKind.REPAIR_ATTRIBUTION,
        payload=forged, workspace_revision=core.revision,
    )
    with pytest.raises(ValueError):
        await core.reopen_writer_from_verification(
            verification_ref=ref, attribution_ref=forged_ref, evidence_store=store,
        )
    assert core.states["writer"].logical_status is NodeLogicalStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_verification_prose_cannot_provide_deterministic_check(tmp_path):
    core, _, store, ref, _, _ = await fixture(tmp_path)
    source = core.states["verify"].attempts[-1]
    result = make_verification_result(
        verification_node_id="verify", verification_execution_id=source.execution_id,
        verification_attempt=source.attempt,
        observed_workspace_revision=source.post_workspace_revision,
        observed_repository_state_fingerprint=source.post_workspace_revision.repository_state_fingerprint,
        checks=(VerificationCheckResult(
            check_id="unit-tests", status=VerificationCheckStatus.FAILED, deterministic=False,
        ),),
        repository_state_unchanged=True,
    )
    spoof_ref = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.VERIFICATION_RESULT,
        payload=result, workspace_revision=result.observed_workspace_revision,
    )
    await core.attach_attempt_evidence(node_id="verify", evidence_ref=spoof_ref, evidence_store=store)
    decision = resolve_verification_repair_attribution(
        dag=core.dag, source_attempt=core.states["verify"].attempts[-1],
        verification_ref=spoof_ref, node_states=core.states, evidence_store=store,
    )
    assert decision.kind is RepairAttributionKind.SOURCE_INELIGIBLE


@pytest.mark.asyncio
async def test_multi_owner_binding_does_not_pick_one_writer(tmp_path):
    core, _, store, ref, decision, attribution_ref = await fixture(
        tmp_path, candidates=("writer", "verify"),
    )
    assert decision.kind is RepairAttributionKind.MULTI_WRITER
    assert decision.target_write_node_id is None
    with pytest.raises(RepairScopeInvalidated, match="no unique"):
        await core.reopen_writer_from_verification(
            verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
        )
    assert core.states["writer"].acceptance_epoch == 1


@pytest.mark.asyncio
async def test_waiting_workspace_ticket_revoked_without_cancel_backend(tmp_path):
    core, manager, store, ref, _, attribution_ref = await fixture(tmp_path, consumer=True)
    backend = FakeExecutionBackend([FakeExecutionScenario()])
    async with manager.access(WorkspaceAccess.WRITE):
        ticket = await core.claim("reviewer")
        running = asyncio.create_task(core.run_claim(ticket, backend, accept=accept))
        for _ in range(40):
            if core.tickets[ticket.ticket_id].state is NodeDispatchTicketState.WAITING_WORKSPACE:
                break
            await asyncio.sleep(0)
        assert core.tickets[ticket.ticket_id].state is NodeDispatchTicketState.WAITING_WORKSPACE
        await core.reopen_writer_from_verification(
            verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
        )
    assert await running is None
    assert core.states["reviewer"].attempts == ()
    assert backend.cancelled_execution_ids == set()
    assert backend.records == []


@pytest.mark.asyncio
async def test_locked_precommit_ticket_revoked_before_atomic_commit(tmp_path):
    core, manager, store, ref, _, attribution_ref = await fixture(tmp_path, consumer=True)
    ticket = await core.claim("reviewer")
    await core._advance(ticket.ticket_id, NodeDispatchTicketState.WAITING_WORKSPACE)
    async with manager.access(WorkspaceAccess.READ):
        await core._advance(ticket.ticket_id, NodeDispatchTicketState.LOCKED_PRECOMMIT)
        await core.reopen_writer_from_verification(
            verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
        )
        with pytest.raises(DispatchRevoked):
            await core._commit(ticket.ticket_id, evidence_validated=True)
    assert core.states["reviewer"].attempts == ()
    assert core.revision.generation == 0
    assert core.states["writer"].acceptance_epoch == 2


@pytest.mark.asyncio
async def test_successful_nonverification_consumer_forbids_reopen(tmp_path):
    core, manager, store, ref, _, attribution_ref = await fixture(tmp_path, consumer=True)
    await core.run_claim(
        await core.claim("reviewer"),
        FakeExecutionBackend([FakeExecutionScenario()]), accept=accept,
    )
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.SUCCEEDED
    with pytest.raises(RepairScopeInvalidated, match="COMMITTED_DOWNSTREAM_SUCCESS"):
        await core.reopen_writer_from_verification(
            verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
        )
    assert core.failed and manager.dispatch_closed
    assert core.states["writer"].accepted_attempt == 1


@pytest.mark.asyncio
async def test_unattached_valid_attribution_ref_not_usable_as_authority(tmp_path):
    core, _, store, ref, decision, attribution_ref = await fixture(tmp_path)
    # A separate, correctly sealed ref is still not a trusted Runtime attachment.
    extra_ref = store.put_attempt(
        task_id=core.task_id, node_id="verify",
        execution_id=core.states["verify"].attempts[-1].execution_id,
        attempt=1, kind=AttemptEvidenceKind.REPAIR_ATTRIBUTION,
        payload=decision, workspace_revision=core.revision,
    )
    assert extra_ref != attribution_ref
    with pytest.raises(ValueError, match="attached"):
        await core.reopen_writer_from_verification(
            verification_ref=ref, attribution_ref=extra_ref, evidence_store=store,
        )
    assert core.states["writer"].acceptance_epoch == 1


@pytest.mark.asyncio
async def test_stale_reopen_revision_fails_closed_without_rewriting_writer(tmp_path):
    core, manager, store, ref, _, attribution_ref = await fixture(tmp_path)
    core.revision = core.revision.model_copy(update={"generation": 1})
    with pytest.raises(RepairScopeInvalidated, match="STALE"):
        await core.reopen_writer_from_verification(
            verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
        )
    assert manager.dispatch_closed and core.failed
    assert core.states["writer"].accepted_attempt == 1


@pytest.mark.asyncio
async def test_reopen_does_not_allocate_repair_execution_before_lock(tmp_path):
    core, manager, store, ref, _, attribution_ref = await fixture(tmp_path)
    await core.reopen_writer_from_verification(
        verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
    )
    claim = await core.claim("writer")
    assert core.states["writer"].next_attempt == 2
    assert len(core.states["writer"].attempts) == 1
    assert claim.dependency_acceptance_stamps == ()
    await core.revoke(claim.ticket_id)
    assert core.states["writer"].attempts[0].status.value == "accepted"
    assert core.states["writer"].accepted_handoff is None


@pytest.mark.asyncio
async def test_repair_feedback_freshness_checked_under_workspace_lock(tmp_path):
    core, _, store, ref, _, attribution_ref = await fixture(tmp_path)
    await core.reopen_writer_from_verification(
        verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
    )
    ticket = await core.claim("writer")
    await core._advance(ticket.ticket_id, NodeDispatchTicketState.WAITING_WORKSPACE)
    await core._advance(ticket.ticket_id, NodeDispatchTicketState.LOCKED_PRECOMMIT)
    core.revision = core.revision.model_copy(update={"generation": core.revision.generation + 1})
    with pytest.raises(DispatchRevoked, match="RepairFeedback stale"):
        await core._commit(ticket.ticket_id, evidence_validated=True)
    assert core.states["writer"].attempts[-1].attempt == 1


@pytest.mark.asyncio
async def test_failed_check_with_no_runtime_tool_proof_is_ineligible(tmp_path):
    core, _, store, _, _, _ = await fixture(tmp_path)
    source = core.states["verify"].attempts[-1]
    fake_result = make_verification_result(
        verification_node_id="verify",
        verification_execution_id=source.execution_id,
        verification_attempt=source.attempt,
        observed_workspace_revision=source.post_workspace_revision,
        observed_repository_state_fingerprint=source.post_workspace_revision.repository_state_fingerprint,
        checks=(VerificationCheckResult(
            check_id="unit-tests", status=VerificationCheckStatus.FAILED,
            deterministic=True, evidence_refs=(),
        ),),
        repository_state_unchanged=True,
    )
    fake_ref = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.VERIFICATION_RESULT,
        payload=fake_result, workspace_revision=source.post_workspace_revision,
    )
    await core.attach_attempt_evidence(
        node_id="verify", evidence_ref=fake_ref, evidence_store=store,
    )
    decision = resolve_verification_repair_attribution(
        dag=core.dag, source_attempt=core.states["verify"].attempts[-1],
        verification_ref=fake_ref, node_states=core.states, evidence_store=store,
    )
    assert decision.kind is RepairAttributionKind.SOURCE_INELIGIBLE
    assert decision.target_write_node_id is None


@pytest.mark.asyncio
async def test_failed_check_with_foreign_execution_proof_is_ineligible(tmp_path):
    core, _, store, _, _, _ = await fixture(tmp_path)
    source = core.states["verify"].attempts[-1]
    foreign = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id="unrelated-execution",
        attempt=source.attempt, kind=AttemptEvidenceKind.TOOL_RECEIPT_LEDGER,
        payload={"exit_code": 1}, workspace_revision=source.post_workspace_revision,
    )
    fake_result = make_verification_result(
        verification_node_id="verify",
        verification_execution_id=source.execution_id,
        verification_attempt=source.attempt,
        observed_workspace_revision=source.post_workspace_revision,
        observed_repository_state_fingerprint=source.post_workspace_revision.repository_state_fingerprint,
        checks=(VerificationCheckResult(
            check_id="unit-tests", status=VerificationCheckStatus.FAILED,
            deterministic=True, evidence_refs=(foreign,),
        ),),
        repository_state_unchanged=True,
    )
    fake_ref = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.VERIFICATION_RESULT,
        payload=fake_result, workspace_revision=source.post_workspace_revision,
    )
    await core.attach_attempt_evidence(
        node_id="verify", evidence_ref=fake_ref, evidence_store=store,
    )
    decision = resolve_verification_repair_attribution(
        dag=core.dag, source_attempt=core.states["verify"].attempts[-1],
        verification_ref=fake_ref, node_states=core.states, evidence_store=store,
    )
    assert decision.kind is RepairAttributionKind.SOURCE_INELIGIBLE


@pytest.mark.asyncio
async def test_deterministic_proof_with_wrong_workspace_fingerprint_is_ineligible(tmp_path):
    core, _, store, _, _, _ = await fixture(tmp_path)
    source = core.states["verify"].attempts[-1]
    altered = source.post_workspace_revision.model_copy(
        update={"repository_state_fingerprint": "wrong-git-state"}
    )
    mismatched_proof = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.TOOL_RECEIPT_LEDGER,
        payload={"exit_code": 1}, workspace_revision=altered,
    )
    result = make_verification_result(
        verification_node_id="verify",
        verification_execution_id=source.execution_id,
        verification_attempt=source.attempt,
        observed_workspace_revision=source.post_workspace_revision,
        observed_repository_state_fingerprint=source.post_workspace_revision.repository_state_fingerprint,
        checks=(VerificationCheckResult(
            check_id="unit-tests", status=VerificationCheckStatus.FAILED,
            deterministic=True, evidence_refs=(mismatched_proof,),
        ),),
        repository_state_unchanged=True,
    )
    result_ref = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.VERIFICATION_RESULT,
        payload=result, workspace_revision=source.post_workspace_revision,
    )
    await core.attach_attempt_evidence(
        node_id="verify", evidence_ref=result_ref, evidence_store=store,
    )
    decision = resolve_verification_repair_attribution(
        dag=core.dag, source_attempt=core.states["verify"].attempts[-1],
        verification_ref=result_ref, node_states=core.states, evidence_store=store,
    )
    assert decision.kind is RepairAttributionKind.SOURCE_INELIGIBLE


@pytest.mark.asyncio
async def test_declared_unchanged_repository_must_match_before_and_after(tmp_path):
    core, _, store, ref, _, _ = await fixture(tmp_path)
    prior = core.states["verify"]
    attempt = prior.attempts[-1]
    invalid_pre = attempt.pre_workspace_revision.model_copy(
        update={"repository_state_fingerprint": "before-is-different"}
    )
    invalid_attempt = attempt.model_copy(update={"pre_workspace_revision": invalid_pre})
    forged_state = prior.model_copy(update={"attempts": prior.attempts[:-1] + (invalid_attempt,)})
    states = dict(core.states)
    states["verify"] = forged_state
    decision = resolve_verification_repair_attribution(
        dag=core.dag, source_attempt=invalid_attempt, verification_ref=ref,
        node_states=states, evidence_store=store,
    )
    assert decision.kind is RepairAttributionKind.SOURCE_INELIGIBLE


@pytest.mark.asyncio
async def test_r109_ready_descendant_without_ticket_becomes_pending(tmp_path):
    core, _, store, ref, _, attr = await fixture(tmp_path, consumer=True)
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.READY
    await core.reopen_writer_from_verification(
        verification_ref=ref, attribution_ref=attr, evidence_store=store
    )
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.PENDING
    assert core.states["reviewer"].attempts == ()

@pytest.mark.asyncio
async def test_r118_old_epoch_ticket_never_reauthorizes_after_repair(tmp_path):
    core, _, store, ref, _, attr = await fixture(tmp_path, consumer=True)
    old_ticket = await core.claim("reviewer")
    assert old_ticket.dependency_acceptance_stamps[0].acceptance_epoch == 1
    await core.reopen_writer_from_verification(
        verification_ref=ref, attribution_ref=attr, evidence_store=store
    )
    assert core.states["writer"].acceptance_epoch == 2
    await core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario(
            mutation_evidence=MutationEvidence.OBSERVED
        )]), accept=accept,
    )
    assert core.states["writer"].acceptance_epoch == 3
    assert core.tickets[old_ticket.ticket_id].state is NodeDispatchTicketState.REVOKED
    with pytest.raises(DispatchRevoked):
        await core._commit(old_ticket.ticket_id, evidence_validated=True)
    new_ticket = await core.claim("reviewer")
    assert new_ticket.dependency_acceptance_stamps[0].acceptance_epoch == 3
    assert new_ticket.dependency_acceptance_stamps[0].handoff_fingerprint == "h-writer-2"
