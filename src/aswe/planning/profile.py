"""Immutable bounded repository context (specs/01-task-planning.md §4.2)."""
from __future__ import annotations

from typing import Literal
from pydantic import Field

from aswe.core.contracts._base import FrozenModel


class AnchorMatch(FrozenModel):
    anchor: str = Field(min_length=1)
    match_kind: Literal["path", "symbol", "string", "config", "test"]
    path: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1)
    context: str | None = None


class RepositoryProfile(FrozenModel):
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    tracked_file_count: int = Field(ge=0)
    top_level_tree: tuple[str, ...]
    languages: dict[str, int]
    manifests: tuple[str, ...]
    test_configs: tuple[str, ...]
    build_configs: tuple[str, ...]
    ci_configs: tuple[str, ...]
    guidance_files: tuple[str, ...]
    test_framework_hints: tuple[str, ...]
    build_system_hints: tuple[str, ...]
    task_anchor_matches: tuple[AnchorMatch, ...]
    truncated: bool
