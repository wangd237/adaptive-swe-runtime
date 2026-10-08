"""Extra terminal PoC: contract authority, ignored mutation, old evidence, task scope."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from aswe.core.contracts import (
    AttemptEvidenceKind, HandoffEvidence, TaskEvidenceKind,
)
from aswe.evidence import LocalEvidenceStore
from aswe.runtime.finalization import (
    RepositoryDisposition, PatchDisposition, WorkspaceDisposition,
    TaskLogicalStatus, finalize_task,
)
from aswe.workspace.session import WorkspaceSessionStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario
from tests.unit.test_scheduler_foundation import accept
from tests.unit.test_task_finalization import terminal_fixture, verdict


@pytest.mark.asyncio
async def test_contract_verdict_fingerprint_not_bound_to_expected_contract_is_denied(terminal_fixture):
    core, _, binding, store = terminal_fixture
    await core.run_claim(await core.claim("writer"),
                         FakeExecutionBackend([FakeExecutionScenario()]), accept=accept)
    await core.complete_task()
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store,
                           contract_verdict=verdict(),
                           expected_contract_fingerprint="wrong-authority")
    assert result.status is TaskLogicalStatus.FAILED


@pytest.mark.asyncio
async def test_r97_ignored_cache_mutation_distinct_from_git_patch(terminal_fixture):
    core, manager, binding, store = terminal_fixture
    repo = Path(binding.repository_root)
    exclude = repo / ".git" / "info" / "exclude"
    with exclude.open("a") as output:
        output.write("\n.cache/\n")
    (repo / ".cache").mkdir()
    (repo / ".cache" / "ignored").write_text("physical side effect")
    await core.fail_closed("EXTERNAL_MUTATION_UNCERTAIN")
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert result.status is TaskLogicalStatus.FAILED
    assert result.workspace_disposition is WorkspaceDisposition.STABLE_WITH_UNCERTAINTY
    assert result.repository_disposition is RepositoryDisposition.BASELINE_CLEAN
    assert result.patch_disposition is PatchDisposition.NONE


@pytest.mark.asyncio
async def test_r108_quarantine_preserves_only_verified_historical_attempt_artifacts(terminal_fixture, monkeypatch):
    core, manager, binding, store = terminal_fixture
    await core.run_claim(await core.claim("writer"),
                         FakeExecutionBackend([FakeExecutionScenario()]), accept=accept)
    attempt = core.states["writer"].attempts[-1]
    ref = store.put_attempt(task_id=core.task_id, node_id="writer",
                            execution_id=attempt.execution_id, attempt=attempt.attempt,
                            kind=AttemptEvidenceKind.ACCEPTANCE_VERDICT,
                            payload={"accepted": True},
                            workspace_revision=attempt.post_workspace_revision)
    await core.attach_attempt_evidence(node_id="writer", evidence_ref=ref, evidence_store=store)
    async with core.state_mutex:
        core._fail_close_locked("LATE_MUTATION_POSSIBLE")
    await manager.close_dispatch()
    await manager.terminalize(quiescence_proven=False)
    from aswe.runtime import finalization
    monkeypatch.setattr(finalization, "capture_repository_state", lambda _: 1 / 0)
    outcome = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert ref in outcome.last_trusted_evidence_refs
    assert outcome.final_repository_state is None
    assert outcome.final_repository_changeset is None
    assert outcome.workspace_disposition is WorkspaceDisposition.QUARANTINED


def test_r107_task_evidence_cannot_appear_as_node_attempt_handoff(terminal_fixture):
    _, _, binding, store = terminal_fixture
    artifact = store.put_task(
        task_id="aswe-task-test", finalization_id="aswe-final-test",
        kind=TaskEvidenceKind.FINAL_REPOSITORY_CHANGESET,
        payload={"patch": "content"}, workspace_revision=None,
    )
    with pytest.raises(ValidationError):
        HandoffEvidence(repository_changeset=artifact)
