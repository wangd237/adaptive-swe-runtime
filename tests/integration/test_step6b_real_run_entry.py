"""Step 6B: application runtime, not the Step 5 test-only preparation source."""
from pathlib import Path

import pytest

from aswe.integrations.deerflow.developer_entry import execute_swe_task
from tests.unit.test_deerflow_mvp_task_step5fcb import prepared_mvp
from tests.integration.test_deerflow_mvp_e2e_step5fcb import RealGraphScriptedRepairModel
from tests.integration.test_deerflow_docker_canonical_step5fd import _digest


@pytest.mark.asyncio
async def test_real_cli_application_composes_native_compiler_and_docker(
        prepared_mvp, tmp_path, monkeypatch):
    repo,_,_,_,_ = prepared_mvp
    monkeypatch.setenv("LLM_API_KEY","offline-only-not-transmitted")
    monkeypatch.setenv("LLM_MODEL","offline-scripted")
    home=tmp_path/"run-storage"
    report_path,report,trace_path=await execute_swe_task(
        repository=Path(repo.repository_root),
        task="Repair calc.answer so that unittest passes",
        runtime_dir=home, image=_digest(),
        check_argv=("python","-B","-m","unittest","discover","-s","tests","-q"),
        model_factory=lambda **kwargs:RealGraphScriptedRepairModel(),
    )
    assert report.native_status=="completed"
    assert report.verification_status=="passed"
    assert report.changed_files==("calc.py",)
    assert report.agent_dynamic_command_count==2
    assert report.delivery_status=="tests_passed_scheduler_quarantined"
    assert report_path.exists() and trace_path.exists()
    import json
    recorded=json.loads(report_path.read_text())
    assert recorded["execution_id"]==report.execution_id
    events=[json.loads(x) for x in trace_path.read_text().splitlines()]
    assert events[0]["event_type"]=="plan.compiled"
    assert [x["event_type"] for x in events].count("tool.call.finished")==6
    assert [x["event_type"] for x in events].count("model.turn.finished")>=6
    assert [x["event_type"] for x in events].count("scheduler.execution.committed")==1
    assert [x["event_type"] for x in events].count("verification.finished")==1
    assert [x["event_type"] for x in events].count("repair.decision")==1
    execution_ids={x["payload"]["execution_id"] for x in events
                   if x["event_type"] in ("model.turn.finished","tool.call.finished",
                                          "verification.finished","repair.decision")}
    assert execution_ids=={report.execution_id}
    model_rounds=[x["payload"]["round"] for x in events
                  if x["event_type"]=="model.turn.finished"]
    assert model_rounds==list(range(1,len(model_rounds)+1))
    assert all("content" not in x["payload"] and "prompt" not in x["payload"]
               for x in events)
    assert events[-1]["event_type"]=="mvp.task.finished"
    assert (Path(repo.repository_root)/"calc.py").read_text()=="def answer():\n    return 1\n"
    assert "return 42" not in trace_path.read_text()
