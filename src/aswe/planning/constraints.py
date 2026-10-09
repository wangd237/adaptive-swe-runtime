"""Early ConstraintCompiler provenance entry points (Step 3A).

This deliberately compiles *only* verified user semantic fallback and
repository guidance. Runtime policy injection, merge algebra, conflict
detection and general contract finalization remain subsequent Step 3 work.
No arbitrary caller-provided origin/enforcement is accepted.
"""
from __future__ import annotations

import hashlib

from aswe.core.fingerprint import fingerprint
from aswe.planning.contracts import (
    CompiledConstraint, ConstraintCandidate, ConstraintEnforcement,
    ConstraintEvidenceRef, ConstraintOrigin, ConstraintProvenance,
    TaskRequestEnvelope,
)


class ConstraintProvenanceError(ValueError):
    pass


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _constraint(*, key, operator, value, enforcement, origin, evidence,
                verification_mode, method, candidate_key) -> CompiledConstraint:
    body = {
        "key": key, "operator": operator, "value": value,
        "enforcement": enforcement,
        "provenance": ConstraintProvenance(
            origin=origin, evidence=(evidence,),
            provenance_verified=True, extraction_method=method,
        ),
        "verification_mode": verification_mode,
        "contributors": (candidate_key,),
    }
    return CompiledConstraint(
        id="constraint-" + fingerprint(body)[:24], **body
    )


def compile_explicit_user_candidate(
    envelope: TaskRequestEnvelope, candidate: ConstraintCandidate
) -> CompiledConstraint:
    """Only an exact verifiable original-user quote can become HARD.

    Do not trust origin_hint, modality_hint, or a Planner paraphrase.
    Unrecognized requirements become semantic.requirement, not dropped.
    """
    quote = candidate.evidence_quote
    if not quote or quote not in envelope.raw_text:
        raise ConstraintProvenanceError(
            "cannot issue USER_EXPLICIT provenance without exact request quote"
        )
    # P1 fallback preserves semantic requirements. Named registry keys will
    # be introduced only with their compiler-validated value/merge rules.
    evidence = ConstraintEvidenceRef(
        source_kind="task_request", source_id=envelope.request_id,
        source_hash=envelope.content_hash,
        locator=f"raw_text:{envelope.raw_text.index(quote)}:{len(quote)}",
        quote=quote,
    )
    return _constraint(
        key="semantic.requirement", operator="requires", value=quote,
        enforcement=ConstraintEnforcement.HARD,
        origin=ConstraintOrigin.USER_EXPLICIT, evidence=evidence,
        verification_mode="semantic", method="llm", candidate_key=candidate.key,
    )


def compile_repository_guidance(
    *, repository_path: str, file_content: str, guidance_text: str,
    candidate: ConstraintCandidate,
) -> CompiledConstraint:
    """Repository text is proof of existence, never an instruction authority."""
    if not guidance_text or guidance_text not in file_content:
        raise ConstraintProvenanceError("repository quote not present in source")
    ref = ConstraintEvidenceRef(
        source_kind="repository_file", source_id=repository_path,
        source_hash=_sha256(file_content),
        locator=f"content:{file_content.index(guidance_text)}:{len(guidance_text)}",
        quote=guidance_text,
    )
    return _constraint(
        key="semantic.requirement", operator="prefers", value=guidance_text,
        enforcement=ConstraintEnforcement.SOFT,
        origin=ConstraintOrigin.REPOSITORY_GUIDANCE,
        evidence=ref, verification_mode="semantic",
        method="llm", candidate_key=candidate.key,
    )
