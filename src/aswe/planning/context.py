"""Deterministic planning context gate and strictly read-only Git HEAD Recon.

Recon evidence is informational only: never compiler authority, tool execution,
or an executable work-item. No shell, bash, write tools or external MCP actions.
"""
from __future__ import annotations
from pathlib import Path
from typing import Literal
from pydantic import Field,model_validator
from aswe.core.contracts._base import FrozenModel
from aswe.core.fingerprint import fingerprint
from aswe.planning.analyzer import TaskSpec,TaskType,RiskLevel
from aswe.planning.profile import RepositoryProfile
from aswe.planning.profiler import collect_repository_profile

class ReconFinding(FrozenModel):
    claim: str = Field(min_length=1)
    path: str | None = None
    line_start: int | None = Field(default=None,ge=1)
    line_end: int | None = Field(default=None,ge=1)
    confidence: Literal["observed","inferred"]

    @model_validator(mode="after")
    def checked(self):
        if self.line_end is not None and (self.line_start is None or self.line_end < self.line_start):
            raise ValueError("recon line range invalid")
        return self


class ReconReport(FrozenModel):
    findings: tuple[ReconFinding,...]
    likely_areas: tuple[str,...]
    unresolved_questions: tuple[str,...]


def needs_recon(task:TaskSpec,profile:RepositoryProfile) -> bool:
    if task.planning_uncertainties:
        return True
    if task.repository_level and task.task_type in (
        TaskType.BUG_FIX,TaskType.REFACTOR,TaskType.ARCHITECTURE_CHANGE,
    ):
        if task.complexity.value=="low" and task.risk is RiskLevel.LOW and task.scope_hints:
            return False
        return not bool(profile.task_anchor_matches)
    return False


def deterministic_recon(root:str | Path, *, task:TaskSpec,
                        profile:RepositoryProfile) -> ReconReport:
    # No additional arbitrary tool calls: a second pinned Git HEAD profile
    # confirms freshness and searches only bounded existing target symbols.
    anchors=" ".join(task.scope_hints)
    looked=collect_repository_profile(root,task_text=anchors,base_sha=profile.base_sha)
    finds=tuple(ReconFinding(claim="PRESENT_AT_BASE_SHA",path=m.path,
          line_start=m.line,line_end=m.line,confidence="observed")
          for m in looked.task_anchor_matches)
    qs=tuple(sorted(set(task.planning_uncertainties)))
    if not finds: qs=tuple(sorted(set(qs+("UNRESOLVED_REPOSITORY_CONTEXT",))))
    return ReconReport(findings=finds,
                       likely_areas=tuple(sorted({f.path for f in finds if f.path})),
                       unresolved_questions=qs)


def build_planning_context(*, task:TaskSpec,profile:RepositoryProfile,
                           root:str | Path | None=None):
    from aswe.planning.planner import PlanningContext
    if not needs_recon(task,profile):
        return PlanningContext(repository_profile=profile,context_complete=True)
    report=deterministic_recon(root,task=task,profile=profile) if root is not None else None
    questions=tuple(sorted(set(task.planning_uncertainties+
           (report.unresolved_questions if report else ("RECON_REQUIRED",)))))
    return PlanningContext(repository_profile=profile,recon_report=report,
              context_complete=bool(report and not questions),
              unresolved_questions=questions)
