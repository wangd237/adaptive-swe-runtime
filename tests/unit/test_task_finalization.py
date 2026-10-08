"""TaskResult terminal evidence, residual patches, contract gate and quarantine."""
from __future__ import annotations

import subprocess

import pytest

from aswe.core.contracts import WorkspaceRevision
from aswe.evidence import LocalEvidenceStore
from aswe.evaluation.contracts import (
    ConstraintEnforcement, ContractLeafStatus, ContractLeafVerdict,
    build_contract_verdict,
)
from aswe.repository import bootstrap_repository, capture_repository_state
from aswe.runtime.finalization import (
    PatchDisposition, RepositoryDisposition, TaskLogicalStatus,
    WorkspaceDisposition, TaskResult, finalize_task,
)
from aswe.runtime.dispatch import TaskDispatchGateState
from aswe.workspace.session import WorkspaceSessionStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario
from tests.unit.test_scheduler_foundation import accept, node, scheduler


@pytest.fixture
def terminal_fixture(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    def git(*args):
        subprocess.run(["git", "-C", str(source), *args], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (source / "file.py").write_text("base\n")
    git("add", "-A")
    git("commit", "-m", "base")
    binding = bootstrap_repository(source, tmp_path / "workspace", requested_ref="main")
    digest = capture_repository_state(binding)
    core, manager = scheduler(tmp_path / "workspace", node("writer"))
    core.revision = WorkspaceRevision(
        generation=0, base_sha=digest.base_sha, head_sha=digest.head_sha,
        head_matches_baseline=True, repository_state_fingerprint=digest.fingerprint, dirty=False
    )
    store = LocalEvidenceStore(tmp_path / "runtime", workspace_root=binding.repository_root)
    return core, manager, binding, store


def verdict(status=ContractLeafStatus.SATISFIED):
    return build_contract_verdict("contract-authority", (
        ContractLeafVerdict(constraint_id="must-pass", enforcement=ConstraintEnforcement.HARD,
                            status=status),
    ))


@pytest.mark.asyncio
async def test_normal_completed_task_requires_valid_contract_verdict(terminal_fixture):
    core, manager, binding, store = terminal_fixture
    await core.run_claim(await core.claim("writer"),
                         FakeExecutionBackend([FakeExecutionScenario()]), accept=accept)
    await core.complete_task()
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store,
                           contract_verdict=verdict())
    assert result.status is TaskLogicalStatus.SUCCEEDED
    assert result.repository_disposition is RepositoryDisposition.BASELINE_CLEAN
    assert result.patch_disposition is PatchDisposition.NONE
    assert result.final_repository_state and result.final_contract_verdict
    assert store.get(result.final_contract_verdict)["all_required_satisfied"] is True


@pytest.mark.asyncio
async def test_missing_contract_verdict_never_produces_success(terminal_fixture):
    core, _, binding, store = terminal_fixture
    await core.run_claim(await core.claim("writer"),
                         FakeExecutionBackend([FakeExecutionScenario()]), accept=accept)
    await core.complete_task()
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert result.status is TaskLogicalStatus.FAILED
    assert result.root_failures[0].failure_kind == "TASK_CONTRACT_UNVERIFIED"


@pytest.mark.asyncio
async def test_failed_task_retains_unaccepted_patch_as_task_evidence(terminal_fixture):
    core, _, binding, store = terminal_fixture
    from pathlib import Path
    (Path(binding.repository_root) / "file.py").write_text("unaccepted patch\n")
    await core.fail_closed("DIRTY_WRITE_FAILURE", root_node="writer")
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store,
                           physical_attribution_complete=False)
    assert result.status is TaskLogicalStatus.FAILED
    assert result.repository_disposition is RepositoryDisposition.PATCH_PRESENT
    assert result.patch_disposition is PatchDisposition.RESIDUAL_UNACCEPTED
    assert result.workspace_disposition is WorkspaceDisposition.STABLE_WITH_UNCERTAINTY
    assert result.final_repository_changeset is not None
    assert "unaccepted patch" in store.get(result.final_repository_changeset)["tracked_diff"]


@pytest.mark.asyncio
async def test_user_cancel_keeps_residual_patch_but_not_business_success(terminal_fixture):
    core, manager, binding, store = terminal_fixture
    from pathlib import Path
    (Path(binding.repository_root) / "file.py").write_text("partial edit\n")
    await core.cancel_task()
    assert core.cancelled and manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert result.status is TaskLogicalStatus.CANCELLED
    assert result.patch_disposition is PatchDisposition.RESIDUAL_UNACCEPTED
    assert result.cancelled_node_ids == ("writer",)


@pytest.mark.asyncio
async def test_quarantine_never_reads_current_git_state(terminal_fixture, monkeypatch):
    core, manager, binding, store = terminal_fixture
    async with core.state_mutex:
        core._fail_close_locked("BACKEND_QUIESCENCE_UNKNOWN")
    await manager.close_dispatch()
    await manager.terminalize(quiescence_proven=False)
    from aswe.runtime import finalization
    def illegal_git(*_args, **_kwargs):
        raise AssertionError("QUARANTINED must not inspect workspace")
    monkeypatch.setattr(finalization, "capture_repository_state", illegal_git)
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert result.status is TaskLogicalStatus.FAILED
    assert result.workspace_disposition is WorkspaceDisposition.QUARANTINED
    assert result.repository_disposition is RepositoryDisposition.UNKNOWN
    assert result.patch_disposition is PatchDisposition.UNAVAILABLE
    assert result.final_repository_state is None


@pytest.mark.asyncio
async def test_hard_unverified_blocking_constraint_cannot_be_downgraded(terminal_fixture):
    core, manager, binding, store = terminal_fixture
    await core.run_claim(await core.claim("writer"),
                         FakeExecutionBackend([FakeExecutionScenario()]), accept=accept)
    await core.complete_task()
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store,
                           contract_verdict=verdict(ContractLeafStatus.UNVERIFIED))
    assert result.status is TaskLogicalStatus.FAILED


@pytest.mark.asyncio
async def test_finalization_before_drain_is_rejected(terminal_fixture):
    core, _, binding, store = terminal_fixture
    with pytest.raises(RuntimeError, match="terminalization requires"):
        finalize_task(scheduler=core, binding=binding, evidence_store=store)
