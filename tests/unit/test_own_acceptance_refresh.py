"""R24 — an own AcceptanceFailure has its own attested recheck authority."""
from pathlib import Path
import sys

import pytest

from aswe.core.contracts import AttemptEvidenceKind
from aswe.evidence import LocalEvidenceStore
from aswe.repository import capture_repository_state
from aswe.runtime.canonical_verifier import CanonicalVerifier, make_command_policy
from aswe.runtime.own_acceptance import (
    CanonicalAcceptanceVerdict, arm_own_acceptance_repair, build_acceptance_verdict,
)
from aswe.runtime.state import NodeLogicalStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario
from tests.unit.test_scheduler_foundation import node, scheduler, accept
from tests.unit.test_canonical_verifier import canonical_workspace


async def _own_failure(canonical_workspace):
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
    core._canonical_check_policies = {"own-acceptance": policy}
    await core.run_claim(await core.claim("writer"), FakeExecutionBackend([FakeExecutionScenario()]))
    source = core.states["writer"].attempts[-1]
    assert source.failure_kind == "ACCEPTANCE_OR_EXECUTION_FAILED"
    ref, receipt = canonical.run(
        node_id="writer", execution_id=source.execution_id, attempt=source.attempt,
        policy=policy, revision=rev,
    )
    assert receipt.status == "failed"
    verdict = build_acceptance_verdict(
        node_id="writer", execution_id=source.execution_id,
        attempt=source.attempt, revision=rev, policy=policy,
        receipt_ref=ref, status=receipt.status,
    )
    verdict_ref = store.put_attempt(
        task_id=core.task_id, node_id="writer",
        execution_id=source.execution_id, attempt=source.attempt,
        kind=AttemptEvidenceKind.ACCEPTANCE_VERDICT,
        payload=verdict, workspace_revision=rev,
    )
    await core.attach_attempt_evidence(node_id="writer", evidence_ref=verdict_ref,
                                       evidence_store=store)
    fb = await arm_own_acceptance_repair(
        core, node_id="writer", acceptance_ref=verdict_ref, evidence_store=store,
    )
    assert fb.acceptance_verdict == verdict_ref
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
    core, binding, store, previous = await _own_failure(canonical_workspace)
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
    assert new_verdict.observed_workspace_revision.generation == 1
    assert new_verdict.status == "failed"
    assert new_verdict.canonical_proof != previous.receipt_refs[0].ledger_evidence
    assert core.states["writer"].accepted_attempt == 2


@pytest.mark.asyncio
async def test_r24_own_acceptance_refresh_holds_blocks_redundant_repair(canonical_workspace):
    core, binding, store, previous = await _own_failure(canonical_workspace)
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
    assert newer.observed_workspace_revision.generation == 1
