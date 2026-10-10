"""Bounded LLM team planning for the developer workflow.

A proposed topology is *advisory*: it cannot change tool permissions,
verification commands, model credentials or trusted execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from aswe.integrations.deerflow.adaptive_team import (
    TeamDecision, explore_repository, select_team,
)


class ProposedTeam(BaseModel):
    model_config = ConfigDict(extra="forbid")
    needs_explorer: bool
    coder_objective: str = Field(min_length=1, max_length=1600)
    explorer_objective: str = Field(default="", max_length=800)
    rationale: str = Field(min_length=1, max_length=600)


@dataclass(frozen=True)
class PlannedTeam:
    decision: TeamDecision
    coder_objective: str
    explorer_objective: str
    planning_mode: str


async def plan_developer_team(
    *, task: str, repository: Path, mode: str = "rules",
    planner_factory: Callable[[], Any] | None = None,
) -> PlannedTeam:
    if mode not in ("rules", "llm"):
        raise ValueError("UNSUPPORTED_DEV_PLANNER_MODE")
    fallback = select_team(task, repository)
    if mode == "rules":
        return PlannedTeam(fallback, task, task, "rules")

    # The planner receives names only, not source text, secrets or tool
    # credentials. It cannot select a free-form agent roster.
    candidates = explore_repository(repository, task, max_files=20)
    if planner_factory is None:
        if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("ASWE_MODEL"):
            raise ValueError("ASWE_MODEL_OR_OPENAI_API_KEY_MISSING")
        from langchain_openai import ChatOpenAI
        options: dict[str, Any] = {
            "model": os.environ["ASWE_MODEL"], "temperature": 0,
            "timeout": 60, "max_retries": 0,
        }
        if os.environ.get("ASWE_BASE_URL"):
            options["base_url"] = os.environ["ASWE_BASE_URL"]
        planner = ChatOpenAI(**options)
    else:
        planner = planner_factory()

    system = (
        "You are an SWE task planner. Return a structured plan. Choose "
        "needs_explorer only if code discovery would materially help. "
        "coder_objective must describe an achievable coding task without "
        "inventing file paths. explorer_objective describes read-only search. "
        "Never alter test acceptance, runtime policy, or tool permissions."
    )
    user = ("User task:\n" + task[:12000] +
            "\n\nTracked source candidates (names only):\n" +
            "\n".join(candidates))
    structured = planner.with_structured_output(ProposedTeam)
    raw = await structured.ainvoke([
        ("system", system), ("human", user)
    ])
    proposal = (raw if isinstance(raw, ProposedTeam)
                else ProposedTeam.model_validate(raw))
    roles = ("explorer", "coder", "tester") if proposal.needs_explorer else ("coder",)
    reason = "llm_proposed_exploration" if proposal.needs_explorer else "llm_proposed_direct_coding"
    decision = TeamDecision(roles=roles, reason=reason,
                            complexity="medium" if proposal.needs_explorer else "low",
                            evidence_paths=fallback.evidence_paths)
    # Runtime preserves the original user requirement regardless of proposal.
    objective = task + "\n\nImplementation focus: " + proposal.coder_objective
    return PlannedTeam(decision, objective,
                       proposal.explorer_objective or task, "llm")
