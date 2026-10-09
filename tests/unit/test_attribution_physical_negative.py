"""Adversarial physical Git mutation and crashed-verifier attribution negative tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from aswe.core.contracts import (
    AttemptEvidenceKind, BackendTerminalStatus, VerificationRepairBinding,
    WorkKind, WorkspaceAccess,
)
from aswe.core.dag_fingerprint import build_task_dag, structure_fingerprint
from aswe.repository import capture_repository_state
from aswe.evidence import LocalEvidenceStore
from aswe.runtime.canonical_verifier import CanonicalVerifier, make_command_policy
from aswe.runtime.repair import (
    RepairAttributionKind, VerificationCheckResult, VerificationCheckStatus,
    make_verification_result, resolve_verification_repair_attribution,
)
from aswe.runtime.state import NodeLogicalStatus
from aswe.workspace.session import WorkspaceSessionStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario, MutationEvidence
from tests.unit.test_scheduler_foundation import accept, node, scheduler
from tests.unit.test_canonical_verifier import canonical_workspace


def _two_nodes(tmp_path):
    writer = node("writer")
    verifier = node("verify", deps=("writer",), ordinal=1,
                    kind=WorkKind.VERIFICATION, access=WorkspaceAccess.WRITE)
    core, manager = scheduler(tmp_path, writer, verifier)
    b = VerificationRepairBinding(
        verification_node_id="verify", verification_check_id="unit",
        candidate_write_node_ids=("writer",), derivation="dag_business_writer_ancestors",
        dag_structure_fingerprint=structure_fingerprint((writer, verifier)),
        fingerprint="compiled-unit",
    )
    core.dag = build_task_dag((writer, verifier), (b,))
    return core, manager


@pytest.mark.asyncio
async def test_r84_real_verifier_tracked_mutation_invalidates_stable_git_attribution(canonical_workspace):
    binding, revision, store, _ = canonical_workspace
    core, manager = _two_nodes(Path(binding.repository_root))
    core.revision = revision
    await core.run_claim(
        await core.claim("writer"), FakeExecutionBackend([FakeExecutionScenario()]),
        accept=accept,
    )
    class MutatingVerifier(FakeExecutionBackend):
        async def execute_prepared(self, preparation, invocation):
            Path(binding.repository_root, "source.py").write_text("MUTATED = True\n")
            return await super().execute_prepared(preparation, invocation)

    await core.run_claim(
        await core.claim("verify"), MutatingVerifier([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.FAILED,
            mutation_evidence=MutationEvidence.OBSERVED,
            failure_kind="VERIFICATION_FAILED",
        )]),
    )
    real_state = capture_repository_state(binding)
    assert real_state.fingerprint != revision.repository_state_fingerprint
    assert core.states["verify"].logical_status is NodeLogicalStatus.FAILED
    assert core.failed and manager.dispatch_closed
    canonical = CanonicalVerifier(
        task_id=core.task_id, runtime_data_dir=store.root,
        evidence_store=store, binding=binding,
    )
    source = core.states["verify"].attempts[-1]
    with pytest.raises(ValueError, match="pre-state is stale"):
        canonical.run(
            node_id="verify", execution_id=source.execution_id,
            attempt=source.attempt, revision=revision,
            policy=make_command_policy("unit", ("git", "status", "--short")),
        )


@pytest.mark.asyncio
async def test_r85_backend_crash_cannot_manufacture_a_verification_repair_owner(tmp_path):
    core, manager = _two_nodes(tmp_path)
    await core.run_claim(
        await core.claim("writer"), FakeExecutionBackend([FakeExecutionScenario()]),
        accept=accept,
    )
    class CrashedVerifier(FakeExecutionBackend):
        async def execute_prepared(self, preparation, invocation):
            raise RuntimeError("verifier backend failed before reliable result")

    with pytest.raises(RuntimeError, match="verifier backend"):
        await core.run_claim(
            await core.claim("verify"), CrashedVerifier(),
        )
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.QUARANTINED
    source = core.states["verify"].attempts[-1]
    assert source.failure_kind == "BACKEND_QUIESCENCE_UNKNOWN"
    assert source.post_workspace_revision is None
    store = LocalEvidenceStore(tmp_path / "evidence")
    proof = store.put_attempt(
        task_id=core.task_id, node_id="verify",
        execution_id=source.execution_id, attempt=source.attempt,
        kind=AttemptEvidenceKind.TOOL_RECEIPT_LEDGER,
        payload={"check_id": "unit", "exit_code": 1, "claim": "fabricated"},
        workspace_revision=source.pre_workspace_revision,
    )
    forged = make_verification_result(
        verification_node_id="verify", verification_execution_id=source.execution_id,
        verification_attempt=source.attempt,
        observed_workspace_revision=source.pre_workspace_revision,
        observed_repository_state_fingerprint=source.pre_workspace_revision.repository_state_fingerprint,
        checks=(VerificationCheckResult(
            check_id="unit", status=VerificationCheckStatus.FAILED,
            deterministic=True, evidence_refs=(proof,),
        ),), repository_state_unchanged=True,
    )
    ref = store.put_attempt(
        task_id=core.task_id, node_id="verify", execution_id=source.execution_id,
        attempt=source.attempt, kind=AttemptEvidenceKind.VERIFICATION_RESULT,
        payload=forged, workspace_revision=source.pre_workspace_revision,
    )
    await core.attach_attempt_evidence(node_id="verify", evidence_ref=ref, evidence_store=store)
    outcome = resolve_verification_repair_attribution(
        dag=core.dag, source_attempt=core.states["verify"].attempts[-1],
        verification_ref=ref, node_states=core.states, evidence_store=store,
    )
    assert outcome.kind is RepairAttributionKind.SOURCE_INELIGIBLE
    assert outcome.target_write_node_id is None
