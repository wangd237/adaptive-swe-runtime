"""Strict canonical tool-execution proof, persisted attribution and typed feedback E2E."""
import sys
from pathlib import Path
import pytest

from aswe.core.contracts import (
    AttemptEvidenceKind, BackendTerminalStatus, VerificationRepairBinding,
    WorkKind, WorkspaceAccess,
)
from aswe.core.dag_fingerprint import build_task_dag, structure_fingerprint
from aswe.evidence import LocalEvidenceStore
from aswe.runtime.canonical_verifier import CanonicalVerifier, make_command_policy
from aswe.runtime.repair import (
    VerificationCheckResult, VerificationCheckStatus,
    make_verification_result, resolve_verification_repair_attribution,
    RepairAttributionKind,
)
from aswe.runtime.scheduler import SchedulerCore
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario, MutationEvidence
from tests.unit.test_scheduler_foundation import node, scheduler, accept
from tests.unit.test_canonical_verifier import canonical_workspace


@pytest.mark.asyncio
async def test_runtime_canonical_receipt_authorizes_exact_single_writer_reopen(canonical_workspace):
    binding, revision, store, _ = canonical_workspace
    writer = node("writer")
    verifier_node = node("verify", deps=("writer",), ordinal=1,
                         access=WorkspaceAccess.WRITE, kind=WorkKind.VERIFICATION)
    core, _ = scheduler(Path(binding.repository_root), writer, verifier_node)
    core.revision = revision
    canonical = CanonicalVerifier(
        task_id=core.task_id, runtime_data_dir=store.root,
        evidence_store=store, binding=binding,
    )
    core._canonical_verifier = canonical
    core._test_only_allow_fixture_receipts = False
    sfp = structure_fingerprint((writer, verifier_node))
    binding_spec = VerificationRepairBinding(
        verification_node_id="verify", verification_check_id="canonical-check",
        candidate_write_node_ids=("writer",), derivation="dag_business_writer_ancestors",
        dag_structure_fingerprint=sfp, fingerprint="binding-fixture"
    )
    core.dag = build_task_dag((writer, verifier_node), (binding_spec,))
    await core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario()]), accept=accept
    )
    await core.run_claim(
        await core.claim("verify"),
        FakeExecutionBackend([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.FAILED,
            mutation_evidence=MutationEvidence.PROVEN_NONE,
            failure_kind="VERIFICATION_FAILED",
        )]),
    )
    source = core.states["verify"].attempts[-1]
    proof, receipt = canonical.run(
        node_id="verify", execution_id=source.execution_id, attempt=source.attempt,
        policy=make_command_policy("canonical-check",
                                   (sys.executable, "-c", "raise SystemExit(1)")),
        revision=source.post_workspace_revision,
    )
    assert receipt.status == "failed"
    verification = make_verification_result(
        verification_node_id="verify", verification_execution_id=source.execution_id,
        verification_attempt=source.attempt,
        observed_workspace_revision=source.post_workspace_revision,
        observed_repository_state_fingerprint=source.post_workspace_revision.repository_state_fingerprint,
        checks=(VerificationCheckResult(
            check_id="canonical-check", status=VerificationCheckStatus.FAILED,
            deterministic=True, evidence_refs=(proof,)
        ),),
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
        canonical_verifier=canonical,
    )
    assert decision.kind is RepairAttributionKind.UNIQUE_WRITER
    aref = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.REPAIR_ATTRIBUTION,
        payload=decision, workspace_revision=source.post_workspace_revision,
    )
    await core.attach_attempt_evidence(node_id="verify", evidence_ref=aref, evidence_store=store)
    await core.reopen_writer_from_verification(
        verification_ref=vref, attribution_ref=aref, evidence_store=store,
    )
    fb = core._typed_repair_feedback["writer"]
    assert fb.failed_check_ids == ("canonical-check",)
    assert fb.receipt_refs[0].ledger_evidence == proof
    invocation = await core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario()]), accept=accept,
    )
    assert invocation.attempt_kind.value == "repair"
    assert fb.bounded_projection() in invocation.repair_feedback_text
    assert core.states["writer"].acceptance_epoch == 3


@pytest.mark.asyncio
async def test_fake_attribution_without_runtime_canonical_verifier_denied(tmp_path):
    writer = node("writer")
    verifier_node = node("verify", deps=("writer",), ordinal=1,
                         work_kind=WorkKind.VERIFICATION) if False else None
    # A production Scheduler has no fixture bypass by default.
    from aswe.core.contracts import WorkspaceRevision
    from aswe.core.dag_fingerprint import build_task_dag
    from aswe.workspace import WorkspaceSession, WorkspaceSessionStatus, WorkspaceLifecycle, WorkspaceAccessManager
    life = WorkspaceLifecycle(WorkspaceSession(
        task_id="aswe-prod", thread_id="aswe-thread", user_id="aswe-user",
        workspace_root=str(tmp_path.resolve()),
        status=WorkspaceSessionStatus.BOOTSTRAPPING
    ))
    life.mark_ready()
    core = SchedulerCore(
        task_id="aswe-prod", dag=build_task_dag((writer,)),
        workspace=WorkspaceAccessManager(life),
        initial_revision=WorkspaceRevision(
            generation=0, base_sha="a"*40, head_sha="a"*40,
            head_matches_baseline=True, repository_state_fingerprint="base",
            dirty=False,
        ),
        evidence_checker=lambda h: True,
    )
    assert core._canonical_verifier is None
    assert core._test_only_allow_fixture_receipts is False


@pytest.mark.asyncio
async def test_repair_gate_rejects_fixture_receipts_when_test_override_disabled(tmp_path):
    from tests.unit.test_scheduler_repair import fixture
    core, _, store, vref, _, aref = await fixture(tmp_path)
    core._test_only_allow_fixture_receipts = False
    with pytest.raises(ValueError, match="Runtime Canonical Verifier required"):
        await core.reopen_writer_from_verification(
            verification_ref=vref, attribution_ref=aref, evidence_store=store
        )
    assert core.states["writer"].accepted_attempt == 1
