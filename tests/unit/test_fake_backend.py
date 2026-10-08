import asyncio
import pytest
from aswe.core.contracts import BackendExecutionPhase, BackendTerminalStatus, NodeAttemptKind, NodeExecutionInvocation, TaskNode, WorkKind, WorkspaceAccess, WorkspaceRevision
from aswe.core.ids import new_execution_id, new_run_id, new_safe_id, new_task_id
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario, MutationEvidence

def _node()->TaskNode:
    return TaskNode(id="implement",objective="implement change",work_kind=WorkKind.IMPLEMENTATION,required_capabilities=("code_modification",),provider_id="coder",dependencies=(),workspace_access=WorkspaceAccess.WRITE,planner_ordinal=0,fingerprint="node-fp")

def _invocation(execution_id:str)->NodeExecutionInvocation:
    return NodeExecutionInvocation(task_id=new_task_id(),node_id="implement",attempt=1,attempt_kind=NodeAttemptKind.INITIAL,execution_id=execution_id,run_id=new_run_id(),execution_workspace_revision=WorkspaceRevision(generation=0,base_sha="a"*40,head_sha="a"*40,head_matches_baseline=True,repository_state_fingerprint="repo0",dirty=False),dispatch_ticket_id=new_safe_id("ticket"),task_dispatch_epoch=0,dependency_acceptance_stamps=(),dependency_context_text="",dependency_handoff_fingerprints=(),repair_feedback_text=None,context_fingerprint="ctx")

@pytest.mark.asyncio
async def test_prepare_allocates_no_execution_identity()->None:
    backend=FakeExecutionBackend()
    prep=await backend.prepare_node(_node())
    assert prep.preparation_id.startswith("aswe-prep-")
    assert "execution_id" not in type(prep).model_fields
    assert "run_id" not in type(prep).model_fields
    assert "attempt" not in type(prep).model_fields

@pytest.mark.asyncio
async def test_fake_backend_is_deterministic_and_uses_commit_identity()->None:
    backend=FakeExecutionBackend([FakeExecutionScenario(terminal_status=BackendTerminalStatus.FAILED,execution_phase=BackendExecutionPhase.STARTED,mutation_evidence=MutationEvidence.OBSERVED,result=None,error="boom")])
    prep=await backend.prepare_node(_node())
    execution_id=new_execution_id()
    record=await backend.execute_prepared(prep,_invocation(execution_id))
    assert record.execution_id==execution_id
    assert record.terminal_status is BackendTerminalStatus.FAILED
    assert record.mutation_evidence is MutationEvidence.OBSERVED

@pytest.mark.asyncio
async def test_fake_backend_has_controlled_barrier()->None:
    release=asyncio.Event()
    backend=FakeExecutionBackend([FakeExecutionScenario(release_event=release)])
    prep=await backend.prepare_node(_node())
    task=asyncio.create_task(backend.execute_prepared(prep,_invocation(new_execution_id())))
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    record=await task
    assert record.quiescent is True

@pytest.mark.asyncio
async def test_cancel_node_unblocks_waiting_fake_without_release() -> None:
    release = asyncio.Event()
    backend = FakeExecutionBackend([FakeExecutionScenario(release_event=release)])
    prep = await backend.prepare_node(_node())
    execution_id = new_execution_id()
    task = asyncio.create_task(backend.execute_prepared(prep, _invocation(execution_id)))
    await asyncio.sleep(0)
    assert not task.done()
    await backend.cancel_node(execution_id)
    record = await asyncio.wait_for(task, timeout=1)
    assert record.terminal_status is BackendTerminalStatus.CANCELLED
    assert not release.is_set()


@pytest.mark.asyncio
async def test_external_asyncio_cancellation_cleans_fake_wait_registry() -> None:
    release = asyncio.Event()
    backend = FakeExecutionBackend([FakeExecutionScenario(release_event=release)])
    prep = await backend.prepare_node(_node())
    execution_id = new_execution_id()
    task = asyncio.create_task(backend.execute_prepared(prep, _invocation(execution_id)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert execution_id not in backend._cancel_events
    assert execution_id not in backend.cancelled_execution_ids
    assert backend.records == []
    assert not release.is_set()

@pytest.mark.asyncio
async def test_fake_cancellation_is_idempotent_and_does_not_poison_later_execution() -> None:
    backend = FakeExecutionBackend([FakeExecutionScenario(), FakeExecutionScenario()])
    first = await backend.prepare_node(_node())
    execution_id = new_execution_id()
    await backend.cancel_node(execution_id)
    await backend.cancel_node(execution_id)
    cancelled = await backend.execute_prepared(first, _invocation(execution_id))
    assert cancelled.terminal_status is BackendTerminalStatus.CANCELLED
    assert backend.cancelled_execution_ids == set()
    normal = await backend.execute_prepared(
        await backend.prepare_node(_node()), _invocation(new_execution_id())
    )
    assert normal.terminal_status is BackendTerminalStatus.COMPLETED

@pytest.mark.asyncio
async def test_fake_backend_preparation_cannot_be_replayed() -> None:
    backend = FakeExecutionBackend([FakeExecutionScenario(), FakeExecutionScenario()])
    prep = await backend.prepare_node(_node())
    await backend.execute_prepared(prep, _invocation(new_execution_id()))
    with pytest.raises(ValueError, match="already been used"):
        await backend.execute_prepared(prep, _invocation(new_execution_id()))

@pytest.mark.asyncio
async def test_fake_backend_rejects_duplicate_execution_identity_across_preparations() -> None:
    backend = FakeExecutionBackend([FakeExecutionScenario(), FakeExecutionScenario()])
    execution_id = new_execution_id()
    await backend.execute_prepared(
        await backend.prepare_node(_node()), _invocation(execution_id)
    )
    with pytest.raises(ValueError, match="execution identity has already been used"):
        await backend.execute_prepared(
            await backend.prepare_node(_node()), _invocation(execution_id)
        )
