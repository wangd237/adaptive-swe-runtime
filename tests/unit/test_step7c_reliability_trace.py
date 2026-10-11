"""Step 7C regression: safety and semantics of diagnostic trace projections."""
from __future__ import annotations

import json

from aswe.trace.reliability import (
    SCHEMA_VERSION, safe_model_usage, summarize_execution_trace,
)


def event(seq, kind, payload=None, *, task="task-a"):
    return {
        "task_id": task, "seq": seq, "event_type": kind,
        "timestamp": f"2026-10-11T04:00:{seq:02d}+00:00",
        "payload": payload or {},
    }


def test_complete_trace_preserves_native_failure_and_host_denied_receipts():
    secret = "highly-secret-prompt-please-never-project"
    events = [
        event(1, "workflow.started", {"raw_prompt": secret}),
        event(2, "model.turn.finished", {
            "usage": {"input_tokens": 13, "output_tokens": 7,
                      "total_tokens": 20, "extra": secret},
            "content": secret,
        }),
        event(3, "tool.call.finished", {
            "tool_call_id": "a", "execution_id": "execution-a",
            "tool_name": "str_replace", "status": "denied",
            "failure_code": "SWE_READ_BEFORE_WRITE_REQUIRED",
            "arguments": secret,
        }),
        event(4, "tool.call.finished", {
            "tool_call_id": "b", "execution_id": "execution-a",
            "tool_name": "read_file", "status": "completed",
            "tool_output": secret,
        }),
        event(5, "tool.call.finished", {
            "tool_call_id": "c", "execution_id": "execution-a",
            "tool_name": "str_replace", "status": "completed",
        }),
        event(6, "workflow.repair.scheduled"),
        event(7, "dag.verification.executed", {"status": "passed"}),
        event(8, "workflow.stage.finished", {
            "native_status": "completed", "native_stop_reason": "turn_capped"}),
        event(9, "workflow.finished", {
            "verification_status": "passed", "final_native_stop_reason": "turn_capped"}),
    ]
    result = summarize_execution_trace(events, round_reports=[{
        "native_status": "completed", "native_stop_reason": "turn_capped",
        "verification_status": "passed",
    }])
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["trace_integrity"] == "verified"
    assert result["outcome_category"] == "VERIFIED_WITH_NATIVE_CAP"
    assert result["native_status"] == "completed"
    assert result["native_stop_reason"] == "turn_capped"
    assert result["native_stop_reason_counts"] == {"turn_capped": 1}
    assert result["model_turns"] == 1
    assert result["token_reported_turns"] == 1
    assert result["token_usage_reported"] == {
        "input_tokens": 13, "output_tokens": 7, "total_tokens": 20}
    assert result["tool_calls"] == 3
    assert result["tool_status_counts"] == {"completed": 2, "denied": 1}
    assert result["tool_failure_code_counts"] == {
        "SWE_READ_BEFORE_WRITE_REQUIRED": 1}
    assert result["repair_rounds_scheduled"] == 1
    assert result["independent_verifier_results"] == ["passed"]
    assert result["elapsed_observed_ms"] == 8000
    serialized = json.dumps(result)
    assert secret not in serialized
    assert "str_replace" not in serialized
    assert "execution-a" not in serialized
    assert "cost" not in serialized


def test_top_level_failed_tester_outranks_child_success():
    events = [
        event(1, "workflow.started"),
        event(2, "workflow.stage.finished", {"native_status": "completed"}),
        event(3, "dag.verification.executed", {"status": "failed"}),
        event(4, "workflow.finished", {"verification_status": "failed"}),
    ]
    result = summarize_execution_trace(events, round_reports=[{
        "native_status": "completed", "verification_status": "passed",
    }])
    assert result["verification_status"] == "failed"
    assert result["outcome_category"] == "CANONICAL_TESTS_FAILED"


def test_absent_token_receipts_are_not_assumed_and_invalid_values_rejected():
    assert safe_model_usage({"input_tokens": True, "output_tokens": -5,
                             "total_tokens": "123", "key": "sensitive"}) == {}
    assert safe_model_usage({"input_tokens": 0, "output_tokens": 5,
                             "total_tokens": 5}) == {
                                 "input_tokens": 0, "output_tokens": 5,
                                 "total_tokens": 5}
    trace = [
        event(1, "model.turn.finished", {"usage": {"prompt": "private"}}),
        event(2, "workflow.finished", {"verification_status": "passed"}),
    ]
    result = summarize_execution_trace(trace)
    assert result["model_turns"] == 1
    assert result["token_reported_turns"] == 0
    assert result["token_usage_reported"] == {}


def test_fail_closed_on_corrupt_trace_and_untrusted_failure_codes():
    cases = [
        event(1, "workflow.started"),
        event(3, "tool.call.finished", {
            "tool_call_id": "dup", "execution_id": "e",
            "status": "denied", "failure_code": "PRIVATE=secret"}),
        event(4, "tool.call.finished", {
            "tool_call_id": "dup", "execution_id": "e",
            "status": "denied", "failure_code": "SWE_PATH_FORBIDDEN"}),
        event(5, "workflow.finished", {"verification_status": "passed"}),
    ]
    result = summarize_execution_trace(cases)
    assert result["trace_integrity"] == "invalid"
    assert result["outcome_category"] == "TRACE_INTEGRITY_INVALID"
    assert result["tool_failure_code_counts"] == {
        "UNCLASSIFIED_FAILURE": 1, "SWE_PATH_FORBIDDEN": 1}
    assert "PRIVATE" not in json.dumps(result)
    assert "dup" not in json.dumps(result)


def test_partial_trace_is_not_claimed_as_verified():
    result = summarize_execution_trace([
        event(1, "workflow.started"), event(2, "model.turn.finished")])
    assert result["workflow_finished_observed"] is False
    assert result["outcome_category"] == "WORKFLOW_INCOMPLETE"
    assert result["verification_status"] == "unverified"


def test_cancel_and_repair_exhaustion_remain_distinct():
    cancelled = summarize_execution_trace([
        event(1, "workflow.started"),
        event(2, "workflow.stage.finished", {"native_status": "cancelled"}),
        event(3, "workflow.finished", {"verification_status": "unverified"}),
    ])
    assert cancelled["outcome_category"] == "NATIVE_EXECUTION_INCOMPLETE"
    exhausted = summarize_execution_trace([
        event(1, "workflow.started"),
        event(2, "workflow.stage.finished", {"native_status": "completed"}),
        event(3, "workflow.repair.budget_exhausted"),
        event(4, "workflow.finished", {"verification_status": "failed"}),
    ])
    assert exhausted["outcome_category"] == "REPAIR_BUDGET_EXHAUSTED"
