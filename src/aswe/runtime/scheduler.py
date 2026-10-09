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
from dataclasses import dataclass, field
from typing import Any, Protocol

from aswe.core.config import RuntimeBudgetConfig
from aswe.core.contracts import (
    AttemptEvidenceKind, BackendTerminalStatus, DependencyAcceptanceStamp, EvidenceRef,
    NodeAttemptKind, NodeExecutionInvocation, NodeHandoff, TaskDAG, WorkspaceRevision,
    WorkKind,
)
from aswe.core.ids import new_execution_id, new_run_id, new_safe_id
from aswe.runtime.dispatch import (
    DispatchRevoked, NodeDispatchTicket, NodeDispatchTicketState,
    RepairScopeInvalidated, TaskDispatchGate, TaskDispatchGateState,
)
from aswe.runtime.repair import (
    RepairAttributionEvidence, RepairAttributionKind,
    resolve_verification_repair_attribution,
)
from aswe.evidence import LocalEvidenceStore
from aswe.runtime.canonical_verifier import CanonicalVerifier, CanonicalCommandPolicy
from aswe.runtime.feedback import RepairFeedback, build_verification_repair_feedback
from aswe.runtime.repair import VerificationResult
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


@dataclass
class CommittedExecution:
    """A committed execution remains registered until its Workspace lock is released."""
    backend: FakeBackendPort | None
    owner: asyncio.Task | None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    quiescent: bool | None = None
    cancel_error: str | None = None



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
        canonical_verifier: CanonicalVerifier | None = None,
        canonical_check_policies: dict[str, CanonicalCommandPolicy] | None = None,
        canonical_acceptance_policies: dict[str, CanonicalCommandPolicy] | None = None,
        test_only_allow_fixture_receipts: bool = False,
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
        self._canonical_verifier = canonical_verifier
        self._canonical_check_policies = dict(canonical_check_policies or {})
        self._canonical_acceptance_policies = dict(canonical_acceptance_policies or {})
        self._test_only_allow_fixture_receipts = test_only_allow_fixture_receipts
        self.states = {
            node_id: NodeRuntimeState(
                node_id=node_id, logical_status=NodeLogicalStatus.PENDING,
                next_attempt=1, repair_count=0,
            ) for node_id in self.nodes
        }
        self.tickets: dict[str, NodeDispatchTicket] = {}
        self.failure_kinds: list[str] = []
        # Secondary cancellation side effects never create business root failures.
        self.secondary_runtime_diagnostics: list[str] = []
        self._pending_attempt_kinds: dict[str, NodeAttemptKind] = {}
        self._repair_feedback_revision: dict[str, WorkspaceRevision] = {}
        self._repair_feedback_text: dict[str, str] = {}
        self._typed_repair_feedback: dict[str, RepairFeedback] = {}
        self._task_failed = False
        self._committed: dict[str, CommittedExecution] = {}
        self._terminal_mutex = asyncio.Lock()
        self._quiescence_unknown = False
        self._locally_cancelled_nodes: set[str] = set()
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

    _TRANSIENT_FAILURES = frozenset({
        "EXECUTION_TRANSIENT_FAILURE", "EXECUTION_TIMEOUT", "EXECUTION_CAPPED_PARTIAL",
    })

    def _retry_eligible(self, invocation: NodeExecutionInvocation, result: Any,
                        mutation: MutationEvidence) -> bool:
        """Policy/backend/acceptance failures are never retried merely because clean."""
        return (
            mutation is MutationEvidence.PROVEN_NONE
            and getattr(result, "terminal_status", None) in (
                BackendTerminalStatus.FAILED, BackendTerminalStatus.TIMED_OUT,
            )
            and getattr(result, "failure_kind", None) in self._TRANSIENT_FAILURES
            and invocation.attempt - 1 < self.budget.max_retries_per_node
        )

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
        backend: FakeBackendPort | None = None,
    ) -> NodeExecutionInvocation:
        """Linearization point; call only AFTER physical WorkspaceAccess granted."""
        async with self.state_mutex:
            ticket = self.tickets[ticket_id]
            if not evidence_validated or not self._is_current_locked(ticket):
                raise DispatchRevoked("stale ticket, dependency evidence or task gate")
            state = self.states[ticket.node_id]
            attempt = state.next_attempt
            kind = self._pending_attempt_kinds.get(
                ticket.node_id, NodeAttemptKind.INITIAL if attempt == 1 else NodeAttemptKind.RETRY
            )
            if kind is NodeAttemptKind.REPAIR and (
                self._repair_feedback_revision.get(ticket.node_id) != self.revision
                or ticket.node_id not in self._typed_repair_feedback
                or self._typed_repair_feedback[ticket.node_id].observed_workspace_revision != self.revision
            ):
                raise DispatchRevoked("RepairFeedback stale against current locked WorkspaceRevision")
            invocation = NodeExecutionInvocation(
                task_id=self.task_id, node_id=ticket.node_id,
                attempt=attempt,
                attempt_kind=kind,
                execution_id=new_execution_id(), run_id=new_run_id(),
                execution_workspace_revision=self.revision,
                dispatch_ticket_id=ticket_id, task_dispatch_epoch=self.gate.epoch,
                dependency_acceptance_stamps=ticket.dependency_acceptance_stamps,
                dependency_context_text="",
                dependency_handoff_fingerprints=tuple(
                    s.handoff_fingerprint for s in ticket.dependency_acceptance_stamps
                ),
                repair_feedback_text=self._repair_feedback_text.get(ticket.node_id)
                if kind is NodeAttemptKind.REPAIR else None,
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
            self._committed[invocation.execution_id] = CommittedExecution(
                backend=backend, owner=asyncio.current_task(),
            )
            self._pending_attempt_kinds.pop(ticket.node_id, None)
            if kind is NodeAttemptKind.REPAIR:
                self._repair_feedback_revision.pop(ticket.node_id, None)
                self._repair_feedback_text.pop(ticket.node_id, None)
                self._typed_repair_feedback.pop(ticket.node_id, None)
            return invocation

    async def _finish(self, invocation: NodeExecutionInvocation, result: Any,
                      handoff: NodeHandoff | None, *,
                      certified_post: WorkspaceRevision | None = None,
                      own_acceptance_feedback: RepairFeedback | None = None,
                      own_evidence_refs: tuple[EvidenceRef, ...] = ()) -> None:
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
            if certified_post is not None:
                if (certified_post.generation != post.generation
                        or certified_post.base_sha != post.base_sha
                        or not certified_post.head_matches_baseline):
                    raise ValueError("invalid canonical acceptance post-revision")
                post = certified_post
            self.revision = post
            own_repair = (
                own_acceptance_feedback is not None
                and own_acceptance_feedback.trigger_kind.value == "node_acceptance"
                and own_acceptance_feedback.feedback_source_node_id == invocation.node_id
                and own_acceptance_feedback.feedback_source_execution_id == invocation.execution_id
                and own_acceptance_feedback.feedback_source_attempt == invocation.attempt
                and own_acceptance_feedback.target_write_node_id == invocation.node_id
                and own_acceptance_feedback.target_write_attempt == invocation.attempt
                and own_acceptance_feedback.observed_workspace_revision == post
                and len(own_evidence_refs) >= 2
                and mutation is MutationEvidence.OBSERVED
                and getattr(result, "terminal_status", None) is BackendTerminalStatus.COMPLETED
                and getattr(result, "quiescent", False)
                and self.nodes[invocation.node_id].work_kind is WorkKind.IMPLEMENTATION
                and self.nodes[invocation.node_id].workspace_access.value == "write"
                and state.repair_count < self.budget.max_repairs_per_write
                and self.gate.state is TaskDispatchGateState.OPEN
            )
            success = (
                self.gate.state is TaskDispatchGateState.OPEN
                and getattr(result, "terminal_status", None) is BackendTerminalStatus.COMPLETED
                and getattr(result, "quiescent", False)
                and handoff is not None
                and invocation.node_id not in self._locally_cancelled_nodes
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
            local_cancel = invocation.node_id in self._locally_cancelled_nodes
            cancelled = (local_cancel or
                         getattr(result, "terminal_status", None) is BackendTerminalStatus.CANCELLED)
            record = running.model_copy(update={
                "status": (NodeAttemptStatus.ACCEPTED if success else
                           NodeAttemptStatus.CANCELLED if cancelled else NodeAttemptStatus.FAILED),
                "post_workspace_revision": post,
                "failure_kind": None if success else (
                    "FAIL_CLOSED_CONSUMER_CANCELLED"
                    if (cancelled and self.gate.state is TaskDispatchGateState.CLOSED
                        and not self.cancelled and not local_cancel) else
                    "ACCEPTANCE_FAILED" if own_repair else
                    getattr(result, "failure_kind", None) or "ACCEPTANCE_OR_EXECUTION_FAILED"
                ),
                "handoff": handoff if success else None,
                "evidence_refs": own_evidence_refs if own_repair else running.evidence_refs,
            })
            changes: dict[str, Any] = {
                "attempts": state.attempts[:-1] + (record,),
                "active_dispatch_ticket_id": None,
            }
            if cancelled and (self.cancelled or local_cancel
                              or self.gate.state is TaskDispatchGateState.CLOSED):
                # A task-fail-close cancelled consumer is a consequence of the
                # original business failure, not another independent root.
                changes.update(
                    logical_status=NodeLogicalStatus.CANCELLED,
                    terminal_failure_kind=None,
                )
                if (not self.cancelled and not local_cancel
                        and self.gate.state is TaskDispatchGateState.CLOSED):
                    if mutation is not MutationEvidence.PROVEN_NONE:
                        self.secondary_runtime_diagnostics.append(
                            "FAIL_CLOSED_CONSUMER_MUTATION:" + invocation.node_id
                        )
                    if not getattr(result, "quiescent", False):
                        self.secondary_runtime_diagnostics.append(
                            "FAIL_CLOSED_CONSUMER_QUIESCENCE_UNKNOWN:" + invocation.node_id
                        )
            elif success:
                changes.update(
                    logical_status=NodeLogicalStatus.SUCCEEDED,
                    accepted_attempt=invocation.attempt,
                    accepted_handoff=handoff,
                    acceptance_epoch=state.acceptance_epoch + 1,
                )
            elif own_repair:
                # A changed WRITE is repairable ONLY when Runtime has already
                # executed and attested the exact deterministic Acceptance check.
                changes.update(
                    logical_status=NodeLogicalStatus.REMEDIATION_PENDING,
                    repair_count=state.repair_count + 1,
                    terminal_failure_kind=None,
                )
                self._pending_attempt_kinds[invocation.node_id] = NodeAttemptKind.REPAIR
                self._typed_repair_feedback[invocation.node_id] = own_acceptance_feedback
                self._repair_feedback_revision[invocation.node_id] = post
                self._repair_feedback_text[invocation.node_id] = own_acceptance_feedback.bounded_projection()
            elif self.gate.state is TaskDispatchGateState.OPEN and self._retry_eligible(
                invocation, result, mutation
            ):
                changes["logical_status"] = NodeLogicalStatus.REMEDIATION_PENDING
                self._pending_attempt_kinds[invocation.node_id] = NodeAttemptKind.RETRY
            else:
                budget_exhausted = (
                    own_acceptance_feedback is not None
                    and mutation is MutationEvidence.OBSERVED
                    and getattr(result, "quiescent", False)
                    and state.repair_count >= self.budget.max_repairs_per_write
                    and self.nodes[invocation.node_id].work_kind is WorkKind.IMPLEMENTATION
                )
                review_rejected = (
                    self.nodes[invocation.node_id].work_kind is WorkKind.REVIEW
                    and getattr(result, "failure_kind", None) == "REVIEW_GATE_REJECTED"
                    and mutation is MutationEvidence.PROVEN_NONE
                )
                terminal_reason = (
                    "REPAIR_BUDGET_EXHAUSTED" if budget_exhausted else
                    "REVIEW_GATE_REJECTED" if review_rejected else
                    "DIRTY_WRITE_FAILURE" if mutation is not MutationEvidence.PROVEN_NONE else
                    "ATTEMPT_FAILED"
                )
                changes.update(
                    logical_status=NodeLogicalStatus.FAILED,
                    terminal_failure_kind=terminal_reason,
                )
                if (mutation is not MutationEvidence.PROVEN_NONE
                        or self.gate.state is TaskDispatchGateState.CLOSED):
                    self._fail_close_locked(terminal_reason, root_node=invocation.node_id)
                    close_dispatch = True
            self.states[invocation.node_id] = state.model_copy(update=changes)
            if local_cancel:
                self._locally_cancelled_nodes.discard(invocation.node_id)
                if mutation is not MutationEvidence.PROVEN_NONE:
                    # Shared Workspace changed during a cancelled attempt: unrelated
                    # branches cannot safely continue without a clean baseline.
                    self._fail_close_locked("LOCAL_CANCEL_MUTATION", root_node=invocation.node_id)
                    close_dispatch = True
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

    def _descendants_locked(self, upstream_id: str) -> set[str]:
        """Closure includes direct and indirect consumers, not the source writer."""
        descendants: set[str] = set()
        frontier = [upstream_id]
        while frontier:
            current = frontier.pop()
            for node_id, node in self.nodes.items():
                if current in node.dependencies and node_id not in descendants:
                    descendants.add(node_id)
                    frontier.append(node_id)
        return descendants

    async def attach_attempt_evidence(
        self, *, node_id: str, evidence_ref: EvidenceRef,
        evidence_store: LocalEvidenceStore,
    ) -> None:
        """Verify durable provenance outside mutex, then publish attempt evidence."""
        evidence_store.get(evidence_ref)
        if not evidence_ref.evidence_id.startswith(self.task_id + "__"):
            raise ValueError("attempt evidence belongs to a different task")
        if evidence_ref.source_node_id != node_id:
            raise ValueError("evidence node mismatch")
        async with self.state_mutex:
            state = self.states[node_id]
            matching = next((a for a in state.attempts
                             if a.execution_id == evidence_ref.source_execution_id
                             and a.attempt == evidence_ref.source_attempt), None)
            if matching is None or matching.status is NodeAttemptStatus.RUNNING:
                raise ValueError("evidence must attach to a completed historical attempt")
            attempts = tuple(
                a.model_copy(update={"evidence_refs": a.evidence_refs + (evidence_ref,)})
                if a == matching and evidence_ref not in a.evidence_refs else a
                for a in state.attempts
            )
            self.states[node_id] = state.model_copy(update={"attempts": attempts})

    async def reopen_writer_from_verification(
        self, *, verification_ref: EvidenceRef, attribution_ref: EvidenceRef,
        evidence_store: LocalEvidenceStore,
    ) -> RepairAttributionEvidence:
        """Validate durable ownership, then linearize Writer reopen vs commit.

        No evidence-store reads, Workspace waits or backend calls in state_mutex.
        Successful return revokes current Writer Handoff authority, increments
        its epoch and makes the same immutable Writer eligible for REPAIR.
        """
        if attribution_ref.kind is not AttemptEvidenceKind.REPAIR_ATTRIBUTION:
            raise ValueError("repair attribution must use typed EvidenceRef")
        attribution = RepairAttributionEvidence.model_validate(evidence_store.get(attribution_ref))
        if (attribution_ref.source_node_id != attribution.source_verification_node_id
            or attribution_ref.source_execution_id != attribution.source_verification_execution_id
            or attribution_ref.source_attempt != attribution.source_verification_attempt):
            raise ValueError("repair attribution evidence provenance mismatch")
        source_id = attribution.source_verification_node_id
        async with self.state_mutex:
            if source_id not in self.states:
                raise ValueError("unknown verification source")
            source = self.states[source_id]
            source_attempt = source.attempts[-1] if source.attempts else None
            if source_attempt is None:
                raise ValueError("missing verification attempt")
            if (attribution_ref not in source_attempt.evidence_refs
                or not attribution_ref.evidence_id.startswith(self.task_id + "__")):
                raise ValueError("repair attribution must be attached to current source attempt")
            # Capture only immutable snapshots; do integrity I/O outside mutex.
            state_snapshot = dict(self.states)
        if self._canonical_verifier is None and not self._test_only_allow_fixture_receipts:
            raise ValueError("Runtime Canonical Verifier required for real repair authorization")
        resolved = resolve_verification_repair_attribution(
            dag=self.dag, source_attempt=source_attempt,
            verification_ref=verification_ref, node_states=state_snapshot,
            evidence_store=evidence_store, canonical_verifier=self._canonical_verifier,
        )
        if attribution != resolved:
            raise ValueError("stored repair attribution differs from deterministic resolution")
        if attribution.kind is not RepairAttributionKind.UNIQUE_WRITER:
            raise RepairScopeInvalidated("verification has no unique legal repair owner")
        writer_id = attribution.target_write_node_id
        assert writer_id is not None
        source_result = VerificationResult.model_validate(evidence_store.get(verification_ref))
        feedback = build_verification_repair_feedback(
            source=source_result, source_ref=verification_ref,
            attribution=attribution, attribution_ref=attribution_ref,
        )
        fail_reason = None
        async with self.state_mutex:
            source_now = self.states[source_id]
            writer = self.states[writer_id]
            if (self.gate.state is not TaskDispatchGateState.OPEN
                or source_now != state_snapshot[source_id]
                or writer != state_snapshot[writer_id]
                or self.revision != attribution.observed_workspace_revision
                or writer.logical_status is not NodeLogicalStatus.SUCCEEDED
                or writer.accepted_attempt != attribution.target_write_attempt):
                fail_reason = "REPAIR_SCOPE_INVALIDATED_STALE"
            elif writer.repair_count >= self.budget.max_repairs_per_write:
                fail_reason = "REPAIR_BUDGET_EXHAUSTED"
            else:
                descendants = self._descendants_locked(writer_id)
                for node_id in descendants:
                    if node_id == source_id:
                        continue  # Failed source Verification is a legitimate trigger.
                    node_state = self.states[node_id]
                    running = (node_state.logical_status is NodeLogicalStatus.RUNNING
                               or any(t.node_id == node_id and
                                      t.state is NodeDispatchTicketState.COMMITTED
                                      for t in self.tickets.values()))
                    if running:
                        fail_reason = "REPAIR_SCOPE_INVALIDATED_ACTIVE_DOWNSTREAM_DISPATCH"
                        break
                    if (node_state.logical_status is NodeLogicalStatus.SUCCEEDED
                        and self.nodes[node_id].work_kind is not WorkKind.VERIFICATION):
                        fail_reason = "REPAIR_SCOPE_INVALIDATED_COMMITTED_DOWNSTREAM_SUCCESS"
                        break
                if fail_reason is None:
                    # Entire authority revocation and ticket invalidation form
                    # one SchedulerStateMutex transaction, before any consumer commit.
                    for tid, ticket in tuple(self.tickets.items()):
                        if ticket.node_id in descendants and ticket.state in (
                            NodeDispatchTicketState.PREPARING,
                            NodeDispatchTicketState.WAITING_WORKSPACE,
                            NodeDispatchTicketState.LOCKED_PRECOMMIT,
                        ):
                            self.tickets[tid] = ticket.model_copy(update={
                                "state": NodeDispatchTicketState.REVOKED,
                            })
                    self.states[writer_id] = writer.model_copy(update={
                        "logical_status": NodeLogicalStatus.REMEDIATION_PENDING,
                        "accepted_attempt": None, "accepted_handoff": None,
                        "acceptance_epoch": writer.acceptance_epoch + 1,
                        "repair_count": writer.repair_count + 1,
                    })
                    self._pending_attempt_kinds[writer_id] = NodeAttemptKind.REPAIR
                    self._typed_repair_feedback[writer_id] = feedback
                    self._repair_feedback_revision[writer_id] = feedback.observed_workspace_revision
                    self._repair_feedback_text[writer_id] = feedback.bounded_projection()
                    if source_now.logical_status is not NodeLogicalStatus.FAILED:
                        raise RuntimeError("verification source no longer FAILED")
                    self.states[source_id] = source_now.model_copy(update={
                        "logical_status": NodeLogicalStatus.REMEDIATION_PENDING,
                        "terminal_failure_kind": None,
                    })
                    self._pending_attempt_kinds[source_id] = NodeAttemptKind.REVERIFY
                    for node_id in descendants:
                        if node_id == source_id:
                            continue
                        descendant = self.states[node_id]
                        if descendant.active_dispatch_ticket_id is not None:
                            self.states[node_id] = descendant.model_copy(update={
                                "active_dispatch_ticket_id": None,
                            })
                            descendant = self.states[node_id]
                        if descendant.logical_status in (NodeLogicalStatus.READY,
                                  NodeLogicalStatus.BLOCKED) and (
                            descendant.logical_status is NodeLogicalStatus.READY
                            or descendant.block_reason is NodeBlockReason.UPSTREAM_FAILURE
                        ):
                            self.states[node_id] = descendant.model_copy(update={
                                "logical_status": NodeLogicalStatus.PENDING,
                                "block_reason": None, "blocked_by": (),
                            })
                    self._recompute_locked()
            if fail_reason is not None:
                self._fail_close_locked(fail_reason, root_node=source_id)
        if fail_reason is not None:
            await self.workspace.close_dispatch()
            await self.drain_committed()
            raise RepairScopeInvalidated(fail_reason)
        return attribution

    async def complete_task(self) -> None:
        """Close successful scheduling without incorrectly marking a root failure.

        ContractVerdict is checked separately by Runtime-only TaskResult finalizer.
        """
        async with self.state_mutex:
            if self.gate.state is not TaskDispatchGateState.OPEN or self._task_failed:
                raise RuntimeError("task is not eligible for normal completion")
            if any(s.logical_status is not NodeLogicalStatus.SUCCEEDED for s in self.states.values()):
                raise RuntimeError("ordinary nodes not all accepted")
            if any(t.state in (NodeDispatchTicketState.PREPARING, NodeDispatchTicketState.WAITING_WORKSPACE,
                              NodeDispatchTicketState.LOCKED_PRECOMMIT, NodeDispatchTicketState.COMMITTED)
                   for t in self.tickets.values()):
                raise RuntimeError("task still has pending dispatch")
            self.gate = TaskDispatchGate(state=TaskDispatchGateState.CLOSED, epoch=self.gate.epoch + 1)
        await self.drain_committed()

    async def cancel_node(self, node_id: str, *, timeout: float = 2.0) -> None:
        """Cancel only one logical node and BLOCK its ordinary descendants.

        A precommit ticket is revoked without manufacturing an attempt.
        For committed nodes, request backend cancellation and JOIN its owner
        before returning. Unknown quiescence fails the whole shared task closed.
        """
        if timeout <= 0:
            raise ValueError("join timeout must be positive")
        async with self.state_mutex:
            if self.gate.state is not TaskDispatchGateState.OPEN:
                raise DispatchRevoked("task dispatch gate closed")
            if node_id not in self.states:
                raise KeyError(node_id)
            state = self.states[node_id]
            if state.logical_status is NodeLogicalStatus.CANCELLED:
                return
            if state.logical_status not in (
                NodeLogicalStatus.PENDING, NodeLogicalStatus.READY,
                NodeLogicalStatus.REMEDIATION_PENDING, NodeLogicalStatus.RUNNING,
            ):
                raise DispatchRevoked("node already terminal")
            if state.logical_status is NodeLogicalStatus.RUNNING:
                active = state.attempts[-1]
                item = self._committed.get(active.execution_id)
                if item is None:
                    raise RuntimeError("RUNNING node missing committed execution")
                self._locally_cancelled_nodes.add(node_id)
                execution_id = active.execution_id
            else:
                if state.active_dispatch_ticket_id:
                    ticket_id = state.active_dispatch_ticket_id
                    ticket = self.tickets[ticket_id]
                    if ticket.state in (NodeDispatchTicketState.COMMITTED,
                                        NodeDispatchTicketState.FINISHED):
                        raise DispatchRevoked("committed attempt cannot be revoked")
                    self.tickets[ticket_id] = ticket.model_copy(
                        update={"state": NodeDispatchTicketState.REVOKED}
                    )
                self.states[node_id] = state.model_copy(update={
                    "logical_status": NodeLogicalStatus.CANCELLED,
                    "active_dispatch_ticket_id": None,
                    "block_reason": None, "blocked_by": (),
                    "terminal_failure_kind": None,
                })
                self._recompute_locked()
                return

        # Do not hold SchedulerStateMutex while invoking backend or joining.
        try:
            if item.backend is None or item.owner is asyncio.current_task():
                raise RuntimeError("committed local cancellation cannot be joined")
            await asyncio.wait_for(item.backend.cancel_node(execution_id), timeout)
            await asyncio.wait_for(item.done.wait(), timeout)
            if item.quiescent is not True or item.cancel_error is not None:
                raise RuntimeError("local cancellation quiescence not proven")
        except (Exception, asyncio.CancelledError):
            self._quiescence_unknown = True
            await self.fail_closed("LOCAL_CANCEL_QUIESCENCE_UNKNOWN", root_node=node_id)
            raise

    async def cancel_task(self) -> None:
        """Cancellation is not a business failure; residual patches stay unaccepted."""
        async with self.state_mutex:
            if self.gate.state is not TaskDispatchGateState.CLOSED:
                self._fail_close_locked("TASK_USER_CANCELLED")
            self._task_cancelled = True
            for node_id, state in tuple(self.states.items()):
                if state.logical_status in (
                    NodeLogicalStatus.PENDING, NodeLogicalStatus.READY,
                    NodeLogicalStatus.REMEDIATION_PENDING, NodeLogicalStatus.BLOCKED,
                ):
                    self.states[node_id] = state.model_copy(update={
                        "logical_status": NodeLogicalStatus.CANCELLED,
                        "active_dispatch_ticket_id": None,
                        "block_reason": None, "blocked_by": (),
                    })
        await self.drain_committed()

    @property
    def cancelled(self) -> bool:
        return getattr(self, "_task_cancelled", False)

    async def fail_closed(self, reason: str, *, root_node: str | None = None) -> None:
        async with self.state_mutex:
            self._fail_close_locked(reason, root_node=root_node)
        await self.drain_committed()


    async def _settle_if_drained(self) -> None:
        """Never mark FROZEN while a committed runner or workspace holder remains."""
        from aswe.workspace.session import WorkspaceSessionStatus
        async with self._terminal_mutex:
            if self.gate.state is not TaskDispatchGateState.CLOSED:
                return
            if self.workspace.lifecycle.current.status in (
                WorkspaceSessionStatus.FROZEN, WorkspaceSessionStatus.QUARANTINED,
                WorkspaceSessionStatus.CLOSED,
            ):
                return
            if self.workspace.active_accesses or any(
                not item.done.is_set() for item in self._committed.values()
            ):
                return
            proven = not self._quiescence_unknown and all(
                item.quiescent is True and item.cancel_error is None
                for item in self._committed.values()
            )
            await self.workspace.terminalize(quiescence_proven=proven)

    async def drain_committed(self, *, timeout: float = 2.0) -> None:
        """Cancel and JOIN executions; cancel acknowledgement is not quiescence."""
        if timeout <= 0:
            raise ValueError("join timeout must be positive")
        owner = asyncio.current_task()
        async with self.state_mutex:
            if self.gate.state is TaskDispatchGateState.OPEN:
                self._fail_close_locked("TASK_DRAIN_REQUESTED")
            active = [(eid, item) for eid, item in self._committed.items()
                      if not item.done.is_set() and item.owner is not owner]

        await self.workspace.close_dispatch()

        async def cancel_join(eid: str, item: CommittedExecution) -> None:
            if item.backend is None:
                self._quiescence_unknown = True
                return
            try:
                await asyncio.wait_for(item.backend.cancel_node(eid), timeout)
                await asyncio.wait_for(item.done.wait(), timeout)
            except (Exception, asyncio.CancelledError) as exc:
                item.cancel_error = type(exc).__name__
                self._quiescence_unknown = True

        try:
            if active:
                await asyncio.gather(*(cancel_join(eid, item) for eid, item in active))
        except BaseException:
            # The drain coordinator itself may be cancelled. No completed
            # join proof exists; never leave the workspace merely ACTIVE.
            self._quiescence_unknown = True
            from aswe.workspace.session import WorkspaceSessionStatus
            if self.workspace.lifecycle.current.status not in (
                WorkspaceSessionStatus.QUARANTINED, WorkspaceSessionStatus.FROZEN,
                WorkspaceSessionStatus.CLOSED,
            ):
                await self.workspace.terminalize(quiescence_proven=False)
            raise
        if self._quiescence_unknown:
            from aswe.workspace.session import WorkspaceSessionStatus
            if self.workspace.lifecycle.current.status not in (
                WorkspaceSessionStatus.QUARANTINED, WorkspaceSessionStatus.FROZEN,
                WorkspaceSessionStatus.CLOSED,
            ):
                await self.workspace.terminalize(quiescence_proven=False)
        await self._settle_if_drained()



    async def _abort_committed(
        self, invocation: NodeExecutionInvocation, *, failure_kind: str,
        quiescence_proven: bool,
    ) -> None:
        """Terminalize a committed attempt even when execution/acceptance raises.

        Quiescence cannot be inferred from a completed coroutine alone.
        """
        async with self.state_mutex:
            state = self.states[invocation.node_id]
            if state.logical_status is NodeLogicalStatus.RUNNING:
                attempt = state.attempts[-1]
                if attempt.execution_id != invocation.execution_id:
                    raise RuntimeError("attempt ownership mismatch")
                post = self.revision
                if not quiescence_proven:
                    post = post.model_copy(update={"generation": post.generation + 1})
                    self.revision = post
                finished = attempt.model_copy(update={
                    "status": NodeAttemptStatus.FAILED,
                    "failure_kind": failure_kind,
                    "post_workspace_revision": post if quiescence_proven else None,
                })
                self.states[invocation.node_id] = state.model_copy(update={
                    "logical_status": NodeLogicalStatus.FAILED,
                    "terminal_failure_kind": failure_kind,
                    "attempts": state.attempts[:-1] + (finished,),
                })
                self.tickets[invocation.dispatch_ticket_id] = self.tickets[
                    invocation.dispatch_ticket_id
                ].model_copy(update={"state": NodeDispatchTicketState.FINISHED})
            self._fail_close_locked(failure_kind, root_node=invocation.node_id)
        await self.workspace.close_dispatch()
        if not quiescence_proven:
            await self.workspace.terminalize(quiescence_proven=False)

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
        completed_quiescent = False
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
                try:
                    invocation = await self._commit(current_id, evidence_validated=refs_ok, backend=backend)
                except DispatchRevoked as exc:
                    if "RepairFeedback stale" not in str(exc):
                        raise
                    # Preserve the physical WRITE lock while refreshing, but never
                    # execute checks or EvidenceStore I/O under SchedulerStateMutex.
                    from aswe.runtime.refresh import refresh_stale_verification
                    if not await refresh_stale_verification(self, current_id):
                        raise DispatchRevoked("RepairFeedback stale: no authorized repair remains")
                    invocation = await self._commit(current_id, evidence_validated=refs_ok, backend=backend)
                try:
                    result = await backend.execute_prepared(preparation, invocation)
                except BaseException:
                    # The backend has not returned an independent quiescence proof.
                    try:
                        await backend.cancel_node(invocation.execution_id)
                    finally:
                        await self._abort_committed(
                            invocation, failure_kind="BACKEND_QUIESCENCE_UNKNOWN",
                            quiescence_proven=False,
                        )
                    raise
                completed_quiescent = bool(getattr(result, "quiescent", False))
                try:
                    handoff = None
                    observed = MutationEvidence(getattr(result, "mutation_evidence", "unknown"))
                    if not getattr(result, "quiescent", False):
                        observed = MutationEvidence.UNKNOWN
                    post = self.revision if observed is MutationEvidence.PROVEN_NONE else self.revision.model_copy(
                        update={"generation": self.revision.generation + 1}
                    )
                    certified_post = None
                    own_fb = None
                    own_refs = ()
                    policy = self._canonical_acceptance_policies.get(invocation.node_id)
                    if (observed is MutationEvidence.OBSERVED
                            and self._canonical_verifier is not None
                            and self.nodes[invocation.node_id].workspace_access.value == "write"):
                        from aswe.repository import capture_repository_state
                        state = await asyncio.to_thread(
                            capture_repository_state, self._canonical_verifier.binding,
                        )
                        if not state.head_matches_baseline or state.base_sha != self.revision.base_sha:
                            raise RuntimeError("own acceptance repository baseline invariant broken")
                        post = post.model_copy(update={
                            "repository_state_fingerprint": state.fingerprint,
                            "head_sha": state.head_sha,
                            "dirty": state.dirty_vs_base,
                            "head_matches_baseline": state.head_matches_baseline,
                        })
                        certified_post = post
                    if result.terminal_status is BackendTerminalStatus.COMPLETED and result.quiescent:
                        if accept is not None:
                            handoff = await accept(result, invocation, post)
                        if (handoff is None and accept is not None
                                and certified_post is not None
                                and policy is not None):
                            from aswe.runtime.own_acceptance import certify_mutated_own_failure
                            own_fb, own_refs = await certify_mutated_own_failure(
                                self, invocation, post, policy,
                            )
                    await self._finish(
                        invocation, result, handoff,
                        certified_post=certified_post,
                        own_acceptance_feedback=own_fb,
                        own_evidence_refs=own_refs,
                    )
                except BaseException:
                    await self._abort_committed(
                        invocation, failure_kind="EVIDENCE_FINALIZATION_FAILURE",
                        quiescence_proven=bool(getattr(result, "quiescent", False)),
                    )
                    raise
                if not getattr(result, "quiescent", False):
                    await self.workspace.terminalize(quiescence_proven=False)
                return invocation
        except (DispatchRevoked, WorkspaceClosedError) as exc:
            if invocation is not None:
                raise  # A committed attempt is never silently uncommitted.
            await self.revoke(current_id)
            if (isinstance(exc, DispatchRevoked)
                    and "RepairFeedback stale" in str(exc)
                    and self.gate.state is TaskDispatchGateState.OPEN):
                await self.fail_closed("REPAIR_FEEDBACK_STALE", root_node=ticket.node_id)
            return None
        except asyncio.CancelledError:
            if invocation is None:
                await self.revoke(current_id)
            raise
        except Exception:
            if invocation is None:
                await self.revoke(current_id)
            raise
        finally:
            if invocation is not None:
                item = self._committed[invocation.execution_id]
                item.quiescent = completed_quiescent
                item.done.set()
            # A stale refresh can close the gate without a Writer attempt.
            await self._settle_if_drained()

    @property
    def failed(self) -> bool:
        return self._task_failed
