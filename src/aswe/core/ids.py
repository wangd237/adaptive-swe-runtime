from __future__ import annotations
import re
from uuid import uuid4

SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

def validate_safe_id(value: str) -> str:
    if not SAFE_ID_PATTERN.fullmatch(value):
        raise ValueError(f"unsafe runtime id: {value!r}")
    return value

def new_safe_id(prefix: str) -> str:
    validate_safe_id(prefix)
    return validate_safe_id(f"{prefix}-{uuid4().hex}")

def new_task_id() -> str: return new_safe_id("aswe-task")
def new_execution_id() -> str: return new_safe_id("aswe-exec")
def new_run_id() -> str: return new_safe_id("aswe-run")
def new_preparation_id() -> str: return new_safe_id("aswe-prep")
def new_finalization_id() -> str: return new_safe_id("aswe-final")
def new_evidence_id() -> str: return new_safe_id("aswe-evidence")
