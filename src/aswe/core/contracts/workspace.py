from enum import Enum
from ._base import FrozenModel

class WorkspaceAccess(str, Enum):
    READ = "read"
    WRITE = "write"

class WorkspaceRevision(FrozenModel):
    generation: int
    base_sha: str
    head_sha: str
    head_matches_baseline: bool
    repository_state_fingerprint: str
    dirty: bool

class ExecutionCompleteness(str, Enum):
    UNCAPPED = "uncapped"
    CAPPED = "capped"
