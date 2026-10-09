"""Deterministic P0-D concurrency barriers: R119/R120/R121/R125/R126.

Every test drives a named scheduling boundary via Events or a held mutex.
No randomized timing, sleeps measured in wall time, or probabilistic stress.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from aswe.core.contracts import WorkKind, WorkspaceAccess
from aswe.runtime.dispatch import (
    DispatchRevoked, NodeDispatchTicketState, TaskDispatchGateState,
)
from aswe.runtime.state import NodeLogicalStatus, NodeBlockReason
from aswe.runtime.finalization import TaskLogicalStatus
from aswe.workspace.session import WorkspaceSessionStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario
from tests.unit.test_scheduler_foundation import scheduler, node, accept
from tests.unit.test_scheduler_repair import fixture


async def until(predicate, *, iterations=1200):
    """Yield at a known async barrier, never rely on a wall-clock race."""
    for _ in range(iterations):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("concurrency boundary was not reached")


@pytest.mark.asyncio
async def test_r119_waiting_and_locked_tickets_revoked_by_same_failclose_epoch(tmp_path):
    core, manager = scheduler(
        tmp_path, node("locked"), node("waiting", ordinal=1),
    )
    locked = await core.claim("locked")
    waiting = await core.claim("waiting")
    wait_backend = FakeExecutionBackend([FakeExecutionScenario()])
    await core._advance(locked.ticket_id, NodeDispatchTicketState.WAITING_WORKSPACE)
    # Hold physical WRITE for a genuine LOCKED_PRECOMMIT ticket, while
    # the other real run_claim blocks in WorkspaceAccessManager.
    async with manager.access(WorkspaceAccess.WRITE):
        await core._advance(locked.ticket_id, NodeDispatchTicketState.LOCKED_PRECOMMIT)
        contender = asyncio.create_task(core.run_claim(waiting, wait_backend, accept=accept))
        await until(lambda: core.tickets[waiting.ticket_id].state
                    is NodeDispatchTicketState.WAITING_WORKSPACE)
        gate_before = core.gate.epoch
        failing = asyncio.create_task(core.fail_closed("R119_CONTROLLED_FAILCLOSE", root_node="locked"))
        await until(lambda: core.gate.state is TaskDispatchGateState.CLOSED)
        assert core.gate.epoch == gate_before + 1
        assert core.task_logical_status is TaskLogicalStatus.FAILED
        assert core.tickets[locked.ticket_id].state is NodeDispatchTicketState.REVOKED
        assert core.tickets[waiting.ticket_id].state is NodeDispatchTicketState.REVOKED
        assert not failing.done()  # physical holder still owns Workspace.
        with pytest.raises(DispatchRevoked):
            await core._commit(locked.ticket_id, evidence_validated=True, backend=wait_backend)
        assert all(not x.attempts for x in core.states.values())
    assert await contender is None
    await failing
    assert wait_backend.records == []
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN
    assert all(s.logical_status is NodeLogicalStatus.BLOCKED for s in core.states.values())


@pytest.mark.asyncio
async def test_r120_prepare_barrier_revoked_before_workspace_or_execution(tmp_path):
    core, manager = scheduler(tmp_path, node("preparing"))
    entered = asyncio.Event()
    release = asyncio.Event()

    class DelayedPreparation(FakeExecutionBackend):
        async def prepare_node(self, task):
            entered.set()
            await release.wait()
            return await super().prepare_node(task)

    backend = DelayedPreparation([FakeExecutionScenario()])
    ticket = await core.claim("preparing")
    runner = asyncio.create_task(core.run_claim(ticket, backend, accept=accept))
    await asyncio.wait_for(entered.wait(), timeout=2)
    assert core.tickets[ticket.ticket_id].state is NodeDispatchTicketState.PREPARING
    assert backend.preparations == [] and backend.records == []
    await core.fail_closed("R120_PREPARE_REVOKED")
    release.set()
    assert await runner is None
    assert core.tickets[ticket.ticket_id].state is NodeDispatchTicketState.REVOKED
    assert core.states["preparing"].attempts == ()
    assert core.states["preparing"].next_attempt == 1
    assert backend.records == [] and manager.active_accesses == 0


@pytest.mark.asyncio
async def test_r121_blocking_dependency_evidence_io_does_not_hold_state_mutex_or_loop(tmp_path):
    core, manager = scheduler(
        tmp_path, node("writer"), node("consumer", deps=("writer",), ordinal=1,
                                      access=WorkspaceAccess.READ),
    )
    await core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario()]), accept=accept,
    )
    entered = threading.Event()
    release = threading.Event()
    checker_locks = []

    def deliberately_blocking_io(handoff):
        checker_locks.append(core.state_mutex.locked())
        entered.set()
        assert release.wait(timeout=5), "test cleanup must release evidence I/O"
        return True

    core._evidence_checker = deliberately_blocking_io
    ticket = await core.claim("consumer")
    backend = FakeExecutionBackend([FakeExecutionScenario()])
    run = asyncio.create_task(core.run_claim(ticket, backend, accept=accept))
    try:
        await asyncio.wait_for(asyncio.to_thread(entered.wait, 3), timeout=4)
        # This would deadlock if the checker ran synchronously on the event
        # loop or inside SchedulerStateMutex.
        terminal = asyncio.create_task(core.fail_closed("R121_DURING_SLOW_IO"))
        await asyncio.wait_for(_gate_closed(core), timeout=2)
        assert not core.state_mutex.locked()
        assert core.task_logical_status is TaskLogicalStatus.FAILED
    finally:
        release.set()
    assert await asyncio.wait_for(run, timeout=3) is None
    await asyncio.wait_for(terminal, timeout=3)
    assert checker_locks == [False]
    assert backend.records == []
    assert core.states["consumer"].attempts == ()
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.FROZEN


async def _gate_closed(core):
    await until(lambda: core.gate.state is TaskDispatchGateState.CLOSED)


@pytest.mark.asyncio
async def test_r125_acceptance_publication_barrier_never_exposes_partial_stamp(tmp_path):
    core, _ = scheduler(
        tmp_path, node("writer"),
        node("consumer", deps=("writer",), ordinal=1, access=WorkspaceAccess.READ),
    )
    acceptance_entered = asyncio.Event()
    release_acceptance = asyncio.Event()

    async def slow_accept(result, invocation, revision):
        acceptance_entered.set()
        await release_acceptance.wait()
        return await accept(result, invocation, revision)

    writer = asyncio.create_task(core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario()]), accept=slow_accept,
    ))
    await asyncio.wait_for(acceptance_entered.wait(), timeout=2)
    assert core.states["writer"].logical_status is NodeLogicalStatus.RUNNING
    assert core.states["consumer"].logical_status is NodeLogicalStatus.PENDING
    with pytest.raises(DispatchRevoked):
        await core.claim("consumer")
    assert core.states["consumer"].active_dispatch_ticket_id is None

    # Race claim against the release of the acceptance callback.
    racing_claim = asyncio.create_task(core.claim("consumer"))
    release_acceptance.set()
    outcome = await asyncio.gather(writer, racing_claim, return_exceptions=True)
    assert not isinstance(outcome[0], Exception)
    ticket = outcome[1]
    if isinstance(ticket, DispatchRevoked):
        ticket = await core.claim("consumer")
    else:
        assert not isinstance(ticket, Exception)
    async with core.state_mutex:
        accepted = core.states["writer"]
        assert accepted.logical_status is NodeLogicalStatus.SUCCEEDED
        assert accepted.accepted_attempt == accepted.attempts[-1].attempt == 1
        assert accepted.accepted_handoff == accepted.attempts[-1].handoff
        assert accepted.acceptance_epoch == 1
        assert core.states["consumer"].logical_status is NodeLogicalStatus.READY
        assert core.states["consumer"].active_dispatch_ticket_id == ticket.ticket_id
        stamps = ticket.dependency_acceptance_stamps
        assert len(stamps) == 1
        assert stamps[0].accepted_attempt == accepted.accepted_attempt
        assert stamps[0].acceptance_epoch == accepted.acceptance_epoch
        assert stamps[0].handoff_fingerprint == accepted.accepted_handoff.fingerprint


@pytest.mark.asyncio
async def test_r126_claim_wins_mutex_before_reopen_revokes_complete_old_epoch_ticket(tmp_path):
    core, _, store, verification_ref, _, attribution_ref = await fixture(tmp_path, consumer=True)
    previous = core.states["writer"]
    async with core.state_mutex:
        claimant = asyncio.create_task(core.claim("reviewer"))
        # Force claimant onto SchedulerStateMutex queue before reopen.
        await asyncio.sleep(0)
        reopening = asyncio.create_task(core.reopen_writer_from_verification(
            verification_ref=verification_ref, attribution_ref=attribution_ref,
            evidence_store=store,
        ))
        await asyncio.sleep(0)
    ticket, _ = await asyncio.gather(claimant, reopening)
    assert ticket.dependency_acceptance_stamps[0].acceptance_epoch == previous.acceptance_epoch == 1
    assert ticket.dependency_acceptance_stamps[0].accepted_attempt == previous.accepted_attempt
    assert ticket.dependency_acceptance_stamps[0].handoff_fingerprint == previous.accepted_handoff.fingerprint
    assert core.tickets[ticket.ticket_id].state is NodeDispatchTicketState.REVOKED
    assert core.states["writer"].accepted_handoff is None
    assert core.states["writer"].acceptance_epoch == 2
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.PENDING
    backend = FakeExecutionBackend([FakeExecutionScenario()])
    assert await core.run_claim(ticket, backend, accept=accept) is None
    assert backend.records == [] and core.states["reviewer"].attempts == ()


@pytest.mark.asyncio
async def test_r126_reopen_wins_gate_before_late_claim_cannot_revive_old_authority(tmp_path):
    core, _, store, verification_ref, _, attribution_ref = await fixture(tmp_path, consumer=True)
    first = core.states["writer"].accepted_handoff
    await core.reopen_writer_from_verification(
        verification_ref=verification_ref, attribution_ref=attribution_ref,
        evidence_store=store,
    )
    async with core.state_mutex:
        late_claim = asyncio.create_task(core.claim("reviewer"))
        await asyncio.sleep(0)
    with pytest.raises(DispatchRevoked):
        await late_claim
    assert core.states["writer"].acceptance_epoch == 2
    assert core.states["writer"].accepted_handoff is None
    assert first != core.states["writer"].accepted_handoff
    assert core.states["reviewer"].active_dispatch_ticket_id is None
    assert core.states["reviewer"].attempts == ()
