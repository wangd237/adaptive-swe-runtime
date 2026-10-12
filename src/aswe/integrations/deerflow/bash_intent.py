"""Conservative host interpretation of SIMPLE Bash invocations.

Advisory classification, never sandbox authorization and never evidence of
independent canonical verification. Unknown/compound commands fail closed.
"""
from __future__ import annotations

import shlex
from typing import Any


def classify_bash(argument: Any) -> str:
    command = argument.get("command") if isinstance(argument, dict) else None
    if not isinstance(command, str) or not command or len(command) > 4096:
        return "other"
    # Quotes do not make shell operators safe to interpret. Conservative:
    # drop ambiguous commands rather than invent a test verdict.
    if any(ch in command for ch in (";", "|", "&", ">", "<", "\n", "\r", "`", "$")):
        return "other"
    try:
        args = shlex.split(command)
    except ValueError:
        return "other"
    if not args:
        return "other"
    command_name = args[0].rsplit("/", 1)[-1]
    args_after = args[1:]
    if command_name in ("python", "python3") and len(args) >= 3:
        module_at = (2 if args[1] == "-m"
                     else 3 if len(args) >= 4 and args[1:3] == ["-B", "-m"]
                     else -1)
        if module_at > 0 and args[module_at] in ("pytest", "unittest"):
            args_after = args[module_at + 1:]
            command_name = args[module_at]
    if command_name in ("pytest", "py.test", "unittest"):
        # Collection, help and diagnostics are NOT a passing test.
        informational = {
            "-h", "--help", "--version", "-V", "--collect-only",
            "--fixtures", "--fixtures-per-test", "--markers", "--trace-config",
            "--co", "--durations", "help",
        }
        if any(item in informational for item in args_after):
            return "other"
        # An empty pytest invocation can be an actual test discovery run.
        return "test_like"
    if command_name in ("grep", "rg", "find", "ls", "cat", "sed", "head", "tail"):
        return "search_like"
    if command_name == "git" and args_after and args_after[0] in (
        "status", "diff", "show", "log",
    ):
        return "inspect_like"
    return "other"
