"""LLM team decisions remain proposals; execution uses the normal workflow."""
import json
import subprocess
from types import SimpleNamespace

import pytest
from aswe.integrations.deerflow.dev_team_planner import (
    plan_developer_team, ProposedTeam,
)
from aswe.integrations.deerflow.dev_workflow import execute_dev_workflow


class ScriptedStructuredPlanner:
    def __init__(self, needs_explorer):
        self.needs_explorer = needs_explorer
        self.prompts = []
    def with_structured_output(self, schema):
        assert schema is ProposedTeam
        return self
    async def ainvoke(self, messages):
        self.prompts.append(messages)
        return ProposedTeam(
            needs_explorer=self.needs_explorer,
            coder_objective="Fix the regression in the existing code.",
            explorer_objective="Find relevant modules.",
            rationale="Enough context from task and tracked paths.")


@pytest.fixture
def source(tmp_path):
    root=tmp_path/"source"
    root.mkdir()
    subprocess.run(["git","init",str(root)],check=True,capture_output=True)
    for p in ("orders.py","inventory.py","tests/test_orders.py"):
        path=root/p;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("pass\n")
    subprocess.run(["git","-C",str(root),"add","-A"],check=True)
    subprocess.run(["git","-C",str(root),"-c","user.name=CI",
                    "-c","user.email=ci@example.invalid","commit","-m","fixture"],
                   check=True,capture_output=True)
    return root


@pytest.mark.asyncio
async def test_llm_proposes_explorer_and_runtime_bounds_roles(source):
    planner=ScriptedStructuredPlanner(True)
    chosen=await plan_developer_team(
        task="Fix orders regression",repository=source,
        mode="llm",planner_factory=lambda:planner)
    assert chosen.decision.roles==("explorer","coder","tester")
    assert chosen.planning_mode=="llm"
    assert "Fix orders regression" in chosen.coder_objective
    prompt=str(planner.prompts)
    assert "orders.py" in prompt
    assert "pass\\n" not in prompt


@pytest.mark.asyncio
async def test_llm_can_select_single_coder(source):
    chosen=await plan_developer_team(
        task="Fix order typo",repository=source,mode="llm",
        planner_factory=lambda:ScriptedStructuredPlanner(False))
    assert chosen.decision.roles==("coder",)


@pytest.mark.asyncio
async def test_workflow_uses_llm_decision_and_does_not_skip_canonical_tester(
        source,tmp_path,monkeypatch):
    import aswe.integrations.deerflow.dev_workflow as module
    from aswe.trace.minimal_events import LocalRuntimeEventSink
    seen=[]
    async def run(**kwargs):
        seen.append(kwargs)
        path=kwargs["runtime_dir"]/"tasks"/"child-1"/"report.json"
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("{}")
        LocalRuntimeEventSink(kwargs["runtime_dir"],"child-1").emit(
            "model.turn.finished",payload={"round":1})
        return path,SimpleNamespace(
            task_id="child-1",execution_id="execution-1",
            verification_check_id="check-1",verification_status="passed",
            native_status="completed",changed_files=("orders.py",)),None
    monkeypatch.setattr(module,"execute_swe_task",run)
    result=await execute_dev_workflow(
        repository=source,task="Fix order regression",
        runtime_dir=tmp_path/"runtime",image="python@sha256:mock",
        check_argv=("python",),adaptive=True,planner="llm",
        planner_factory=lambda:ScriptedStructuredPlanner(True))
    trace=[json.loads(line) for line in result.trace_path.read_text().splitlines()]
    assert trace[0]["event_type"]=="team.selected"
    assert trace[0]["payload"]["planning_mode"]=="llm"
    assert trace[1]["event_type"]=="semantic_plan.validated"
    assert trace[2]["event_type"]=="semantic_node.started"
    assert trace[3]["event_type"]=="explorer.finished"
    assert sum(x["event_type"]=="workflow.test.finished" for x in trace)==1
    assert result.verification_status=="passed"
    assert "Fix order regression" in seen[0]["task"]


@pytest.mark.asyncio
async def test_llm_planner_needs_explicit_adaptive(source,tmp_path):
    with pytest.raises(ValueError,match="LLM_PLANNER_REQUIRES_ADAPTIVE"):
        await execute_dev_workflow(repository=source,task="fix",
            runtime_dir=tmp_path/"out",image="python@sha256:fake",
            check_argv=("python",),planner="llm")
