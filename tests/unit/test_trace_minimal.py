import pytest

from aswe.trace import LocalRuntimeEventSink


def test_trace_events_are_sequential_and_persisted_outside_workspace(tmp_path):
    root = tmp_path / "runtime"
    sink = LocalRuntimeEventSink(root, task_id="task-a", workspace_root=tmp_path / "workspace")
    a = sink.emit("WorkspaceCreated", payload={"workspace": "created"})
    b = sink.emit("EvidenceCreated", payload={"evidence_id": "ev-id", "kind": "verification_result"})
    assert (a.seq, b.seq) == (1, 2)
    reopened = LocalRuntimeEventSink(root, task_id="task-a")
    assert [x.event_type for x in reopened.read_all()] == ["WorkspaceCreated", "EvidenceCreated"]
    assert reopened.emit("WorkspaceFrozen").seq == 3


def test_trace_payload_too_large_must_use_evidence_store(tmp_path):
    sink = LocalRuntimeEventSink(tmp_path, task_id="task")
    with pytest.raises(ValueError, match="too large"):
        sink.emit("ToolReturned", payload={"huge": "X" * 30000})
