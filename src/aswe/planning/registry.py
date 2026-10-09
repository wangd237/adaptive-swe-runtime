"""P1 small typed constraint registry; no user-supplied arbitrary DSL.

The source quote parser accepts a deliberately narrow declaration format.
A model candidate's key/operator/value cannot override the parsed directive.
"""
from __future__ import annotations

from enum import Enum
import re

from pydantic import Field

from aswe.core.contracts._base import FrozenModel


class DeliverableEffect(str, Enum):
    REPORT_ONLY = "report_only"
    REPOSITORY_MUTATION = "repository_mutation"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"


class DeliverableRequirement(FrozenModel):
    description: str = Field(min_length=1)
    effect: DeliverableEffect


class ConstraintSpec(FrozenModel):
    key: str
    merge_strategy: str
    verification_mode: str


CONSTRAINT_REGISTRY: dict[str, ConstraintSpec] = {
    k: ConstraintSpec(key=k, merge_strategy=merge, verification_mode=mode)
    for k, merge, mode in (
        ("deliverables.required", "union", "semantic"),
        ("repo.paths.allowed", "intersection", "deterministic"),
        ("repo.paths.forbidden", "union", "deterministic"),
        ("actions.forbidden", "union", "deterministic"),
        ("verification.required", "union", "deterministic"),
        ("review.required", "union", "deterministic"),
        ("change.max_files", "minimum", "deterministic"),
        ("target.exact_path", "exact", "deterministic"),
        ("preference.test_command", "priority", "semantic"),
        ("semantic.requirement", "union", "semantic"),
    )
}
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_./*:@+-]+$")
_SAFE_PATH = re.compile(r"^[A-Za-z0-9_./*-]+$")


def normalize_path(path: str, *, pattern: bool = False) -> str:
    """Only an exact repo-relative POSIX path or an anchored subtree/** scope."""
    if not isinstance(path, str) or not path or "\\" in path:
        raise ValueError("invalid relative path")
    cleaned = path.removeprefix("./")
    if (cleaned.startswith("/") or "//" in cleaned or
            any(x in (".", "..", "") for x in cleaned.split("/"))):
        raise ValueError("unsafe relative path")
    if not _SAFE_PATH.fullmatch(cleaned):
        raise ValueError("unsupported path expression")
    if cleaned == "**":
        if pattern:
            return cleaned
        raise ValueError("exact path required")
    if not pattern and "*" in cleaned:
        raise ValueError("exact path cannot contain glob")
    if pattern and "*" in cleaned and not (
        cleaned.endswith("/**") and "*" not in cleaned[:-3]
    ):
        raise ValueError("unsupported glob scope; cannot prove containment")
    return cleaned


def _items(raw: object, *, paths: bool = False) -> tuple[str, ...]:
    if isinstance(raw, str):
        tokens = [t.strip() for t in raw.split(",")]
    elif isinstance(raw, (tuple, list, set, frozenset)):
        tokens = list(raw)
    else:
        raise ValueError("expected set of strings")
    if not tokens or any(not isinstance(v, str) or not v.strip() for v in tokens):
        raise ValueError("empty or non-string set item")
    normalized = [
        normalize_path(v.strip(), pattern=True) if paths else v.strip()
        for v in tokens
    ]
    if not paths and any(not _SAFE_TOKEN.fullmatch(x) for x in normalized):
        raise ValueError("unsafe forbidden action / requirement name")
    return tuple(sorted(set(normalized)))


def canonical_value(key: str, value: object) -> object:
    """Raise instead of guessing for malformed recognized hard constraints."""
    if key not in CONSTRAINT_REGISTRY:
        raise ValueError("unknown typed constraint key: " + key)
    if key in ("repo.paths.allowed", "repo.paths.forbidden"):
        return _items(value, paths=True)
    if key in ("actions.forbidden", "verification.required"):
        return _items(value)
    if key == "deliverables.required":
        raw = (value,) if isinstance(value, (dict, DeliverableRequirement)) else value
        if not isinstance(raw, (tuple, list)) or not raw:
            raise ValueError("deliverable requirement list required")
        deliverables = [
            d if isinstance(d, DeliverableRequirement) else DeliverableRequirement.model_validate(d)
            for d in raw
        ]
        return tuple(sorted(set(deliverables), key=lambda d: (d.effect.value, d.description)))
    if key == "review.required":
        if type(value) is not bool:
            raise ValueError("review.required must be boolean")
        return value
    if key == "change.max_files":
        if type(value) is not int or value < 0:
            raise ValueError("change.max_files must be a nonnegative integer")
        return value
    if key == "target.exact_path":
        return normalize_path(value)
    if key == "preference.test_command":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("nonempty preference required")
        return value.strip()
    if key == "semantic.requirement":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("semantic requirement must be nonempty text")
        return value.strip()
    raise AssertionError(key)


def parse_exact_user_directive(quote: str) -> tuple[str, object] | None:
    """Only literal 'known.key: value' can supply structured user authority.

    Quoted prose, a model-generated value field, or partial snippets do not
    authorize repository mutation. All such requirements stay semantic HARD.
    """
    if ": " not in quote:
        return None
    key, raw = quote.split(": ", 1)
    if key not in CONSTRAINT_REGISTRY:
        return None
    raw = raw.strip()
    if key == "deliverables.required":
        if " | " not in raw:
            raise ValueError("deliverable syntax is 'effect | description'")
        effect, description = raw.split(" | ", 1)
        return key, canonical_value(key, DeliverableRequirement(
            effect=DeliverableEffect(effect), description=description,
        ))
    if key == "review.required":
        if raw not in ("true", "false"):
            raise ValueError("expected true/false")
        return key, canonical_value(key, raw == "true")
    if key == "change.max_files":
        if not re.fullmatch(r"[0-9]+", raw):
            raise ValueError("expected numeric max_files")
        return key, canonical_value(key, int(raw))
    return key, canonical_value(key, raw)
