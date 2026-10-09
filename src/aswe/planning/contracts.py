"""Canonical Step-3 immutable source and constraint candidate contracts.

An analyzer's candidate is not a CompiledConstraint: it cannot sign its own
origin or choose its enforcement authority.
"""
from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts.constraint import ConstraintEnforcement


class TaskRequestEnvelope(FrozenModel):
    request_id: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hash(self) -> "TaskRequestEnvelope":
        actual = hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()
        if self.content_hash != actual:
            raise ValueError("TaskRequestEnvelope source digest mismatch")
        return self


def make_task_request(*, request_id: str, raw_text: str) -> TaskRequestEnvelope:
    return TaskRequestEnvelope(
        request_id=request_id, raw_text=raw_text,
        content_hash=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


class ConstraintCandidate(FrozenModel):
    key: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    value: Any
    origin_hint: str | None = None
    modality_hint: str | None = None
    evidence_quote: str | None = None
    evidence_locator: str | None = None


class TaskContractDraft(FrozenModel):
    candidates: tuple[ConstraintCandidate, ...]


class ConstraintOrigin(str, Enum):
    RUNTIME_POLICY = "runtime_policy"
    USER_EXPLICIT = "user_explicit"
    REPOSITORY_GUIDANCE = "repository_guidance"
    RUNTIME_DERIVED = "runtime_derived"


class ConstraintEvidenceRef(FrozenModel):
    source_kind: Literal["task_request", "runtime_policy", "repository_file", "task_spec"]
    source_id: str = Field(min_length=1)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(min_length=1)
    quote: str | None = None


class ConstraintProvenance(FrozenModel):
    origin: ConstraintOrigin
    evidence: tuple[ConstraintEvidenceRef, ...]
    provenance_verified: bool
    extraction_method: Literal["deterministic", "llm"]


class CompiledConstraint(FrozenModel):
    id: str = Field(min_length=1)
    key: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    value: Any
    enforcement: ConstraintEnforcement
    provenance: ConstraintProvenance
    verification_mode: Literal["deterministic", "semantic", "none"]
    contributors: tuple[str, ...]

    @model_validator(mode="after")
    def validate_compiler_id(self):
        from aswe.core.fingerprint import fingerprint
        expected = "constraint-" + fingerprint(
            self.model_dump(mode="json", exclude={"id"})
        )[:24]
        if self.id != expected:
            raise ValueError("compiled constraint identity mismatch")
        return self


class CompiledTaskContract(FrozenModel):
    task_request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Bind compiler normalization semantics and all loaded guidance content,
    # including guidance with no extracted candidates.
    compiler_ruleset_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    repository_guidance_hashes: tuple[tuple[str, str], ...]
    repository_base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    constraints: tuple[CompiledConstraint, ...]
    compiler_repairs: tuple[dict[str, Any], ...]
    warnings: tuple[dict[str, Any], ...]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_contract_hash(self):
        from aswe.core.fingerprint import fingerprint
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("compiled contract fingerprint mismatch")
        if self.repository_guidance_hashes != tuple(sorted(set(self.repository_guidance_hashes))):
            raise ValueError("guidance provenance hashes must be canonical")
        if any(not p or len(h) != 64 or any(ch not in "0123456789abcdef" for ch in h)
               for p, h in self.repository_guidance_hashes):
            raise ValueError("guidance provenance invalid")
        ids = tuple(c.id for c in self.constraints)
        keys = tuple(c.key for c in self.constraints)
        if len(set(ids)) != len(ids) or keys != tuple(sorted(set(keys))):
            raise ValueError("compiled constraint order/identity not canonical")
        return self


class TaskExecutionAuthority(FrozenModel):
    repository_mutation_allowed: bool
    external_side_effects_allowed: frozenset[str]
    granting_constraint_ids: tuple[str, ...]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_authority_hash(self):
        from aswe.core.fingerprint import fingerprint
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("task execution authority fingerprint mismatch")
        if self.external_side_effects_allowed:
            raise ValueError("P1 external side effects must be denied")
        if self.repository_mutation_allowed != bool(self.granting_constraint_ids):
            raise ValueError("authority grant ids inconsistent")
        return self
