"""Scheduler-owned revocable dispatch contracts (Spec 03, §9.10).

These are neither TaskNodes nor persisted evidence. Only SchedulerCore may
transition these objects; consumers receive immutable snapshots.
"""
from enum import Enum

from pydantic import Field

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts import DependencyAcceptanceStamp


class NodeDispatchTicketState(str, Enum):
    PREPARING = "preparing"
    WAITING_WORKSPACE = "waiting_workspace"
    LOCKED_PRECOMMIT = "locked_precommit"
    COMMITTED = "committed"
    REVOKED = "revoked"
    FINISHED = "finished"


class NodeDispatchTicket(FrozenModel):
    ticket_id: str
    node_id: str
    task_dispatch_epoch: int = Field(ge=0)
    dependency_acceptance_stamps: tuple[DependencyAcceptanceStamp, ...]
    state: NodeDispatchTicketState


class TaskDispatchGateState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class TaskDispatchGate(FrozenModel):
    state: TaskDispatchGateState = TaskDispatchGateState.OPEN
    epoch: int = Field(default=0, ge=0)


class DispatchRevoked(RuntimeError):
    """Pre-commit ticket was invalidated without creating an attempt."""


class RepairScopeInvalidated(RuntimeError):
    """A downstream consumer crossed the non-rollbackable dispatch boundary."""
