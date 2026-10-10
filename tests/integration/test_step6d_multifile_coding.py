"""Real pinned DeerFlow + Docker, two-file repair and truthful DAG limitations."""
from pathlib import Path
import json
import subprocess

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from aswe.integrations.deerflow.developer_entry import execute_swe_task
from tests.unit.test_deerflow_mvp_task_step5fcb import prepared_mvp
from tests.integration.test_deerflow_docker_canonical_step5fd import _digest


class TwoFileRepairModel(BaseChatModel):
    turn: int = 0

    @property
    def _llm_type(self):
        return "offline-multifile-repair"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.turn += 1
        actions = [
            ("read_file", {"path": "calc.py"}),
            ("read_file", {"path": "helper.py"}),
            ("str_replace", {"path": "calc.py",
                              "old_str": "return 1", "new_str": "return 42"}),
            ("bash", {"command": "grep -q 'fixed' helper.py"}),
            ("str_replace", {"path": "helper.py",
                              "old_str": "return 'broken'", "new_str": "return 'fixed'"}),
            ("bash", {"command": "python -B -m unittest discover -s tests -q"}),
        ]
        if self.turn <= len(actions):
            name,args=actions[self.turn-1]
            message=AIMessage(content="",tool_calls=[
                {"name":name,"args":args,"id":f"multifile-{self.turn}"}
            ])
        else:
            message=AIMessage(content="Repairs completed; unit tests passed.")
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.asyncio
async def test_multifile_repair_actual_deerflow_docker_and_timeline(
        prepared_mvp,tmp_path,monkeypatch):
    repo,_,_,_,_=prepared_mvp
    src=Path(repo.repository_root)
    # Extend a disposable tracked fixture and commit it as the new baseline.
    (src/"helper.py").write_text("def label():\n    return 'broken'\n")
    (src/"tests"/"test_helper.py").write_text(
        "import unittest\nfrom helper import label\n"
        "class TestHelper(unittest.TestCase):\n"
        "    def test_label(self):\n"
        "        self.assertEqual(label(), 'fixed')\n")
    subprocess.run(["git","add","helper.py","tests/test_helper.py"],cwd=src,check=True)
    subprocess.run(["git","-c","user.name=CI","-c",
                    "user.email=ci@example.invalid","commit","-m","two-file fixture"],
                   cwd=src,check=True,capture_output=True)
    monkeypatch.setenv("OPENAI_API_KEY","offline-ci-not-transmitted")
    monkeypatch.setenv("ASWE_MODEL","offline-scripted")
    output, report, trace_path = await execute_swe_task(
        repository=src,runtime_dir=tmp_path/"runs",
        task="Repair the calc and helper modules; make all tests pass",
        image=_digest(),
        check_argv=("python","-B","-m","unittest","discover","-s","tests","-q"),
        model_factory=lambda **_:TwoFileRepairModel(),
    )
    assert report.native_status=="completed"
    assert report.verification_status=="passed"
    assert set(report.changed_files)=={"calc.py","helper.py"}
    assert report.agent_dynamic_command_count==2
    assert report.workspace_status=="quarantined"
    events=[json.loads(s) for s in trace_path.read_text().splitlines()]
    types=[e["event_type"] for e in events]
    assert types.count("model.turn.finished")>=6
    assert types.count("tool.call.finished")==6
    assert types.count("verification.finished")==1
    # A failed native Docker check must produce feedback; this is distinct
    # from the later trusted canonical verifier verdict.
    observations=[event["payload"] for event in events
                  if event["event_type"]=="agent.test.observed"]
    assert [event["passed"] for event in observations]==[False,True]
    assert all(event["authority"]=="agent_observed_only" for event in observations)
    feedback=[event for event in events
              if event["event_type"]=="repair.feedback.available"]
    assert len(feedback)==1
    assert feedback[0]["payload"]["failed_check_count"]==1
    assert feedback[0]["payload"]["execution_id"]==report.execution_id
    assert events[-1]["payload"]["changed_files"]==["calc.py","helper.py"]
    assert next(e for e in events if e["event_type"]=="repair.decision")[
        "payload"]["status"]=="not_scheduled"
    assert "return 'fixed'" not in trace_path.read_text()
    assert (src/"helper.py").read_text()=="def label():\n    return 'broken'\n"
