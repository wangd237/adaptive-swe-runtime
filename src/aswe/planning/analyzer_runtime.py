"""Structured TaskAnalyzer and deterministic post-model rule validation."""
from __future__ import annotations
import json
import re
from pydantic import BaseModel
from aswe.core.contracts._base import FrozenModel
from aswe.planning.analyzer import TaskSpec, TaskType, ReasoningBackend, RiskLevel
from aswe.planning.contracts import TaskRequestEnvelope, TaskContractDraft
from aswe.planning.profile import RepositoryProfile

class TaskAnalysis(FrozenModel):
    spec: TaskSpec
    draft: TaskContractDraft


def validate_task_analysis(
    analysis: TaskAnalysis, *, request: TaskRequestEnvelope,
    profile: RepositoryProfile,
) -> TaskAnalysis:
    spec=analysis.spec
    hints=set(spec.capability_hints)
    uncertainties=set(spec.planning_uncertainties)
    text=request.raw_text.lower()
    if spec.task_type is TaskType.BUG_FIX:
        hints.add("code_modification")  # HINT only, never authority
    regression=bool(re.search(r"\b(regression tests?|regression testing|run regression)\b|回归测试",text))
    explicit_file=tuple(m.anchor for m in profile.task_anchor_matches if m.match_kind=="path")
    if regression and not spec.testing_required:
        spec=spec.model_copy(update={"testing_required":True})
    if spec.risk is RiskLevel.HIGH and not spec.review_required:
        spec=spec.model_copy(update={"review_required":True})
    for anchor in re.findall(r"(?<!\w)[A-Za-z_][\w./-]*\.(?:py|ts|go|rs)(?!\w)",request.raw_text):
        if not any(m.anchor==anchor for m in profile.task_anchor_matches):
            uncertainties.add("UNRESOLVED_TARGET:"+anchor)
    scopes=set(spec.scope_hints)|set(explicit_file)
    spec=spec.model_copy(update={
        "capability_hints":tuple(sorted(hints)),
        "planning_uncertainties":tuple(sorted(uncertainties)),
        "scope_hints":tuple(sorted(scopes)),
    })
    return TaskAnalysis(spec=spec,draft=analysis.draft)


class TaskAnalyzer:
    def __init__(self,backend:ReasoningBackend):
        self.backend=backend

    async def analyze(self, *, request:TaskRequestEnvelope,
                      profile:RepositoryProfile) -> TaskAnalysis:
        result=await self.backend.generate_structured(
            purpose="task_analyzer",
            system_prompt=("Return TaskSpec and candidate-only TaskContractDraft. "
                           "Do not claim enforcement or execution permission."),
            data_context=json.dumps({"request":request.model_dump(mode="json"),
                  "profile":profile.model_dump(mode="json")},sort_keys=True),
            response_schema=TaskAnalysis.model_json_schema(),
        )
        return validate_task_analysis(
            TaskAnalysis.model_validate(result.data),request=request,profile=profile,
        )
