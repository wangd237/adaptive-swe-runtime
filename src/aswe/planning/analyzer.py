"""Task analysis data and provider-neutral structured ReasoningBackend."""
from __future__ import annotations

from enum import Enum
from typing import Any, Protocol

from pydantic import Field

from aswe.core.contracts._base import FrozenModel
from aswe.planning.immutable import deep_freeze
from pydantic import model_validator


class TaskType(str, Enum):
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    ARCHITECTURE_CHANGE = "architecture_change"
    TEST = "test"
    DOCUMENTATION = "documentation"
    ANALYSIS = "analysis"
    OTHER = "other"


class Complexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskSpec(FrozenModel):
    task_type: TaskType
    description: str = Field(min_length=1)
    domains: tuple[str, ...]
    repository_level: bool
    complexity: Complexity
    risk: RiskLevel
    # Hints only: cannot authorize repository mutation, tools, or final gates.
    testing_required: bool
    review_required: bool
    scope_hints: tuple[str, ...]
    capability_hints: tuple[str, ...]
    planning_uncertainties: tuple[str, ...]


class StructuredReasoningResult(FrozenModel):
    data: dict[str, Any]
    model_role: str | None = None
    provider_model: str | None = None
    usage: dict[str, int | float] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def freeze_payload(self):
        object.__setattr__(self,"data",deep_freeze(self.data))
        object.__setattr__(self,"usage",deep_freeze(self.usage))
        return self


class ReasoningBackend(Protocol):
    async def generate_structured(
        self, *, purpose: str, system_prompt: str, data_context: str,
        response_schema: dict[str, Any], model_role: str | None = None,
    ) -> StructuredReasoningResult: ...
