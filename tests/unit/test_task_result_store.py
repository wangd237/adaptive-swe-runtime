"""Terminal TaskResult publication survives process restart, rejects overwrite/tamper."""
import json
import pytest

from aswe.runtime.result_store import LocalTaskResultStore, TaskResultIntegrityError, finalize_and_persist_task
from aswe.runtime.finalization import TaskLogicalStatus
from tests.unit.test_task_finalization import terminal_fixture
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario
from tests.unit.test_scheduler_foundation import accept


@pytest.mark.asyncio
async def test_terminal_result_persists_outside_workspace_and_survives_restart(terminal_fixture, tmp_path):
    core, _, binding, evidence = terminal_fixture
    await core.run_claim(await core.claim("writer"),
                         FakeExecutionBackend([FakeExecutionScenario()]), accept=accept)
    await core.complete_task()
    path = tmp_path / "terminals"
    store = LocalTaskResultStore(runtime_data_dir=path, workspace_root=binding.repository_root)
    result = finalize_and_persist_task(
        result_store=store, scheduler=core, binding=binding,
        evidence_store=evidence,
    )
    assert result.status is TaskLogicalStatus.FAILED  # No ContractVerdict may be inferred
    assert LocalTaskResultStore(runtime_data_dir=path).get(core.task_id) == result
    with pytest.raises(TaskResultIntegrityError, match="already published"):
        store.persist(result)


@pytest.mark.asyncio
async def test_tampered_terminal_result_is_never_returned(terminal_fixture, tmp_path):
    core, _, binding, evidence = terminal_fixture
    await core.fail_closed("FAILED")
    store = LocalTaskResultStore(runtime_data_dir=tmp_path / "terminals")
    result = finalize_and_persist_task(result_store=store, scheduler=core,
        binding=binding, evidence_store=evidence)
    file = store._path(core.task_id)
    data = json.loads(file.read_text())
    data["status"] = "succeeded"
    file.write_text(json.dumps(data))
    with pytest.raises(TaskResultIntegrityError, match="corrupted"):
        store.get(core.task_id)


def test_terminal_store_rejects_workspace_root(tmp_path):
    with pytest.raises(ValueError, match="outside Workspace"):
        LocalTaskResultStore(runtime_data_dir=tmp_path / "workspace" / "runtime",
                             workspace_root=tmp_path / "workspace")
