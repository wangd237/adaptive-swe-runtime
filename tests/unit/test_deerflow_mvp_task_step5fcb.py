"""5F-C-B actual Scheduler commit + independent canonical Python test + MVP report.

No fake success: every positive 'passed' verdict is a real Runtime-spawned
test, signed with CanonicalVerifier and validated from LocalEvidenceStore.
Strict Core continues quarantining unproven external quiescence.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from aswe.core.contracts.backend import BackendTerminalStatus, BackendExecutionPhase
from aswe.integrations.deerflow.native_execution import NativeExecutionRecord
from aswe.integrations.deerflow.mvp_task import MVPTaskRunner, MVPIntegrationError
from aswe.repository import bootstrap_repository, capture_repository_state
from aswe.evidence import LocalEvidenceStore
from aswe.runtime.canonical_verifier import CanonicalVerifier, make_command_policy
from aswe.runtime.state import NodeLogicalStatus, NodeAttemptStatus
from aswe.workspace.session import WorkspaceSessionStatus
from tests.unit.test_node_workspace_delta import git, rev
from tests.unit.test_step4_physical_p3 import build
from tests.unit.test_scheduler_foundation import scheduler
from aswe.core.contracts.task import WorkKind


@pytest.fixture
def prepared_mvp(tmp_path):
    source=tmp_path/"source"
    source.mkdir()
    git(source,"init","-b","main")
    git(source,"config","user.name","MVP")
    git(source,"config","user.email","mvp@example.invalid")
    (source/".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    (source/"calc.py").write_text("def answer():\n    return 1\n")
    tests=source/"tests"
    tests.mkdir()
    (tests/"test_calc.py").write_text(
        "import unittest\nfrom calc import answer\n"
        "class TestAnswer(unittest.TestCase):\n"
        "    def test_answer(self):\n"
        "        self.assertEqual(answer(), 42)\n"
    )
    git(source,"add","-A")
    git(source,"commit","-m","broken fixture")
    repo=bootstrap_repository(source,tmp_path/"workspace",requested_ref="main")
    _c,_p,_r,dag=build(("writer",WorkKind.IMPLEMENTATION,"code_modification"))
    core,_=scheduler(Path(repo.repository_root),*dag.nodes)
    core.revision=rev(capture_repository_state(repo))
    store=LocalEvidenceStore(tmp_path/"trusted-evidence",workspace_root=repo.repository_root)
    verifier=CanonicalVerifier(
        task_id=core.task_id,
        runtime_data_dir=tmp_path/"private-runtime",
        evidence_store=store,
        binding=repo,
    )
    policy=make_command_policy(
        "mvp-python-regression",
        (sys.executable,"-B","-m","unittest","discover","-s","tests","-q"),
        timeout_seconds=10,
    )
    return repo,core,store,verifier,policy


class NativeShapedWriter:
    """Offline native-shaped adapter; no vendor/model here.

    The physical installed-vendor model/tool loop is tested separately
    in tests/integration/test_deerflow_pinned_native_step5eb.py.
    """
    def __init__(self, repo, *, content="def answer():\n    return 42\n",
                 terminal=BackendTerminalStatus.COMPLETED):
        self.repo=repo
        self.content=content
        self.terminal=terminal
        self.committed=None

    async def prepare_node(self,node):
        return node
    async def execute_prepared(self,preparation,invocation):
        self.committed=invocation
        if self.content is not None:
            (Path(self.repo.repository_root)/"calc.py").write_text(self.content)
        return NativeExecutionRecord(
            execution_id=invocation.execution_id,node_id=invocation.node_id,
            attempt=invocation.attempt,terminal_status=self.terminal,
            execution_phase=BackendExecutionPhase.STARTED,
            quiescent=False,mutation_evidence="unknown",
            result="synthetic native output",error=None,failure_kind=None,
        )
    async def cancel_node(self,execution_id):pass
    def release_preparation(self,p):pass


@pytest.mark.asyncio
async def test_mvp_scheduler_commit_git_diff_and_runtime_canonical_green(prepared_mvp):
    repo,core,store,verifier,policy=prepared_mvp
    backend=NativeShapedWriter(repo)
    runner=MVPTaskRunner(scheduler=core,backend=backend,repository=repo,
                         verifier=verifier,policy=policy)
    report=await runner.run_node("writer")
    assert backend.committed is not None
    assert report.execution_id==backend.committed.execution_id
    assert report.native_status=="completed"
    assert report.verification_status=="passed"
    assert report.verified_returncode==0
    assert report.changed_files==("calc.py",)
    assert "return 42" in report.git_diff
    assert report.tests_passed
    assert report.canonical_receipt_ref is not None
    receipt=store.get(report.canonical_receipt_ref)
    assert receipt["status"]=="holds"
    assert receipt["source_execution_id"] if "source_execution_id" in receipt else True
    assert report.delivery_status=="tests_passed_scheduler_quarantined"
    assert report.scheduler_failed
    assert report.workspace_status=="quarantined"
    assert report.scheduler_node_status=="failed"
    assert core.states["writer"].attempts[0].status is NodeAttemptStatus.FAILED
    assert core.states["writer"].accepted_handoff is None
    with pytest.raises(MVPIntegrationError,match="MVP_TASK_REPLAY"):
        await runner.run_node("writer")


@pytest.mark.asyncio
async def test_mvp_failing_independent_test_never_becomes_pass(prepared_mvp):
    repo,core,store,verifier,policy=prepared_mvp
    backend=NativeShapedWriter(repo,content="def answer():\n    return 41\n")
    report=await MVPTaskRunner(
        scheduler=core,backend=backend,repository=repo,
        verifier=verifier,policy=policy,
    ).run_node("writer")
    assert report.verification_status=="failed"
    assert report.verified_returncode!=0
    assert report.delivery_status=="tests_failed"
    assert not report.tests_passed
    assert report.canonical_receipt_ref is not None
    assert store.get(report.canonical_receipt_ref)["status"]=="failed"


@pytest.mark.asyncio
async def test_mvp_native_failure_does_not_execute_verification(prepared_mvp):
    repo,core,store,verifier,policy=prepared_mvp
    backend=NativeShapedWriter(
        repo,content=None,terminal=BackendTerminalStatus.FAILED)
    report=await MVPTaskRunner(
        scheduler=core,backend=backend,repository=repo,
        verifier=verifier,policy=policy,
    ).run_node("writer")
    assert report.native_status=="failed"
    assert report.verification_status=="not_run"
    assert report.canonical_receipt_ref is None
    assert report.delivery_status=="unverified"
    assert report.changed_files==()
    assert report.scheduler_failed


@pytest.mark.asyncio
async def test_mvp_verification_not_trusted_if_canonical_command_unavailable(prepared_mvp):
    repo,core,store,verifier,_policy=prepared_mvp
    policy=make_command_policy(
        "mvp-missing-test",
        ("aswe-no-such-mvp-binary-19999",),timeout_seconds=1,
    )
    report=await MVPTaskRunner(
        scheduler=core,backend=NativeShapedWriter(repo),repository=repo,
        verifier=verifier,policy=policy,
    ).run_node("writer")
    assert report.verification_status=="unverified"
    assert report.verified_returncode is None
    assert not report.tests_passed


def test_mvp_rejects_foreign_task_verifier(prepared_mvp,tmp_path):
    repo,core,store,verifier,policy=prepared_mvp
    foreign=CanonicalVerifier(
        task_id="a-foreign-task",
        runtime_data_dir=tmp_path/"foreign-keys",
        evidence_store=store,
        binding=repo,
    )
    with pytest.raises(MVPIntegrationError,match="MVP_RUNTIME_AUTHORITY_MISMATCH"):
        MVPTaskRunner(
            scheduler=core,backend=NativeShapedWriter(repo),
            repository=repo,verifier=foreign,policy=policy,
        )
