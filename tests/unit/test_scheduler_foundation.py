"""Scheduler Step-2 foundation: executable authority/dispatch/race regression tests.

These are deterministic and use only FakeExecutionBackend, never LLM/DeerFlow.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aswe.core.config import RuntimeBudgetConfig
from aswe.core.contracts import (
    BackendTerminalStatus, ExecutionCompleteness, HandoffEvidence, NodeHandoff,
    TaskNode, WorkKind, WorkspaceAccess, WorkspaceRevision,
)
from aswe.core.dag_fingerprint import build_task_dag
from aswe.runtime.dispatch import DispatchRevoked, NodeDispatchTicketState, TaskDispatchGateState
from aswe.runtime.scheduler import SchedulerCore
from aswe.runtime.state import NodeAttemptStatus, NodeBlockReason, NodeLogicalStatus
from aswe.workspace import WorkspaceAccessManager, WorkspaceLifecycle, WorkspaceSession, WorkspaceSessionStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario, MutationEvidence


def node(name: str, *, deps: tuple[str, ...] = (), ordinal: int = 0,
         access: WorkspaceAccess = WorkspaceAccess.WRITE,
         kind: WorkKind = WorkKind.IMPLEMENTATION) -> TaskNode:
    return TaskNode(
        id=name, objective=name, work_kind=kind,
        required_capabilities=("test",), provider_id="fake", dependencies=deps,
        workspace_access=access, planner_ordinal=ordinal, fingerprint="node-" + name,
    )


def scheduler(tmp_path: Path, *nodes: TaskNode, budget: RuntimeBudgetConfig | None = None):
    life = WorkspaceLifecycle(WorkspaceSession(
        task_id="aswe-task-test", thread_id="aswe-thread", user_id="aswe-user",
        workspace_root=str(tmp_path.resolve()), status=WorkspaceSessionStatus.BOOTSTRAPPING,
    ))
    life.mark_ready()
    life.transition(WorkspaceSessionStatus.ACTIVE)
    manager = WorkspaceAccessManager(life)
    revision = WorkspaceRevision(
        generation=0, base_sha="a" * 40, head_sha="a" * 40,
        head_matches_baseline=True, repository_state_fingerprint="base", dirty=False,
    )
    # Trusted resolver stub models a pre-verified EvidenceStore in this fake-only test.
    core = SchedulerCore(
        task_id="aswe-task-test", dag=build_task_dag(nodes),
        workspace=manager, initial_revision=revision, budget=budget,
        evidence_checker=lambda handoff: handoff.evidence == HandoffEvidence(),
    )
    return core, manager


async def accept(_result, invocation, revision):
    """Only tests supply this trusted, deterministic acceptance callback."""
    return NodeHandoff(
        source_node_id=invocation.node_id,
        source_execution_id=invocation.execution_id,
        source_attempt=invocation.attempt,
        source_provider_id="fake",
        observed_workspace_revision=revision,
        self_report="fixture only", evidence=HandoffEvidence(),
        backend_stop_reason=None,
        execution_completeness=ExecutionCompleteness.UNCAPPED,
        fingerprint=f"h-{invocation.node_id}-{invocation.attempt}",
    )


@pytest.mark.asyncio
async def test_claim_is_atomic_one_ticket_and_creates_no_attempt(tmp_path):
    core, _ = scheduler(tmp_path, node("writer"))
    ticket = await core.claim("writer")
    state = core.states["writer"]
    assert state.logical_status is NodeLogicalStatus.READY
    assert state.active_dispatch_ticket_id == ticket.ticket_id
    assert state.attempts == () and state.next_attempt == 1
    with pytest.raises(DispatchRevoked):
        await core.claim("writer")
    await core.revoke(ticket.ticket_id)
    assert core.tickets[ticket.ticket_id].state is NodeDispatchTicketState.REVOKED
    assert core.states["writer"].attempts == ()
    again = await core.claim("writer")
    assert again.ticket_id != ticket.ticket_id


@pytest.mark.asyncio
async def test_commit_allocates_attempt_only_after_lock_and_publishes_handoff(tmp_path):
    core, _ = scheduler(
        tmp_path, node("writer"), node("reviewer", deps=("writer",), ordinal=1,
                                      access=WorkspaceAccess.READ, kind=WorkKind.REVIEW),
    )
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.PENDING
    ticket = await core.claim("writer")
    invocation = await core.run_claim(ticket, FakeExecutionBackend([FakeExecutionScenario()]), accept=accept)
    assert invocation is not None
    assert invocation.attempt == 1
    assert core.tickets[ticket.ticket_id].state is NodeDispatchTicketState.FINISHED
    writer = core.states["writer"]
    assert writer.logical_status is NodeLogicalStatus.SUCCEEDED
    assert writer.accepted_attempt == 1 and writer.acceptance_epoch == 1
    assert writer.attempts[0].status is NodeAttemptStatus.ACCEPTED
    assert core.states["reviewer"].logical_status is NodeLogicalStatus.READY
    downstream = await core.claim("reviewer")
    stamps = downstream.dependency_acceptance_stamps
    assert len(stamps) == 1 and stamps[0].accepted_attempt == 1
    assert stamps[0].acceptance_epoch == 1
    assert stamps[0].handoff_fingerprint == writer.accepted_handoff.fingerprint


@pytest.mark.asyncio
async def test_clean_transient_failure_uses_same_node_for_retry(tmp_path):
    core, _ = scheduler(tmp_path, node("writer"))
    backend = FakeExecutionBackend([
        FakeExecutionScenario(terminal_status=BackendTerminalStatus.FAILED,
                              mutation_evidence=MutationEvidence.PROVEN_NONE,
                              failure_kind="EXECUTION_TRANSIENT_FAILURE"),
        FakeExecutionScenario(),
    ])
    first = await core.run_claim(await core.claim("writer"), backend)
    assert first is not None and first.attempt == 1
    assert core.states["writer"].logical_status is NodeLogicalStatus.REMEDIATION_PENDING
    second = await core.run_claim(await core.claim("writer"), backend, accept=accept)
    assert second is not None and second.attempt == 2
    assert second.attempt_kind.value == "retry"
    st = core.states["writer"]
    assert st.logical_status is NodeLogicalStatus.SUCCEEDED
    assert [a.kind.value for a in st.attempts] == ["initial", "retry"]
    assert [a.status.value for a in st.attempts] == ["failed", "accepted"]


@pytest.mark.asyncio
async def test_precommit_ticket_revoked_while_waiting_lock_has_no_attempt(tmp_path):
    core, manager = scheduler(tmp_path, node("writer", access=WorkspaceAccess.WRITE))
    backend = FakeExecutionBackend([FakeExecutionScenario()])
    async with manager.access(WorkspaceAccess.READ):
        ticket = await core.claim("writer")
        run = asyncio.create_task(core.run_claim(ticket, backend, accept=accept))
        await asyncio.sleep(0)
        await core.revoke(ticket.ticket_id)
    assert await run is None
    assert core.states["writer"].attempts == ()
    assert core.states["writer"].next_attempt == 1
    assert backend.records == []
    assert core.tickets[ticket.ticket_id].state is NodeDispatchTicketState.REVOKED


@pytest.mark.asyncio
async def test_task_failclose_revokes_unrelated_ticket_and_blocks_ready_nodes(tmp_path):
    core, manager = scheduler(tmp_path, node("writer"), node("other", ordinal=1))
    other_ticket = await core.claim("other")
    await core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.FAILED,
            mutation_evidence=MutationEvidence.OBSERVED,
        )]),
    )
    assert core.failed
    assert core.gate.state is TaskDispatchGateState.CLOSED
    assert core.gate.epoch == 1
    assert manager.dispatch_closed
    assert core.tickets[other_ticket.ticket_id].state is NodeDispatchTicketState.REVOKED
    other = core.states["other"]
    assert other.logical_status is NodeLogicalStatus.BLOCKED
    assert other.block_reason is NodeBlockReason.TASK_FAIL_CLOSED
    assert other.attempts == ()
    with pytest.raises(DispatchRevoked):
        await core.claim("other")


@pytest.mark.asyncio
async def test_backend_completed_without_acceptance_is_not_success(tmp_path):
    core, _ = scheduler(tmp_path, node("writer"))
    await core.run_claim(await core.claim("writer"), FakeExecutionBackend([FakeExecutionScenario()]))
    assert core.states["writer"].logical_status is NodeLogicalStatus.FAILED
    assert core.states["writer"].accepted_handoff is None


@pytest.mark.asyncio
async def test_workspace_revision_bumps_for_fake_observed_mutation(tmp_path):
    core, _ = scheduler(tmp_path, node("writer"))
    backend = FakeExecutionBackend([FakeExecutionScenario(
        mutation_evidence=MutationEvidence.OBSERVED,
    )])
    inv = await core.run_claim(await core.claim("writer"), backend, accept=accept)
    assert inv is not None
    assert core.revision.generation == 1
    assert core.states["writer"].accepted_handoff.observed_workspace_revision.generation == 1


@pytest.mark.asyncio
async def test_gate_close_after_claim_before_execution_creates_no_attempt(tmp_path):
    core, _ = scheduler(tmp_path, node("writer"))
    ticket = await core.claim("writer")
    await core.fail_closed("POLICY_FAILURE")
    backend = FakeExecutionBackend([FakeExecutionScenario()])
    assert await core.run_claim(ticket, backend, accept=accept) is None
    assert core.states["writer"].attempts == ()
    assert core.tickets[ticket.ticket_id].state is NodeDispatchTicketState.REVOKED


@pytest.mark.asyncio
async def test_success_callback_does_not_override_a_failed_backend(tmp_path):
    core, _ = scheduler(tmp_path, node("writer"))
    await core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario(terminal_status=BackendTerminalStatus.FAILED)]),
        accept=accept,
    )
    assert core.states["writer"].accepted_handoff is None
    assert core.states["writer"].logical_status is NodeLogicalStatus.FAILED


@pytest.mark.asyncio
async def test_concurrent_claims_linearize_at_mutex(tmp_path):
    core, _ = scheduler(tmp_path, node("writer"))
    out = await asyncio.gather(core.claim("writer"), core.claim("writer"), return_exceptions=True)
    assert sum(isinstance(x, DispatchRevoked) for x in out) == 1
    assert sum(isinstance(x, Exception) is False for x in out) == 1
    assert core.states["writer"].attempts == ()


@pytest.mark.asyncio
async def test_backend_exception_terminalizes_committed_attempt_and_quarantines(tmp_path):
    core, manager = scheduler(tmp_path, node("writer"))
    class RaisingBackend(FakeExecutionBackend):
        async def execute_prepared(self, preparation, invocation):
            raise RuntimeError("backend lost executor completion signal")

    with pytest.raises(RuntimeError, match="backend lost"):
        await core.run_claim(await core.claim("writer"), RaisingBackend())
    state = core.states["writer"]
    assert state.logical_status is NodeLogicalStatus.FAILED
    assert state.attempts[0].status is NodeAttemptStatus.FAILED
    assert state.attempts[0].failure_kind == "BACKEND_QUIESCENCE_UNKNOWN"
    assert core.failed and manager.dispatch_closed
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.QUARANTINED


@pytest.mark.asyncio
async def test_acceptance_exception_terminalizes_attempt_without_fake_success(tmp_path):
    core, manager = scheduler(tmp_path, node("writer"))

    async def failed_acceptance(_result, _invocation, _revision):
        raise ValueError("evidence store unavailable")

    with pytest.raises(ValueError, match="evidence store"):
        await core.run_claim(
            await core.claim("writer"),
            FakeExecutionBackend([FakeExecutionScenario()]),
            accept=failed_acceptance,
        )
    state = core.states["writer"]
    assert state.logical_status is NodeLogicalStatus.FAILED
    assert state.attempts[0].failure_kind == "EVIDENCE_FINALIZATION_FAILURE"
    assert state.accepted_handoff is None and core.failed
    assert manager.dispatch_closed


@pytest.mark.asyncio
async def test_unexpected_physical_read_mutation_never_unlocks_dependent(tmp_path):
    core, _ = scheduler(
        tmp_path,
        node("reader", access=WorkspaceAccess.READ, kind=WorkKind.DISCOVERY),
        node("consumer", deps=("reader",), ordinal=1),
    )
    await core.run_claim(
        await core.claim("reader"),
        FakeExecutionBackend([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.COMPLETED,
            mutation_evidence=MutationEvidence.OBSERVED,
        )]),
        accept=accept,
    )
    state = core.states["reader"]
    assert state.logical_status is NodeLogicalStatus.FAILED
    assert state.accepted_handoff is None
    assert core.failed
    assert core.states["consumer"].logical_status is NodeLogicalStatus.BLOCKED


@pytest.mark.asyncio
async def test_unquiescent_result_quarantines_even_with_completed_backend_status(tmp_path):
    core, manager = scheduler(tmp_path, node("writer"))
    await core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario(quiescent=False)]),
        accept=accept,
    )
    assert core.states["writer"].logical_status is NodeLogicalStatus.FAILED
    assert core.failed
    assert manager.lifecycle.current.status is WorkspaceSessionStatus.QUARANTINED
    with pytest.raises(RuntimeError, match="requires proven FROZEN"):
        manager.lifecycle.assert_can_finalize()


@pytest.mark.asyncio
async def test_clean_policy_denial_never_consumes_retry_budget(tmp_path):
    core, _ = scheduler(tmp_path, node("writer"))
    backend = FakeExecutionBackend([FakeExecutionScenario(
        terminal_status=BackendTerminalStatus.FAILED,
        mutation_evidence=MutationEvidence.PROVEN_NONE,
        failure_kind="POLICY_DENIED",
    )])
    await core.run_claim(await core.claim("writer"), backend)
    assert core.states["writer"].logical_status is NodeLogicalStatus.FAILED
    assert core.states["writer"].next_attempt == 2
    with pytest.raises(DispatchRevoked):
        await core.claim("writer")


@pytest.mark.asyncio
async def test_explicit_transient_with_unknown_mutation_is_not_retryable(tmp_path):
    core, _ = scheduler(tmp_path, node("writer"))
    await core.run_claim(
        await core.claim("writer"),
        FakeExecutionBackend([FakeExecutionScenario(
            terminal_status=BackendTerminalStatus.FAILED,
            mutation_evidence=MutationEvidence.UNKNOWN,
            failure_kind="EXECUTION_TRANSIENT_FAILURE",
        )]),
    )
    assert core.states["writer"].logical_status is NodeLogicalStatus.FAILED
    assert core.failed
