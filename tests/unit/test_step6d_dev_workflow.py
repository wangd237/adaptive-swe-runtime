"""Developer workflow control-flow tests: actual Git checkpoints and trace."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest

from aswe.integrations.deerflow.dev_workflow import execute_dev_workflow


def git(path,*args):
    return subprocess.run(["git","-C",str(path),*args],check=True,
                          capture_output=True,text=True)


@pytest.mark.asyncio
async def test_failed_canonical_round_schedules_repair_with_git_handoff(
        tmp_path,monkeypatch):
    import aswe.integrations.deerflow.dev_workflow as flow
    repo=tmp_path/"source"
    repo.mkdir()
    git(repo,"init")
    (repo/"calc.py").write_text("value=0\n")
    git(repo,"add","-A")
    subprocess.run(["git","-C",str(repo),"-c","user.name=CI","-c",
                    "user.email=ci@example.invalid","commit","-m","start"],check=True,
                   capture_output=True)
    calls=[]
    async def execute_swe_task(**kwargs):
        number=len(calls)
        calls.append(kwargs)
        path=tmp_path/"runtime"/"tasks"/f"child-{number}"/"report.json"
        workspace=path.parent/"workspace"
        workspace.mkdir(parents=True)
        subprocess.run(["git","clone","-q",str(kwargs["repository"]),str(workspace)],check=True)
        (workspace/"calc.py").write_text("value=1\n" if number==0 else "value=42\n")
        path.write_text("{}")
        task_id=f"child-{number}"
        from aswe.trace.minimal_events import LocalRuntimeEventSink
        child=LocalRuntimeEventSink(tmp_path/"runtime",task_id)
        child.emit("model.turn.finished",payload={"round":1})
        return path,SimpleNamespace(
            task_id=task_id,node_id="writer",execution_id=f"exec-{number}",
            verification_check_id="unit",verification_status="failed" if number==0 else "passed",
            native_status="completed",changed_files=("calc.py",)),child.path
    monkeypatch.setattr(flow,"execute_swe_task",execute_swe_task)
    result=await execute_dev_workflow(repository=repo,task="fix bug",
        runtime_dir=tmp_path/"runtime",image="python@sha256:x",
        check_argv=("python","-m","unittest"),max_repairs=1)
    assert result.round_count==2
    assert result.verification_status=="passed"
    assert calls[1]["repository"]==result.round_reports[0].parent/"workspace"
    assert "previous coding pass failed" in calls[1]["task"]
    assert (repo/"calc.py").read_text()=="value=0\n"
    events=[json.loads(x) for x in result.trace_path.read_text().splitlines()]
    assert [e["event_type"] for e in events].count("workflow.test.finished")==2
    assert [e["event_type"] for e in events].count("workflow.repair.scheduled")==1
    assert events[-1]["payload"]["verification_status"]=="passed"
    assert result.report_path.exists()


@pytest.mark.asyncio
async def test_repair_budget_rejects_invalid_without_execution(tmp_path):
    with pytest.raises(ValueError,match="WORKFLOW_REPAIR_BUDGET_INVALID"):
        await execute_dev_workflow(repository=tmp_path,task="test",
            runtime_dir=tmp_path/"runs",check_argv=("python",),image="test",
            max_repairs=4)
