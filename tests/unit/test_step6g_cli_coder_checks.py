"""CLI admits a focused Coder test but never weakens DAG canonical Test."""
from pathlib import Path
from types import SimpleNamespace

from aswe.cli import main


def args(tmp_path):
    return ["workflow","Fix inventory",
        "--repo",str(tmp_path/"repo"),
        "--runtime-dir",str(tmp_path/"runs"),
        "--docker-image","python@sha256:"+"f"*64,
        "--adaptive",
        "--check-command","python -B -m unittest discover -s tests -q"]


def test_cli_forwards_distinct_focused_and_full_checks(tmp_path,monkeypatch):
    import aswe.integrations.deerflow.dev_workflow as module
    captured={}
    async def mock_workflow(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            workflow_id="workflow-1",round_count=2,
            verification_status="passed",report_path=tmp_path/"out.json",
            trace_path=tmp_path/"events.jsonl")
    monkeypatch.setattr(module,"execute_dev_workflow",mock_workflow)
    status=main(args(tmp_path)+[
        "--coder-check-command","python -B -m unittest tests.test_inventory -q"])
    assert status==0
    assert captured["physical_dag"]
    assert captured["check_argv"]==(
        "python","-B","-m","unittest","discover","-s","tests","-q")
    assert captured["initial_coder_check_argv"]==(
        "python","-B","-m","unittest","tests.test_inventory","-q")


def test_cli_rejects_shell_injection_in_coder_check(tmp_path,capsys):
    code=main(args(tmp_path)+[
        "--coder-check-command","python -m unittest; cat /etc/passwd"])
    assert code==2
    assert "VERIFICATION_COMMAND_UNSAFE" in capsys.readouterr().err
