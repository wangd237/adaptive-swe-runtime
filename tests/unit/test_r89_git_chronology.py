"""POC-R89: real intervening Writer Git mutation invalidates singleton attribution."""
from pathlib import Path
import sys

import pytest

from aswe.core.contracts import (
    AttemptEvidenceKind, BackendTerminalStatus, WorkKind,
    VerificationRepairBinding, WorkspaceAccess,
)
from aswe.core.dag_fingerprint import build_task_dag, structure_fingerprint
from aswe.repository import capture_repository_state
from aswe.runtime.canonical_verifier import CanonicalVerifier, make_command_policy
from aswe.runtime.repair import (
    RepairAttributionKind, VerificationCheckResult, VerificationCheckStatus,
    make_verification_result, resolve_verification_repair_attribution,
)
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario, MutationEvidence
from tests.unit.test_scheduler_foundation import scheduler, node, accept
from tests.unit.test_canonical_verifier import canonical_workspace


@pytest.mark.asyncio
async def test_r89_actual_intervening_business_writer_changes_git_and_invalidates_attribution(canonical_workspace):
    binding, baseline_revision, store, _ = canonical_workspace
    a = node("writerA")
    b = node("writerB", ordinal=1)
    verify = node(
        "verify", deps=("writerA", "writerB"), ordinal=2,
        kind=WorkKind.VERIFICATION, access=WorkspaceAccess.WRITE,
    )
    nodes = (a, b, verify)
    compiled = VerificationRepairBinding(
        verification_node_id="verify", verification_check_id="test",
        candidate_write_node_ids=("writerA",),
        derivation="dag_business_writer_ancestors",
        dag_structure_fingerprint=structure_fingerprint(nodes),
        fingerprint="compile-writerA-ownership",
    )
    core, _ = scheduler(Path(binding.repository_root), *nodes)
    core.dag = build_task_dag(nodes, (compiled,))
    core.revision = baseline_revision
    canonical = CanonicalVerifier(
        task_id=core.task_id, runtime_data_dir=store.root,
        evidence_store=store, binding=binding,
    )
    core._canonical_verifier = canonical
    core._test_only_allow_fixture_receipts = False

    await core.run_claim(
        await core.claim("writerA"),
        FakeExecutionBackend([FakeExecutionScenario()]), accept=accept,
    )
    a_post = core.states["writerA"].attempts[-1].post_workspace_revision

    class RealGitWritingBackend(FakeExecutionBackend):
        async def execute_prepared(self, preparation, invocation):
            Path(binding.repository_root, "source.py").write_text(
                "CHANGED_BY_WRITER_B = True\n"
            )
            return await super().execute_prepared(preparation, invocation)

    await core.run_claim(
        await core.claim("writerB"),
        RealGitWritingBackend([FakeExecutionScenario(
            mutation_evidence=MutationEvidence.OBSERVED,
        )]), accept=accept,
    )
    b_attempt = core.states["writerB"].attempts[-1]
    physical = capture_repository_state(binding)
    assert physical.fingerprint != baseline_revision.repository_state_fingerprint
    assert b_attempt.pre_workspace_revision == a_post
    assert b_attempt.post_workspace_revision.repository_state_fingerprint == physical.fingerprint
    assert b_attempt.post_workspace_revision.generation == a_post.generation + 1
    assert core.revision == b_attempt.post_workspace_revision

    await core.run_claim(
        await core.claim("verify"),
        FakeExecutionBackend([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.FAILED,
            failure_kind="VERIFICATION_FAILED",
            mutation_evidence=MutationEvidence.PROVEN_NONE,
        )]),
    )
    source = core.states["verify"].attempts[-1]
    policy = make_command_policy("test", (
        sys.executable, "-c", "raise SystemExit(1)",
    ))
    receipt_ref, receipt = canonical.run(
        node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, revision=source.post_workspace_revision,
        policy=policy,
    )
    assert receipt.status == "failed"
    result = make_verification_result(
        verification_node_id="verify",
        verification_execution_id=source.execution_id,
        verification_attempt=source.attempt,
        observed_workspace_revision=source.post_workspace_revision,
        observed_repository_state_fingerprint=source.post_workspace_revision.repository_state_fingerprint,
        checks=(VerificationCheckResult(
            check_id="test", status=VerificationCheckStatus.FAILED,
            deterministic=True, evidence_refs=(receipt_ref,),
        ),), repository_state_unchanged=True,
    )
    result_ref = store.put_attempt(
        task_id=core.task_id, node_id="verify",
        execution_id=source.execution_id, attempt=source.attempt,
        kind=AttemptEvidenceKind.VERIFICATION_RESULT,
        payload=result, workspace_revision=result.observed_workspace_revision,
    )
    await core.attach_attempt_evidence(
        node_id="verify", evidence_ref=result_ref, evidence_store=store,
    )
    verdict = resolve_verification_repair_attribution(
        dag=core.dag, source_attempt=core.states["verify"].attempts[-1],
        verification_ref=result_ref, node_states=core.states,
        evidence_store=store, canonical_verifier=canonical,
    )
    assert verdict.kind is RepairAttributionKind.SCOPE_INVALIDATED
    assert verdict.target_write_node_id is None
    assert "INTERVENING_DISTINCT_WRITER" in verdict.reason_codes
