"""Frozen runtime state contracts; transition logic begins in Coding Step 2.

The Scheduler, not these data types, owns state transactions.
"""
from __future__ import annotations
from enum import Enum
from pydantic import Field, model_validator
from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts.backend import NodeAttemptKind
from aswe.core.contracts.evidence import EvidenceRef, NodeHandoff
from aswe.core.contracts.workspace import WorkspaceRevision

class NodeAttemptStatus(str, Enum):
    RUNNING = "running"
    ACCEPTED = "accepted"
    FAILED = "failed"
    CANCELLED = "cancelled"

class NodeLogicalStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    REMEDIATION_PENDING = "remediation_pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

class NodeBlockReason(str, Enum):
    UPSTREAM_FAILURE = "upstream_failure"
    TASK_FAIL_CLOSED = "task_fail_closed"

class NodeAttemptRecord(FrozenModel):
    # Attempt transitions publish validated replacement snapshots, not field edits.
    node_id: str
    attempt: int = Field(ge=1)
    kind: NodeAttemptKind
    execution_id: str
    pre_workspace_revision: WorkspaceRevision
    post_workspace_revision: WorkspaceRevision | None
    status: NodeAttemptStatus
    failure_kind: str | None
    evidence_refs: tuple[EvidenceRef, ...] = ()
    handoff: NodeHandoff | None = None

    @model_validator(mode="after")
    def validate_attempt_handoff(self) -> "NodeAttemptRecord":
        if (self.status is NodeAttemptStatus.ACCEPTED) != (self.handoff is not None):
            raise ValueError("only ACCEPTED attempts have an accepted handoff")
        if self.handoff is not None and (
            self.handoff.source_node_id != self.node_id
            or self.handoff.source_execution_id != self.execution_id
            or self.handoff.source_attempt != self.attempt
        ):
            raise ValueError("attempt handoff identity mismatch")
        return self

class NodeRuntimeState(FrozenModel):
    # Mutable logical state is realized through atomically replaced snapshots.
    # The Step-2 Scheduler owns publication under its state mutex.
    node_id: str
    logical_status: NodeLogicalStatus
    next_attempt: int = Field(ge=1)
    repair_count: int = Field(ge=0)
    acceptance_epoch: int = Field(default=0, ge=0)
    accepted_attempt: int | None = Field(default=None, ge=1)
    accepted_handoff: NodeHandoff | None = None
    active_dispatch_ticket_id: str | None = None
    terminal_failure_kind: str | None = None
    block_reason: NodeBlockReason | None = None
    blocked_by: tuple[str, ...] = ()
    attempts: tuple[NodeAttemptRecord, ...] = ()

    @model_validator(mode="after")
    def validate_current_authority(self) -> "NodeRuntimeState":
        # Validate assembled snapshots, never intermediate field-by-field edits.
        if (self.accepted_attempt is None) != (self.accepted_handoff is None):
            raise ValueError("accepted_attempt and accepted_handoff must be set or cleared together")
        if len({a.attempt for a in self.attempts}) != len(self.attempts):
            raise ValueError("attempt identities must be unique within a logical Node")
        if any(a.node_id != self.node_id for a in self.attempts):
            raise ValueError("historical attempts must belong to this node")
        if self.attempts and self.next_attempt <= max(a.attempt for a in self.attempts):
            raise ValueError("next_attempt must exceed every historical attempt")
        if self.logical_status is NodeLogicalStatus.SUCCEEDED and self.accepted_attempt is None:
            raise ValueError("SUCCEEDED must publish an accepted attempt and handoff")
        if self.accepted_attempt is not None and self.logical_status is not NodeLogicalStatus.SUCCEEDED:
            raise ValueError("only SUCCEEDED logical nodes may own current accepted authority")
        if self.accepted_attempt is not None:
            accepted = next((a for a in self.attempts if a.attempt == self.accepted_attempt), None)
            if accepted is None or accepted.handoff is None or accepted.status is not NodeAttemptStatus.ACCEPTED:
                raise ValueError("accepted authority must be owned by an accepted historical attempt")
            h = self.accepted_handoff
            assert h is not None
            if h.source_node_id != self.node_id or h.source_attempt != self.accepted_attempt:
                raise ValueError("accepted handoff identity does not match accepted attempt")
            if h != accepted.handoff:
                raise ValueError("accepted handoff must exactly match historical attempt handoff")
            if h.source_execution_id != accepted.execution_id:
                raise ValueError("accepted handoff execution does not match accepted attempt")
        return self
