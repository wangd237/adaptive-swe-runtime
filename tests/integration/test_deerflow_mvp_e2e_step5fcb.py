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


class CommittedPhysicalBindingStore:
    """Fixture composes genuine vendor graph, Guard and Docker AFTER commit."""

    def __init__(self, *, core, repository, image, compiled_policy):
        self.core=core
        self.repository=repository
        self.image=image
        self.policy=compiled_policy
        self.preparation_backend=self
        self.last_binding=None
        self.bind_calls=0
        self.release_calls=0

    async def prepare_node(self, node):
        assert node.id==self.policy.node_id
        return node

    def release_preparation(self, preparation):
        pass

    async def bind(self, *, preparation, invocation):
        assert self.core.is_committed_invocation(invocation)
        assert self.core.is_active_execution(invocation)
        assert invocation.node_id == self.policy.node_id
        self.bind_calls += 1
        assert self.bind_calls==1
        root=Path(self.repository.repository_root)
        runtime=ControlledSWEWorkspace(
            invocation=invocation,policy=self.policy,root=root,
            command_backend=DockerCommandBackend(workspace_root=root,image=self.image),
        )
        tools=runtime.make_tools(("read_file","str_replace","bash"))
        resources=SimpleNamespace(
            model_name="offline-pinned",
            app_config=AppConfig.model_validate({
                "sandbox":{"use":"deerflow.sandbox.local:LocalSandboxProvider",
                           "allow_host_bash":False}
            }),
            subagent_config=SubagentConfig(
                name="general-purpose",description="physical MVP coding",
                model="inherit",tools=[tool.name for tool in tools],
                disallowed_tools=[],skills=[],system_prompt="Repair calc.answer",
                max_turns=25,timeout_seconds=50,
            ),
            extensions=get_loaded_extensions(),
            node_id=invocation.node_id,
            effective_max_turns=25,effective_timeout_seconds=50,
            policy_fingerprint=self.policy.fingerprint,
            assert_intact=lambda:None,
        )
        principal=SimpleNamespace(
            user_id="mvp-runtime-owned",role="worker",
            oauth_provider=None,oauth_id=None,channel_user_id=None,
            is_internal=False,attributes={},
        )
        view=BoundToolView(
            names=tuple(tool.name for tool in tools),objects=tools,
            object_seals=tuple(_tool_seal(tool) for tool in tools),
        )
        guard=ToolCallGuard(
            invocation=invocation,resources=resources,view=view,
            principal=principal,provider=None,request_factory=None,
            auth_enabled=False,policy=self.policy,
            execution_live_checker=self.core.is_active_execution,
            swe_runtime=runtime,
        )
        binding=NodeExecutionBinding(
            execution_id=invocation.execution_id,
            preparation_id="installed-offline-physical-e2e",
            invocation=invocation,resources=resources,tool_view=view,
            guard=guard,swe_runtime=runtime,
        )
        self.last_binding=binding
        return binding

    def release(self,execution_id):
        self.release_calls+=1
        assert self.last_binding is not None
        assert self.last_binding.execution_id==execution_id
        self.last_binding.guard.close()


@pytest.mark.asyncio
async def test_real_installed_deerflow_real_docker_scheduler_to_verified_mvp_report(
        prepared_mvp):
    repo, core, store, verifier, canonical_policy=prepared_mvp
    policy=write_policy(tools=("read_file","str_replace","bash"))
    assert policy.node_id=="writer"
    image=local_image_digest()
    binding_store=CommittedPhysicalBindingStore(
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
    assert binding_store.bind_calls==1 and binding_store.release_calls==1
    binding=binding_store.last_binding
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
