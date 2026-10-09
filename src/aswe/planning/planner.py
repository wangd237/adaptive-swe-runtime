"""Provider-neutral semantic planning proposals are NEVER executable DAG nodes."""
from __future__ import annotations

import json
from typing import Any

from pydantic import Field, model_validator
from aswe.core.fingerprint import fingerprint
from aswe.planning.context import ReconReport

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts.task import WorkKind
from aswe.planning.analyzer import ReasoningBackend, TaskSpec
from aswe.planning.contracts import CompiledTaskContract
from aswe.planning.profile import RepositoryProfile


class PlanningContext(FrozenModel):
    """Frozen context snapshot, never an instruction/constraint authority."""
    repository_profile: RepositoryProfile
    recon_report: "ReconReport | None" = None
    context_complete: bool = True
    unresolved_questions: tuple[str, ...] = ()
    fingerprint: str = ""

    @model_validator(mode="after")
    def validate_fingerprint(self):
        expected = fingerprint(self.model_dump(mode="json", exclude={"fingerprint"}))
        if self.fingerprint and self.fingerprint != expected:
            raise ValueError("PlanningContext fingerprint mismatch")
        if not self.fingerprint:
            object.__setattr__(self,"fingerprint",expected)
        return self


class WorkItemProposal(FrozenModel):
    id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    work_kind: WorkKind
    capability_hints: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    coverage_claims: tuple[str, ...] = ()
    acceptance_intent: tuple[str, ...] = ()


class WorkPlanProposal(FrozenModel):
    items: tuple[WorkItemProposal, ...] = Field(min_length=1)
    rationale: str


class SemanticPlanner:
    """LLM backend may propose only, with no provider roster or execute tools."""

    def __init__(self, backend: ReasoningBackend) -> None:
        self.backend = backend

    async def propose(
        self, *, task: TaskSpec, contract: CompiledTaskContract,
        context: PlanningContext, capability_catalog: tuple[str, ...],
    ) -> WorkPlanProposal:
        # Context gate prevents hallucinated implementation when recon is missing.
        if not context.context_complete:
            raise ValueError("PLANNING_CONTEXT_INCOMPLETE: resolve context before proposal")
        # The model must not receive hidden provider IDs or execution tools.
        content = {
            "task": task.model_dump(mode="json"),
            "contract": contract.model_dump(mode="json"),
            "repository_profile": context.repository_profile.model_dump(mode="json"),
            "context_complete": context.context_complete,
            "unresolved_questions": list(context.unresolved_questions),
            "untrusted_recon_report": (
                context.recon_report.model_dump(mode="json") if context.recon_report else None
            ),
            "semantic_capability_ids": sorted(set(capability_catalog)),
        }
        result = await self.backend.generate_structured(
            purpose="semantic_plan_proposal",
            system_prompt=(
                "Propose bounded work packages using only the semantic capabilities "
                "provided. Your JSON is an untrusted proposal, NOT an executable plan. "
                "Do not invent provider IDs or Runtime-owned __aswe_ gates."
            ),
            data_context=json.dumps(content, sort_keys=True, ensure_ascii=False),
            response_schema=WorkPlanProposal.model_json_schema(),
        )
        return WorkPlanProposal.model_validate(result.data)
