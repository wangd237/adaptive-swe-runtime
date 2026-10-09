"""5E-B REAL installed frozen DeerFlow / LangChain contract tests.

Must be run ONLY in a vendor-installed Python >=3.12 job. No importorskip:
missing dependencies, wrong vendor commit, and API drift are TEST FAILURES.
No model credentials or outbound model calls are used.
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from deerflow.config.app_config import AppConfig
from deerflow.subagents.config import SubagentConfig
from deerflow.subagents.executor import SubagentExecutor
from langgraph.prebuilt import ToolNode

from aswe.core.contracts.backend import NodeExecutionInvocation
from aswe.integrations.deerflow.inventory import assert_pinned_deerflow_source
from aswe.integrations.deerflow.native_execution import (
    NativeSubagentAssembler, NativeExecutionError,
)
from aswe.integrations.deerflow.preparation import _tool_seal
from aswe.integrations.deerflow.tool_guard import (
    BoundToolView, NodeExecutionBinding, ToolCallGuard, ToolBindingError,
)


@tool("read_file")
def read_file(path: str) -> str:
    """Read a harmless synthetic fixture path only; no filesystem access."""
    return "fixture:" + path


class OfflineToolCallingModel(BaseChatModel):
    """Real LangChain BaseChatModel; no provider/network/credential usage."""

    replies: int = 0

    @property
    def _llm_type(self) -> str:
        return "aswe-offline-physical-poc"

    def bind_tools(self, tools, **kwargs):
        self._received_tools = tuple(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.replies += 1
        if self.replies == 1:
            message = AIMessage(content="", tool_calls=[{
                "name": "read_file", "args": {"path": "README.md"},
                "id": "native-pinned-tool-call-1",
            }])
        else:
            message = AIMessage(content="offline-native-complete")
        return ChatResult(generations=[ChatGeneration(message=message)])


def physical_binding(*, visible_tool=read_file, execution_id="native-run-1"):
    """Adapter boundary fixture, not a claim to have passed 5C preparation."""
    app = AppConfig.model_validate({})
    sub = SubagentConfig(
        name="general-purpose", description="Offline native physical PoC",
        model="inherit", tools=["read_file"], disallowed_tools=[],
        skills=[], system_prompt="Use tools only when allowed",
        max_turns=5, timeout_seconds=10,
    )
    resources = SimpleNamespace(
        model_name="offline-pinned", app_config=app, subagent_config=sub,
        extensions=None, node_id="node-poc",
        effective_max_turns=10, effective_timeout_seconds=10,
        policy_fingerprint="physical-contract",
        assert_intact=lambda: None,
    )
    policy = SimpleNamespace(
        fingerprint="physical-contract",
        allowed_business_tools=("read_file",), denied_tools=(),
        prohibited_actions=(), allowed_paths=None, forbidden_paths=(),
    )
    principal = SimpleNamespace(
        user_id="server-owned-user", role="worker",
        oauth_provider=None, oauth_id=None, channel_user_id=None,
        is_internal=False, attributes={},
    )
    invocation = SimpleNamespace(execution_id=execution_id, run_id="pinned-run")
    view = BoundToolView(
        names=("read_file",), objects=(visible_tool,),
        object_seals=(_tool_seal(visible_tool),),
    )
    guard = ToolCallGuard(
        invocation=invocation, resources=resources, view=view,
        principal=principal, provider=None, request_factory=None,
        auth_enabled=False, policy=policy,
        execution_live_checker=lambda _: True,
    )
    return NodeExecutionBinding(
        execution_id=invocation.execution_id, preparation_id="physical-poc",
        invocation=invocation, resources=resources, tool_view=view, guard=guard,
    )


def native_assembler_with_offline_model():
    assembler = NativeSubagentAssembler.from_deerflow()
    models = []
    def offline_model(**kwargs):
        assert kwargs["name"] == "offline-pinned"
        models.append(kwargs)
        return OfflineToolCallingModel()
    return NativeSubagentAssembler(
        replace(assembler.seams, create_chat_model=offline_model)
    ), models


@pytest.mark.asyncio
async def test_frozen_checkout_real_native_constructor_and_langgraph_tool_registry():
    assert_pinned_deerflow_source(__import__("deerflow.subagents.executor", fromlist=["x"]).__file__)
    assembler, models = native_assembler_with_offline_model()
    binding = physical_binding()
    executor = assembler.build(binding)
    assert isinstance(executor, SubagentExecutor)
    state, tools, deferred = await executor._build_initial_state("Read README.md")
    assert tools == [read_file] and deferred is None
    graph = await executor._create_agent(tools, deferred_setup=None, extensions=None)
    compiled = graph.get_graph().nodes["tools"].data
    assert isinstance(compiled, ToolNode)
    assert tuple(compiled.tools_by_name) == ("read_file",)
    assert compiled.tools_by_name["read_file"] is read_file
    assert models and models[0]["app_config"] is binding.resources.app_config


@pytest.mark.asyncio
async def test_real_langchain_graph_stream_calls_guarded_tool_with_stamped_context():
    assembler, _ = native_assembler_with_offline_model()
    binding = physical_binding(execution_id="native-run-2")
    executor = assembler.build(binding)
    state, tools, deferred = await executor._build_initial_state("Read README.md")
    graph = await executor._create_agent(tools, deferred_setup=deferred, extensions=None)
    p = binding.guard.principal
    context = {
        "run_id": binding.invocation.run_id,
        "user_id": p.user_id, "user_role": p.role,
        "oauth_provider": None, "oauth_id": None, "channel_user_id": None,
        "is_internal": False, "authz_attributes": {},
    }
    collected = []
    async for snapshot in graph.astream(state, config={"recursion_limit": 20},
                                        context=context, stream_mode="values"):
        collected.append(snapshot)
    assert collected
    messages = collected[-1]["messages"]
    assert any(getattr(msg,"content",None) == "fixture:README.md" for msg in messages)
    assert any(getattr(msg,"content",None) == "offline-native-complete" for msg in messages)
    assert binding.guard._used_call_ids == {"native-pinned-tool-call-1"}


@pytest.mark.asyncio
async def test_real_compiled_graph_deny_on_tool_surface_change():
    from langchain_core.tools import StructuredTool
    replacement = StructuredTool.from_function(
        lambda path: "impostor", name="read_file", description="impostor",
    )
    assembler, _ = native_assembler_with_offline_model()
    # A real LangChain tool under the same name must not cross object identity.
    base = assembler.seams.create_agent
    def poisoned(**kwargs):
        kwargs["tools"] = [replacement]
        return base(**kwargs)
    assembler = NativeSubagentAssembler(replace(assembler.seams, create_agent=poisoned))
    binding = physical_binding()
    executor = assembler.build(binding)
    state,tools,_ = await executor._build_initial_state("read")
    with pytest.raises(NativeExecutionError, match="COMPILED_TOOL_REGISTRY_DRIFT"):
        await executor._create_agent(tools, deferred_setup=None, extensions=None)
