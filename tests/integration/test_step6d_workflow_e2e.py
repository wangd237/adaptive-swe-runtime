"""Actual two-round developer workflow with pinned DeerFlow and Docker."""
import json
from pathlib import Path

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from aswe.integrations.deerflow.dev_workflow import execute_dev_workflow
from tests.unit.test_deerflow_mvp_task_step5fcb import prepared_mvp
from tests.integration.test_deerflow_docker_canonical_step5fd import _digest


class OneRoundCodingModel(BaseChatModel):
    target: int
    previous: int
    turn: int = 0

    @property
    def _llm_type(self):
        return "scripted-two-round-real-tools"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.turn += 1
        if self.turn == 1:
            message = AIMessage(content="", tool_calls=[{
                "name":"read_file","args":{"path":"calc.py"},
                "id":f"read-{self.target}"}])
        elif self.turn == 2:
            message = AIMessage(content="", tool_calls=[{
                "name":"str_replace","args":{
                    "path":"calc.py","old_str":f"return {self.previous}",
                    "new_str":f"return {self.target}"},
                "id":f"edit-{self.target}"}])
        else:
            message = AIMessage(content="I applied the code change.")
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.asyncio
async def test_actual_coder_failed_test_repair_passed_test(
        prepared_mvp, tmp_path, monkeypatch):
    repo, *_ = prepared_mvp
    monkeypatch.setenv("LLM_API_KEY","offline-synthetic-not-sent")
    monkeypatch.setenv("LLM_MODEL","offline-model")
    # Exercise real top-level independent Docker Tester feedback -> Repair.
    import aswe.integrations.deerflow.dev_workflow as workflow_module
    original_execute = workflow_module.execute_swe_task
    observed_prompts = []
    async def capture_real_execution(**kwargs):
        observed_prompts.append(kwargs["task"])
        return await original_execute(**kwargs)
    monkeypatch.setattr(workflow_module,"execute_swe_task",capture_real_execution)
    built = []
    def model_factory(**kwargs):
        index=len(built)
        assert index < 2
        model=OneRoundCodingModel(
            previous=1 if index == 0 else 41,
            target=41 if index == 0 else 42)
        built.append(model)
        return model
    result = await execute_dev_workflow(
        repository=Path(repo.repository_root),
        task="Fix calc.answer to pass unit tests",
        runtime_dir=tmp_path/"runs",image=_digest(),
        check_argv=("python","-B","-m","unittest","discover","-s","tests","-q"),
        max_repairs=1,adaptive=True,physical_dag=True,
        model_factory=model_factory)
    assert result.round_count==2
    assert result.verification_status=="passed"
    assert len(built)==2
    assert len(observed_prompts)==2
    assert "test_failure_output" in observed_prompts[1]
    assert "AssertionError" in observed_prompts[1]
    assert "41" in observed_prompts[1] and "42" in observed_prompts[1]
    first=json.loads(result.round_reports[0].read_text())
    second=json.loads(result.round_reports[1].read_text())
    assert first["verification_status"]=="failed"
    assert second["verification_status"]=="passed"
    assert "return 41" in first["git_diff"]
    assert "return 42" in second["git_diff"]
    assert (Path(repo.repository_root)/"calc.py").read_text()=="def answer():\n    return 1\n"
    events=[json.loads(x) for x in result.trace_path.read_text().splitlines()]
    kinds=[x["event_type"] for x in events]
    assert kinds.count("workflow.stage.started")==2
    assert kinds.count("workflow.test.finished")==2
    assert kinds.count("workflow.repair.scheduled")==1
    assert kinds.count("model.turn.finished")>=4
    assert kinds.count("tool.call.finished")==4
    assert events[-1]["payload"]["verification_status"]=="passed"
    report=json.loads(result.report_path.read_text())
    assert len(report["task_dag_fingerprint"])==64
    assert report["dag_dispatch_attempts"]["coder"]==2
    assert report["dag_dispatch_attempts"]["__aswe_verify"]==2
    assert report["repair_rounds_scheduled"]==1
    assert len(report["last_failure_output_sha256"])==64
    assert "AssertionError" not in json.dumps(report)
    assert any(e["event_type"]=="repair.feedback.available" for e in events)
    assert all("OPENAI_API_KEY" not in json.dumps(x) for x in events)
