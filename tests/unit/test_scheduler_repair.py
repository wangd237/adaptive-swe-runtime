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
    result = make_verification_result(
        verification_node_id="verify",
        verification_execution_id=source.execution_id,
        verification_attempt=source.attempt,
        observed_workspace_revision=source.post_workspace_revision,
        observed_repository_state_fingerprint=source.post_workspace_revision.repository_state_fingerprint,
        checks=(VerificationCheckResult(
            check_id="unit-tests", status=VerificationCheckStatus.FAILED,
            deterministic=True,
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
    backend = FakeExecutionBackend([FakeExecutionScenario(
        release_event=event,
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
    assert core.states["reviewer"].attempts[0].status.value == "running"
    await backend.cancel_node(core.states["reviewer"].attempts[0].execution_id)
    await running
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.FAILED


@pytest.mark.asyncio
async def test_forged_stored_attribution_is_rejected_before_reopen(tmp_path):
    core, _, store, ref, decision, _ = await fixture(tmp_path)
    forged = decision.model_copy(update={"reason_codes": ("trust-the-model",)})
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
