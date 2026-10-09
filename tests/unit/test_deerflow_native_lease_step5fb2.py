"""5F-B2 lease owner and executor-owned quiescence negatives.

Real SandboxLeaseManager release semantics are separately exercised in
installed DeerFlow CI. These unit seams never claim a fake supervisor proves
a production process tree drained.
"""
from __future__ import annotations

import asyncio
import pytest

from aswe.integrations.deerflow.native_lease_supervisor import (
    NativeSandboxQuiescenceSupervisor, native_lease_owner, native_lease_task_id,
)
from tests.unit.test_deerflow_managed_foreground_step5fb import _approved
from tests.unit.test_node_workspace_delta import repository as repository_fixture


class Manager:
    def __init__(self): self.bindings={}
    def binding_for(self, owner):return self.bindings.get(owner)


@pytest.mark.asyncio
async def test_scope_verification_denies_lease_in_use_and_unjoined_task(repository_fixture):
    _, inv, _ = _approved(repository_fixture, ("pytest", "-q"))
    manager=Manager()
    provider=object()
    done={"value":False}
    async def no_process(_,__):return True
    witness=NativeSandboxQuiescenceSupervisor(
        initialized_provider=lambda:provider,
        manager_lookup=lambda x:manager,
        process_tree_probe=no_process)
    owner=witness.register_execution(inv,native_finished=lambda:done["value"])
    assert owner=="subagent:"+native_lease_task_id(inv)
    assert owner==native_lease_owner(inv)
    manager.bindings[owner]="sandbox-live"
    first=await witness.inspect(task_id=inv.task_id,execution_id=inv.execution_id)
    assert not first.complete and not first.sandbox_lease_released
    done["value"]=True
    still=await witness.inspect(task_id=inv.task_id,execution_id=inv.execution_id)
    assert not still.complete and still.tool_workers_drained
    del manager.bindings[owner]
    after=await witness.inspect(task_id=inv.task_id,execution_id=inv.execution_id)
    assert after.complete and after.sandbox_lease_released
    assert after.process_tree_drained
    witness.release_execution(inv.execution_id)
    stale=await witness.inspect(task_id=inv.task_id,execution_id=inv.execution_id)
    assert not stale.complete


@pytest.mark.asyncio
async def test_no_external_process_probe_never_positive_even_when_lease_removed(repository_fixture):
    _, inv, _ = _approved(repository_fixture, ("pytest", "-q"))
    manager=Manager()
    owner=native_lease_owner(inv)
    witness=NativeSandboxQuiescenceSupervisor(
        initialized_provider=lambda: object(),
        manager_lookup=lambda _: manager,
        process_tree_probe=None,
    )
    witness.register_execution(inv,native_finished=lambda:True)
    result=await witness.inspect(task_id=inv.task_id,execution_id=inv.execution_id)
    assert result.sandbox_lease_released is True
    assert result.process_tree_drained is False
    assert not result.complete


@pytest.mark.asyncio
async def test_provider_unknown_wrong_execution_or_probe_failure_denied(repository_fixture):
    _, inv, _ = _approved(repository_fixture, ("pytest", "-q"))
    async def fail_probe(*_):raise RuntimeError("not authenticated")
    witness=NativeSandboxQuiescenceSupervisor(
        initialized_provider=lambda:None,
        manager_lookup=lambda _: Manager(),
        process_tree_probe=fail_probe,
    )
    witness.register_execution(inv,native_finished=lambda:True)
    wrong=await witness.inspect(task_id=inv.task_id,execution_id="other")
    assert not wrong.complete
    no_provider=await witness.inspect(task_id=inv.task_id,execution_id=inv.execution_id)
    assert not no_provider.complete
    with pytest.raises(ValueError,match="NATIVE_LEASE_SCOPE_REPLAY"):
        witness.register_execution(inv,native_finished=lambda:True)
    witness2=NativeSandboxQuiescenceSupervisor(
        initialized_provider=lambda:object(),
        manager_lookup=lambda _:Manager(),
        process_tree_probe=fail_probe,
    )
    witness2.register_execution(inv,native_finished=lambda:True)
    failed=await witness2.inspect(task_id=inv.task_id,execution_id=inv.execution_id)
    assert not failed.complete
