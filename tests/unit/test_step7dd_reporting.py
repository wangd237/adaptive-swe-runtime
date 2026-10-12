"""Step 7D-D: failure must keep safe metrics and never raw tool/provider text."""
import json

from scripts.step7d_real_issue_eval import _redacted_failure_observations


def test_failure_reporting_handles_no_persisted_trace(tmp_path):
    assert _redacted_failure_observations(tmp_path) == {"failed_child_count": 0}


def test_failure_reporting_remains_bounded_and_secret_free(tmp_path):
    secret = "PRIVATE-REPO-PATH-AND-APIKEY-DO-NOT-LOG"
    trace = tmp_path / "tasks" / "task-1" / "events.jsonl"
    trace.parent.mkdir(parents=True)
    def event(seq, event_type, payload):
        return {
            "task_id": "case", "seq": seq,
            "timestamp": f"2026-10-12T00:00:{seq:02d}+00:00",
            "event_type": event_type, "payload": payload,
        }
    records = [
        event(1, "model.turn.finished", {
            "usage": {"input_tokens": 100, "output_tokens": 10,
                      "total_tokens": 110},
            "prompt": secret,
        }),
        event(2, "tool.call.finished", {
            "tool_name": "bash", "status": "completed",
            "bash_category": "other", "duration_ms": 11,
            "repeated_exact_arguments": False,
            "arguments": {"command": secret},
        }),
        event(3, "model.turn.finished", {
            "usage": {"input_tokens": 250, "output_tokens": 20,
                      "total_tokens": 270},
        }),
    ]
    trace.write_text(
        "\n".join(json.dumps(e) for e in records) + "\n",
        encoding="utf-8",
    )
    result = _redacted_failure_observations(tmp_path)
    assert result["failed_child_count"] == 1
    assert result["model_turns"] == 2
    assert result["tool_calls"] == 1
    assert result["tool_name_counts"]["bash"] == 1
    assert result["token_usage_reported"]["total_tokens"] == 380
    assert result["peak_input_tokens_per_turn"] == 250
    assert secret not in json.dumps(result)
