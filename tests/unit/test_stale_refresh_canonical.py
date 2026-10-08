"""Executable stale feedback refresh: fresh revision, receipts and no redundant repair."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aswe.core.contracts import (
    AttemptEvidenceKind, BackendTerminalStatus, WorkKind, WorkspaceAccess,
    VerificationRepairBinding,
)
from aswe.core.dag_fingerprint import build_task_dag, structure_fingerprint
from aswe.repository import capture_repository_state
from aswe.runtime.canonical_verifier import CanonicalVerifier, make_command_policy
from aswe.runtime.repair import (
    RepairAttributionKind, VerificationCheckResult, VerificationCheckStatus,
    VerificationResult, make_verification_result, resolve_verification_repair_attribution,
)
from aswe.runtime.scheduler import SchedulerCore
from aswe.runtime.state import NodeLogicalStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario, MutationEvidence
from tests.unit.test_scheduler_foundation import node, scheduler, accept
from tests.unit.test_canonical_verifier import canonical_workspace


async def _initial_failure(binding, revision, store, policy):
    writer = node("writer")
    verify = node("verify", deps=("writer",), ordinal=1,
                  kind=WorkKind.VERIFICATION, access=WorkspaceAccess.WRITE)
    core, _ = scheduler(Path(binding.repository_root), writer, verify)
    core.revision = revision
    canonical = CanonicalVerifier(task_id=core.task_id, runtime_data_dir=store.root,
                                   evidence_store=store, binding=binding)
    core._canonical_verifier = canonical
    core._canonical_check_policies = {policy.check_id: policy}
    core._test_only_allow_fixture_receipts = False
    spec = VerificationRepairBinding(
        verification_node_id="verify", verification_check_id=policy.check_id,
        candidate_write_node_ids=("writer",), derivation="dag_business_writer_ancestors",
        dag_structure_fingerprint=structure_fingerprint((writer, verify)),
        fingerprint="compiled-verification-binding",
    )
    core.dag = build_task_dag((writer, verify), (spec,))
    await core.run_claim(await core.claim("writer"),
                         FakeExecutionBackend([FakeExecutionScenario()]), accept=accept)
    await core.run_claim(
        await core.claim("verify"), FakeExecutionBackend([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.FAILED,
            mutation_evidence=MutationEvidence.PROVEN_NONE,
            failure_kind="VERIFICATION_FAILED",
        )]),
    )
    source = core.states["verify"].attempts[-1]
    old_proof, old_receipt = canonical.run(
        node_id="verify", execution_id=source.execution_id, attempt=source.attempt,
        policy=policy, revision=revision,
    )
    assert old_receipt.status == "failed"
    result = make_verification_result(
        verification_node_id="verify", verification_execution_id=source.execution_id,
        verification_attempt=source.attempt, observed_workspace_revision=revision,
        observed_repository_state_fingerprint=revision.repository_state_fingerprint,
        checks=(VerificationCheckResult(check_id=policy.check_id,
            status=VerificationCheckStatus.FAILED, deterministic=True,
            evidence_refs=(old_proof,)),),
        repository_state_unchanged=True,
    )
    vref = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.VERIFICATION_RESULT,
        payload=result, workspace_revision=revision,
    )
    await core.attach_attempt_evidence(node_id="verify", evidence_ref=vref, evidence_store=store)
    attribution = resolve_verification_repair_attribution(
        dag=core.dag, source_attempt=core.states["verify"].attempts[-1],
        verification_ref=vref, node_states=core.states, evidence_store=store,
        canonical_verifier=canonical,
    )
    assert attribution.kind is RepairAttributionKind.UNIQUE_WRITER
    aref = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.REPAIR_ATTRIBUTION,
        payload=attribution, workspace_revision=revision,
    )
    await core.attach_attempt_evidence(node_id="verify", evidence_ref=aref, evidence_store=store)
    await core.reopen_writer_from_verification(
        verification_ref=vref, attribution_ref=aref, evidence_store=store,
    )
    return core, old_proof, vref


def _advance_physical_revision(core, binding, content):
    Path(binding.repository_root, "source.py").write_text(content)
    physical = capture_repository_state(binding)
    core.revision = core.revision.model_copy(update=dict(
        generation=core.revision.generation + 1,
        repository_state_fingerprint=physical.fingerprint,
        head_sha=physical.head_sha, base_sha=physical.base_sha,
        dirty=physical.dirty_vs_base,
    ))


@pytest.mark.asyncio
async def test_r23_r25_stale_failure_gets_new_attempt_refs_revision_then_repairs(canonical_workspace):
    binding, rev, store, _ = canonical_workspace
    script = ("from pathlib import Path; import sys; "
              "sys.exit(0 if 'FIXED' in Path('source.py').read_text() else 1)")
    policy = make_command_policy("check", (sys.executable, "-c", script))
    core, old_proof, old_vref = await _initial_failure(binding, rev, store, policy)
    old_fb = core._typed_repair_feedback["writer"]
    _advance_physical_revision(core, binding, "BASELINE = False\n")
    backend = FakeExecutionBackend([FakeExecutionScenario()])
    writer_exec = await core.run_claim(
        await core.claim("writer"), backend, accept=accept,
    )
    assert writer_exec is not None and writer_exec.attempt_kind.value == "repair"
    assert len(backend.records) == 1
    source = core.states["verify"]
    assert len(source.attempts) == 2
    refreshed_attempt = source.attempts[-1]
    assert refreshed_attempt.kind.value == "reverify"
    assert refreshed_attempt.execution_id != source.attempts[0].execution_id
    new_vref = next(r for r in refreshed_attempt.evidence_refs
                    if r.kind is AttemptEvidenceKind.VERIFICATION_RESULT)
    new_proof = next(r for r in refreshed_attempt.evidence_refs
                     if r.kind is AttemptEvidenceKind.TOOL_RECEIPT_LEDGER)
    assert new_vref != old_vref and new_proof != old_proof
    assert new_vref.workspace_revision_generation == core.revision.generation
    new_result = VerificationResult.model_validate(store.get(new_vref))
    assert new_result.observed_workspace_revision.generation == rev.generation + 1
    assert new_result.checks[0].status is VerificationCheckStatus.FAILED
    assert refreshed_attempt.evidence_refs[-1].kind is AttemptEvidenceKind.REPAIR_ATTRIBUTION
    assert old_fb.verification_result != new_vref
    assert writer_exec.repair_feedback_text is not None
    assert core.states["writer"].accepted_attempt == 2
    assert core.states["verify"].logical_status is NodeLogicalStatus.REMEDIATION_PENDING


@pytest.mark.asyncio
async def test_r26_refresh_holds_never_dispatches_redundant_writer_repair(canonical_workspace):
    binding, rev, store, _ = canonical_workspace
    policy = make_command_policy("check", (sys.executable, "-c",
        "from pathlib import Path; import sys; "
        "sys.exit(0 if 'FIXED' in Path('source.py').read_text() else 1)"))
    core, _, _ = await _initial_failure(binding, rev, store, policy)
    _advance_physical_revision(core, binding, "FIXED = True\n")
    backend = FakeExecutionBackend([FakeExecutionScenario()])
    writer_invocation = await core.run_claim(await core.claim("writer"), backend, accept=accept)
    assert writer_invocation is None
    assert backend.records == []
    assert len(core.states["writer"].attempts) == 1
    assert "writer" not in core._typed_repair_feedback
    source = core.states["verify"]
    assert len(source.attempts) == 2
    new_vref = next(r for r in source.attempts[-1].evidence_refs
                    if r.kind is AttemptEvidenceKind.VERIFICATION_RESULT)
    actual = VerificationResult.model_validate(store.get(new_vref))
    assert actual.observed_workspace_revision.generation == rev.generation + 1
    assert actual.checks[0].status is VerificationCheckStatus.HOLDS
    # Writer's revoked handoff must not be resurrected without fresh authority.
    assert core.failed
    assert "REPAIR_SUPERSEDED_REPLAN_REQUIRED" in core.failure_kinds
    assert core.states["writer"].accepted_handoff is None


@pytest.mark.asyncio
async def test_r25_refresh_replaces_typed_feedback_with_new_evidence_fingerprint(canonical_workspace):
    from aswe.runtime.refresh import refresh_stale_verification
    from aswe.runtime.dispatch import NodeDispatchTicketState
    binding, rev, store, _ = canonical_workspace
    policy = make_command_policy("check", (sys.executable, "-c",
        "from pathlib import Path; import sys; "
        "sys.exit(0 if 'FIXED' in Path('source.py').read_text() else 1)"))
    core, old_proof, old_vref = await _initial_failure(binding, rev, store, policy)
    initial = core._typed_repair_feedback["writer"]
    _advance_physical_revision(core, binding, "NOT_FIXED = False\\n")
    ticket = await core.claim("writer")
    await core._advance(ticket.ticket_id, NodeDispatchTicketState.WAITING_WORKSPACE)
    async with core.workspace.access(WorkspaceAccess.WRITE):
        await core._advance(ticket.ticket_id, NodeDispatchTicketState.LOCKED_PRECOMMIT)
        assert await refresh_stale_verification(core, ticket.ticket_id)
        current = core._typed_repair_feedback["writer"]
        assert current != initial
        assert current.fingerprint != initial.fingerprint
        assert current.verification_result != initial.verification_result
        assert current.repair_attribution != initial.repair_attribution
        assert current.observed_workspace_revision == core.revision
        assert current.receipt_refs[0].ledger_evidence != old_proof
        assert current.receipt_refs[0].ledger_evidence.source_attempt == 2
        assert current.feedback_source_attempt == 2
        fresh = VerificationResult.model_validate(store.get(current.verification_result))
        assert fresh.observed_workspace_revision == core.revision
        assert fresh.checks[0].status is VerificationCheckStatus.FAILED
        await core.revoke(ticket.ticket_id)
    assert core.states["writer"].accepted_attempt is None
    assert len(core.states["writer"].attempts) == 1
