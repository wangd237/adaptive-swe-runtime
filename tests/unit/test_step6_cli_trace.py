"""Real console entrypoint and durable trace file smoke."""
import json

from aswe.cli import main
from aswe.trace.minimal_events import LocalRuntimeEventSink


def test_cli_trace_machine_readable_and_tail(tmp_path, capsys):
    store=LocalRuntimeEventSink(tmp_path,"task-step6")
    store.emit("task.started",payload={"work":"coding"})
    store.emit("node.finished",node_id="writer",payload={"outcome":"unverified"})
    assert main(["trace","task-step6","--runtime-dir",str(tmp_path),"--tail","1","--json"])==0
    lines=capsys.readouterr().out.strip().splitlines()
    assert len(lines)==1
    assert json.loads(lines[0])["event_type"]=="node.finished"
    assert json.loads(lines[0])["seq"]==2


def test_cli_report_never_claims_scheduler_acceptance(tmp_path,capsys):
    path=tmp_path/"mvp.json"
    path.write_text(json.dumps({
        "task_id":"t","node_id":"writer","native_status":"completed",
        "verification_status":"passed","delivery_status":"tests_passed_scheduler_quarantined",
        "changed_files":["calc.py"],"tests_passed":True,
    }))
    assert main(["report",str(path)])==0
    output=capsys.readouterr().out
    assert "calc.py" in output
    assert "NOT proven" in output


def test_cli_invalid_trace_tail_and_report_fail_cleanly(tmp_path,capsys):
    assert main(["trace","ok","--runtime-dir",str(tmp_path),"--tail","-2"])==2
    assert main(["report",str(tmp_path/"absent.json")])==2
    assert "aswe:" in capsys.readouterr().err
