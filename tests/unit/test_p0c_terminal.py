"""P0-C terminal acceptance: budget, residual patch, fail-close consumers.

FakeBackend models executor results; real temporary Git worktrees validate
Repository/Patch disposition. No LLM or DeerFlow integration is claimed.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aswe.core.contracts import (
    AttemptEvidenceKind, BackendTerminalStatus, VerificationRepairBinding,
    WorkKind, WorkspaceAccess,
)
from aswe.core.dag_fingerprint import build_task_dag, structure_fingerprint
from aswe.runtime.finalization import (
    TaskLogicalStatus, WorkspaceDisposition, RepositoryDisposition,
    PatchDisposition, finalize_task,
)
from aswe.runtime.repair import (
    RepairAttributionKind, VerificationCheckResult, VerificationCheckStatus,
    make_verification_result, resolve_verification_repair_attribution,
)
from aswe.runtime.dispatch import RepairScopeInvalidated, DispatchRevoked
from aswe.runtime.review import ReviewVerdict, ReviewDecision, make_review_verdict
from aswe.runtime.state import NodeLogicalStatus, NodeBlockReason
from aswe.workspace.session import WorkspaceSessionStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario, MutationEvidence
from tests.unit.test_scheduler_foundation import scheduler, node, accept
from tests.unit.test_task_finalization import terminal_fixture
from tests.unit.test_own_acceptance_refresh import _mutated_own_failure
from tests.unit.test_canonical_verifier import canonical_workspace


@pytest.mark.asyncio
async def test_r101_r102_mutating_own_repair_exhausted_freezes_with_unaccepted_real_patch(canonical_workspace):
    core, binding, store, first_fb = await _mutated_own_failure(canonical_workspace)
    assert not core.failed
    assert core.states["writer"].repair_count == 1
    assert core.states["writer"].logical_status is NodeLogicalStatus.REMEDIATION_PENDING
    assert first_fb.acceptance_verdict is not None
    class FailingSecondWriter(FakeExecutionBackend):
        async def execute_prepared(self, preparation, invocation):
            Path(binding.repository_root, "source.py").write_text("STILL_BROKEN_AFTER_REPAIR = True\n")
            return await super().execute_prepared(preparation, invocation)
    async def failed_acceptance(_result, _invocation, _revision):
        return None
    inv = await core.run_claim(
        await core.claim("writer"),
        FailingSecondWriter([FakeExecutionScenario(mutation_evidence=MutationEvidence.OBSERVED)]),
        accept=failed_acceptance,
    )
    assert inv is not None and inv.attempt_kind.value == "repair"
    state = core.states["writer"]
    assert state.repair_count == 1 and state.next_attempt == 3
    assert len(state.attempts) == 2
    # Repair exhaustion must not discard the final attested failure proof.
    final_acceptance_refs = tuple(
        ref for ref in state.attempts[-1].evidence_refs
        if ref.kind is AttemptEvidenceKind.ACCEPTANCE_VERDICT
    )
    assert len(final_acceptance_refs) == 1
    assert final_acceptance_refs[0] != first_fb.acceptance_verdict
    assert state.logical_status is NodeLogicalStatus.FAILED
    assert state.terminal_failure_kind == "REPAIR_BUDGET_EXHAUSTED"
    assert core.failed and core.failure_kinds == ["REPAIR_BUDGET_EXHAUSTED"]
    assert core.workspace.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
    with pytest.raises(DispatchRevoked):
        await core.claim("writer")
    outcome = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert outcome.status is TaskLogicalStatus.FAILED
    assert outcome.workspace_disposition is WorkspaceDisposition.STABLE_WITH_UNCERTAINTY
    assert outcome.repository_disposition is RepositoryDisposition.PATCH_PRESENT
    assert outcome.patch_disposition is PatchDisposition.RESIDUAL_UNACCEPTED
    assert len(outcome.root_failures) == 1
    assert outcome.root_failures[0].node_id == "writer"
    assert outcome.root_failures[0].failure_kind == "REPAIR_BUDGET_EXHAUSTED"
    assert outcome.final_repository_changeset is not None
    assert "STILL_BROKEN_AFTER_REPAIR" in store.get(outcome.final_repository_changeset)["tracked_diff"]
    assert outcome.final_repository_state is not None
    assert final_acceptance_refs[0] in outcome.last_trusted_evidence_refs


@pytest.mark.asyncio
async def test_r91_r94_r95_r103_dirty_writer_failed_reviewer_never_runs_and_patch_is_runtime_only(terminal_fixture):
    baseline, _, binding, store = terminal_fixture
    core, manager = scheduler(
        Path(binding.repository_root),
        node("writer"),
        node("review", ordinal=1, deps=("writer",), access=WorkspaceAccess.READ, kind=WorkKind.REVIEW),
        node("independent", ordinal=2),
    )
    core.revision = baseline.revision
    class DirtyFailWriter(FakeExecutionBackend):
        async def execute_prepared(self, preparation, invocation):
            Path(binding.repository_root, "file.py").write_text("DIRTY_FAILURE = True\n")
            return await super().execute_prepared(preparation, invocation)
    backend = DirtyFailWriter([FakeExecutionScenario(
        terminal_status=BackendTerminalStatus.FAILED,
        mutation_evidence=MutationEvidence.OBSERVED,
        failure_kind="EXECUTION_NON_TRANSIENT_FAILURE",
        quiescent=True,
    )])
    reviewer = FakeExecutionBackend([FakeExecutionScenario()])
    ready_elsewhere = await core.claim("independent")
    await core.run_claim(await core.claim("writer"), backend)
    assert core.failed and manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
    assert core.task_logical_status is TaskLogicalStatus.FAILED
    assert core.states["writer"].logical_status is NodeLogicalStatus.FAILED
    assert core.states["review"].logical_status is NodeLogicalStatus.BLOCKED
    assert core.states["independent"].logical_status is NodeLogicalStatus.BLOCKED
    assert core.states["independent"].block_reason is NodeBlockReason.TASK_FAIL_CLOSED
    assert manager.dispatch_closed
    assert await core.run_claim(ready_elsewhere, reviewer) is None
    assert reviewer.records == [] and reviewer.preparations != []  # no execution
    with pytest.raises(DispatchRevoked):
        await core.claim("review")
    result = finalize_task(
        scheduler=core, binding=binding, evidence_store=store,
        physical_attribution_complete=True,
    )
    assert result.status is TaskLogicalStatus.FAILED
    assert result.workspace_disposition is WorkspaceDisposition.STABLE
    assert result.repository_disposition is RepositoryDisposition.PATCH_PRESENT
    assert result.patch_disposition is PatchDisposition.RESIDUAL_UNACCEPTED
    assert result.final_repository_changeset is not None
    assert len(result.root_failures) == 1 and result.root_failures[0].node_id == "writer"
    assert "DIRTY_FAILURE" in store.get(result.final_repository_changeset)["tracked_diff"]


@pytest.mark.asyncio
async def test_r100_review_request_changes_preserves_writer_patch_but_not_acceptance(terminal_fixture):
    baseline, _, binding, store = terminal_fixture
    core, _ = scheduler(
        Path(binding.repository_root), node("writer"),
        node("review", deps=("writer",), ordinal=1,
             kind=WorkKind.REVIEW, access=WorkspaceAccess.READ),
    )
    core.revision = baseline.revision
    class Writer(FakeExecutionBackend):
        async def execute_prepared(self, prep, invocation):
            Path(binding.repository_root, "file.py").write_text("VALID_PATCH_PENDING_REVIEW = True\n")
            return await super().execute_prepared(prep, invocation)
    await core.run_claim(
        await core.claim("writer"),
        Writer([FakeExecutionScenario(mutation_evidence=MutationEvidence.OBSERVED)]),
        accept=accept,
    )
    async def trusted_review(_result, invocation, revision):
        return make_review_verdict(
            node_id=invocation.node_id, execution_id=invocation.execution_id,
            attempt=invocation.attempt, revision=revision,
            decision=ReviewDecision.REQUEST_CHANGES,
            findings=("patch needs contract-compatible behavior",),
        )
    await core.run_claim(
        await core.claim("review"),
        FakeExecutionBackend([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.COMPLETED,
            result="model prose is not a repair authority",
            mutation_evidence=MutationEvidence.PROVEN_NONE,
        )]),
        review_gate=trusted_review, review_evidence_store=store,
    )
    review_attempt = core.states["review"].attempts[-1]
    assert len(review_attempt.evidence_refs) == 1
    assert review_attempt.evidence_refs[0].kind is AttemptEvidenceKind.REVIEW_VERDICT
    review_data = ReviewVerdict.model_validate(store.get(review_attempt.evidence_refs[0]))
    assert review_data.decision is ReviewDecision.REQUEST_CHANGES
    assert review_data.source_execution_id == review_attempt.execution_id
    assert core.states["writer"].logical_status is NodeLogicalStatus.SUCCEEDED
    assert core.states["review"].logical_status is NodeLogicalStatus.FAILED
    assert core.states["review"].terminal_failure_kind == "REVIEW_GATE_REJECTED"
    await core.fail_closed("REVIEW_GATE_REJECTED", root_node="review")
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert result.status is TaskLogicalStatus.FAILED
    assert result.patch_disposition is PatchDisposition.RESIDUAL_UNACCEPTED
    assert result.repository_disposition is RepositoryDisposition.PATCH_PRESENT
    assert len(result.root_failures) == 1
    assert result.root_failures[0].node_id == "review"
    assert result.root_failures[0].failure_kind == "REVIEW_GATE_REJECTED"
    assert result.root_failures[0].supporting_evidence_refs == review_attempt.evidence_refs
    assert review_attempt.evidence_refs[0] in result.last_trusted_evidence_refs
    assert "VALID_PATCH_PENDING_REVIEW" in store.get(result.final_repository_changeset)["tracked_diff"]


async def _scope_cancel_fixture(terminal_fixture, *, quiescent=True):
    baseline, _, binding, store = terminal_fixture
    writer = node("writer")
    verify = node("verify", deps=("writer",), ordinal=1,
                  kind=WorkKind.VERIFICATION, access=WorkspaceAccess.WRITE)
    consumer = node("consumer", deps=("writer",), ordinal=2, access=WorkspaceAccess.READ,
                    kind=WorkKind.REVIEW)
    nodes = (writer, verify, consumer)
    core, manager = scheduler(Path(binding.repository_root), *nodes)
    core.revision = baseline.revision
    compiled = VerificationRepairBinding(
        verification_node_id="verify", verification_check_id="unit",
        candidate_write_node_ids=("writer",),
        derivation="dag_business_writer_ancestors",
        dag_structure_fingerprint=structure_fingerprint(nodes),
        fingerprint="test-compiled-unit",
    )
    core.dag = build_task_dag(nodes, (compiled,))
    await core.run_claim(
        await core.claim("writer"), FakeExecutionBackend([FakeExecutionScenario()]), accept=accept,
    )
    await core.run_claim(
        await core.claim("verify"), FakeExecutionBackend([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.FAILED,
            mutation_evidence=MutationEvidence.PROVEN_NONE,
            failure_kind="VERIFICATION_FAILED",
        )]),
    )
    source = core.states["verify"].attempts[-1]
    proof = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.TOOL_RECEIPT_LEDGER,
        payload={"check_id": "unit", "exit_code": 1, "checker": "test-fixture"},
        workspace_revision=source.post_workspace_revision,
    )
    verification = make_verification_result(
        verification_node_id="verify", verification_execution_id=source.execution_id,
        verification_attempt=source.attempt, observed_workspace_revision=source.post_workspace_revision,
        observed_repository_state_fingerprint=source.post_workspace_revision.repository_state_fingerprint,
        checks=(VerificationCheckResult(check_id="unit", status=VerificationCheckStatus.FAILED,
                                        deterministic=True, evidence_refs=(proof,)),),
        repository_state_unchanged=True,
    )
    vref = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.VERIFICATION_RESULT,
        payload=verification, workspace_revision=source.post_workspace_revision,
    )
    await core.attach_attempt_evidence(node_id="verify", evidence_ref=vref, evidence_store=store)
    decision = resolve_verification_repair_attribution(
        dag=core.dag, source_attempt=core.states["verify"].attempts[-1],
        verification_ref=vref, node_states=core.states, evidence_store=store,
    )
    assert decision.kind is RepairAttributionKind.UNIQUE_WRITER
    aref = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.REPAIR_ATTRIBUTION,
        payload=decision, workspace_revision=source.post_workspace_revision,
    )
    await core.attach_attempt_evidence(node_id="verify", evidence_ref=aref, evidence_store=store)

    class SideEffectConsumer(FakeExecutionBackend):
        async def execute_prepared(self, preparation, invocation):
            Path(binding.repository_root, "file.py").write_text("CONSUMER_CANCEL_SIDE_EFFECT = True\n")
            return await super().execute_prepared(preparation, invocation)
    backend = SideEffectConsumer([FakeExecutionScenario(
        release_event=asyncio.Event(),
        mutation_evidence=MutationEvidence.OBSERVED,
        quiescent=quiescent,
    )])
    runner = asyncio.create_task(core.run_claim(
        await core.claim("consumer"), backend, accept=accept,
    ))
    for _ in range(300):
        if core.states["consumer"].logical_status is NodeLogicalStatus.RUNNING:
            break
        await asyncio.sleep(0)
    assert core.states["consumer"].logical_status is NodeLogicalStatus.RUNNING
    with pytest.raises(RepairScopeInvalidated, match="ACTIVE_DOWNSTREAM_DISPATCH"):
        await core.reopen_writer_from_verification(
            verification_ref=vref, attribution_ref=aref, evidence_store=store,
        )
    await runner
    assert core.failed and not core.cancelled
    assert core.task_logical_status is TaskLogicalStatus.FAILED
    assert core.states["consumer"].logical_status is NodeLogicalStatus.CANCELLED
    assert core.states["consumer"].attempts[-1].status.value == "cancelled"
    assert core.states["verify"].logical_status is NodeLogicalStatus.FAILED
    return core, manager, binding, store


@pytest.mark.asyncio
async def test_r123_failclose_cancelled_consumer_patch_is_secondary_not_business_root(terminal_fixture):
    core, manager, binding, store = await _scope_cancel_fixture(terminal_fixture)
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert result.status is TaskLogicalStatus.FAILED
    assert len(result.root_failures) == 1
    assert result.root_failures[0].node_id == "verify"
    assert result.cancelled_node_ids == ("consumer",)
    assert "FAIL_CLOSED_CONSUMER_MUTATION:consumer" in result.warnings
    assert "TASK_TERMINATION:REPAIR_SCOPE_INVALIDATED_ACTIVE_DOWNSTREAM_DISPATCH" in result.warnings
    assert result.repository_disposition is RepositoryDisposition.PATCH_PRESENT
    assert result.patch_disposition is PatchDisposition.RESIDUAL_UNACCEPTED
    assert result.final_repository_changeset is not None
    assert "CONSUMER_CANCEL_SIDE_EFFECT" in store.get(result.final_repository_changeset)["tracked_diff"]


@pytest.mark.asyncio
async def test_r123_consumer_uncertain_cancel_quarantines_without_git_probe(terminal_fixture, monkeypatch):
    core, manager, binding, store = await _scope_cancel_fixture(terminal_fixture, quiescent=False)
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.QUARANTINED
    from aswe.runtime import finalization
    def disallow(*args, **kwargs):
        raise AssertionError("quarantined workspace must not be probed")
    monkeypatch.setattr(finalization, "capture_repository_state", disallow)
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert result.status is TaskLogicalStatus.FAILED
    assert result.workspace_disposition is WorkspaceDisposition.QUARANTINED
    assert result.repository_disposition is RepositoryDisposition.UNKNOWN
    assert result.patch_disposition is PatchDisposition.UNAVAILABLE
    assert result.final_repository_state is None
    assert result.root_failures[0].node_id == "verify"
    assert result.cancelled_node_ids == ("consumer",)


@pytest.mark.asyncio
async def test_r99_quarantine_preserves_preexisting_repository_changeset_only(terminal_fixture, monkeypatch):
    core, manager, binding, store = terminal_fixture
    await core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario()]), accept=accept,
    )
    attempt = core.states["writer"].attempts[-1]
    historical = store.put_attempt(
        task_id=core.task_id, node_id="writer", execution_id=attempt.execution_id,
        attempt=attempt.attempt, kind=AttemptEvidenceKind.REPOSITORY_CHANGESET,
        payload={"tracked_diff": "historical-only", "verified_before_quarantine": True},
        workspace_revision=attempt.post_workspace_revision,
    )
    await core.attach_attempt_evidence(
        node_id="writer", evidence_ref=historical, evidence_store=store,
    )
    async with core.state_mutex:
        core._fail_close_locked("BACKEND_QUIESCENCE_UNKNOWN")
    await manager.close_dispatch()
    await manager.terminalize(quiescence_proven=False)
    from aswe.runtime import finalization
    def disallow(*args, **kwargs):
        raise AssertionError("quarantine may not inspect current Git")
    monkeypatch.setattr(finalization, "capture_repository_state", disallow)
    monkeypatch.setattr(finalization, "materialize_repository_changeset", disallow)
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert result.status is TaskLogicalStatus.FAILED
    assert historical in result.last_trusted_evidence_refs
    assert store.get(historical)["tracked_diff"] == "historical-only"
    assert result.repository_disposition is RepositoryDisposition.UNKNOWN
    assert result.patch_disposition is PatchDisposition.UNAVAILABLE
    assert result.final_repository_changeset is None
    assert result.final_repository_state is None
    assert result.final_workspace_revision is None


@pytest.mark.asyncio
async def test_r128_taskwide_user_cancel_uncertain_backend_results_in_quarantine_without_git_probe(
        terminal_fixture, monkeypatch):
    core, manager, binding, store = terminal_fixture
    backend = FakeExecutionBackend([FakeExecutionScenario(
        release_event=asyncio.Event(),
        mutation_evidence=MutationEvidence.UNKNOWN,
        quiescent=False,
    )])
    runner = asyncio.create_task(core.run_claim(await core.claim("writer"), backend))
    for _ in range(300):
        if core.states["writer"].logical_status is NodeLogicalStatus.RUNNING:
            break
        await asyncio.sleep(0)
    assert core.states["writer"].logical_status is NodeLogicalStatus.RUNNING
    await core.cancel_task()
    await runner
    assert core.cancelled and manager.lifecycle.current.status is WorkspaceSessionStatus.QUARANTINED
    assert core.task_logical_status is TaskLogicalStatus.CANCELLED
    from aswe.runtime import finalization
    def disallow(*args, **kwargs):
        raise AssertionError("quarantine cannot read current workspace")
    monkeypatch.setattr(finalization, "capture_repository_state", disallow)
    monkeypatch.setattr(finalization, "materialize_repository_changeset", disallow)
    final = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert final.status is TaskLogicalStatus.CANCELLED
    assert final.workspace_disposition is WorkspaceDisposition.QUARANTINED
    assert final.repository_disposition is RepositoryDisposition.UNKNOWN
    assert final.patch_disposition is PatchDisposition.UNAVAILABLE
    assert final.final_repository_state is None
    assert final.final_repository_changeset is None
    assert final.root_failures == ()
    assert final.cancelled_node_ids == ("writer",)


@pytest.mark.asyncio
async def test_r102_verification_repair_budget_zero_closes_gate_without_new_writer_attempt(tmp_path):
    from aswe.core.config import RuntimeBudgetConfig
    from tests.unit.test_scheduler_repair import fixture
    core, manager, store, verification_ref, attribution, attribution_ref = await fixture(tmp_path)
    assert attribution.kind is RepairAttributionKind.UNIQUE_WRITER
    writer = core.states["writer"]
    core.budget = RuntimeBudgetConfig(max_repairs_per_write=0)
    with pytest.raises(RepairScopeInvalidated, match="REPAIR_BUDGET_EXHAUSTED"):
        await core.reopen_writer_from_verification(
            verification_ref=verification_ref, attribution_ref=attribution_ref,
            evidence_store=store,
        )
    assert core.failed and manager.dispatch_closed
    assert core.failure_kinds == ["REPAIR_BUDGET_EXHAUSTED"]
    assert core.states["writer"].accepted_handoff == writer.accepted_handoff
    assert core.states["writer"].attempts == writer.attempts
    assert core.states["verify"].logical_status is NodeLogicalStatus.FAILED
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN


@pytest.mark.asyncio
async def test_r100_review_gate_rejects_forged_or_unbound_request_changes(terminal_fixture):
    baseline, _, binding, store = terminal_fixture
    core, _ = scheduler(
        Path(binding.repository_root),
        node("review", kind=WorkKind.REVIEW, access=WorkspaceAccess.READ),
    )
    core.revision = baseline.revision
    async def forged(_result, invocation, revision):
        return make_review_verdict(
            node_id=invocation.node_id,
            execution_id="different-executor",
            attempt=invocation.attempt,
            revision=revision,
            decision=ReviewDecision.REQUEST_CHANGES,
            findings=("untrusted",),
        )
    with pytest.raises(ValueError, match="ReviewVerdict provenance"):
        await core.run_claim(
            await core.claim("review"),
            FakeExecutionBackend([FakeExecutionScenario()]),
            review_gate=forged, review_evidence_store=store,
        )
    assert core.failed
    assert core.task_logical_status is TaskLogicalStatus.FAILED
    assert core.states["review"].accepted_handoff is None
    assert core.workspace.lifecycle.current.status is WorkspaceSessionStatus.FROZEN


@pytest.mark.asyncio
async def test_p0c_late_user_cancel_does_not_overwrite_previous_business_failure(terminal_fixture):
    core, manager, binding, store = terminal_fixture
    await core.fail_closed("EXISTING_TASK_ROOT", root_node="writer")
    assert core.task_logical_status is TaskLogicalStatus.FAILED
    await core.cancel_task()
    assert not core.cancelled
    assert core.task_logical_status is TaskLogicalStatus.FAILED
    assert core.failure_kinds == ["EXISTING_TASK_ROOT"]
    final = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert final.status is TaskLogicalStatus.FAILED
    assert final.root_failures[0].failure_kind == "EXISTING_TASK_ROOT"


@pytest.mark.asyncio
async def test_p0c_late_user_cancel_does_not_change_completed_contract_success(terminal_fixture):
    from tests.unit.test_task_finalization import verdict
    core, manager, binding, store = terminal_fixture
    await core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario()]), accept=accept,
    )
    await core.complete_task()
    await core.cancel_task()
    assert not core.cancelled and not core.failed
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
    final = finalize_task(
        scheduler=core, binding=binding, evidence_store=store,
        contract_verdict=verdict(),
        expected_contract_fingerprint="contract-authority",
    )
    assert final.status is TaskLogicalStatus.SUCCEEDED
    assert final.root_failures == ()


@pytest.mark.asyncio
async def test_terminal_failclose_completed_consumer_after_cancel_is_not_second_root(tmp_path):
    from tests.unit.test_scheduler_repair import fixture
    core, manager, store, ref, _, attribution_ref = await fixture(tmp_path, consumer=True)
    release = asyncio.Event()
    class CancellationRacesCompletion(FakeExecutionBackend):
        async def cancel_node(self, execution_id):
            # A compliant executor may settle COMPLETED before cancellation
            # takes effect; cancellation still must join physical quiescence.
            release.set()
    backend = CancellationRacesCompletion([FakeExecutionScenario(
        release_event=release, mutation_evidence=MutationEvidence.PROVEN_NONE,
    )])
    runner = asyncio.create_task(core.run_claim(
        await core.claim("reviewer"), backend, accept=accept,
    ))
    for _ in range(300):
        if core.states["reviewer"].logical_status is NodeLogicalStatus.RUNNING:
            break
        await asyncio.sleep(0)
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.RUNNING
    with pytest.raises(RepairScopeInvalidated, match="ACTIVE_DOWNSTREAM_DISPATCH"):
        await core.reopen_writer_from_verification(
            verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
        )
    await runner
    assert backend.records[-1].terminal_status is BackendTerminalStatus.COMPLETED
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.CANCELLED
    assert core.states["reviewer"].accepted_handoff is None
    assert core.failure_kinds == ["REPAIR_SCOPE_INVALIDATED_ACTIVE_DOWNSTREAM_DISPATCH"]
    assert core.task_logical_status is TaskLogicalStatus.FAILED
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
