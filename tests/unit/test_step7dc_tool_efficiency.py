"""Step 7D-C host-observed tool-efficiency diagnostics and soft hints."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aswe.integrations.deerflow.tool_guard import _bash_category
from aswe.trace.minimal_events import LocalRuntimeEventSink
from aswe.trace.reliability import summarize_execution_trace
from tests.unit.test_deerflow_tool_guard_step5d import (
    bind_during_scheduler,
    record_async,
)
from tests.unit.test_deerflow_controlled_swe_step5fc import env
from tests.unit.test_node_workspace_delta import repository as repository_fixture


@pytest.mark.parametrize(("argument", "expected"), [
    ({"command": "python -B -m unittest tests.test_calc -q"}, "test_like"),
    ({"command": "python -m pytest tests/test_calc.py"}, "test_like"),
    ({"command": "rg -n MultiReplace boltons/strutils.py"}, "search_like"),
    ({"command": "ls -l"}, "search_like"),
    ({"command": "python -m unittest; echo x"}, "other"),
    ({"command": "pytest | cat"}, "other"),
    ({"command": "cat $SECRET"}, "other"),
    ({"command": "python -c 'print(42)'"}, "other"),
    ({"not_command": "python -m unittest"}, "other"),
    ({"command": 42}, "other"),
])
def test_only_conservative_advisory_bash_categories(argument, expected):
    assert _bash_category(argument) == expected


@pytest.mark.asyncio
async def test_identical_tool_args_are_observed_without_skipping_calls(tmp_path):
    result, store, _, _, _, _, tool, _, inv = await bind_during_scheduler(tmp_path)
    gate = result["binding"].guard
    sink = LocalRuntimeEventSink(tmp_path / "safe-observability", inv.task_id)
    gate.trace_sink = sink
    calls = []
    secret = "private-path-OR-KEY-never-export"
    args = {"path": secret}
    for i in range(2):
        assert await gate.ainvoke(
            tool=tool, tool_call_id=f"repeat-{i}", tool_input=args,
            handler=lambda: record_async(calls, "fresh"),
        ) == "fresh"
    assert len(calls) == 2
    events = sink.read_all()
    receipt_events = [event for event in events if event.event_type == "tool.call.finished"]
    assert len(receipt_events) == 2
    assert [x.payload["repeated_exact_arguments"] for x in receipt_events] == [False, True]
    assert all(type(x.payload["duration_ms"]) is int
               and x.payload["duration_ms"] >= 0 for x in receipt_events)
    aggregate = summarize_execution_trace(events)
    assert aggregate["repeated_exact_argument_calls"] == 1
    assert aggregate["repeated_bash_argument_calls"] == 0
    assert aggregate["tool_duration_observed_calls"] == 2
    assert secret not in json.dumps(aggregate)
    assert secret not in sink.path.read_text()
    store.release(inv.execution_id)


@pytest.mark.asyncio
async def test_repeated_bash_executes_fresh_and_never_fakes_verification(repository_fixture):
    workspace, sandbox = env(repository_fixture)
    (Path(repository_fixture.repository_root) / "calc.py").write_text("def calc():\n    return 1\n")
    await workspace.read_file(path="calc.py")
    await workspace.str_replace(path="calc.py", old_str="return 1", new_str="return 42")

    command = "python -B -m unittest tests.test_calc -q"
    first = await workspace.bash(command=command)
    second = await workspace.bash(command=command)
    assert len(sandbox.commands) == 2
    assert "Efficiency hint:" not in first
    assert "Efficiency hint:" in second
    assert "this is a fresh result" in second
    assert first.startswith("exit_code=0; timed_out=False\n")
    assert second.startswith("exit_code=0; timed_out=False\n")
    assert "Completion hint:" in first
    assert "NOT host acceptance" in first


@pytest.mark.asyncio
async def test_no_passing_test_hint_without_patch_or_unambiguous_test(repository_fixture):
    workspace, sandbox = env(repository_fixture)
    no_patch = await workspace.bash(command="python -m unittest -q")
    assert "Completion hint:" not in no_patch
    (Path(repository_fixture.repository_root) / "calc.py").write_text("abc")
    await workspace.read_file(path="calc.py")
    await workspace.str_replace(path="calc.py", old_str="abc", new_str="xyz")
    compound = await workspace.bash(command="python -m unittest -q; echo ignore")
    assert "Completion hint:" not in compound
    assert len(sandbox.commands) == 2


def test_summary_defaults_do_not_invent_tool_efficiency_savings():
    result = summarize_execution_trace(())
    assert result["repeated_exact_argument_calls"] == 0
    assert result["tool_duration_observed_calls"] == 0
    assert result["tool_duration_max_ms"] is None
    assert result["bash_category_counts"] == {}
