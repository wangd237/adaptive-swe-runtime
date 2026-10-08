"""Deterministic Scheduler foundation. No DeerFlow or LLM in control decisions.

Ownership:
  - immutable TaskDAG is compile output;
  - NodeRuntimeState snapshots and tickets belong to SchedulerStateMutex;
  - physical WorkspaceAccess is held before the final dispatch commit;
  - accepted NodeHandoffs MUST be supplied by a trusted acceptance/evidence layer.

Step-2 foundation only: the verified RepairAttributionResolver and TaskResult
finalizer will be wired in subsequent commits of this same coding step.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Awaitable
from typing import Any, Protocol

from aswe.core.config import RuntimeBudgetConfig
from aswe.core.contracts import (
    BackendTerminalStatus, DependencyAcceptanceStamp, NodeAttemptKind,
    NodeExecutionInvocation, NodeHandoff, TaskDAG, WorkspaceRevision,
)
from aswe.core.ids import new_execution_id, new_run_id, new_safe_id
from aswe.runtime.dispatch import (
    DispatchRevoked, NodeDispatchTicket, NodeDispatchTicketState,
    TaskDispatchGate, TaskDispatchGateState,
)
from aswe.runtime.state import (
    NodeAttemptRecord, NodeAttemptStatus, NodeBlockReason,
    NodeLogicalStatus, NodeRuntimeState,
)
from aswe.workspace.access import WorkspaceAccessManager, WorkspaceClosedError
from aswe.workspace.delta import MutationEvidence


class FakeBackendPort(Protocol):
    """Narrow fake-only adapter. Real ExecutionBackend seam belongs to Step 5."""
    async def prepare_node(self, node: Any) -> Any: ...
    async def execute_prepared(self, preparation: Any, invocation: NodeExecutionInvocation) -> Any: ...
    async def cancel_node(self, execution_id: str) -> None: ...


Acceptance = Callable[[Any, NodeExecutionInvocation, WorkspaceRevision], Awaitable[NodeHandoff | None]]
EvidenceChecker = Callable[[NodeHandoff], bool]


class SchedulerCore:
    """Single-task deterministic state engine.

    Never await I/O inside state_mutex. Public snapshots are FrozenModels.
    A ready claim and all its direct-dependency stamps are captured atomically.
    A ticket is not an attempt until _commit() while WorkspaceAccess is held.
    """

    def __init__(
        self, *, task_id: str, dag: TaskDAG, workspace: WorkspaceAccessManager,
        initial_revision: WorkspaceRevision, evidence_checker: EvidenceChecker,
        budget: RuntimeBudgetConfig | None = None,
    ) -> None:
        if not task_id or not callable(evidence_checker):
            raise ValueError("task identity and trusted evidence checker required")
        self.task_id = task_id
        self.dag = dag
        self.nodes = {n.id: n for n in dag.nodes}
        self.workspace = workspace
        self.budget = budget or RuntimeBudgetConfig()
        self.state_mutex = asyncio.Lock()  # SchedulerStateMutex
        self.gate = TaskDispatchGate()
        self.revision = initial_revision
        self._evidence_checker = evidence_checker
        self.states = {
            node_id: NodeRuntimeState(
                node_id=node_id, logical_status=NodeLogicalStatus.PENDING,
                next_attempt=1, repair_count=0,
            ) for node_id in self.nodes
        }
        self.tickets: dict[str, NodeDispatchTicket] = {}
        self.failure_kinds: list[str] = []
        self._task_failed = False
        self._recompute_locked()

    def _dependencies_locked(self, node_id: str) -> tuple[DependencyAcceptanceStamp, ...] | None:
        stamps: list[DependencyAcceptanceStamp] = []
        for upstream_id in self.nodes[node_id].dependencies:
            state = self.states[upstream_id]
            h = state.accepted_handoff
            if state.logical_status is not NodeLogicalStatus.SUCCEEDED or (
                state.accepted_attempt is None or h is None
            ):
                return None
            stamps.append(DependencyAcceptanceStamp(
                upstream_node_id=upstream_id,
                acceptance_epoch=state.acceptance_epoch,
                accepted_attempt=state.accepted_attempt,
                handoff_fingerprint=h.fingerprint,
            ))
        return tuple(stamps)

    def _recompute_locked(self) -> None:
        """READY is a property of current accepted authority, not old attempt history."""
        if self.gate.state is TaskDispatchGateState.CLOSED:
            return
        for node_id in self.dag.topological_order:
            state = self.states[node_id]
            if state.logical_status not in (NodeLogicalStatus.PENDING, NodeLogicalStatus.READY):
                continue
            upstream = [self.states[d] for d in self.nodes[node_id].dependencies]
            failures = [s.node_id for s in upstream if s.logical_status in (
                NodeLogicalStatus.FAILED, NodeLogicalStatus.BLOCKED, NodeLogicalStatus.CANCELLED
            )]
            if failures:
                state = state.model_copy(update={
                    "logical_status": NodeLogicalStatus.BLOCKED,
                    "block_reason": NodeBlockReason.UPSTREAM_FAILURE,
                    "blocked_by": tuple(failures),
                })
            else:
                ready = self._dependencies_locked(node_id) is not None
                state = state.model_copy(update={
                    "logical_status": NodeLogicalStatus.READY if ready else NodeLogicalStatus.PENDING,
                })
            self.states[node_id] = state

    async def claim(self, node_id: str) -> NodeDispatchTicket:
        """One short atomic READY + stamps + ticket claim."""
        async with self.state_mutex:
            if self.gate.state is not TaskDispatchGateState.OPEN:
                raise DispatchRevoked("task dispatch gate closed")
            if node_id not in self.states:
                raise KeyError(node_id)
            self._recompute_locked()
            state = self.states[node_id]
            if state.logical_status not in (NodeLogicalStatus.READY, NodeLogicalStatus.REMEDIATION_PENDING) or state.active_dispatch_ticket_id:
                raise DispatchRevoked("node not READY or already claimed")
            stamps = self._dependencies_locked(node_id)
            if stamps is None:
                raise DispatchRevoked("dependency authority unavailable")
            ticket = NodeDispatchTicket(
                ticket_id=new_safe_id("ticket"), node_id=node_id,
                task_dispatch_epoch=self.gate.epoch,
                dependency_acceptance_stamps=stamps,
                state=NodeDispatchTicketState.PREPARING,
            )
            self.tickets[ticket.ticket_id] = ticket
            self.states[node_id] = state.model_copy(update={
                "active_dispatch_ticket_id": ticket.ticket_id,
            })
            return ticket

    async def _advance(self, ticket_id: str, stage: NodeDispatchTicketState) -> NodeDispatchTicket:
        async with self.state_mutex:
            ticket = self.tickets[ticket_id]
            if ticket.state in (NodeDispatchTicketState.REVOKED, NodeDispatchTicketState.FINISHED):
                raise DispatchRevoked("ticket revoked or finished")
            transitions = {
                NodeDispatchTicketState.PREPARING: NodeDispatchTicketState.WAITING_WORKSPACE,
                NodeDispatchTicketState.WAITING_WORKSPACE: NodeDispatchTicketState.LOCKED_PRECOMMIT,
            }
            if transitions.get(ticket.state) is not stage:
                raise ValueError("invalid pre-commit ticket stage")
            ticket = ticket.model_copy(update={"state": stage})
            self.tickets[ticket_id] = ticket
            return ticket

    async def revoke(self, ticket_id: str) -> None:
        """Revocation creates no attempt and consumes no execution budget."""
        async with self.state_mutex:
            ticket = self.tickets[ticket_id]
            if ticket.state in (NodeDispatchTicketState.COMMITTED, NodeDispatchTicketState.FINISHED):
                raise DispatchRevoked("a committed attempt cannot be revoked")
            if ticket.state is NodeDispatchTicketState.REVOKED:
                return
            self.tickets[ticket_id] = ticket.model_copy(update={
                "state": NodeDispatchTicketState.REVOKED
            })
            node_state = self.states[ticket.node_id]
            if node_state.active_dispatch_ticket_id == ticket_id:
                self.states[ticket.node_id] = node_state.model_copy(update={
                    "active_dispatch_ticket_id": None,
                })
            self._recompute_locked()

    def _is_current_locked(self, ticket: NodeDispatchTicket) -> bool:
        state = self.states[ticket.node_id]
        return (
            self.gate.state is TaskDispatchGateState.OPEN
            and self.gate.epoch == ticket.task_dispatch_epoch
            and state.logical_status in (NodeLogicalStatus.READY, NodeLogicalStatus.REMEDIATION_PENDING)
            and state.active_dispatch_ticket_id == ticket.ticket_id
            and ticket.state is NodeDispatchTicketState.LOCKED_PRECOMMIT
            and self._dependencies_locked(ticket.node_id) == ticket.dependency_acceptance_stamps
        )

    async def _commit(
        self, ticket_id: str, *, evidence_validated: bool,
    ) -> NodeExecutionInvocation:
        """Linearization point; call only AFTER physical WorkspaceAccess granted."""
        async with self.state_mutex:
            ticket = self.tickets[ticket_id]
            if not evidence_validated or not self._is_current_locked(ticket):
                raise DispatchRevoked("stale ticket, dependency evidence or task gate")
            state = self.states[ticket.node_id]
            attempt = state.next_attempt
            invocation = NodeExecutionInvocation(
                task_id=self.task_id, node_id=ticket.node_id,
                attempt=attempt,
                attempt_kind=NodeAttemptKind.INITIAL if attempt == 1 else NodeAttemptKind.RETRY,
                execution_id=new_execution_id(), run_id=new_run_id(),
                execution_workspace_revision=self.revision,
                dispatch_ticket_id=ticket_id, task_dispatch_epoch=self.gate.epoch,
                dependency_acceptance_stamps=ticket.dependency_acceptance_stamps,
                dependency_context_text="",
                dependency_handoff_fingerprints=tuple(
                    s.handoff_fingerprint for s in ticket.dependency_acceptance_stamps
                ),
                repair_feedback_text=None,
                context_fingerprint="step2-fake-backend-context",
            )
            running = NodeAttemptRecord(
                node_id=ticket.node_id, attempt=attempt, kind=invocation.attempt_kind,
                execution_id=invocation.execution_id,
                pre_workspace_revision=self.revision, post_workspace_revision=None,
                status=NodeAttemptStatus.RUNNING, failure_kind=None,
            )
            self.states[ticket.node_id] = state.model_copy(update={
                "logical_status": NodeLogicalStatus.RUNNING,
                "active_dispatch_ticket_id": None,
                "next_attempt": attempt + 1,
                "attempts": state.attempts + (running,),
            })
            self.tickets[ticket_id] = ticket.model_copy(update={
                "state": NodeDispatchTicketState.COMMITTED,
            })
            return invocation

    async def _finish(self, invocation: NodeExecutionInvocation, result: Any,
                      handoff: NodeHandoff | None) -> None:
        close_dispatch = False
        async with self.state_mutex:
            state = self.states[invocation.node_id]
            if state.logical_status is not NodeLogicalStatus.RUNNING:
                raise RuntimeError("attempt not RUNNING")
            running = state.attempts[-1]
            if running.execution_id != invocation.execution_id:
                raise RuntimeError("wrong attempt execution identity")
            if not getattr(result, "quiescent", False):
                mutation = MutationEvidence.UNKNOWN
            else:
                mutation = MutationEvidence(getattr(result, "mutation_evidence", "unknown"))
            post = self.revision
            if mutation is not MutationEvidence.PROVEN_NONE:
                post = post.model_copy(update={"generation": post.generation + 1})
            self.revision = post
            success = (
                self.gate.state is TaskDispatchGateState.OPEN
                and getattr(result, "terminal_status", None) is BackendTerminalStatus.COMPLETED
                and getattr(result, "quiescent", False)
                and handoff is not None
                and handoff.source_node_id == invocation.node_id
                and handoff.source_execution_id == invocation.execution_id
                and handoff.source_attempt == invocation.attempt
                and handoff.observed_workspace_revision == post
            )
            if handoff is not None and not success:
                # A forged/stale success artifact must never be accepted.
                # Turn it into a terminal fail-closed outcome, not a thrown
                # exception leaving a RUNNING attempt indefinitely.
                self._fail_close_locked("HANDOFF_AUTHORITY_INVALID", root_node=invocation.node_id)
                close_dispatch = True
                handoff = None
            if success and self.nodes[invocation.node_id].workspace_access.value == "read" and mutation is not MutationEvidence.PROVEN_NONE:
                success = False
                handoff = None
                self._fail_close_locked("READ_WORKSPACE_MUTATION", root_node=invocation.node_id)
                close_dispatch = True
            record = running.model_copy(update={
                "status": NodeAttemptStatus.ACCEPTED if success else NodeAttemptStatus.FAILED,
                "post_workspace_revision": post,
                "failure_kind": None if success else "ACCEPTANCE_OR_EXECUTION_FAILED",
                "handoff": handoff if success else None,
            })
            changes: dict[str, Any] = {
                "attempts": state.attempts[:-1] + (record,),
                "active_dispatch_ticket_id": None,
            }
            if success:
                changes.update(
                    logical_status=NodeLogicalStatus.SUCCEEDED,
                    accepted_attempt=invocation.attempt,
                    accepted_handoff=handoff,
                    acceptance_epoch=state.acceptance_epoch + 1,
                )
            elif mutation is MutationEvidence.PROVEN_NONE and (
                invocation.attempt - 1 < self.budget.max_retries_per_node
            ) and self.gate.state is TaskDispatchGateState.OPEN:
                changes["logical_status"] = NodeLogicalStatus.REMEDIATION_PENDING
            else:
                changes.update(
                    logical_status=NodeLogicalStatus.FAILED,
                    terminal_failure_kind=(
                        "DIRTY_WRITE_FAILURE" if mutation is not MutationEvidence.PROVEN_NONE
                        else "ATTEMPT_FAILED"
                    ),
                )
                if mutation is not MutationEvidence.PROVEN_NONE or self.gate.state is TaskDispatchGateState.CLOSED:
                    self._fail_close_locked("DIRTY_WRITE_FAILURE", root_node=invocation.node_id)
                    close_dispatch = True
            self.states[invocation.node_id] = state.model_copy(update=changes)
            self.tickets[invocation.dispatch_ticket_id] = self.tickets[
                invocation.dispatch_ticket_id
            ].model_copy(update={"state": NodeDispatchTicketState.FINISHED})
            self._recompute_locked()
        if close_dispatch:
            await self.workspace.close_dispatch()

    def _fail_close_locked(self, reason: str, *, root_node: str | None = None) -> None:
        if self.gate.state is TaskDispatchGateState.CLOSED:
            return
        self.gate = TaskDispatchGate(state=TaskDispatchGateState.CLOSED,
                                     epoch=self.gate.epoch + 1)
        self.failure_kinds.append(reason)
        self._task_failed = True
        for tid, ticket in tuple(self.tickets.items()):
            if ticket.state in (
                NodeDispatchTicketState.PREPARING,
                NodeDispatchTicketState.WAITING_WORKSPACE,
                NodeDispatchTicketState.LOCKED_PRECOMMIT,
            ):
                self.tickets[tid] = ticket.model_copy(update={
                    "state": NodeDispatchTicketState.REVOKED,
                })
        for node_id, state in tuple(self.states.items()):
            if state.logical_status in (
                NodeLogicalStatus.PENDING, NodeLogicalStatus.READY,
                NodeLogicalStatus.REMEDIATION_PENDING,
            ):
                self.states[node_id] = state.model_copy(update={
                    "logical_status": NodeLogicalStatus.BLOCKED,
                    "active_dispatch_ticket_id": None,
                    "block_reason": NodeBlockReason.TASK_FAIL_CLOSED,
                    "blocked_by": (root_node,) if root_node else (),
                })

    async def fail_closed(self, reason: str, *, root_node: str | None = None) -> None:
        async with self.state_mutex:
            self._fail_close_locked(reason, root_node=root_node)
        await self.workspace.close_dispatch()

    async def run_claim(
        self, ticket: NodeDispatchTicket, backend: FakeBackendPort, *,
        accept: Acceptance | None = None,
    ) -> NodeExecutionInvocation | None:
        """Deterministic FakeBackend orchestration; no model-derived acceptance.

        No accepted Handoff without a separate trusted acceptance callback.
        Pre-commit cancellation creates no attempt.
        """
        current_id = ticket.ticket_id
        invocation: NodeExecutionInvocation | None = None
        try:
            preparation = await backend.prepare_node(self.nodes[ticket.node_id])
            await self._advance(current_id, NodeDispatchTicketState.WAITING_WORKSPACE)
            async with self.workspace.access(self.nodes[ticket.node_id].workspace_access):
                await self._advance(current_id, NodeDispatchTicketState.LOCKED_PRECOMMIT)
                # Expensive integrity resolution happens outside SchedulerStateMutex,
                # after the physical lock is acquired; stamps are rechecked at commit.
                refs_ok = True
                for stamp in ticket.dependency_acceptance_stamps:
                    h = self.states[stamp.upstream_node_id].accepted_handoff
                    if h is None or not self._evidence_checker(h):
                        refs_ok = False
                        break
                invocation = await self._commit(current_id, evidence_validated=refs_ok)
                try:
                    result = await backend.execute_prepared(preparation, invocation)
                except BaseException:
                    # No quiescence proof from a thrown backend task.
                    await backend.cancel_node(invocation.execution_id)
                    await self.fail_closed("BACKEND_QUIESCENCE_UNKNOWN", root_node=ticket.node_id)
                    raise
                handoff = None
                observed = MutationEvidence(getattr(result, "mutation_evidence", "unknown"))
                if not getattr(result, "quiescent", False):
                    observed = MutationEvidence.UNKNOWN
                post = self.revision if observed is MutationEvidence.PROVEN_NONE else self.revision.model_copy(
                    update={"generation": self.revision.generation + 1}
                )
                if result.terminal_status is BackendTerminalStatus.COMPLETED and result.quiescent:
                    if accept is not None:
                        handoff = await accept(result, invocation, post)
                await self._finish(invocation, result, handoff)
                return invocation
        except (DispatchRevoked, WorkspaceClosedError):
            if invocation is not None:
                raise  # A committed attempt is never silently uncommitted.
            await self.revoke(current_id)
            return None
        except asyncio.CancelledError:
            if invocation is None:
                await self.revoke(current_id)
            raise
        except Exception:
            if invocation is None:
                await self.revoke(current_id)
            raise

    @property
    def failed(self) -> bool:
        return self._task_failed
