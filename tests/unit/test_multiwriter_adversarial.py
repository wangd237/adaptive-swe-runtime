"""P0-B adversarial attribution matrix against real Scheduler attempts and bindings.

All command receipts in this unit matrix are explicitly fake-only; the strict
canonical auth boundary is separately exercised in test_strict_canonical_repair.
"""
from __future__ import annotations

import pytest

from aswe.core.contracts import (
    AttemptEvidenceKind, BackendTerminalStatus, VerificationRepairBinding,
    WorkKind, WorkspaceAccess,
)
from aswe.core.dag_fingerprint import build_task_dag, structure_fingerprint
from aswe.evidence import LocalEvidenceStore
from aswe.runtime.dispatch import RepairScopeInvalidated
from aswe.runtime.repair import (
    RepairAttributionKind, VerificationCheckResult, VerificationCheckStatus,
    make_verification_result, resolve_verification_repair_attribution,
)
from aswe.runtime.state import NodeLogicalStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario, MutationEvidence
from tests.unit.test_scheduler_foundation import accept, node, scheduler


async def _actual_writers(tmp_path, bindings, *, two=True, retry_a=False,
                          report="Writer A caused failure", verification_write=True):
    """Execute actual business Writer(s) followed by one failed Verification attempt."""
    a = node("writerA")
    b = node("writerB", ordinal=1)
    nodes = [a] + ([b] if two else [])
    verify = node("verify", deps=tuple(n.id for n in nodes), ordinal=2,
                  access=WorkspaceAccess.WRITE if verification_write else WorkspaceAccess.READ,
                  kind=WorkKind.VERIFICATION)
    nodes.append(verify)
    core, _ = scheduler(tmp_path, *nodes)
    sfp = structure_fingerprint(nodes)
    specs = [
        VerificationRepairBinding(
            verification_node_id="verify", verification_check_id=check_id,
            candidate_write_node_ids=tuple(candidates),
            derivation="dag_business_writer_ancestors",
            dag_structure_fingerprint=sfp, fingerprint="compile-" + check_id,
        )
        for check_id, candidates in bindings.items()
    ]
    core.dag = build_task_dag(nodes, specs)
    if retry_a:
        backend = FakeExecutionBackend([
            FakeExecutionScenario(
                terminal_status=BackendTerminalStatus.FAILED,
                mutation_evidence=MutationEvidence.PROVEN_NONE,
                failure_kind="EXECUTION_TRANSIENT_FAILURE",
            ), FakeExecutionScenario(),
        ])
        await core.run_claim(await core.claim("writerA"), backend)
        await core.run_claim(await core.claim("writerA"), backend, accept=accept)
    else:
        await core.run_claim(
            await core.claim("writerA"),
            FakeExecutionBackend([FakeExecutionScenario()]), accept=accept,
        )
    if two:
        await core.run_claim(
            await core.claim("writerB"),
            FakeExecutionBackend([FakeExecutionScenario()]), accept=accept,
        )
    await core.run_claim(
        await core.claim("verify"),
        FakeExecutionBackend([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.FAILED,
            mutation_evidence=MutationEvidence.PROVEN_NONE,
            failure_kind="VERIFICATION_FAILED", result=report,
        )]),
    )
    store = LocalEvidenceStore(tmp_path / "evidence")
    source = core.states["verify"].attempts[-1]
    checks = []
    for check_id in bindings:
        proof = store.put_attempt(
            task_id=core.task_id, node_id="verify",
            execution_id=source.execution_id, attempt=source.attempt,
            kind=AttemptEvidenceKind.TOOL_RECEIPT_LEDGER,
            payload={"check_id": check_id, "exit_code": 1},
            workspace_revision=source.post_workspace_revision,
        )
        checks.append(VerificationCheckResult(
            check_id=check_id, status=VerificationCheckStatus.FAILED,
            deterministic=True, evidence_refs=(proof,),
        ))
    verification = make_verification_result(
        verification_node_id="verify", verification_execution_id=source.execution_id,
        verification_attempt=source.attempt,
        observed_workspace_revision=source.post_workspace_revision,
        observed_repository_state_fingerprint=source.post_workspace_revision.repository_state_fingerprint,
        checks=tuple(checks), repository_state_unchanged=True,
    )
    ref = store.put_attempt(
        task_id=core.task_id, node_id="verify",
        execution_id=source.execution_id, attempt=source.attempt,
        kind=AttemptEvidenceKind.VERIFICATION_RESULT,
        payload=verification, workspace_revision=source.post_workspace_revision,
    )
    await core.attach_attempt_evidence(node_id="verify", evidence_ref=ref, evidence_store=store)
    return core, store, ref


def _decision(core, store, ref):
    return resolve_verification_repair_attribution(
        dag=core.dag, source_attempt=core.states["verify"].attempts[-1],
        verification_ref=ref, node_states=core.states, evidence_store=store,
    )


@pytest.mark.asyncio
async def test_r76_multiple_failed_checks_same_actual_single_writer(tmp_path):
    core, store, ref = await _actual_writers(
        tmp_path, {"build": ("writerA",), "unit": ("writerA",)}, two=False,
    )
    result = _decision(core, store, ref)
    assert result.kind is RepairAttributionKind.UNIQUE_WRITER
    assert result.failed_check_ids == ("build", "unit")
    assert result.target_write_node_id == "writerA"
    assert result.target_write_attempt == 1


