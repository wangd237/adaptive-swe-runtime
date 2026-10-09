"""Step 3B deterministic constraint compiler; no LLM enforcement authority.

Rule sources:
- RuntimePolicyConfig: injected by trusted operator runtime (NOT LLM).
- User ConstraintCandidate: only compiler-verified exact TaskRequest quotes.
- RepositoryGuidanceSource: verified content, at most SOFT.

Outputs include immutable, digest-sealed CompiledTaskContract and a *separate*
coarse-grained TaskExecutionAuthority projection. The projection grants no
external side effects in P1.
"""
from __future__ import annotations

import hashlib
from typing import Any

from pydantic import Field

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts.constraint import ConstraintEnforcement
from aswe.core.fingerprint import fingerprint
from aswe.planning.constraints import (
    ConstraintProvenanceError, _constraint, compile_explicit_user_candidate,
)
from aswe.planning.contracts import (
    CompiledConstraint, CompiledTaskContract, ConstraintCandidate,
    ConstraintEvidenceRef, ConstraintOrigin, ConstraintProvenance,
    TaskExecutionAuthority, TaskRequestEnvelope,
)
from aswe.planning.analyzer import TaskSpec, RiskLevel
from aswe.planning.registry import (
    CONSTRAINT_REGISTRY, DeliverableEffect, canonical_value,
    normalize_path, parse_exact_user_directive,
)


class ContractCompilationError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


class RuntimePolicyRule(FrozenModel):
    key: str = Field(min_length=1)
    value: Any
    enforcement: ConstraintEnforcement = ConstraintEnforcement.LOCKED


class RuntimePolicyConfig(FrozenModel):
    policy_id: str = Field(min_length=1)
    rules: tuple[RuntimePolicyRule, ...] = ()
    # An operator-granted deterministic derivation, NOT analyzer self-authority.
    high_risk_requires_review: bool = False


class RepositoryGuidanceSource(FrozenModel):
    path: str = Field(min_length=1)
    content: str
    candidates: tuple[ConstraintCandidate, ...] = ()


class _SourceConstraint(FrozenModel):
    constraint: CompiledConstraint
    priority: int


def _source_constraint(key: str, value: Any, *, enforcement, origin,
                       evidence, method="deterministic", contributor: str):
    info = CONSTRAINT_REGISTRY[key]
    return _constraint(
        key=key, operator="effective", value=canonical_value(key, value),
        enforcement=enforcement, origin=origin, evidence=evidence,
        verification_mode=info.verification_mode,
        method=method, candidate_key=contributor,
    )


def _rank(constraint: CompiledConstraint) -> int:
    return {
        ConstraintOrigin.RUNTIME_POLICY: 4,
        ConstraintOrigin.RUNTIME_DERIVED: 3,
        ConstraintOrigin.USER_EXPLICIT: 2,
        ConstraintOrigin.REPOSITORY_GUIDANCE: 1,
    }[constraint.provenance.origin]


def _scope_contains(parent: str, child: str) -> bool:
    if parent == "**":
        return True
    if parent == child:
        return True
    if parent.endswith("/**"):
        prefix = parent[:-3]
        return child.startswith(prefix + "/") or child == prefix
    return False


