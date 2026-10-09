"""Single authoritative ConstraintEnforcement shared by compiler and evaluator."""
from enum import Enum


class ConstraintEnforcement(str, Enum):
    LOCKED = "locked"
    HARD = "hard"
    SOFT = "soft"
