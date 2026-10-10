"""Adaptive developer topology: real Git index, not test-only hardcoded roster."""
import json
import subprocess
from pathlib import Path

import pytest
from aswe.integrations.deerflow.adaptive_team import select_team, explore_repository
from aswe.integrations.deerflow.dev_workflow import execute_dev_workflow


def repository(tmp_path):
    repo=tmp_path/"source"
    repo.mkdir()
    subprocess.run(["git","init",str(repo)],check=True,capture_output=True)
    for path in ("auth.py","orders.py","inventory.py","tests/test_orders.py"):
        p=repo/path;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text("pass\n")
    subprocess.run(["git","-C",str(repo),"add","-A"],check=True)
    return repo


def test_minimal_team_and_complex_team_from_real_git_index(tmp_path):
    repo=repository(tmp_path)
    single=select_team("Fix typo in auth.py",repo)
    assert single.roles==("coder",)
    complex=select_team("Investigate regression across orders.py and inventory.py",repo)
    assert complex.roles==("explorer","coder","tester")
    assert complex.evidence_paths==("inventory.py","orders.py")
    assert "orders.py" in explore_repository(repo,"debug orders.py")


@pytest.mark.asyncio
async def test_adaptive_workflow_traces_selection_and_real_explorer(tmp_path,monkeypatch):
    import aswe.integrations.deerflow.dev_workflow as flow
    repo=repository(tmp_path)
    calls=[]
    async def fake_entry(**kwargs):
        calls.append(kwargs)
        from types import SimpleNamespace
        from aswe.trace.minimal_events import LocalRuntimeEventSink
        home=kwargs["runtime_dir"]
        task_id="child-1"
        child=LocalRuntimeEventSink(home,task_id)
        child.emit("model.turn.finished",payload={"round":1})
        path=home/"tasks"/task_id/"report.json"
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("{}")
        return path,SimpleNamespace(
            task_id=task_id,execution_id="exec-1",node_id="writer",
            verification_check_id="test",verification_status="passed",
            native_status="completed",changed_files=("orders.py",)),child.path
    monkeypatch.setattr(flow,"execute_swe_task",fake_entry)
    result=await execute_dev_workflow(repository=repo,
        task="Investigate regression in orders.py",runtime_dir=tmp_path/"artifacts",
        image="python@sha256:fake",check_argv=("python",),
        max_repairs=1,adaptive=True)
    events=[json.loads(x) for x in result.trace_path.read_text().splitlines()]
    assert events[0]["event_type"]=="team.selected"
    assert events[0]["payload"]["roles"]==["explorer","coder","tester"]
    assert events[1]["event_type"]=="explorer.finished"
    assert "orders.py" in calls[0]["task"]
    assert events[-1]["event_type"]=="workflow.finished"
    report=json.loads(result.report_path.read_text())
    assert report["selected_roles"]==["explorer","coder","tester"]
