"""5F deterministic workspace evidence, same-attempt integrity, and quiescence tests.

The supervisor below is explicitly a synthetic Runtime-owned fake. It cannot
certify that a real DeerFlow subprocess, sandbox, or lease has terminated.
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from aswe.core.contracts.backend import NodeAttemptKind, NodeExecutionInvocation
from aswe.core.contracts import WorkspaceRevision
from aswe.evidence import LocalEvidenceStore
from aswe.integrations.deerflow.execution_evidence import (
    ExecutionEvidenceCollector, ExecutionEvidenceError,
    QuiescenceObservation,
)
from aswe.repository import capture_repository_state
from aswe.workspace.delta import MutationEvidence
from tests.unit.test_node_workspace_delta import repository as repository_fixture


class FakeSupervisor:
    def __init__(self, *, good=True, task_id="task5f", execution_id="exec5f",
                 fail=False, pending=False):
        self.good=good
        self.task_id=task_id
        self.execution_id=execution_id
        self.fail=fail
        self.pending=pending
        self.calls=[]

    async def inspect(self, *, task_id, execution_id):
        self.calls.append((task_id,execution_id))
        if self.fail: raise RuntimeError("CREDENTIAL_FROM_UNTRUSTED_SUPERVISOR")
        return QuiescenceObservation(
            task_id=self.task_id, execution_id=self.execution_id,
            process_tree_drained=self.good, sandbox_lease_released=self.good,
            tool_workers_drained=self.good, complete=self.good,
            provenance="runtime-sandbox-supervisor",
        )


def invocation(repo, *, revision=None):
    digest=capture_repository_state(repo)
    revision = revision or WorkspaceRevision(
        generation=0,base_sha=digest.base_sha,head_sha=digest.head_sha,
        head_matches_baseline=digest.head_matches_baseline,
        repository_state_fingerprint=digest.fingerprint,dirty=digest.dirty_vs_base,
    )
    return NodeExecutionInvocation(
        task_id="task5f",node_id="node5f",attempt=1,
        attempt_kind=NodeAttemptKind.INITIAL,
        execution_id="exec5f",run_id="run5f",
        execution_workspace_revision=revision,
        dispatch_ticket_id="ticket5f",task_dispatch_epoch=0,
        dependency_acceptance_stamps=(),dependency_context_text="",
        dependency_handoff_fingerprints=(),repair_feedback_text=None,
        context_fingerprint="dummy-fingerprint",
    )


def collector(repo,tmp_path,*,supervisor=None,max_paths=10000):
    return ExecutionEvidenceCollector(
        repository=repo,
        evidence_store=LocalEvidenceStore(tmp_path/"trusted-evidence",
                                          workspace_root=repo.repository_root),
        supervisor=supervisor,max_paths=max_paths,
    )


def guard(*,closed=True,pending=0):
    return SimpleNamespace(
        closed=closed,_pending_calls={str(i) for i in range(pending)},
        _call_lock=threading.RLock(),
        receipt_snapshot=lambda: (),
    )


@pytest.mark.asyncio
async def test_missing_external_supervisor_never_proves_quiescence(repository_fixture,tmp_path):
    repo=repository_fixture
    store=collector(repo,tmp_path)
    base=await store.begin(invocation(repo))
    result=await store.finish(base,guard=guard(),native_task_done=True)
    assert not result.quiescent
    assert result.mutation_evidence is MutationEvidence.UNKNOWN
    assert "EXTERNAL_RESOURCE_SUPERVISOR_MISSING" in result.unknown_reasons
    assert result.workspace_delta is not None
    assert store.evidence_store.get(result.evidence_ref)["quiescence_proven"] is False
    with pytest.raises(ExecutionEvidenceError,match="EVIDENCE_BASELINE_REPLAY"):
        await store.begin(invocation(repo))


@pytest.mark.asyncio
async def test_external_supervisor_fixture_plus_complete_clean_git_scans_prove_none(repository_fixture,tmp_path):
    repo=repository_fixture
    sup=FakeSupervisor()
    store=collector(repo,tmp_path,supervisor=sup)
    inv=invocation(repo)
    base=await store.begin(inv)
    result=await store.finish(base,guard=guard(),native_task_done=True)
    assert result.quiescent
    assert result.mutation_evidence is MutationEvidence.PROVEN_NONE
    assert result.workspace_delta.changed_paths == ()
    assert result.workspace_delta.repository_changed_paths == ()
    assert result.evidence_ref.source_execution_id == inv.execution_id
    assert result.tool_receipt_ref.kind.value == "tool_receipt_ledger"
    assert store.evidence_store.get(result.tool_receipt_ref)["receipts"] == []
    payload=store.evidence_store.get(result.evidence_ref)
    assert payload["authority"] == "host-snapshot-not-agent"
    assert payload["execution_id"] == inv.execution_id
    assert payload["post_repository_fingerprint"] == base.repository.fingerprint
    assert sup.calls == [("task5f","exec5f")]


@pytest.mark.asyncio
async def test_attempt_local_git_and_filesystem_mutation_is_observed(repository_fixture,tmp_path):
    repo=repository_fixture
    store=collector(repo,tmp_path,supervisor=FakeSupervisor())
    base=await store.begin(invocation(repo))
    (Path(repo.repository_root)/"changed.py").write_text("print(1)\n")
    result=await store.finish(base,guard=guard(),native_task_done=True)
    assert result.quiescent
    assert result.mutation_evidence is MutationEvidence.OBSERVED
    assert result.workspace_delta.repository_changed_paths == ("changed.py",)
    assert result.workspace_delta.changed_paths == ("changed.py",)
    assert result.workspace_delta.before_revision_generation == 0
    assert result.workspace_delta.after_revision_generation == 1
    assert store.evidence_store.get(result.evidence_ref)["mutation_evidence"] == "observed"


@pytest.mark.asyncio
async def test_ignored_cache_change_is_unknown_not_proven_none(repository_fixture,tmp_path):
    repo=repository_fixture
    store=collector(repo,tmp_path,supervisor=FakeSupervisor())
    base=await store.begin(invocation(repo))
    ignored=Path(repo.repository_root)/".cache"
    ignored.mkdir()
    (ignored/"hidden-by-scan").write_text("side effect")
    result=await store.finish(base,guard=guard(),native_task_done=True)
    assert result.quiescent
    assert result.mutation_evidence is MutationEvidence.UNKNOWN
    assert result.workspace_delta.attribution_truncated
    assert "EVIDENCE_SCANNER_INCOMPLETE" in result.unknown_reasons


@pytest.mark.asyncio
@pytest.mark.parametrize("case",["native_unjoined","pending","not_closed","wrong_execution",
                                "supervisor_denied","supervisor_failed"])
async def test_quiescence_must_be_independently_complete(repository_fixture,tmp_path,case):
    repo=repository_fixture
    sup=FakeSupervisor(
        good=case!="supervisor_denied",
        execution_id="wrong" if case=="wrong_execution" else "exec5f",
        fail=case=="supervisor_failed",
    )
    store=collector(repo,tmp_path,supervisor=sup)
    base=await store.begin(invocation(repo))
    out=await store.finish(base,guard=guard(
        closed=case!="not_closed",pending=int(case=="pending")),
        native_task_done=case!="native_unjoined")
    assert not out.quiescent
    assert out.mutation_evidence is MutationEvidence.UNKNOWN
    assert out.evidence_ref is not None
    assert out.unknown_reasons
    assert store.evidence_store.get(out.evidence_ref)["quiescence_proven"] is False


@pytest.mark.asyncio
async def test_precommit_revision_drift_fails_before_execution(repository_fixture,tmp_path):
    repo=repository_fixture
    store=collector(repo,tmp_path,supervisor=FakeSupervisor())
    inv=invocation(repo)
    (Path(repo.repository_root)/"out-of-band.txt").write_text("changed")
    with pytest.raises(ExecutionEvidenceError,match="EVIDENCE_PRECOMMIT_REVISION_DRIFT"):
        await store.begin(inv)


@pytest.mark.asyncio
async def test_failed_workspace_scan_can_never_derive_proven_none(repository_fixture,tmp_path):
    repo=repository_fixture
    store=collector(repo,tmp_path,supervisor=FakeSupervisor(),max_paths=1)
    base=await store.begin(invocation(repo))
    (Path(repo.repository_root)/"another.txt").write_text("new")
    result=await store.finish(base,guard=guard(),native_task_done=True)
    assert result.mutation_evidence is MutationEvidence.OBSERVED
    assert result.workspace_delta.attribution_truncated
    assert "EVIDENCE_SCANNER_INCOMPLETE" in result.unknown_reasons
