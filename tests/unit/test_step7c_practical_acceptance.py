"""Step 7C-C practical mode: actual Scheduler acceptance, not mocked status.

The test intentionally uses offline tool execution and canonical Python to
exercise runtime-owned artifacts. Pinned vendor + real Docker acceptance is a
separate physical integration gate; no fake is presented as that proof.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from aswe.core.contracts.backend import (
    BackendExecutionPhase, BackendTerminalStatus,
)
from aswe.evidence import LocalEvidenceStore
from aswe.integrations.deerflow.controlled_swe import (
    ControlledSWEWorkspace, DockerCommandBackend,
)
from aswe.integrations.deerflow.execution_evidence import ExecutionEvidenceCollector
from aswe.integrations.deerflow.mvp_task import MVPTaskRunner, MVPIntegrationError
from aswe.integrations.deerflow.native_execution import NativeExecutionRecord
from aswe.integrations.deerflow.practical_acceptance import verify_practical_handoff
from aswe.integrations.deerflow.tool_guard import BoundToolView, ToolCallGuard
from aswe.runtime.state import NodeLogicalStatus
from tests.unit.test_deerflow_controlled_swe_step5fc import policy as writer_policy
from tests.unit.test_deerflow_mvp_task_step5fcb import prepared_mvp


class BoundedWriter:
    def __init__(self, repo, evidence_store, *, replacement="42",
                 active=False, corrupt=False, leave_guard_open=False):
        self.repo=repo
        self.replacement=replacement
        self.active=active
        self.corrupt=corrupt
        self.leave_guard_open=leave_guard_open
        self.evidence_collector=ExecutionEvidenceCollector(
            repository=repo, evidence_store=evidence_store,
            acceptance_profile="practical",
        )
        self.docker=DockerCommandBackend(
            workspace_root=Path(repo.repository_root),
            image="python:3.12-slim@sha256:" + "0"*64,
        )

    async def prepare_node(self, node):
        return node

    async def execute_prepared(self, preparation, inv):
        baseline=await self.evidence_collector.begin(inv)
        policy=writer_policy(tools=("read_file", "str_replace"))
        assert policy.node_id == inv.node_id
        workspace=ControlledSWEWorkspace(
            invocation=inv, policy=policy,
            root=self.repo.repository_root, command_backend=self.docker,
        )
        tools=(SimpleNamespace(name="read_file"),
               SimpleNamespace(name="str_replace"))
        view=BoundToolView(
            names=("read_file", "str_replace"),
            objects=tools, object_seals=((), ()),
        )
        guard=ToolCallGuard(
            invocation=inv, resources=SimpleNamespace(
                policy_fingerprint=policy.fingerprint, node_id=inv.node_id,
            ), view=view, principal=SimpleNamespace(user_id="host"),
            provider=None, request_factory=lambda **kw: kw,
            auth_enabled=False, policy=policy,
            execution_live_checker=lambda _: True,
            swe_runtime=workspace,
        )
        await workspace.read_file(path="calc.py")
        await workspace.str_replace(
            path="calc.py", old_str="return 1",
            new_str="return " + self.replacement,
        )
        if not self.leave_guard_open:
            guard.close()
        if self.active:
            self.docker._active_commands=1
        if self.corrupt:
            self.docker._cleanup_uncertain=True
        proof=await self.evidence_collector.finish(
            baseline, guard=guard, native_task_done=True,
        )
        return NativeExecutionRecord(
            execution_id=inv.execution_id, node_id=inv.node_id,
            attempt=inv.attempt,
            terminal_status=BackendTerminalStatus.COMPLETED,
            execution_phase=BackendExecutionPhase.STARTED,
            mutation_evidence=proof.mutation_evidence.value,
            quiescent=proof.quiescent, result="host-test", error=None,
            failure_kind=None, workspace_evidence_ref=proof.evidence_ref,
            tool_receipt_ref=proof.tool_receipt_ref,
        )

    async def cancel_node(self, execution_id):
        pass

    def release_preparation(self, p):
        pass


async def run_practical(prepared, *, replacement="42", **kwargs):
    repo, core, evidence, verifier, policy = prepared
    # The production developer_entry wires both in the constructor.
    core._canonical_verifier=verifier
    core._evidence_checker=lambda handoff: verify_practical_handoff(
        handoff, evidence_store=evidence)
    backend=BoundedWriter(repo, evidence, replacement=replacement, **kwargs)
    runner=MVPTaskRunner(
        scheduler=core, backend=backend, repository=repo, verifier=verifier,
        policy=policy, execution_evidence_store=evidence,
        acceptance_profile="practical",
    )
    report=await runner.run_node("writer")
    return report, core, backend


@pytest.mark.asyncio
async def test_runtime_handoff_is_accepted_with_correct_patch(prepared_mvp):
    report, core, backend = await run_practical(prepared_mvp)
    assert report.acceptance_profile == "practical"
    assert report.verification_status == "passed"
    assert report.scheduler_node_status == "succeeded"
    assert not report.scheduler_failed
    assert report.quiescence_proven
    assert report.delivery_status == "tests_passed_practical_handoff"
    handoff=core.states["writer"].accepted_handoff
    assert handoff is not None
    assert handoff.fingerprint == report.accepted_handoff_fingerprint
    assert handoff.source_execution_id == report.execution_id
    assert verify_practical_handoff(handoff,evidence_store=prepared_mvp[2])
    assert handoff.evidence.workspace_changeset is not None
    assert core.revision.repository_state_fingerprint == report.workspace_state_fingerprint


@pytest.mark.asyncio
async def test_coder_handoff_survives_failed_precheck_for_independent_tester(prepared_mvp):
    report, core, _ = await run_practical(prepared_mvp, replacement="41")
    assert report.verification_status == "failed"
    assert report.scheduler_node_status == "succeeded"
    assert report.delivery_status == "coder_practical_handoff_test_failed"
    assert core.states["writer"].accepted_handoff is not None
    assert core.states["writer"].logical_status is NodeLogicalStatus.SUCCEEDED


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe", [
    {"active": True},
    {"corrupt": True},
    {"leave_guard_open": True},
])
async def test_unsafe_resource_lifecycle_never_yields_handoff(prepared_mvp, unsafe):
    report, core, _ = await run_practical(prepared_mvp, **unsafe)
    assert not report.quiescence_proven
    assert report.accepted_handoff_fingerprint is None
    assert core.states["writer"].accepted_handoff is None
    assert report.scheduler_node_status == "failed"
    assert core.failed


@pytest.mark.asyncio
async def test_strict_mode_remains_quarantined(prepared_mvp):
    from tests.unit.test_deerflow_mvp_task_step5fcb import NativeShapedWriter
    repo, core, evidence, verifier, policy=prepared_mvp
    report=await MVPTaskRunner(
        scheduler=core, backend=NativeShapedWriter(repo),
        repository=repo, verifier=verifier, policy=policy,
    ).run_node("writer")
    assert report.acceptance_profile == "strict"
    assert report.accepted_handoff_fingerprint is None
    assert report.scheduler_node_status == "failed"


def test_practical_configuration_without_evidence_is_refused(prepared_mvp):
    repo, core, evidence, verifier, policy=prepared_mvp
    with pytest.raises(MVPIntegrationError,match="MVP_PRACTICAL_PROOF_NOT_CONFIGURED"):
        MVPTaskRunner(
            scheduler=core, backend=object(), repository=repo,
            verifier=verifier, policy=policy,
            acceptance_profile="practical",
        )