def _intersect_scopes(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    # An allow set is a union of safely-recognized anchored subtrees.
    found = []
    for a in left:
        for b in right:
            if _scope_contains(a, b):
                found.append(b)
            elif _scope_contains(b, a):
                found.append(a)
            # unrelated scopes cannot enlarge an intersection
    return tuple(sorted(set(found)))


def _in_any_scope(path: str, scopes: tuple[str, ...]) -> bool:
    return any(_scope_contains(pattern, path) for pattern in scopes)


def _has_mutation_scope(allowed, blocked) -> bool:
    """Conservatively reject a grant when all admitted subtrees are denied."""
    if blocked is None:
        return allowed is None or bool(allowed.value)
    denies = tuple(blocked.value)
    if "**" in denies:
        return False
    if allowed is None:
        return True
    return any(not any(_scope_contains(deny, scope) for deny in denies)
               for scope in allowed.value)


def _merge(key: str, group: list[CompiledConstraint], warnings: list[dict]) -> object:
    strategy = CONSTRAINT_REGISTRY[key].merge_strategy
    ordered = sorted(group, key=lambda c: (-_rank(c), c.id))
    values = [c.value for c in ordered]
    if strategy == "intersection":
        result = values[0]
        for value in values[1:]:
            result = _intersect_scopes(result, value)
        return result
    if strategy == "union":
        if key == "review.required":
            return any(values)
        if key == "deliverables.required":
            return tuple(sorted(
                {v for seq in values for v in seq},
                key=lambda d: (d.effect.value, d.description),
            ))
        if key == "semantic.requirement":
            return tuple(sorted(set(values)))
        return tuple(sorted({v for seq in values for v in seq}))
    if strategy == "minimum":
        return min(values)
    if strategy in ("exact", "priority"):
        fixed = [c for c in ordered if c.enforcement is not ConstraintEnforcement.SOFT]
        if strategy == "exact" and len({c.value for c in fixed}) > 1:
            code = ("CONTRACT_POLICY_CONFLICT"
                    if any(c.enforcement is ConstraintEnforcement.LOCKED for c in fixed)
                    else "CONTRACT_UNSATISFIABLE")
            raise ContractCompilationError(code, f"incompatible exact choices: {key}")
        selected = (fixed or ordered)[0]
        for c in ordered:
            if c.id != selected.id and c.value != selected.value and c.enforcement is ConstraintEnforcement.SOFT:
                warnings.append({"code": "OVERRIDDEN_GUIDANCE", "key": key,
                                 "constraint_id": c.id})
        return selected.value
    raise AssertionError(strategy)


def _combine(key: str, group: list[CompiledConstraint], warnings: list[dict]) -> CompiledConstraint:
    value = _merge(key, group, warnings)
    source = sorted(group, key=lambda c: (-_rank(c), c.id))[0]
    # Keep each contributing evidence locator/hash, even when its origin is
    # lower priority. contributor identity retains the originals.
    refs = {fingerprint(e): e for c in group for e in c.provenance.evidence}
    body = dict(
        key=key, operator="effective", value=value,
        enforcement=max(
            (c.enforcement for c in group),
            key=lambda x: {"soft": 0, "hard": 1, "locked": 2}[x.value],
        ),
        provenance=ConstraintProvenance(
            origin=source.provenance.origin,
            evidence=tuple(refs[k] for k in sorted(refs)),
            provenance_verified=True,
            extraction_method=("llm" if any(
                c.provenance.extraction_method == "llm" for c in group
            ) else "deterministic"),
        ),
        verification_mode=CONSTRAINT_REGISTRY[key].verification_mode,
        contributors=tuple(sorted({c.id for c in group})),
    )
    return CompiledConstraint(id="constraint-" + fingerprint(body)[:24], **body)


def _check_conflicts(by_key: dict[str, CompiledConstraint], raw: list[CompiledConstraint]):
    required = by_key.get("deliverables.required")
    forbidden = by_key.get("actions.forbidden")
    denied = set(forbidden.value) if forbidden else set()
    if required and any(d.effect is DeliverableEffect.REPOSITORY_MUTATION for d in required.value):
        if "repository_mutation" in denied or "repo.write" in denied:
            code = ("CONTRACT_POLICY_CONFLICT" if forbidden.enforcement is ConstraintEnforcement.LOCKED
                    else "CONTRACT_UNSATISFIABLE")
            raise ContractCompilationError(code, "repository mutation deliverable conflicts with forbidden actions")
    path = by_key.get("target.exact_path")
    allowed = by_key.get("repo.paths.allowed")
    blocked = by_key.get("repo.paths.forbidden")
    if path:
        violates = (
            (allowed is not None and not _in_any_scope(path.value, allowed.value))
            or (blocked is not None and _in_any_scope(path.value, blocked.value))
        )
        if violates:
            locked = any(c.enforcement is ConstraintEnforcement.LOCKED for c in raw
                         if c.key in ("repo.paths.allowed", "repo.paths.forbidden"))
            raise ContractCompilationError(
                "CONTRACT_POLICY_CONFLICT" if locked else "CONTRACT_UNSATISFIABLE",
                "exact target path excluded by effective repository scope",
            )
    if required and any(d.effect is DeliverableEffect.REPOSITORY_MUTATION for d in required.value):
        if not _has_mutation_scope(allowed, blocked):
            locked = any(c.enforcement is ConstraintEnforcement.LOCKED
                         for c in raw if c.key in ("repo.paths.allowed", "repo.paths.forbidden"))
            raise ContractCompilationError(
                "CONTRACT_POLICY_CONFLICT" if locked else "CONTRACT_UNSATISFIABLE",
                "no effective repository mutation scope remains",
            )


def project_execution_authority(contract: CompiledTaskContract) -> TaskExecutionAuthority:
    """Only a verified positive deliverable may grant repository mutation.

    Denies always override grants; external side effects remain denied for P1.
    """
    by_key = {c.key: c for c in contract.constraints}
    required = by_key.get("deliverables.required")
    forbidden = by_key.get("actions.forbidden")
    denied = set(forbidden.value) if forbidden else set()
    grant_ids = tuple(sorted(
        c.id for c in contract.constraints
        if c.key == "deliverables.required"
        and c.enforcement in (ConstraintEnforcement.HARD, ConstraintEnforcement.LOCKED)
        and any(d.effect is DeliverableEffect.REPOSITORY_MUTATION for d in c.value)
    ))
    permission = (
        bool(grant_ids)
        and not {"repository_mutation", "repo.write", "*"}.intersection(denied)
        and _has_mutation_scope(by_key.get("repo.paths.allowed"),
                                by_key.get("repo.paths.forbidden"))
    )
    body = dict(
        repository_mutation_allowed=permission,
        external_side_effects_allowed=frozenset(),
        granting_constraint_ids=grant_ids if permission else (),
    )
    return TaskExecutionAuthority(**body, fingerprint=fingerprint(body))


class ConstraintCompiler:
    def __init__(self, policy: RuntimePolicyConfig):
        self.policy = policy

    def compile(
        self, *, request: TaskRequestEnvelope, repository_base_sha: str,
        user_candidates: tuple[ConstraintCandidate, ...] = (),
        guidance: tuple[RepositoryGuidanceSource, ...] = (),
        task_spec: TaskSpec | None = None,
    ) -> tuple[CompiledTaskContract, TaskExecutionAuthority]:
        if len(repository_base_sha) != 40 or any(c not in "0123456789abcdef" for c in repository_base_sha):
            raise ValueError("valid repository pinned sha required")
        policy_hash = fingerprint(self.policy)
        raw: list[CompiledConstraint] = []
        for idx, rule in enumerate(self.policy.rules):
            if rule.key not in CONSTRAINT_REGISTRY:
                raise ContractCompilationError("POLICY_INVALID", f"unknown policy key {rule.key}")
            evidence = ConstraintEvidenceRef(
                source_kind="runtime_policy", source_id=self.policy.policy_id,
                source_hash=policy_hash, locator=f"rules:{idx}", quote=None,
            )
            raw.append(_source_constraint(
                rule.key, rule.value, enforcement=rule.enforcement,
                origin=ConstraintOrigin.RUNTIME_POLICY, evidence=evidence,
                contributor=f"runtime:{idx}",
            ))
        if self.policy.high_risk_requires_review and task_spec is not None and task_spec.risk is RiskLevel.HIGH:
            task_hash = fingerprint(task_spec)
            evidence = ConstraintEvidenceRef(
                source_kind="task_spec", source_id=request.request_id,
                source_hash=task_hash, locator="risk:high",
                quote=None,
            )
            raw.append(_source_constraint(
                "review.required", True, enforcement=ConstraintEnforcement.HARD,
                origin=ConstraintOrigin.RUNTIME_DERIVED, evidence=evidence,
                contributor="runtime-rule:RISK-REVIEW-001:" + policy_hash,
            ))
        for candidate in user_candidates:
            quote = candidate.evidence_quote
            if not quote or quote not in request.raw_text:
                raise ConstraintProvenanceError("unverifiable user explicit quote")
            at = request.raw_text.index(quote)
            if candidate.evidence_locator is not None and candidate.evidence_locator != f"raw_text:{at}:{len(quote)}":
                raise ConstraintProvenanceError("user locator does not match immutable source")
            # A quoted directive inside a sentence or code block is data, not
            # an execution instruction. Only one unquoted complete line can
            # enter the typed registry; otherwise retain semantic HARD.
            line_start = at == 0 or request.raw_text[at - 1] == "\\n"
            end = at + len(quote)
            line_end = end == len(request.raw_text) or request.raw_text[end] == "\\n"
            plain = (
                line_start and line_end
                and "\\n" not in quote and not quote.startswith((">", "- ", "#"))
                and request.raw_text[:at].count("```") % 2 == 0
                and request.raw_text.count(quote) == 1
            )
            try:
                directive = parse_exact_user_directive(quote) if plain else None
            except (ValueError, TypeError) as exc:
                raise ContractCompilationError("CONTRACT_INVALID", str(exc)) from exc
            if directive is None:
                raw.append(compile_explicit_user_candidate(request, candidate))
                continue
            key, val = directive
            evidence = ConstraintEvidenceRef(
                source_kind="task_request", source_id=request.request_id,
                source_hash=request.content_hash,
                locator=f"raw_text:{at}:{len(quote)}", quote=quote,
            )
            raw.append(_source_constraint(
                key, val, enforcement=ConstraintEnforcement.HARD,
                origin=ConstraintOrigin.USER_EXPLICIT, evidence=evidence,
                method="deterministic", contributor="user:" + quote,
            ))
        for source in guidance:
            for candidate in source.candidates:
                quote = candidate.evidence_quote
                if not quote or quote not in source.content:
                    raise ConstraintProvenanceError("unverifiable repository guidance quote")
                at = source.content.index(quote)
                if candidate.evidence_locator is not None and candidate.evidence_locator != f"content:{at}:{len(quote)}":
                    raise ConstraintProvenanceError("repository locator does not match source")
                try:
                    directive = parse_exact_user_directive(quote)
                except ValueError as exc:
                    raise ContractCompilationError("CONTRACT_INVALID", str(exc)) from exc
                key, val = directive if directive else ("semantic.requirement", quote)
                # Repository suggestions must never issue a positive effect
                # grant, even if they contain a recognizable directive.
                if key == "deliverables.required":
                    key, val = "semantic.requirement", quote
                evidence = ConstraintEvidenceRef(
                    source_kind="repository_file", source_id=source.path,
                    source_hash=hashlib.sha256(source.content.encode("utf-8")).hexdigest(),
                    locator=f"content:{at}:{len(quote)}", quote=quote,
                )
                raw.append(_source_constraint(
                    key, val, enforcement=ConstraintEnforcement.SOFT,
                    origin=ConstraintOrigin.REPOSITORY_GUIDANCE, evidence=evidence,
                    method="deterministic" if directive else "llm",
                    contributor="repo:" + source.path + ":" + str(at),
                ))
        groups: dict[str, list[CompiledConstraint]] = {}
        for c in raw:
            groups.setdefault(c.key, []).append(c)
        warnings: list[dict] = []
        combined = tuple(_combine(k, groups[k], warnings) for k in sorted(groups))
        _check_conflicts({c.key: c for c in combined}, raw)
        body = dict(
            task_request_hash=request.content_hash,
            runtime_policy_hash=policy_hash,
            repository_base_sha=repository_base_sha,
            constraints=combined,
            compiler_repairs=(),
            warnings=tuple(sorted(warnings, key=fingerprint)),
        )
        contract = CompiledTaskContract(**body, fingerprint=fingerprint(body))
        return contract, project_execution_authority(contract)
