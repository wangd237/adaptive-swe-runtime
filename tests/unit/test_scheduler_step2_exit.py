"""Targeted POC-R16/R17/R20/R22/R104/R128 negative and terminal cases."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aswe.core.contracts import BackendTerminalStatus, WorkspaceAccess
from aswe.runtime.state import NodeLogicalStatus
from aswe.runtime.finalization import (
    TaskLogicalStatus, WorkspaceDisposition, finalize_task,
)
from aswe.workspace.session import WorkspaceSessionStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario, MutationEvidence
from tests.unit.test_scheduler_foundation import node, scheduler
from tests.unit.test_task_finalization import terminal_fixture


@pytest.mark.asyncio
async def test_r16_r17_retry_then_exhausted_blocks_all_descendants(tmp_path):
    core, _ = scheduler(tmp_path, node("writer"), node("verify", deps=("writer",), ordinal=1),
                        node("review", deps=("verify",), ordinal=2))
    backend = FakeExecutionBackend([
        FakeExecutionScenario(terminal_status=BackendTerminalStatus.FAILED,
                              failure_kind="EXECUTION_TRANSIENT_FAILURE",
                              mutation_evidence=MutationEvidence.PROVEN_NONE),
        FakeExecutionScenario(terminal_status=BackendTerminalStatus.FAILED,
                              failure_kind="EXECUTION_TRANSIENT_FAILURE",
                              mutation_evidence=MutationEvidence.PROVEN_NONE),
    ])
    await core.run_claim(await core.claim("writer"), backend)
    assert core.states["writer"].logical_status is NodeLogicalStatus.REMEDIATION_PENDING
    assert core.states["verify"].logical_status is NodeLogicalStatus.PENDING
    await core.run_claim(await core.claim("writer"), backend)
    assert core.states["writer"].logical_status is NodeLogicalStatus.FAILED
    assert core.states["verify"].logical_status is NodeLogicalStatus.BLOCKED
    assert core.states["review"].logical_status is NodeLogicalStatus.BLOCKED


@pytest.mark.asyncio
async def test_r22_user_cancel_joins_running_and_cancels_unstarted(tmp_path):
    core, manager = scheduler(
        tmp_path, node("reader", access=WorkspaceAccess.READ),
        node("descendant", deps=("reader",), ordinal=1),
    )
    backend = FakeExecutionBackend([FakeExecutionScenario(release_event=asyncio.Event())])
    runner = asyncio.create_task(core.run_claim(await core.claim("reader"), backend))
    for _ in range(100):
        if core.states["reader"].logical_status is NodeLogicalStatus.RUNNING:
            break
        await asyncio.sleep(0)
    assert core.states["reader"].logical_status is NodeLogicalStatus.RUNNING
    await core.cancel_task()
    await runner
    assert core.cancelled
    assert core.states["reader"].logical_status is NodeLogicalStatus.CANCELLED
    assert core.states["descendant"].logical_status is NodeLogicalStatus.CANCELLED
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN


@pytest.mark.asyncio
async def test_r128_user_cancel_without_quiescence_keeps_quarantined(tmp_path):
    core, manager = scheduler(tmp_path, node("reader", access=WorkspaceAccess.READ))
    backend = FakeExecutionBackend([
        FakeExecutionScenario(release_event=asyncio.Event(), quiescent=False),
    ])
    runner = asyncio.create_task(core.run_claim(await core.claim("reader"), backend))
    for _ in range(100):
        if core.states["reader"].logical_status is NodeLogicalStatus.RUNNING:
            break
        await asyncio.sleep(0)
    await core.cancel_task()
    await runner
    assert core.cancelled and manager.lifecycle.current.status is WorkspaceSessionStatus.QUARANTINED


@pytest.mark.asyncio
async def test_r104_single_business_root_and_ten_blocked_consequences(terminal_fixture):
    old, _, binding, store = terminal_fixture
    nodes = [node("root")]
    nodes += [node(f"down-{i}", deps=("root",) if i == 0 else (f"down-{i-1}",),
                   ordinal=i + 1) for i in range(10)]
    core, manager = scheduler(Path(binding.repository_root), *nodes)
    core.revision = old.revision
    await core.run_claim(
        await core.claim("root"),
        FakeExecutionBackend([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.FAILED,
            mutation_evidence=MutationEvidence.OBSERVED,
        )]),
    )
    assert core.failed and manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
    result = finalize_task(scheduler=core, binding=binding, evidence_store=store)
    assert result.status is TaskLogicalStatus.FAILED
    assert len(result.root_failures) == 1 and result.root_failures[0].node_id == "root"
    assert len(result.blocked_node_ids) == 10
