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


def test_cli_run_dispatches_task_to_application_entrypoint(monkeypatch,tmp_path,capsys):
    import sys
    from types import ModuleType,SimpleNamespace
    import aswe.integrations.deerflow as module
    from aswe.integrations.deerflow import developer_entry
    recorded={}
    async def execute_swe_task(**kwargs):
        recorded.update(kwargs)
        report=SimpleNamespace(task_id="task-test",native_status="completed",
            verification_status="passed",delivery_status="tests_passed_scheduler_quarantined")
        return tmp_path/"report.json",report,tmp_path/"events.jsonl"
    monkeypatch.setattr(developer_entry,"execute_swe_task",execute_swe_task)
    code=main(["run","Fix bug","--repo",str(tmp_path/"source"),
        "--runtime-dir",str(tmp_path/"runtime"),
        "--docker-image","python@sha256:"+"f"*64,
        "--env-file",str(tmp_path/".env"),
        "--check-command","python -B -m unittest discover -s tests -q"])
    assert code==0
    assert recorded["task"]=="Fix bug"
    assert recorded["env_file"]==tmp_path/".env"
    assert recorded["check_argv"]==("python","-B","-m","unittest",
                                   "discover","-s","tests","-q")
    assert "task-test" in capsys.readouterr().out


def test_cli_run_rejects_shell_metacharacters_before_backend(tmp_path,capsys):
    assert main(["run","Fix bug","--repo",str(tmp_path),
        "--runtime-dir",str(tmp_path/"runs"),
        "--docker-image","python@sha256:"+"f"*64,
        "--check-command","python -m unittest; rm -rf /"])==2
    assert "VERIFICATION_COMMAND_UNSAFE" in capsys.readouterr().err
