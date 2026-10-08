"""Task-wide committed cancel/join and workspace quiescence proofs."""
from __future__ import annotations

import asyncio
import pytest

from aswe.core.contracts import BackendTerminalStatus, WorkspaceAccess
from aswe.runtime.state import NodeLogicalStatus
from aswe.workspace.session import WorkspaceSessionStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario
from tests.unit.test_scheduler_foundation import node, scheduler, accept


async def running_reader(core, backend, node_id):
    invocation_task = asyncio.create_task(
        core.run_claim(await core.claim(node_id), backend, accept=accept)
    )
    for _ in range(120):
        if core.states[node_id].logical_status is NodeLogicalStatus.RUNNING:
            return invocation_task
        await asyncio.sleep(0)
    raise AssertionError(f"{node_id} never committed")


@pytest.mark.asyncio
async def test_failclose_cancels_and_joins_both_committed_readers(tmp_path):
    core, manager = scheduler(
        tmp_path, node("reader-a", access=WorkspaceAccess.READ),
        node("reader-b", ordinal=1, access=WorkspaceAccess.READ),
    )
    a_backend = FakeExecutionBackend([FakeExecutionScenario(release_event=asyncio.Event())])
    b_backend = FakeExecutionBackend([FakeExecutionScenario(release_event=asyncio.Event())])
    a = await running_reader(core, a_backend, "reader-a")
    b = await running_reader(core, b_backend, "reader-b")
    assert manager.active_accesses == 2

    await core.fail_closed("TASK_POLICY_FAIL_CLOSE", root_node="reader-a")
    await asyncio.gather(a, b)
    assert core.failed and manager.dispatch_closed
    assert manager.active_accesses == 0
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
    assert len(a_backend.records) == len(b_backend.records) == 1
    assert a_backend.records[0].terminal_status is BackendTerminalStatus.CANCELLED
    assert b_backend.records[0].terminal_status is BackendTerminalStatus.CANCELLED
    assert all(
        core.states[n].attempts[0].status.value == "cancelled"
        for n in ("reader-a", "reader-b")
    )


@pytest.mark.asyncio
async def test_cancel_acknowledgement_without_join_forces_quarantine(tmp_path):
    core, manager = scheduler(tmp_path, node("reader", access=WorkspaceAccess.READ))
    release = asyncio.Event()

    class AckOnlyBackend(FakeExecutionBackend):
        async def cancel_node(self, execution_id):
            # Request acknowledged, but underlying execution still holds lock.
            return None

    backend = AckOnlyBackend([FakeExecutionScenario(release_event=release)])
    runner = await running_reader(core, backend, "reader")
    await core.drain_committed(timeout=0.02)
    # A task-wide fail-close must be established separately from this low-level drain.
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.QUARANTINED
    assert not runner.done()
    assert manager.active_accesses == 1
    release.set()
    # The late backend completion must not reopen task dispatch.
    await runner
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.QUARANTINED
    assert manager.dispatch_closed


@pytest.mark.asyncio
async def test_false_quiescence_flag_forces_quarantine_after_backend_return(tmp_path):
    core, manager = scheduler(tmp_path, node("reader", access=WorkspaceAccess.READ))
    task = await running_reader(
        core, FakeExecutionBackend([FakeExecutionScenario(
            release_event=asyncio.Event(), quiescent=False
        )]), "reader"
    )
    await core.fail_closed("FAIL_CLOSE", root_node="reader")
    await task
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.QUARANTINED


@pytest.mark.asyncio
async def test_idempotent_failclose_after_proven_drain(tmp_path):
    core, manager = scheduler(tmp_path, node("writer"))
    await core.fail_closed("FIRST")
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
    await core.fail_closed("SECOND")
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
    assert core.failure_kinds == ["FIRST"]


@pytest.mark.asyncio
async def test_cancelled_drain_coordinator_quarantines_instead_of_assuming_join(tmp_path):
    core, manager = scheduler(tmp_path, node("reader", access=WorkspaceAccess.READ))
    execution_release = asyncio.Event()
    cancel_entered = asyncio.Event()
    cancel_release = asyncio.Event()

    class SlowCancellationBackend(FakeExecutionBackend):
        async def cancel_node(self, execution_id):
            cancel_entered.set()
            await cancel_release.wait()
            await super().cancel_node(execution_id)

    backend = SlowCancellationBackend([
        FakeExecutionScenario(release_event=execution_release)
    ])
    runner = await running_reader(core, backend, "reader")
    drainer = asyncio.create_task(core.drain_committed(timeout=1.0))
    await asyncio.wait_for(cancel_entered.wait(), 1)
    drainer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await drainer

    assert core.failed and manager.dispatch_closed
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.QUARANTINED
    assert not runner.done()
    execution_release.set()
    await runner
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.QUARANTINED
