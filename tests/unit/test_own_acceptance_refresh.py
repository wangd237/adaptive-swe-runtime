"""R24: only attested acceptance failure of observed-mutating WRITE may repair."""
from pathlib import Path
import sys

import pytest

from aswe.core.contracts import AttemptEvidenceKind, BackendTerminalStatus
from aswe.repository import capture_repository_state
from aswe.runtime.canonical_verifier import CanonicalVerifier, make_command_policy
from aswe.runtime.own_acceptance import CanonicalAcceptanceVerdict
from aswe.runtime.state import NodeLogicalStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario, MutationEvidence
from tests.unit.test_scheduler_foundation import node, scheduler, accept
from tests.unit.test_canonical_verifier import canonical_workspace


async def _mutated_own_failure(canonical_workspace):
    binding, rev, store, _ = canonical_workspace
    core, _ = scheduler(Path(binding.repository_root), node("writer"))
    core.revision = rev
    canonical = CanonicalVerifier(
        task_id=core.task_id, runtime_data_dir=store.root,
        evidence_store=store, binding=binding,
    )
    core._canonical_verifier = canonical
    core._test_only_allow_fixture_receipts = False
    policy = make_command_policy("own-acceptance", (sys.executable, "-c",
        "from pathlib import Path; import sys; "
        "sys.exit(0 if 'ACCEPTED' in Path('source.py').read_text() else 1)"))
    core._canonical_acceptance_policies = {"writer": policy}

    class MutatingWriter(FakeExecutionBackend):
        async def execute_prepared(self, preparation, invocation):
            Path(binding.repository_root, "source.py").write_text("CHANGED = True\n")
            return await super().execute_prepared(preparation, invocation)

    async def failed_acceptance(_result, _invocation, _revision):
        return None

    await core.run_claim(
        await core.claim("writer"), MutatingWriter([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.COMPLETED,
            mutation_evidence=MutationEvidence.OBSERVED,
        )]), accept=failed_acceptance,
    )
    assert not core.failed
    assert core.states["writer"].logical_status is NodeLogicalStatus.REMEDIATION_PENDING
    assert core.states["writer"].repair_count == 1
    fb = core._typed_repair_feedback["writer"]
    assert fb.trigger_kind.value == "node_acceptance"
    assert fb.observed_workspace_revision.generation == 1
    assert fb.acceptance_verdict is not None
    assert core.states["writer"].attempts[0].status.value == "failed"
    return core, binding, store, fb


def _change(core, binding, code):
    Path(binding.repository_root, "source.py").write_text(code)
    current = capture_repository_state(binding)
    core.revision = core.revision.model_copy(update={
        "generation": core.revision.generation + 1,
        "repository_state_fingerprint": current.fingerprint,
        "dirty": current.dirty_vs_base,
    })


@pytest.mark.asyncio
async def test_r24_stale_own_acceptance_failure_reruns_new_attested_check(canonical_workspace):
    core, binding, store, previous = await _mutated_own_failure(canonical_workspace)
    _change(core, binding, "BROKEN = True\n")
    backend = FakeExecutionBackend([FakeExecutionScenario()])
    invocation = await core.run_claim(await core.claim("writer"), backend, accept=accept)
    assert invocation is not None and invocation.attempt_kind.value == "repair"
    assert len(backend.records) == 1
    old_attempt = core.states["writer"].attempts[0]
    verdict_refs = [r for r in old_attempt.evidence_refs
                    if r.kind is AttemptEvidenceKind.ACCEPTANCE_VERDICT]
    assert len(verdict_refs) == 2
    assert verdict_refs[1] != previous.acceptance_verdict
    new_verdict = CanonicalAcceptanceVerdict.model_validate(store.get(verdict_refs[1]))
    assert new_verdict.observed_workspace_revision.generation == 2
    assert new_verdict.status == "failed"
    assert new_verdict.canonical_proof != previous.receipt_refs[0].ledger_evidence
    assert core.states["writer"].accepted_attempt == 2


@pytest.mark.asyncio
async def test_r24_own_acceptance_refresh_holds_blocks_redundant_repair(canonical_workspace):
    core, binding, store, previous = await _mutated_own_failure(canonical_workspace)
    _change(core, binding, "ACCEPTED = True\n")
    backend = FakeExecutionBackend([FakeExecutionScenario()])
    result = await core.run_claim(await core.claim("writer"), backend, accept=accept)
    assert result is None
    assert backend.records == []
    assert len(core.states["writer"].attempts) == 1
    assert core.failed and "REPAIR_SUPERSEDED_REPLAN_REQUIRED" in core.failure_kinds
    assert "writer" not in core._typed_repair_feedback
    verdict_refs = [r for r in core.states["writer"].attempts[0].evidence_refs
                    if r.kind is AttemptEvidenceKind.ACCEPTANCE_VERDICT]
    assert len(verdict_refs) == 2
    newer = CanonicalAcceptanceVerdict.model_validate(store.get(verdict_refs[1]))
    assert newer.status == "holds"
    assert newer.observed_workspace_revision.generation == 2
