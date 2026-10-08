from enum import Enum
from typing import Literal
from ._base import FrozenModel
from .workspace import WorkspaceRevision

class NodeAttemptKind(str, Enum):
    INITIAL="initial"; RETRY="retry"; REPAIR="repair"; REVERIFY="reverify"

class BackendTerminalStatus(str, Enum):
    COMPLETED="completed"; FAILED="failed"; CANCELLED="cancelled"; TIMED_OUT="timed_out"

class BackendStopReason(str, Enum):
    TOKEN_CAPPED="token_capped"; TURN_CAPPED="turn_capped"; LOOP_CAPPED="loop_capped"

class BackendExecutionPhase(str, Enum):
    PRE_START="pre_start"; STARTED="started"

class BackendFailureClass(str, Enum):
    NONE="none"; ADMISSION="admission"; POLICY_OR_ASSEMBLY="policy_or_assembly"; EXECUTION="execution"; TIMEOUT="timeout"; CANCELLED="cancelled"

class NodeExecutionPreparation(FrozenModel):
    preparation_id: str
    node_id: str
    provider_id: str
    compiled_policy_fingerprint: str
    planning_inventory_fingerprint: str
    live_inventory_fingerprint: str
    effective_policy_fingerprint: str
    backend_snapshot_id: str
    drift_observed: bool
    drift_diagnostics: tuple[str,...]=()
    status: Literal["prepared"]="prepared"

class DependencyAcceptanceStamp(FrozenModel):
    upstream_node_id: str
    acceptance_epoch: int
    accepted_attempt: int
    handoff_fingerprint: str

class NodeExecutionInvocation(FrozenModel):
    task_id: str
    node_id: str
    attempt: int
    attempt_kind: NodeAttemptKind
    execution_id: str
    run_id: str
    execution_workspace_revision: WorkspaceRevision
    dispatch_ticket_id: str
    task_dispatch_epoch: int
    dependency_acceptance_stamps: tuple[DependencyAcceptanceStamp,...]
    dependency_context_text: str
    dependency_handoff_fingerprints: tuple[str,...]
    repair_feedback_text: str|None
    context_fingerprint: str
