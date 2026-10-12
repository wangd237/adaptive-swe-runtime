"""Host-only conservative Bash intent and non-authoritative shell diagnostics.

classify_bash retains the E1 strict *single-command* authority: compound
shell expressions NEVER become agent test pass/fail or RepairFeedback.
inspect_bash only counts evident syntactic steps for diagnostics; it does
not execute shell grammar, infer outcomes, persist arguments, or change tools.
"""
from __future__ import annotations

import re
import shlex
from typing import Any


_INFORMATIONAL = frozenset({
    "-h", "--help", "--version", "-V", "--collect-only",
    "--fixtures", "--fixtures-per-test", "--markers",
    "--trace-config", "--co", "--durations", "help",
})


def _classify_argv(args: list[str]) -> str:
    if not args:
        return "other"
    name = args[0].rsplit("/", 1)[-1]
    tail = args[1:]
    if name in ("python", "python3") and len(args) >= 3:
        module_at = (
            2 if args[1] == "-m"
            else 3 if len(args) >= 4 and args[1:3] == ["-B", "-m"]
            else -1
        )
        if module_at > 0 and args[module_at] in ("pytest", "unittest"):
            tail = args[module_at + 1:]
            name = args[module_at]
    if name in ("pytest", "py.test", "unittest"):
        return "other" if any(item in _INFORMATIONAL for item in tail) else "test_like"
    if name in ("grep", "rg", "find", "ls", "cat", "sed", "head", "tail"):
        return "search_like"
    if name == "git" and tail and tail[0] in ("status", "diff", "show", "log"):
        return "inspect_like"
    return "other"


def classify_bash(argument: Any) -> str:
    """E1 authority remains a single, unambiguous, simple Bash command."""
    command = argument.get("command") if isinstance(argument, dict) else None
    if not isinstance(command, str) or not command or len(command) > 4096:
        return "other"
    if any(ch in command for ch in (";", "|", "&", ">", "<", "\n", "\r", chr(96), "$")):
        return "other"
    try:
        args = shlex.split(command)
    except ValueError:
        return "other"
    return _classify_argv(args)


def _script_family(command: Any) -> str:
    """Fixed safe diagnostic label; inline script BODY is never inspected."""
    if not isinstance(command, str):
        return "unknown"
    start = command.lstrip()
    python_cmd = r"(?:python|python3|python3[.]12|/usr/bin/python3?)"
    if re.match(r"^" + python_cmd + r"\s+(?:-B\s+)?-\s*<<", start):
        return "python_heredoc"
    if re.match(r"^" + python_cmd + r"\s+(?:-B\s+)?-c(?:\s|$)", start):
        return "python_inline"
    if re.match(r"^(?:bash|sh)\s+-c(?:\s|$)", start):
        return "nested_shell"
    if "\n" in command or "\r" in command:
        return "multiline"
    return "ordinary"


def inspect_bash(argument: Any) -> dict[str, object]:
    """Read-only command *shape*, not shell-execution or verdict authority.

    Only limited common POSIX separators are observed. Shell expansions,
    redirections, background commands, unknown grammar and malformed input
    fail closed. Do not infer whether a subcommand actually executed:
    &&, ||, and pipes make individual return codes non-attributable.
    No shell strings, argv, raw output, paths or hashes are returned.
    """
    unknown = {
        "shape": "unknown", "family": _script_family(argument.get("command") if isinstance(argument, dict) else None),
        "step_count": 0, "contains_test_step": False,
        "contains_search_step": False, "contains_inspect_step": False,
        "test_verdict_attributable": False,
    }
    command = argument.get("command") if isinstance(argument, dict) else None
    if (not isinstance(command, str) or not command or len(command) > 4096
            or any(ch in command for ch in ("\n", "\r", chr(96), "$", "\x00"))):
        return dict(unknown)
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except (ValueError, TypeError):
        return dict(unknown)
    if not tokens or len(tokens) > 128:
        return dict(unknown)
    separators = {"&&", "||", ";", "|"}
    # Commands with redirection, backgrounding or nonstandard shell operators
    # are intentionally unknown; no partial "test passed" inference.
    if any(t in {"<", ">", ">>", "<<", "&", "|&", ">&", "<&"}
           or (t and all(c in ";&|<>" for c in t) and t not in separators)
           for t in tokens):
        return dict(unknown)
    chunks: list[list[str]] = [[]]
    for item in tokens:
        if item in separators:
            if not chunks[-1] or len(chunks) >= 16:
                return dict(unknown)
            chunks.append([])
        else:
            chunks[-1].append(item)
    if not chunks[-1]:
        return dict(unknown)
    kinds = [_classify_argv(part) for part in chunks]
    # An isolated, E1-accepted test is the only attributable agent test.
    isolated = len(chunks) == 1 and classify_bash(argument) == "test_like"
    return {
        "shape": "single" if len(chunks) == 1 else "compound",
        "family": _script_family(command),
        "step_count": len(chunks),
        "contains_test_step": "test_like" in kinds,
        "contains_search_step": "search_like" in kinds,
        "contains_inspect_step": "inspect_like" in kinds,
        "test_verdict_attributable": isolated,
    }
