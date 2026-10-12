"""Step 7D-E: true test semantics, model timings, budget-aware hints.

All hints are advisory; model-authored Bash is NOT independent verification.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aswe.integrations.deerflow.bash_intent import classify_bash
from aswe.integrations.deerflow.native_execution import _HostModelTimingCallback
from aswe.trace.minimal_events import LocalRuntimeEventSink
from aswe.trace.reliability import summarize_execution_trace
from tests.unit.test_deerflow_controlled_swe_step5fc import env
from tests.unit.test_deerflow_tool_guard_step5d import bind_during_scheduler
from tests.unit.test_node_workspace_delta import repository as repository_fixture


@pytest.mark.parametrize(("command", "expected"), [
    ("python -B -m unittest tests.test_x -q", "test_like"),
    ("python -m pytest tests/test_x.py", "test_like"),
    ("pytest -q", "test_like"),
    ("pytest --collect-only", "other"),
    ("pytest --help", "other"),
    ("python -m unittest --help", "other"),
    ("grep -n MultiReplace a.py", "search_like"),
    ("git diff --stat", "inspect_like"),
    ("git status --short", "inspect_like"),
    ("python -m unittest -q && echo ok", "other"),
    ("python -c 'print(1)'", "other"),
    ("ls -la", "search_like"),
    ("cat foo.py", "search_like"),
    ("python -B -m unittest -q | cat", "other"),
])
def test_bash_intent_never_equates_generic_success_with_tests(command, expected):
    assert classify_bash({"command": command}) == expected


@pytest.mark.asyncio
async def test_tool_guard_marks_only_real_test_invocations_as_agent_test(tmp_path):
    result, store, _, _, _, _, _, _, invocation = await bind_during_scheduler(tmp_path)
    guard = result["binding"].guard
    sink = LocalRuntimeEventSink(tmp_path/"semantic-trace", invocation.task_id)
    guard.trace_sink = sink
    outputs = [
        ("ls -la", "exit_code=0; timed_out=False\nfiles", "completed"),
        ("grep something foo.py", "exit_code=1; timed_out=False\n", "completed"),
        ("pytest --collect-only", "exit_code=0; timed_out=False\n", "completed"),
        ("python -B -m unittest -q", "exit_code=1; timed_out=False\nFAILED", "completed"),
        ("python -B -m unittest -q", "exit_code=0; timed_out=False\nOK", "completed"),
        ("python -m unittest -q && echo ignore", "exit_code=0; timed_out=False\n", "completed"),
    ]
    for index, (command, output, status) in enumerate(outputs):
        guard._record(
            name="bash", call_id=f"sem-{index}", argument={"command":command},
            status=status, result=output, duration_ms=index + 1,
        )
    events = sink.read_all()
    observations = [e.payload for e in events if e.event_type=="agent.test.observed"]
    feedback = [e.payload for e in events if e.event_type=="repair.feedback.available"]
    assert [x["passed"] for x in observations] == [False,True]
    assert len(feedback)==1 and feedback[0]["source"]=="agent_bash"
    assert feedback[0]["authority"]=="agent_observed_only"
    assert guard._dev_failed_checks == 1
    summary = summarize_execution_trace(events)
    assert summary["bash_category_counts"]["test_like"] == 2
    assert summary["bash_category_counts"]["search_like"] == 2
    assert summary["bash_category_counts"]["other"] == 2
    store.release(invocation.execution_id)


@pytest.mark.asyncio
async def test_progress_hints_only_with_host_turns_and_current_edit_test(repository_fixture):
    workspace, sandbox = env(repository_fixture)
    root=Path(repository_fixture.repository_root)
    (root/"calc.py").write_text("def f():\n    return 1\n")
    assert workspace.host_observed_progress_phase()=="exploring"
    await workspace.read_file(path="calc.py")
    await workspace.str_replace(path="calc.py", old_str="return 1", new_str="return 42")
    assert workspace.host_observed_progress_phase()=="code_modified"
    workspace.record_native_model_turn(35, 40)
    ordinary = await workspace.bash(command="git diff --stat")
    assert "Completion hint" not in ordinary and "Budget hint" not in ordinary
    passing = await workspace.bash(command="python -B -m unittest -q")
    assert "Completion hint" in passing
    assert workspace.host_observed_progress_phase()=="agent_check_passed"
    assert "Budget hint" not in passing
    workspace.record_native_model_turn(37, 40)
    soon = await workspace.bash(command="git status --short")
    assert "Budget hint" in soon
    assert "latest source edit has an agent-run passing test" in soon
    later = await workspace.bash(command="git diff")
    assert "Budget hint" not in later
    await workspace.read_file(path="calc.py")
    await workspace.str_replace(path="calc.py", old_str="return 42", new_str="return 43")
    assert workspace.host_observed_progress_phase()=="code_modified"
    workspace.record_native_model_turn(38, 40)
    changed = await workspace.bash(command="git status")
    assert "Budget hint" in changed
    assert "Prioritize a focused verification" in changed
    assert "latest source edit has an agent-run passing test" not in changed


@pytest.mark.asyncio
async def test_progress_hint_does_not_accept_model_controlled_budget(repository_fixture):
    workspace, sandbox = env(repository_fixture)
    assert workspace._observed_model_round == 0
    workspace.record_native_model_turn(-1, 40)
    workspace.record_native_model_turn(41, 40)
    workspace.record_native_model_turn(1, 10**9)
    assert workspace._observed_model_round == 0
    (Path(repository_fixture.repository_root)/"f.py").write_text("from math import pi")
    await workspace.read_file(path="f.py")
    await workspace.str_replace(path="f.py",old_str="pi",new_str="tau")
    out = await workspace.bash(command="python -B -m unittest -q")
    assert "Budget hint" not in out
    assert "Completion hint" in out


@pytest.mark.asyncio
async def test_real_model_request_callback_records_duration_without_payload(tmp_path):
    secret = "PRIVATE_LLM_REQUEST_TEXT_SHOULD_NEVER_BE_STORED"
    sink=LocalRuntimeEventSink(tmp_path/"llm-time", "case")
    binding=SimpleNamespace(
        invocation=SimpleNamespace(execution_id="native-exec",attempt=1,node_id="coder"),
        guard=SimpleNamespace(trace_sink=sink),
    )
    timer=_HostModelTimingCallback(binding)
    await timer.on_chat_model_start({"secret":secret},[[secret]],run_id="llm-1")
    await asyncio.sleep(0)
    await timer.on_llm_end(SimpleNamespace(raw_secret=secret),run_id="llm-1")
    await timer.on_llm_start({"secret":secret},[secret],run_id="llm-2")
    await timer.on_llm_error(RuntimeError(secret),run_id="llm-2")
    events=sink.read_all()
    assert [e.payload["status"] for e in events] == ["completed","failed"]
    assert all(type(e.payload["duration_ms"]) is int for e in events)
    summary=summarize_execution_trace(events)
    assert summary["model_request_observed_count"]==2
    assert summary["model_request_failed_count"]==1
    assert summary["model_request_duration_total_ms"]>=0
    assert summary["model_progress_phase_counts"]=={}
    assert secret not in sink.path.read_text()
    assert secret not in json.dumps(summary)


@pytest.mark.asyncio
async def test_failed_recognized_test_and_stale_result_never_count_as_passing(repository_fixture):
    from aswe.integrations.deerflow.controlled_swe import ShellOutcome
    workspace, sandbox = env(repository_fixture)
    root=Path(repository_fixture.repository_root)
    (root/"calc.py").write_text("old")
    await workspace.read_file(path="calc.py")
    await workspace.str_replace(path="calc.py", old_str="old", new_str="new")
    async def failed_run(command, *, timeout, max_output):
        return ShellOutcome(exit_code=1, timed_out=False, output="FAILED")
    sandbox.run = failed_run
    workspace.record_native_model_turn(38,40)
    result = await workspace.bash(command="python -B -m unittest -q")
    assert workspace.host_observed_progress_phase()=="agent_check_failed"
    assert "latest recognized agent-run test failed" in result
    assert "Completion hint" not in result
    # A new source change invalidates the previous test observation.
    await workspace.read_file(path="calc.py")
    await workspace.str_replace(path="calc.py", old_str="new", new_str="fixed")
    assert workspace.host_observed_progress_phase()=="code_modified"


def test_sanitized_execution_phase_aggregation():
    events=[
        {"task_id":"case","seq":1,"timestamp":"2026-10-12T00:00:01+00:00",
         "event_type":"model.turn.finished","payload":{
             "progress_phase":"exploring", "usage":{"input_tokens":10}}},
        {"task_id":"case","seq":2,"timestamp":"2026-10-12T00:00:02+00:00",
         "event_type":"model.turn.finished","payload":{
             "progress_phase":"code_modified", "usage":{"input_tokens":20}}},
        {"task_id":"case","seq":3,"timestamp":"2026-10-12T00:00:03+00:00",
         "event_type":"model.turn.finished","payload":{
             "progress_phase":"secret-arbitrary-text"}},
    ]
    report=summarize_execution_trace(events)
    assert report["model_progress_phase_counts"]=={
        "code_modified":1,"exploring":1,"unknown":1,
    }
    assert "secret-arbitrary-text" not in json.dumps(report)
