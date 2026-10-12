"""Evaluation-only, non-authoritative, content-free matched E3 probe.

Run against both frozen Runtime commits. Never changes tool output, status,
model prompts, scheduling, or independent acceptance. No raw commands logged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex

from aswe.integrations.deerflow.controlled_swe import ControlledSWEWorkspace
from scripts.step7d_real_issue_eval import main as run_original

COUNTS = {
    "recognized_test_commands": 0,
    "recognized_passing_tests_after_edit": 0,
    "recognized_failing_tests_after_edit": 0,
    "post_pass_bash_calls": 0,
    "post_pass_non_test_bash_calls": 0,
    "post_pass_test_bash_calls": 0,
    "post_pass_read_file_calls": 0,
    "post_pass_source_edits": 0,
    "tracked_source_edits": 0,
}
STATE = {}


def is_simple_test(command: str) -> bool:
    # Same deliberately conservative classification for both versions.
    if not isinstance(command, str) or len(command) > 4096:
        return False
    if any(ch in command for ch in (";", "|", "&", ">", "<", "\n", "\r", "`", "$")):
        return False
    try:
        args = shlex.split(command)
    except ValueError:
        return False
    if not args:
        return False
    exe = args[0].rsplit("/", 1)[-1]
    if exe in ("pytest", "py.test"):
        tail = args[1:]
    elif exe in ("python", "python3"):
        idx = 2 if len(args) >= 3 and args[1] == "-m" else (
            3 if len(args) >= 4 and args[1:3] == ["-B", "-m"] else -1
        )
        if idx < 0 or args[idx] not in ("pytest", "unittest"):
            return False
        tail = args[idx + 1:]
    else:
        return False
    return not any(x in {
        "--collect-only", "--co", "--help", "-h", "--version", "-V",
        "--fixtures", "--fixtures-per-test", "--markers", "--trace-config",
    } for x in tail)


def state(obj):
    return STATE.setdefault(id(obj), {"passed_since_last_edit": False, "ever_edited": False})


_original_write = ControlledSWEWorkspace._write
_original_read = ControlledSWEWorkspace.read_file
_original_bash = ControlledSWEWorkspace.bash


def observed_write(self, *args, **kwargs):
    result = _original_write(self, *args, **kwargs)
    item = state(self)
    if item["passed_since_last_edit"]:
        COUNTS["post_pass_source_edits"] += 1
    item["ever_edited"] = True
    item["passed_since_last_edit"] = False
    COUNTS["tracked_source_edits"] += 1
    return result


async def observed_read(self, *args, **kwargs):
    result = await _original_read(self, *args, **kwargs)
    if state(self)["passed_since_last_edit"]:
        COUNTS["post_pass_read_file_calls"] += 1
    return result


async def observed_bash(self, *, command: str):
    category_test = is_simple_test(command)
    result = await _original_bash(self, command=command)
    item = state(self)
    if item["passed_since_last_edit"]:
        COUNTS["post_pass_bash_calls"] += 1
        COUNTS["post_pass_test_bash_calls" if category_test else "post_pass_non_test_bash_calls"] += 1
    if category_test:
        COUNTS["recognized_test_commands"] += 1
        if item["ever_edited"]:
            if result.startswith("exit_code=0; timed_out=False\n"):
                COUNTS["recognized_passing_tests_after_edit"] += 1
                item["passed_since_last_edit"] = True
            else:
                COUNTS["recognized_failing_tests_after_edit"] += 1
    return result


ControlledSWEWorkspace._write = observed_write
ControlledSWEWorkspace.read_file = observed_read
ControlledSWEWorkspace.bash = observed_bash

code = run_original()
report = Path(os.environ["ASWE_STEP7D_EVAL_REPORT_PATH"])
if report.is_file():
    data = json.loads(report.read_text(encoding="utf-8"))
    data["step7de3_post_test_proxy"] = {
        "method": "same-evaluation-only-wrapper-on-both-runtimes",
        "scope": "simple_python_unittest_or_pytest_after_tracked_file_edit",
        "limitation": "compound_shell_and_bash_modified_files_not_recognized;non_test_work_not_necessarily_waste",
        **COUNTS,
    }
    report.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
raise SystemExit(code)
