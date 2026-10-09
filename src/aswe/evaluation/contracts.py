"""P1 task-contract verdict data contracts (Spec 04 §14.4).

The Planner does not assign enforcement authority; these are final evaluator
inputs from a compiler-owned contract, never generated from model prose.
"""
from enum import Enum
from pydantic import model_validator

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts.constraint import ConstraintEnforcement
from aswe.core.contracts import EvidenceRef, TaskEvidenceRef
from aswe.core.fingerprint import fingerprint


class ContractLeafStatus(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNVERIFIED = "unverified"
    NOT_APPLICABLE = "not_applicable"


class ContractLeafVerdict(FrozenModel):
    constraint_id: str
    enforcement: ConstraintEnforcement
    status: ContractLeafStatus
    supporting_refs: tuple[EvidenceRef | TaskEvidenceRef, ...] = ()
    diagnostics: tuple[str, ...] = ()


class ContractVerdict(FrozenModel):
    task_contract_fingerprint: str
    leaves: tuple[ContractLeafVerdict, ...]
    blocking_constraint_ids: tuple[str, ...]
    all_required_satisfied: bool
    fingerprint: str

    @model_validator(mode="after")
    def validate_verdict(self):
        if not self.task_contract_fingerprint or not self.leaves:
            raise ValueError("task-contract authority and nonempty deterministic coverage required")
        ids = tuple(leaf.constraint_id for leaf in self.leaves)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate contract constraint identity")
        blocked = tuple(sorted(leaf.constraint_id for leaf in self.leaves
            if leaf.enforcement in (ConstraintEnforcement.LOCKED, ConstraintEnforcement.HARD)
            and leaf.status in (ContractLeafStatus.VIOLATED, ContractLeafStatus.UNVERIFIED)))
        if self.blocking_constraint_ids != blocked or self.all_required_satisfied != (not blocked):
            raise ValueError("contract verdict blocking authority mismatch")
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("contract verdict fingerprint mismatch")
        return self


def build_contract_verdict(
    task_contract_fingerprint: str,
    leaves: tuple[ContractLeafVerdict, ...],
) -> ContractVerdict:
    blocked = tuple(sorted(leaf.constraint_id for leaf in leaves
        if leaf.enforcement in (ConstraintEnforcement.LOCKED, ConstraintEnforcement.HARD)
        and leaf.status in (ContractLeafStatus.VIOLATED, ContractLeafStatus.UNVERIFIED)))
    fields = dict(task_contract_fingerprint=task_contract_fingerprint,
                  leaves=leaves, blocking_constraint_ids=blocked,
                  all_required_satisfied=not blocked)
    return ContractVerdict(**fields, fingerprint=fingerprint(fields))
