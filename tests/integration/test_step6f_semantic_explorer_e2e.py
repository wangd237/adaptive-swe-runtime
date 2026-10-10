"""Real pinned DeerFlow + Docker with validated plan and distinct LLM Explorer."""
import json
from pathlib import Path

import pytest

from aswe.integrations.deerflow.dev_workflow import execute_dev_workflow
from aswe.integrations.deerflow.dev_llm_explorer import ExplorerFinding
from tests.integration.test_step6d_workflow_e2e import OneRoundCodingModel
from tests.unit.test_step6e_llm_team_planner import ScriptedStructuredPlanner
from tests.unit.test_deerflow_mvp_task_step5fcb import prepared_mvp
from tests.integration.test_deerflow_docker_canonical_step5fd import _digest


class ScriptedExplorer:
    def with_structured_output(self, schema):
        assert schema is ExplorerFinding
        return self

    async def ainvoke(self, messages):
        assert "return 1" in str(messages)
        return ExplorerFinding(
            relevant_paths=("calc.py",),
            diagnosis="calc.answer returns a number incompatible with its test.",
            suggested_approach="Read calc.py and tests, then repair the implementation.")


@pytest.mark.asyncio
async def test_semantic_explorer_coder_verifier_real_docker(
        prepared_mvp,tmp_path,monkeypatch):
    import aswe.integrations.deerflow.dev_workflow as entry
    repo,*_ = prepared_mvp
    monkeypatch.setenv("LLM_API_KEY","offline-e2e-only")
    monkeypatch.setenv("LLM_MODEL","offline-e2e")
    original = entry.execute_swe_task
    observed_prompts = []

    async def capturing_run(**kwargs):
        observed_prompts.append(kwargs["task"])
        return await original(**kwargs)
    monkeypatch.setattr(entry,"execute_swe_task",capturing_run)

    result = await execute_dev_workflow(
        repository=Path(repo.repository_root),
        task="Investigate calc.py regression and make unit tests pass",
        runtime_dir=tmp_path/"runs",image=_digest(),
        check_argv=("python","-B","-m","unittest","discover","-s","tests","-q"),
        adaptive=True,planner="llm",explorer_mode="llm",
        physical_dag=True,max_repairs=0,
        planner_factory=lambda:ScriptedStructuredPlanner(True),
        explorer_factory=lambda:ScriptedExplorer(),
        model_factory=lambda **_: OneRoundCodingModel(target=42, previous=1),
    )
    assert result.verification_status=="passed"
    assert result.round_count==1
    assert "calc.answer returns a number" in observed_prompts[0]
    assert "Repository exploration candidates" in observed_prompts[0]
    assert "calc.py" in observed_prompts[0]
    events=[json.loads(x) for x in result.trace_path.read_text().splitlines()]
    assert [x["event_type"] for x in events].count("semantic_plan.validated")==1
    assert events[1]["event_type"]=="task_dag.compiled"
    assert [node["provider"] for node in events[1]["payload"]["nodes"]] == [
        "explorer","coder","tester"]
    assert [node["id"] for node in events[1]["payload"]["nodes"]] == [
        "explorer","coder","__aswe_verify"]
    assert events[3]["payload"]["nodes"] == [
        {"id":"explorer","work_kind":"discovery",
         "depends_on":[],"runtime_owned":False,
         "capabilities":["repo_exploration"]},
        {"id":"coder","work_kind":"implementation",
         "depends_on":["explorer"],"runtime_owned":False,
         "capabilities":["code_modification"]},
        {"id":"__aswe_verify","work_kind":"verification",
         "depends_on":["coder"],"runtime_owned":True,
         "capabilities":["regression_testing"]},
    ]
    assert any(x["event_type"]=="semantic_node.finished"
               and x["node_id"]=="explorer" for x in events)
    assert any(x["event_type"]=="semantic_node.finished"
               and x["node_id"]=="__aswe_verify"
               and x["payload"]["status"]=="passed" for x in events)
    assert sum(x["event_type"]=="tool.call.finished" for x in events)>=2
    dispatch=[x["node_id"] for x in events
              if x["event_type"]=="dag.scheduler.dispatch"]
    assert dispatch==["explorer","coder","__aswe_verify"]
    report=json.loads(result.report_path.read_text())
    assert len(report["task_dag_fingerprint"])==64
    assert report["dag_dispatch_attempts"]=={
        "explorer":1,"coder":1,"__aswe_verify":1}
    assert (Path(repo.repository_root)/"calc.py").read_text()=="def answer():\n    return 1\n"
