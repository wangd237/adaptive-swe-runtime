"""Revision-scoped typed RepairFeedback (frozen Spec 03 §9.10).

RepairFeedback is an instruction projection of verified evidence, not a new
authority source and never a mutable TaskNode property.
"""
from __future__ import annotations
from enum import Enum
from pydantic import Field, model_validator

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts import EvidenceRef, ReceiptRef, WorkspaceRevision
from aswe.core.fingerprint import fingerprint
from aswe.runtime.repair import RepairAttributionEvidence, RepairAttributionKind, VerificationResult, VerificationCheckStatus


class RepairTriggerKind(str, Enum):
    NODE_ACCEPTANCE = "node_acceptance"
    DOWNSTREAM_VERIFICATION = "downstream_verification"


class RepairFeedback(FrozenModel):
    trigger_kind: RepairTriggerKind
    feedback_source_node_id: str
    feedback_source_execution_id: str
    feedback_source_attempt: int = Field(ge=1)
    target_write_node_id: str
    target_write_attempt: int = Field(ge=1)
    observed_workspace_revision: WorkspaceRevision
    failed_check_ids: tuple[str, ...]
    verification_result: EvidenceRef | None
    acceptance_verdict: EvidenceRef | None
    repair_attribution: EvidenceRef | None
    receipt_refs: tuple[ReceiptRef, ...]
    deterministic_failure_summaries: tuple[str, ...] = ()
    verifier_report: str | None
    fingerprint: str

    @model_validator(mode="after")
    def validate_seal_and_provenance(self) -> "RepairFeedback":
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("RepairFeedback fingerprint mismatch")
        if not self.failed_check_ids or len(self.failed_check_ids) != len(set(self.failed_check_ids)):
            raise ValueError("failed check identities must be nonempty and unique")
        if self.trigger_kind is RepairTriggerKind.DOWNSTREAM_VERIFICATION:
            if self.verification_result is None or self.repair_attribution is None:
                raise ValueError("downstream RepairFeedback requires source and attribution EvidenceRefs")
        for receipt in self.receipt_refs:
            if (receipt.source_execution_id != self.feedback_source_execution_id
                or receipt.ledger_evidence.source_node_id != self.feedback_source_node_id
                or receipt.ledger_evidence.source_attempt != self.feedback_source_attempt
                or receipt.ledger_evidence.source_execution_id != self.feedback_source_execution_id):
                raise ValueError("RepairFeedback receipt provenance mismatch")
        return self

    def bounded_projection(self) -> str:
        """Only compiler-generated check identities; never verifier blame prose."""
        return "deterministic failed checks: " + ", ".join(self.failed_check_ids[:20])


def build_verification_repair_feedback(
    *, source: VerificationResult, source_ref: EvidenceRef,
    attribution: RepairAttributionEvidence, attribution_ref: EvidenceRef,
) -> RepairFeedback:
    if attribution.kind is not RepairAttributionKind.UNIQUE_WRITER:
        raise ValueError("cannot create RepairFeedback for non-unique owner")
    if (attribution.source_verification_execution_id != source.verification_execution_id
        or attribution.source_verification_node_id != source.verification_node_id
        or attribution.source_verification_attempt != source.verification_attempt
        or attribution.observed_workspace_revision != source.observed_workspace_revision):
        raise ValueError("feedback source verification mismatch")
    refs: list[ReceiptRef] = []
    for check in source.checks:
        if check.status is not VerificationCheckStatus.FAILED:
            continue
        for ledger_ref in check.evidence_refs:
            refs.append(ReceiptRef(
                source_execution_id=source.verification_execution_id,
                ledger_evidence=ledger_ref, ledger_index=0,
                display_receipt_id=None, tool_call_id=None, tool_name="canonical_checker",
                args_freshness_stamp=source.observed_workspace_revision.repository_state_fingerprint,
                output_freshness_stamp=source.observed_workspace_revision.repository_state_fingerprint,
            ))
    body=dict(
        trigger_kind=RepairTriggerKind.DOWNSTREAM_VERIFICATION,
        feedback_source_node_id=source.verification_node_id,
        feedback_source_execution_id=source.verification_execution_id,
        feedback_source_attempt=source.verification_attempt,
        target_write_node_id=attribution.target_write_node_id,
        target_write_attempt=attribution.target_write_attempt,
        observed_workspace_revision=source.observed_workspace_revision,
        failed_check_ids=attribution.failed_check_ids,
        verification_result=source_ref, acceptance_verdict=None,
        repair_attribution=attribution_ref, receipt_refs=tuple(refs),
        deterministic_failure_summaries=(
            "Runtime checker returned nonzero exit status",),
        verifier_report=None,
    )
    return RepairFeedback(**body, fingerprint=fingerprint(body))
