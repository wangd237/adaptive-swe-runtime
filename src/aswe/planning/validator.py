"""Deterministic Step 3C semantic plan validation / monotonic normalization.

No Provider, ToolEffect, WorkspaceAccess, or Scheduler execution authority is
inferred here. Stable physical serialization belongs to the Step-4 DAG compiler.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts.constraint import ConstraintEnforcement
from aswe.core.contracts.task import WorkKind
from aswe.core.fingerprint import fingerprint
from aswe.planning.immutable import deep_freeze
from aswe.planning.compiler import _scope_contains
from aswe.planning.contracts import (
    CompiledConstraint, CompiledTaskContract, TaskExecutionAuthority,
)
from aswe.planning.planner import WorkItemProposal, WorkPlanProposal
from aswe.planning.registry import DeliverableEffect


# Canonical Step-4 capability vocabulary; Step-3 parser must not drift.
from aswe.capabilities.registry import (
    READ_CAPABILITIES, MUTATION_CAPABILITIES, ALL_CAPABILITIES,
)
PHASE = {
    WorkKind.DISCOVERY: 0,
    WorkKind.IMPLEMENTATION: 1,
    WorkKind.VERIFICATION: 2,
    WorkKind.REVIEW: 3,
}


class PlanValidationError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


class CoverageMode(str, Enum):
    RUNTIME_ENFORCED = "runtime_enforced"
    PLANNER_DECLARED = "planner_declared"


class PlanCoverageEntry(FrozenModel):
    constraint_id: str = Field(min_length=1)
    mode: CoverageMode
    work_item_ids: tuple[str, ...]


class PlanRepair(FrozenModel):
    code: str = Field(min_length=1)
    affected_work_item_ids: tuple[str, ...] = ()
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def deep_immutable(self):
        object.__setattr__(self,"details",deep_freeze(self.details))
        return self


class PlanWarning(FrozenModel):
    code: str = Field(min_length=1)
    affected_work_item_ids: tuple[str, ...] = ()
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def deep_immutable(self):
        object.__setattr__(self,"details",deep_freeze(self.details))
        return self


class ValidatedWorkItem(FrozenModel):
    id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    work_kind: WorkKind
    capability_hints: tuple[str, ...]
    depends_on: tuple[str, ...]
    coverage_claims: tuple[str, ...] = ()
    acceptance_intent: tuple[str, ...] = ()
    planner_ordinal: int = Field(ge=0)
    runtime_owned: bool = False


class ValidatedWorkPlan(FrozenModel):
    items: tuple[ValidatedWorkItem, ...]
    task_contract_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    repairs: tuple[PlanRepair, ...] = ()
    warnings: tuple[PlanWarning, ...] = ()
    planner_rationale: str
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_structure(self):
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("ValidatedWorkPlan fingerprint mismatch")
        ids = [item.id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate validated work-item identity")
        if tuple(x.planner_ordinal for x in self.items) != tuple(range(len(self.items))):
            raise ValueError("invalid validated item ordinal")
        for item in self.items:
            if item.id.startswith("__aswe_") != item.runtime_owned:
                raise ValueError("runtime-owned item namespace mismatch")
            if item.id in item.depends_on or any(d not in ids for d in item.depends_on):
                raise ValueError("invalid validated dependency")
        return self


def _positive(c: CompiledConstraint) -> bool:
    if c.enforcement is ConstraintEnforcement.SOFT:
        return False
    if c.key in ("deliverables.required", "semantic.requirement",
                 "verification.required", "target.exact_path"):
        return bool(c.value)
    return c.key == "review.required" and c.value is True


def _required_gates(contract: CompiledTaskContract) -> tuple[bool, bool]:
    by_key = {c.key: c for c in contract.constraints}
    verify = by_key.get("verification.required")
    review = by_key.get("review.required")
    return (
        bool(verify and verify.enforcement is not ConstraintEnforcement.SOFT and verify.value),
        bool(review and review.enforcement is not ConstraintEnforcement.SOFT and review.value is True),
    )


def _transitive_dependencies(items: tuple[WorkItemProposal, ...], node_id: str) -> set[str]:
    lookup = {item.id: item for item in items}
    seen: set[str] = set()
    stack = list(lookup[node_id].depends_on)
    while stack:
        parent = stack.pop()
        if parent in seen:
            continue
        seen.add(parent)
        stack.extend(lookup[parent].depends_on)
    return seen


class SemanticPlanValidator:
    def __init__(self, *, max_work_items: int = 8, allowed_capabilities: frozenset[str] = ALL_CAPABILITIES):
        if max_work_items < 1:
            raise ValueError("positive max_work_items required")
        if not allowed_capabilities or not allowed_capabilities.issubset(ALL_CAPABILITIES):
            raise ValueError("capability catalog must use known provider-neutral vocabulary")
        self.max_work_items = max_work_items
        self.allowed_capabilities = allowed_capabilities

    def _precheck(
        self, proposal: WorkPlanProposal, contract: CompiledTaskContract,
        authority: TaskExecutionAuthority,
    ) -> tuple[dict[str, WorkItemProposal], set[str]]:
        ids = [x.id for x in proposal.items]
        if len(set(ids)) != len(ids):
            raise PlanValidationError("PLAN_INVALID", "duplicate work item id")
        if any(x.startswith("__aswe_") for x in ids):
            raise PlanValidationError("PLAN_INVALID", "reserved Runtime namespace is forbidden")
        lookup = {x.id: x for x in proposal.items}
        by_id = {c.id: c for c in contract.constraints}
        positive = {c.id for c in contract.constraints if _positive(c)}
        independent_verify_required, _ = _required_gates(contract)
        if any(x.id != x.id.strip() for x in proposal.items):
            raise PlanValidationError("PLAN_INVALID", "noncanonical work item id")
        for item in proposal.items:
            if not item.capability_hints:
                raise PlanValidationError("PLAN_INVALID", f"missing capability: {item.id}")
            caps = set(item.capability_hints)
            if not caps.issubset(self.allowed_capabilities):
                raise PlanValidationError("PLAN_INVALID", f"unknown capability: {sorted(caps - self.allowed_capabilities)}")
            if item.id in item.depends_on:
                raise PlanValidationError("PLAN_INVALID", f"self dependency: {item.id}")
            if any(dep not in lookup for dep in item.depends_on):
                raise PlanValidationError("PLAN_INVALID", f"unknown dependency: {item.id}")
            if any(PHASE[lookup[dep].work_kind] > PHASE[item.work_kind] for dep in item.depends_on):
                raise PlanValidationError("PHASE_ORDER_CONTRADICTION", f"phase reversal: {item.id}")
            invalid_claims = set(item.coverage_claims) - positive
            if invalid_claims:
                raise PlanValidationError("PLAN_INVALID", f"negative or unknown coverage: {sorted(invalid_claims)}")
            modifying = bool(caps & MUTATION_CAPABILITIES)
            if modifying and item.work_kind is not WorkKind.IMPLEMENTATION:
                raise PlanValidationError("PLAN_INVALID", f"business mutation capability in non-implementation: {item.id}")
            if item.work_kind is WorkKind.IMPLEMENTATION and not modifying:
                raise PlanValidationError("PLAN_INVALID", f"implementation without business mutation capability: {item.id}")
            if modifying and "code_review" in caps:
                raise PlanValidationError("PLAN_INVALID", f"review capability combined with business implementation: {item.id}")
            if (independent_verify_required and item.work_kind is WorkKind.IMPLEMENTATION
                    and "regression_testing" in caps):
                raise PlanValidationError("PLAN_INVALID", f"independent verification merged into writer: {item.id}")
            if (item.work_kind is WorkKind.VERIFICATION and "code_review" in caps):
                raise PlanValidationError("PLAN_INVALID", f"verification merged with review: {item.id}")
            if item.work_kind is WorkKind.VERIFICATION and "regression_testing" not in caps:
                raise PlanValidationError("PLAN_INVALID", f"verification lacks regression_testing: {item.id}")
            if item.work_kind is WorkKind.REVIEW and "code_review" not in caps:
                raise PlanValidationError("PLAN_INVALID", f"review lacks code_review: {item.id}")
            if modifying:
                if not authority.repository_mutation_allowed:
                    raise PlanValidationError("CAPABILITY_AUTHORITY_VIOLATION", f"mutation denied: {item.id}")
                mutation_ids = set(authority.granting_constraint_ids)
                if not mutation_ids.intersection(item.coverage_claims):
                    raise PlanValidationError("PLAN_INVALID", f"mutation deliverable coverage missing: {item.id}")
                if not mutation_ids.issubset(set(by_id)):
                    raise PlanValidationError("PLAN_INVALID", "unknown mutation authorization reference")
        # Global graph acyclicity, including same-phase cycles.
        visited: set[str] = set()
        active: set[str] = set()
        def visit(node_id: str):
            if node_id in active:
                raise PlanValidationError("PLAN_INVALID", f"dependency cycle at {node_id}")
            if node_id in visited:
                return
            active.add(node_id)
            for parent in lookup[node_id].depends_on:
                visit(parent)
            active.remove(node_id)
            visited.add(node_id)
        for item_id in ids:
            visit(item_id)
        return lookup, positive

    def validate(
        self, *, proposal: WorkPlanProposal, contract: CompiledTaskContract,
        authority: TaskExecutionAuthority,
    ) -> ValidatedWorkPlan:
        # Project again from the immutable contract, never trust caller-made
        # TaskExecutionAuthority even with a valid self-consistent fingerprint.
        from aswe.planning.compiler import project_execution_authority
        if authority != project_execution_authority(contract):
            raise PlanValidationError("CAPABILITY_AUTHORITY_VIOLATION", "authority does not match contract projection")
        verify_required, review_required = _required_gates(contract)
        reserve = int(verify_required) + int(review_required)
        if len(proposal.items) > self.max_work_items - reserve:
            raise PlanValidationError("PLAN_INVALID", "planner exceeded reserved gate budget")
        lookup, positive = self._precheck(proposal, contract, authority)
        warnings: list[PlanWarning] = []
        repairs: list[PlanRepair] = []
        items: list[ValidatedWorkItem] = []
        for idx, raw in enumerate(proposal.items):
            deduped = tuple(dict.fromkeys(raw.depends_on))
            if len(deduped) < len(raw.depends_on):
                repairs.append(PlanRepair(
                    code="DEDUPE_DEPENDENCY", affected_work_item_ids=(raw.id,),
                    details={"before": raw.depends_on, "after": deduped},
                ))
            if raw.work_kind is WorkKind.DISCOVERY and len(deduped) > 0:
                warnings.append(PlanWarning(code="DEPENDENT_DISCOVERY", affected_work_item_ids=(raw.id,)))
            items.append(ValidatedWorkItem(
                id=raw.id, objective=raw.objective,
                work_kind=raw.work_kind, capability_hints=tuple(sorted(set(raw.capability_hints))),
                depends_on=deduped, coverage_claims=tuple(sorted(set(raw.coverage_claims))),
                acceptance_intent=raw.acceptance_intent, planner_ordinal=idx,
                runtime_owned=False,
            ))
        original = proposal.items
        implementation = tuple(x.id for x in original if x.work_kind is WorkKind.IMPLEMENTATION)
        verification = tuple(x.id for x in original if x.work_kind is WorkKind.VERIFICATION)
        review = tuple(x.id for x in original if x.work_kind is WorkKind.REVIEW)
        # Valid planner gates are independent bounded nodes downstream of all
        # implementation/verification packages. A decorative gate does not count.
        legal_verify = any(set(implementation).issubset(_transitive_dependencies(original, v)) for v in verification)
        review_upstream = verification if verification else implementation
        legal_review = any(set(review_upstream).issubset(_transitive_dependencies(original, v)) for v in review)
        injected_verify = False
        if verify_required and not legal_verify:
            # Inject a mandatory verifier even when a decorative tester exists.
            items.append(ValidatedWorkItem(
                id="__aswe_verify", objective="Run compiled mandatory verification gate",
                work_kind=WorkKind.VERIFICATION, capability_hints=("regression_testing",),
                depends_on=implementation, coverage_claims=(),
                acceptance_intent=(), planner_ordinal=len(items), runtime_owned=True,
            ))
            repairs.append(PlanRepair(code="INJECT_VERIFICATION_GATE",
                                      affected_work_item_ids=("__aswe_verify",),
                                      details={"compiled_contract": contract.fingerprint}))
            injected_verify = True
        if review_required and (not legal_review or injected_verify):
            # An originally valid Review may not depend on our newly added
            # verifier. Never let Review satisfy the gate before verification.
            upstream = (tuple(x.id for x in items if x.work_kind is WorkKind.VERIFICATION)
                        if (verification or injected_verify) else implementation)
            items.append(ValidatedWorkItem(
                id="__aswe_review", objective="Run compiled mandatory structured review gate",
                work_kind=WorkKind.REVIEW, capability_hints=("code_review",),
                depends_on=upstream, coverage_claims=(),
                acceptance_intent=(), planner_ordinal=len(items), runtime_owned=True,
            ))
            repairs.append(PlanRepair(code="INJECT_REVIEW_GATE",
                                      affected_work_item_ids=("__aswe_review",),
                                      details={"compiled_contract": contract.fingerprint}))
        if len(items) > self.max_work_items:
            raise PlanValidationError("PLAN_INVALID", "runtime gates exceed maximum work items")
        normalized = tuple(items)
        for item in normalized:
            if item.id.startswith("__aswe_") and not item.runtime_owned:
                raise PlanValidationError("PLAN_INVALID", "forged runtime gate")
        coverage = self._coverage_map(normalized, contract)
        missing = sorted(positive - {c.constraint_id for c in coverage})
        if missing:
            raise PlanValidationError("PLAN_INVALID", f"positive obligation lacks plan coverage: {missing}")
        body = dict(
            items=normalized, task_contract_fingerprint=contract.fingerprint,
            repairs=tuple(repairs), warnings=tuple(warnings),
            planner_rationale=proposal.rationale,
        )
        return ValidatedWorkPlan(**body, fingerprint=fingerprint(body))

    def coverage_map(
        self, *, plan: ValidatedWorkPlan, contract: CompiledTaskContract,
    ) -> tuple[PlanCoverageEntry, ...]:
        if plan.task_contract_fingerprint != contract.fingerprint:
            raise PlanValidationError("PLAN_INVALID", "contract/plan fingerprint mismatch")
        return self._coverage_map(plan.items, contract)

    @staticmethod
    def _coverage_map(
        items: tuple[ValidatedWorkItem, ...], contract: CompiledTaskContract,
    ) -> tuple[PlanCoverageEntry, ...]:
        covered: list[PlanCoverageEntry] = []
        for c in contract.constraints:
            if not _positive(c):
                continue
            if c.key in ("verification.required", "review.required"):
                kind = (WorkKind.VERIFICATION if c.key == "verification.required" else WorkKind.REVIEW)
                # A semantically valid independent existing gate is
                # compiler-recognized even if the Planner omitted an explicit
                # coverage claim. It must transitively follow every relevant
                # upstream package, otherwise only our own injected gate counts.
                lookup = {x.id: x for x in items}
                upstream = tuple(x.id for x in items if x.work_kind is (
                    WorkKind.IMPLEMENTATION if kind is WorkKind.VERIFICATION
                    else WorkKind.VERIFICATION
                ))
                if kind is WorkKind.REVIEW and not upstream:
                    upstream = tuple(x.id for x in items if x.work_kind is WorkKind.IMPLEMENTATION)
                def predecessors(item_id):
                    seen = set()
                    pending = list(lookup[item_id].depends_on)
                    while pending:
                        dep = pending.pop()
                        if dep in seen:
                            continue
                        seen.add(dep)
                        pending.extend(lookup[dep].depends_on)
                    return seen
                gate_ids = tuple(
                    x.id for x in items if x.work_kind is kind and
                    (x.runtime_owned or set(upstream).issubset(predecessors(x.id)))
                )
                if gate_ids:
                    covered.append(PlanCoverageEntry(
                        constraint_id=c.id, mode=CoverageMode.RUNTIME_ENFORCED,
                        work_item_ids=gate_ids,
                    ))
                continue
            owners = tuple(x.id for x in items if c.id in x.coverage_claims)
            if owners:
                covered.append(PlanCoverageEntry(
                    constraint_id=c.id, mode=CoverageMode.PLANNER_DECLARED,
                    work_item_ids=owners,
                ))
        return tuple(covered)
