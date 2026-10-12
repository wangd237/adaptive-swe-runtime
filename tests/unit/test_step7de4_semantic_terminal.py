"""Step 7D-E4: diagnose loops without changing test authority or leaking tools."""
import json

import pytest

from aswe.integrations.deerflow.bash_intent import classify_bash, inspect_bash
from aswe.trace.minimal_events import LocalRuntimeEventSink
from aswe.trace.reliability import summarize_execution_trace
from tests.unit.test_deerflow_tool_guard_step5d import bind_during_scheduler


@pytest.mark.parametrize(("command", "expected_shape", "possible_test", "count"), [
    ("python -B -m unittest -q", "single", True, 1),
    ("git diff --stat", "single", False, 1),
    ("rg MultiReplace boltons/strutils.py && python -m pytest -q", "compound", True, 2),
    ("python -m unittest -q | tail -n 2", "compound", True, 2),
    ("python -m pytest -q; git status --short", "compound", True, 2),
    ("pytest --collect-only && echo done", "compound", False, 2),
    ("python -m unittest -q > /tmp/out", "unknown", False, 0),
    ("python -m unittest -q &&", "unknown", False, 0),
    ("python -m unittest -q $(echo secret)", "unknown", False, 0),
    ("python -m unittest -q\nls", "unknown", False, 0),
])
def test_bash_shape_advisory_only(command, expected_shape, possible_test, count):
    observed = inspect_bash({"command": command})
    assert observed["shape"] == expected_shape
    assert observed["contains_test_step"] is possible_test
    assert observed["step_count"] == count
    assert observed["test_verdict_attributable"] is (
        expected_shape == "single" and possible_test
    )
    if expected_shape != "single":
        assert classify_bash({"command": command}) == "other"


@pytest.mark.parametrize("bad", [None, {}, [], {"command": ["pytest"]},
                                      {"command": "x" * 4097}])
def test_malformed_arguments_are_unknown(bad):
    assert inspect_bash(bad)["shape"] == "unknown"
    assert not inspect_bash(bad)["test_verdict_attributable"]


@pytest.mark.asyncio
async def test_compound_test_shape_cannot_emit_agent_pass_or_feedback(tmp_path):
    binding, store, _, _, _, _, _, _, invocation = await bind_during_scheduler(tmp_path)
    guard = binding["binding"].guard
    sink = LocalRuntimeEventSink(tmp_path / "e4-trace", invocation.task_id)
    guard.trace_sink = sink
    secret = "PRIVATE_COMMAND_PATH_OR_TOOL_OUTPUT_DO_NOT_PERSIST"
    guard._record(
        name="bash", call_id="e4-1",
        argument={"command": "rg pattern code.py && python -m pytest -q"},
        status="completed",
        result="exit_code=0; timed_out=False\n" + secret,
        duration_ms=11,
    )
    guard._record(
        name="bash", call_id="e4-2",
        argument={"command": "python -B -m unittest -q | tail -n 3"},
        status="completed",
        result="exit_code=1; timed_out=False\n" + secret,
        duration_ms=12,
    )
    observed = sink.read_all()
    assert [x for x in observed if x.event_type == "agent.test.observed"] == []
    assert [x for x in observed if x.event_type == "repair.feedback.available"] == []
    calls = [x.payload for x in observed if x.event_type == "tool.call.finished"]
    assert all(x["bash_category"] == "other" for x in calls)
    assert all(x["bash_structure"]["shape"] == "compound" for x in calls)
    assert all(x["bash_structure"]["contains_test_step"] is True for x in calls)
    summary = summarize_execution_trace(observed)
    assert summary["bash_structure_counts"] == {"compound": 2}
    assert summary["bash_contains_possible_test_step_calls"] == 2
    assert summary["post_recognized_pass_tool_calls"] is None
    assert secret not in sink.path.read_text()
    assert secret not in json.dumps(summary)
    store.release(invocation.execution_id)


def test_post_pass_chronology_resets_on_source_edit_and_reports_no_denominator():
    def event(t, **p):
        return {"event_type": t, "payload": p}
    events = [
        event("model.turn.finished", tool_call_count=1, progress_phase="exploring"),
        event("tool.call.finished", tool_name="str_replace", status="completed"),
        event("model.turn.finished", tool_call_count=2, progress_phase="code_modified"),
        event("tool.call.finished", tool_name="bash", status="completed",
              bash_category="test_like", bash_structure={
                  "shape": "single", "step_count": 1, "contains_test_step": True}),
        event("agent.test.observed", passed=True, authority="agent_observed_only"),
        event("model.turn.finished", tool_call_count=2, progress_phase="agent_check_passed"),
        event("tool.call.finished", tool_name="bash", status="completed",
              bash_category="inspect_like", bash_structure={"shape": "single"}),
        event("tool.call.finished", tool_name="read_file", status="completed"),
        event("tool.call.finished", tool_name="str_replace", status="completed"),
        event("model.turn.finished", tool_call_count=0, progress_phase="code_modified"),
        event("tool.call.finished", tool_name="bash", status="completed",
              bash_category="other", bash_structure={"shape": "unknown"}),
    ]
    result = summarize_execution_trace(events)
    assert result["agent_recognized_post_edit_passing_test_events"] == 1
    assert result["post_recognized_pass_tool_calls"] == 3
    assert result["post_recognized_pass_bash_calls"] == 1
    assert result["post_recognized_pass_non_test_bash_calls"] == 1
    assert result["post_recognized_pass_source_edits"] == 1
    assert result["post_recognized_pass_model_turns"] == 1
    assert result["last_model_turn_tool_call_count"] == 0
    assert result["model_turns_without_tool_requests"] == 1
    assert result["bash_unknown_shape_calls"] == 1
    assert result["semantic_execution_tail"][-1]["bash_shape"] == "unknown"
    no_tests = summarize_execution_trace(events[:4])
    assert no_tests["post_recognized_pass_tool_calls"] is None


def test_untrusted_test_event_or_plain_bash_success_not_promoted():
    events = [
        {"event_type": "tool.call.finished", "payload": {
            "tool_name": "bash", "status": "completed",
            "bash_structure": {"shape": "compound", "contains_test_step": True}}},
        {"event_type": "agent.test.observed", "payload": {
            "passed": True, "authority": "model_claimed"}},
    ]
    result = summarize_execution_trace(events)
    assert result["agent_recognized_test_events"] == 0
    assert result["agent_recognized_passing_test_events"] == 0
    assert result["post_recognized_pass_tool_calls"] is None
