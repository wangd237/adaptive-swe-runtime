"""Runtime-scoped typed semantic Review gate evidence for Step-2 FakeBackend.

The trusted review_gate callback supplies a structured verdict. A model's
free-text explanation is never interpreted by Scheduler as a repair trigger.
"""
from __future__ import annotations

from enum import Enum
from pydantic import model_validator

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts import WorkspaceRevision
from aswe.core.fingerprint import fingerprint


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    UNVERIFIED = "unverified"


class ReviewVerdict(FrozenModel):
    source_node_id: str
    source_execution_id: str
    source_attempt: int
    observed_workspace_revision: WorkspaceRevision
    decision: ReviewDecision
    findings: tuple[str, ...]
    fingerprint: str

    @model_validator(mode="after")
    def verify_identity(self):
        if self.source_attempt < 1 or not self.source_node_id or not self.source_execution_id:
            raise ValueError("review attempt provenance required")
        if self.decision is ReviewDecision.REQUEST_CHANGES and not self.findings:
            raise ValueError("REQUEST_CHANGES requires review findings")
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("review verdict integrity seal invalid")
        return self


def make_review_verdict(*, node_id: str, execution_id: str, attempt: int,
                        revision: WorkspaceRevision, decision: ReviewDecision,
                        findings: tuple[str, ...] = ()) -> ReviewVerdict:
    body = dict(source_node_id=node_id, source_execution_id=execution_id,
                source_attempt=attempt, observed_workspace_revision=revision,
                decision=decision, findings=findings)
    return ReviewVerdict(**body, fingerprint=fingerprint(body))
