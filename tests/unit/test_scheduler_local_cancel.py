"""Local-node cancellation is not task-wide cancellation (POC-R21)."""
from __future__ import annotations

import asyncio
import pytest

from aswe.core.contracts import WorkspaceAccess
from aswe.runtime.dispatch import DispatchRevoked, NodeDispatchTicketState, TaskDispatchGateState
from aswe.runtime.state import NodeAttemptStatus, NodeLogicalStatus
from aswe.workspace.session import WorkspaceSessionStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario, MutationEvidence
from tests.unit.test_scheduler_foundation import accept, node, scheduler


@pytest.mark.asyncio
async def test_r21_local_precommit_cancel_blocks_descendants_not_unrelated(tmp_path):
    core, _ = scheduler(
        tmp_path, node("target"), node("child", deps=("target",), ordinal=1),
        node("independent", ordinal=2),
    )
    ticket = await core.claim("target")
    await core.cancel_node("target")
    assert core.tickets[ticket.ticket_id].state is NodeDispatchTicketState.REVOKED
    assert core.states["target"].logical_status is NodeLogicalStatus.CANCELLED
    assert core.states["target"].attempts == ()
    assert core.states["child"].logical_status is NodeLogicalStatus.BLOCKED
    assert core.states["independent"].logical_status is NodeLogicalStatus.READY
    assert core.gate.state is TaskDispatchGateState.OPEN
    assert not core.cancelled and not core.failed
    backend = FakeExecutionBackend([FakeExecutionScenario()])
    assert await core.run_claim(ticket, backend, accept=accept) is None
    assert not backend.records
    with pytest.raises(DispatchRevoked):
        await core.claim("child")
    await core.run_claim(await core.claim("independent"), backend, accept=accept)
    assert core.states["independent"].logical_status is NodeLogicalStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_r21_running_local_cancel_joins_without_task_cancel(tmp_path):
    core, manager = scheduler(
        tmp_path, node("target", access=WorkspaceAccess.READ),
        node("child", deps=("target",), ordinal=1),
        node("independent", ordinal=2, access=WorkspaceAccess.READ),
    )
    backend = FakeExecutionBackend([FakeExecutionScenario(release_event=asyncio.Event())])
    runner = asyncio.create_task(core.run_claim(await core.claim("target"), backend, accept=accept))
    for _ in range(100):
        if core.states["target"].logical_status is NodeLogicalStatus.RUNNING:
            break
        await asyncio.sleep(0)
    assert core.states["target"].logical_status is NodeLogicalStatus.RUNNING
    await core.cancel_node("target")
    await runner
    state = core.states["target"]
    assert state.logical_status is NodeLogicalStatus.CANCELLED
    assert state.attempts[0].status is NodeAttemptStatus.CANCELLED
    assert state.accepted_handoff is None
    assert core.states["child"].logical_status is NodeLogicalStatus.BLOCKED
    assert core.states["independent"].logical_status is NodeLogicalStatus.READY
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.ACTIVE
    assert not core.cancelled and not core.failed


@pytest.mark.asyncio
async def test_r21_dirty_local_cancel_fails_closed_instead_of_reusing_workspace(tmp_path):
    core, manager = scheduler(
        tmp_path, node("target"), node("unrelated", ordinal=1),
    )
    backend = FakeExecutionBackend([FakeExecutionScenario(
        release_event=asyncio.Event(), mutation_evidence=MutationEvidence.OBSERVED,
    )])
    runner = asyncio.create_task(core.run_claim(await core.claim("target"), backend))
    for _ in range(100):
        if core.states["target"].logical_status is NodeLogicalStatus.RUNNING:
            break
        await asyncio.sleep(0)
    assert core.states["target"].logical_status is NodeLogicalStatus.RUNNING
    await core.cancel_node("target")
    await runner
    assert core.states["target"].logical_status is NodeLogicalStatus.CANCELLED
    assert core.states["unrelated"].logical_status is NodeLogicalStatus.BLOCKED
    assert core.failed and not core.cancelled
    assert manager.dispatch_closed
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN


@pytest.mark.asyncio
async def test_r21_terminal_success_cannot_be_retroactively_cancelled(tmp_path):
    core, _ = scheduler(tmp_path, node("target"))
    await core.run_claim(
        await core.claim("target"),
        FakeExecutionBackend([FakeExecutionScenario()]), accept=accept,
    )
    with pytest.raises(DispatchRevoked, match="already terminal"):
        await core.cancel_node("target")
    assert core.states["target"].logical_status is NodeLogicalStatus.SUCCEEDED
