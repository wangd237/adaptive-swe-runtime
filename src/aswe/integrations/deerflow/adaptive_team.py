"""Developer-MVP adaptive topology selection and read-only repo exploration.

This is the first deterministic policy layer, NOT an LLM SemanticPlanner
substitute and NOT a separate Explorer LLM. No execution authority is inferred
from natural-language user text. Tool grants remain in the existing compiler.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

_SOURCE_SUFFIXES = frozenset({".py",".js",".ts",".tsx",".go",".rs",".java"})
_COMPLEX = re.compile(
    r"\b(?:regression|refactor|integration|multiple|cross.module|across|"
    r"root cause|trace|investigate|authentication|endpoint|dependency)\b|"
    r"跨模块|多文件|调用链|定位|排查|重构|回归|多个模块|依赖", re.I)
_SIMPLE = re.compile(r"\b(?:typo|spelling|rename|comment|readme)\b|"
                     r"错别字|拼写|注释|修改文档", re.I)
_PATH = re.compile(r"(?<![\w./])([\w.-]+(?:/[\w.-]+)*\.(?:py|ts|tsx|js|go|rs|java))(?!\w)",re.I)


@dataclass(frozen=True)
class TeamDecision:
    roles: tuple[str, ...]
    reason: str
    complexity: str
    evidence_paths: tuple[str, ...]

    @property
    def needs_exploration(self) -> bool:
        return "explorer" in self.roles


def _tracked_sources(repository: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git","-C",str(repository),"ls-files","-z"],
        capture_output=True,check=True,timeout=10,
    )
    paths = (p.decode("utf-8",errors="replace") for p in result.stdout.split(b"\0") if p)
    return tuple(sorted(p for p in paths
                        if Path(p).suffix in _SOURCE_SUFFIXES
                        and not p.startswith((".git/","node_modules/","vendor/"))))[:2000]


def select_team(task: str, repository: Path) -> TeamDecision:
    """Select minimal developer topology from user task and tracked repository.

    The only non-optional role is coder. Tester is the existing independent
    canonical check; explorer performs actual read-only indexed exploration.
    """
    sources = _tracked_sources(repository)
    matches = tuple(sorted(set(p for p in _PATH.findall(task) if p in sources)))
    complex_words = bool(_COMPLEX.search(task))
    multiple_targets = len(matches) > 1
    unanchored = not matches and len(sources) >= 4 and not _SIMPLE.search(task)
    complex_task = complex_words or multiple_targets or unanchored
    if complex_task:
        return TeamDecision(("explorer","coder","tester"),
                            "cross_module_or_unanchored_task",
                            "medium", matches)
    return TeamDecision(("coder",), "bounded_single_coder_task","low",matches)


def explore_repository(repository: Path, task: str, *, max_files: int = 12) -> tuple[str,...]:
    """Read-only, bounded source discovery. Path metadata only; no code contents.

    Never execute repository scripts or include secret-bearing source text in
    the model prompt. This is an actual Git-index exploration, not role theater.
    """
    sources=_tracked_sources(repository)
    words=set(re.findall(r"[a-z][a-z0-9_]{2,}",task.lower()))
    exact=set(_PATH.findall(task))
    ranked=sorted(sources,key=lambda p:(
        -int(p in exact),
        -sum(w in p.lower() for w in words),
        p))
    return tuple(ranked[:max_files])