@pytest.mark.asyncio
async def test_r77_r78_r88_real_two_writers_same_provider_last_writer_not_selected(tmp_path):
    core, store, ref = await _actual_writers(tmp_path, {"global": ("writerA", "writerB")})
    assert core.states["writerB"].accepted_attempt == 1
    assert core.states["writerB"].attempts[-1].execution_id != core.states["writerA"].attempts[-1].execution_id
    assert core.nodes["writerB"].provider_id == core.nodes["writerA"].provider_id == "fake"
    result = _decision(core, store, ref)
    assert result.kind is RepairAttributionKind.MULTI_WRITER
    assert result.candidate_write_node_ids == ("writerA", "writerB")
    assert result.target_write_node_id is None


@pytest.mark.asyncio
async def test_r79_r80_changed_path_or_tester_blame_do_not_override_compiled_owners(tmp_path):
    core, store, ref = await _actual_writers(
        tmp_path, {"global": ("writerA", "writerB")},
        report="Only writerA was at fault, file: writerA_only.py",
    )
    # Test-only handoff diagnostic path overlap is deliberately not a compiler binding.
    a_state = core.states["writerA"]
    a_handoff = a_state.accepted_handoff
    modified = a_handoff.model_copy(update={
        "evidence": a_handoff.evidence.model_copy(update={
            "changed_paths": ("writerA_only.py",),
            "changed_paths_complete": True,
        })
    })
    attempt = a_state.attempts[-1].model_copy(update={"handoff": modified})
    core.states["writerA"] = a_state.model_copy(update={
        "accepted_handoff": modified, "attempts": a_state.attempts[:-1] + (attempt,),
    })
    decision = _decision(core, store, ref)
    assert decision.kind is RepairAttributionKind.MULTI_WRITER
    assert decision.target_write_node_id is None


@pytest.mark.asyncio
async def test_r81_missing_one_owner_poison_entire_multi_check_verdict(tmp_path):
    core, store, ref = await _actual_writers(
        tmp_path, {"owned": ("writerA",), "unowned": ()}, two=False,
    )
    result = _decision(core, store, ref)
    assert result.kind is RepairAttributionKind.NO_OWNER
    assert result.target_write_node_id is None


@pytest.mark.asyncio
async def test_r82_two_checks_bound_to_distinct_actual_writers_remain_ambiguous(tmp_path):
    core, store, ref = await _actual_writers(
        tmp_path, {"unit": ("writerA",), "integration": ("writerB",)},
    )
    result = _decision(core, store, ref)
    assert result.kind is RepairAttributionKind.MULTI_WRITER
    assert result.target_write_node_id is None


@pytest.mark.asyncio
async def test_r83_current_accepted_retry_attempt_not_historical_attempt_1(tmp_path):
    core, store, ref = await _actual_writers(
        tmp_path, {"unit": ("writerA",)}, two=False, retry_a=True,
    )
    assert len(core.states["writerA"].attempts) == 2
    assert core.states["writerA"].accepted_attempt == 2
    result = _decision(core, store, ref)
    assert result.kind is RepairAttributionKind.UNIQUE_WRITER
    assert result.target_write_attempt == 2


@pytest.mark.asyncio
async def test_r86_unverified_only_provides_no_deterministic_repair_owner(tmp_path):
    core, store, _ = await _actual_writers(tmp_path, {"check": ("writerA",)}, two=False)
    source = core.states["verify"].attempts[-1]
    verification = make_verification_result(
        verification_node_id="verify", verification_execution_id=source.execution_id,
        verification_attempt=source.attempt,
        observed_workspace_revision=source.post_workspace_revision,
        observed_repository_state_fingerprint=source.post_workspace_revision.repository_state_fingerprint,
        checks=(VerificationCheckResult(
            check_id="check", status=VerificationCheckStatus.UNVERIFIED,
            deterministic=False, evidence_refs=(),
        ),), repository_state_unchanged=True,
    )
    new_ref = store.put_attempt(
        task_id=core.task_id, node_id="verify",
        execution_id=source.execution_id, attempt=source.attempt,
        kind=AttemptEvidenceKind.VERIFICATION_RESULT,
        payload=verification, workspace_revision=source.post_workspace_revision,
    )
    await core.attach_attempt_evidence(node_id="verify", evidence_ref=new_ref, evidence_store=store)
    assert _decision(core, store, new_ref).kind is RepairAttributionKind.SOURCE_INELIGIBLE


@pytest.mark.asyncio
async def test_r87_physical_write_verifier_does_not_become_business_writer(tmp_path):
    core, store, ref = await _actual_writers(
        tmp_path, {"unit": ("writerA",)}, two=False, verification_write=True,
    )
    assert core.nodes["verify"].workspace_access is WorkspaceAccess.WRITE
    assert core.nodes["verify"].work_kind is WorkKind.VERIFICATION
    result = _decision(core, store, ref)
    assert result.kind is RepairAttributionKind.UNIQUE_WRITER
    assert result.target_write_node_id == "writerA"


@pytest.mark.asyncio
async def test_r89_intervening_changed_business_writer_invalidates_singleton_scope(tmp_path):
    core, store, ref = await _actual_writers(
        tmp_path, {"check": ("writerA",)},
    )
    other = core.states["writerB"]
    attempt = other.attempts[-1]
    changed = attempt.post_workspace_revision.model_copy(update={
        "repository_state_fingerprint": "trusted-intervening-physical-digest",
    })
    # This is a trusted post-attempt digest fixture; avoid path/prose heuristics.
    modified_attempt = attempt.model_copy(update={"post_workspace_revision": changed})
    core.states["writerB"] = other.model_copy(update={
        "attempts": other.attempts[:-1] + (modified_attempt,),
    })
    result = _decision(core, store, ref)
    assert result.kind is RepairAttributionKind.SCOPE_INVALIDATED
    assert "INTERVENING_DISTINCT_WRITER" in result.reason_codes
