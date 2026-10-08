from enum import Enum
from ._base import FrozenModel
from .workspace import ExecutionCompleteness, WorkspaceRevision

class AttemptEvidenceKind(str, Enum):
    TOOL_RECEIPT_LEDGER="tool_receipt_ledger"; REPOSITORY_CHANGESET="repository_changeset"; WORKSPACE_CHANGESET="workspace_changeset"
    REPORT_RECEIPT_VERDICT="report_receipt_verdict"; ACCEPTANCE_VERDICT="acceptance_verdict"; VERIFICATION_RESULT="verification_result"
    REPAIR_ATTRIBUTION="repair_attribution"; REVIEW_VERDICT="review_verdict"; REPOSITORY_INVARIANT="repository_invariant"

class TaskEvidenceKind(str, Enum):
    FINAL_REPOSITORY_STATE="final_repository_state"; FINAL_REPOSITORY_CHANGESET="final_repository_changeset"; FINAL_CONTRACT_VERDICT="final_contract_verdict"

class EvidenceRef(FrozenModel):
    evidence_id: str
    kind: AttemptEvidenceKind
    source_node_id: str
    source_execution_id: str
    source_attempt: int
    workspace_revision_generation: int|None
    workspace_state_fingerprint: str|None
    content_sha256: str

class TaskEvidenceRef(FrozenModel):
    evidence_id: str
    kind: TaskEvidenceKind
    task_id: str
    finalization_id: str
    workspace_revision_generation: int|None
    workspace_state_fingerprint: str|None
    content_sha256: str

class ReceiptRef(FrozenModel):
    source_execution_id: str
    ledger_evidence: EvidenceRef
    ledger_index: int
    display_receipt_id: str|None
    tool_call_id: str|None
    tool_name: str
    args_freshness_stamp: str|None
    output_freshness_stamp: str|None

class HandoffEvidence(FrozenModel):
    receipt_refs: tuple[ReceiptRef,...]=()
    changed_paths: tuple[str,...]=()
    changed_paths_complete: bool=True
    untracked_paths: tuple[str,...]=()
    repository_changeset: EvidenceRef|None=None
    workspace_changeset: EvidenceRef|None=None
    report_receipt_verdict: EvidenceRef|None=None
    acceptance_verdict: EvidenceRef|None=None
    verification_result: EvidenceRef|None=None
    review_verdict: EvidenceRef|None=None

class NodeHandoff(FrozenModel):
    source_node_id: str
    source_execution_id: str
    source_attempt: int
    source_provider_id: str
    observed_workspace_revision: WorkspaceRevision
    self_report: str
    evidence: HandoffEvidence
    backend_stop_reason: str|None
    execution_completeness: ExecutionCompleteness
    warnings: tuple[str,...]=()
    fingerprint: str
