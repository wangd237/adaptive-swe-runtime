"""Installed frozen DeerFlow + ACTUAL Docker + Scheduler + Runtime canonical MVP.

The Store in this *physical topology* test injects a committed-run binding
directly instead of executing the 5C/5D source-inventory compiler. Dedicated
unit tests cover those contracts. Do not claim this single fixture proves full
production planning/5C inventory/AuthorizationProvider.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from deerflow.config.app_config import AppConfig
from deerflow.subagents.config import SubagentConfig
from deerflow.extensions import get_loaded_extensions

from aswe.integrations.deerflow.controlled_swe import (
    ControlledSWEWorkspace, DockerCommandBackend
)
from aswe.integrations.deerflow.native_execution import (
    NativeSubagentAssembler, NativeDeerFlowExecutionBackend
)
from aswe.integrations.deerflow.preparation import _tool_seal
from aswe.integrations.deerflow.tool_guard import (
    BoundToolView, NodeExecutionBinding, ToolCallGuard
)
from aswe.integrations.deerflow.mvp_task import MVPTaskRunner
from tests.unit.test_deerflow_controlled_swe_step5fc import policy as write_policy
from tests.unit.test_deerflow_mvp_task_step5fcb import prepared_mvp
from tests.integration.test_deerflow_docker_swe_step5fc import local_image_digest


class RealGraphScriptedRepairModel(BaseChatModel):
    """Deterministic offline model; real LangChain tool calls & subprocesses."""
    n: int = 0

    @property
    def _llm_type(self):
        return "physical-e2e-offline-scripted-repair"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.n += 1
        script = [
            ("read_file", {"path":"calc.py"}),
            ("str_replace", {"path":"calc.py", "old_str":"return 1",
                             "new_str":"return 2"}),
            ("bash", {"command":"grep -q 'return 42' calc.py"}),
            ("read_file", {"path":"calc.py"}),
            ("str_replace", {"path":"calc.py", "old_str":"return 2",
                             "new_str":"return 42"}),
            ("bash", {"command":"grep -q 'return 42' calc.py"}),
        ]
        if self.n <= len(script):
            name, args = script[self.n - 1]
            message=AIMessage(content="",tool_calls=[{
                "name":name,"args":args,"id":f"mvp-physical-{self.n}"
            }])
        else:
            message=AIMessage(content="calc.answer fixed; test command succeeded")
        return ChatResult(generations=[ChatGeneration(message=message)])


class PhysicalPreparedToolSource:
    """Test-only precommit tool source; full 5C physical inventory is separate.

    Unlike 5D and native execution, this preparer does NOT run the frozen
    5C inventory/compiler workflow. Its source and identity are test-fixed.
    """

    def __init__(self, *, core, repository, compiled_policy):
        from aswe.capabilities.effects import DEERFLOW_USE_BY_CONTRACT
        self.core=core
        self.repository=repository
        self.policy=compiled_policy
        self.prepared=None
        self.resources=None
        self._consumed=False
        self._tool_names=("read_file","str_replace","bash")
        configs=[
            {"name":name, "group":"swe", "use":DEERFLOW_USE_BY_CONTRACT[name]}
            for name in self._tool_names
        ]
        cfg=AppConfig.model_validate({
            "sandbox":{"use":"deerflow.sandbox.local:LocalSandboxProvider",
                       "allow_host_bash":False},
            "tools":configs,
        })
        sub=SubagentConfig(
            name="general-purpose",description="physical MVP coding",
            model="inherit",tools=list(self._tool_names),
            disallowed_tools=[],skills=[],system_prompt="Repair calc.answer",
            max_turns=25,timeout_seconds=50,
        )
        # Only tool NAME and Use contract from frozen 5C are supplied by this
        # fixture. 5D replaces these objects with sealed runtime wrappers.
        original=tuple(
            SimpleNamespace(name=name, func=None, coroutine=None, args_schema=None)
            for name in self._tool_names
        )
        self.resources=SimpleNamespace(
            model_name="offline-pinned",
            app_config=cfg,subagent_config=sub,extensions=get_loaded_extensions(),
            node_id=self.policy.node_id,
            effective_max_turns=25,effective_timeout_seconds=50,
            policy_fingerprint=self.policy.fingerprint,
            allowed_tool_ids=self._tool_names,tools=original,
            assert_intact=lambda:None,
        )

    async def prepare_node(self, node):
        assert node.id==self.policy.node_id
        assert self.prepared is None and not self._consumed
        self.prepared=node
        return node

    def claim_for_execution(self, preparation, invocation):
        from aswe.integrations.deerflow.preparation import DeerFlowPreparationError
        if (self._consumed or preparation is not self.prepared
                or not self.core.is_committed_invocation(invocation)
                or not self.core.is_active_execution(invocation)
                or invocation.node_id!=self.policy.node_id):
            raise DeerFlowPreparationError("PHYSICAL_TEST_PREPARATION_IDENTITY_UNTRUSTED")
        self._consumed=True
        return self.resources

    def release_preparation(self, preparation):
        self.prepared=None


def physical_binding_store(*, core, repository, image, compiled_policy):
    """Real Step 5D BindingStore and Runtime-created guarded SWE tools."""
    from aswe.integrations.deerflow.tool_guard import NodeExecutionBindingStore

    prepared=PhysicalPreparedToolSource(
        core=core,repository=repository,compiled_policy=compiled_policy)
    root=Path(repository.repository_root)
    principal=SimpleNamespace(
        user_id="mvp-runtime-owned",role="worker",
        oauth_provider=None,oauth_id=None,channel_user_id=None,
        is_internal=False,attributes={},
    )
    def build_swe(invocation, resources, policy):
        assert core.is_committed_invocation(invocation)
        return ControlledSWEWorkspace(
            invocation=invocation,policy=policy,root=root,
            command_backend=DockerCommandBackend(workspace_root=root,image=image),
        )
    real_store=NodeExecutionBindingStore(
        preparation_backend=prepared,
        principal_supplier=lambda _:principal,
        provider_supplier=lambda _:None,
        auth_request_factory=lambda **kwargs:kwargs,
        execution_live_checker=core.is_active_execution,
        swe_workspace_factory=build_swe,
        expected_swe_workspace_root=root,
    )
    # The collector is test-only and reads the actual immutable binding
    # returned by Step 5D, without changing its identity.
    original_bind=real_store.bind
    async def capture_bind(*, preparation, invocation):
        bound=await original_bind(preparation=preparation,invocation=invocation)
        real_store._captured_for_e2e=bound
        return bound
    real_store.bind=capture_bind
    return real_store


@pytest.mark.asyncio
async def test_real_installed_deerflow_real_docker_scheduler_to_verified_mvp_report(
        prepared_mvp):
    repo, core, store, verifier, canonical_policy=prepared_mvp
    policy=write_policy(tools=("read_file","str_replace","bash"))
    assert policy.node_id=="writer"
    image=local_image_digest()
    binding_store=physical_binding_store(
        core=core,repository=repo,image=image,compiled_policy=policy,
    )
    assembler=NativeSubagentAssembler.from_deerflow()
    assembler=NativeSubagentAssembler(replace(
        assembler.seams,create_chat_model=lambda **_: RealGraphScriptedRepairModel(),
    ))
    backend=NativeDeerFlowExecutionBackend(
        binding_store=binding_store,assembler=assembler,
        task_renderer=lambda _: "Fix calc.answer and iteratively test it",
        enable_native_execution=True,
        evidence_collector=None,  # full native sandbox quiescence deferred
    )
    result=await MVPTaskRunner(
        scheduler=core,backend=backend,repository=repo,
        verifier=verifier,policy=canonical_policy,
    ).run_node("writer")
    assert result.native_status=="completed"
    assert result.verification_status=="passed"
    assert result.verified_returncode==0
    assert result.changed_files==("calc.py",)
    assert "return 42" in result.git_diff
    assert Path(repo.repository_root,"calc.py").read_text().endswith("return 42\n")
    assert result.delivery_status=="tests_passed_scheduler_quarantined"
    assert result.workspace_status=="quarantined"
    assert result.scheduler_failed and not result.quiescence_proven
    assert result.canonical_receipt_ref is not None
    assert store.get(result.canonical_receipt_ref)["status"]=="holds"
    assert binding_store.preparation_backend._consumed
    assert binding_store.active_count==0
    assert len(binding_store._used)==1
    binding=binding_store._captured_for_e2e
    assert binding.guard.closed
    receipts=binding.guard.receipt_snapshot()
    assert len(receipts)==6
    assert {r["tool_call_id"] for r in receipts}=={
        f"mvp-physical-{i}" for i in range(1,7)}
    assert all(r["status"]=="completed" for r in receipts)
    summary=binding.swe_runtime.development_summary(native_terminal_status="completed")
    assert summary.dynamic_command_count==2
    assert summary.last_dynamic_command_exit_code==0
    assert summary.acceptance_status=="not_evaluated"
