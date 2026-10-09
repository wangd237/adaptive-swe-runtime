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
from deerflow.extensions import get_loaded_extensions
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


TOOL_INVOCATIONS: list[str] = []


@tool("read_file")
def read_file(path: str) -> str:
    """Read a harmless synthetic fixture path only; no filesystem access."""
    TOOL_INVOCATIONS.append(path)
    return "fixture:" + path


class OfflineToolCallingModel(BaseChatModel):
    """Real LangChain BaseChatModel; no provider/network/credential usage."""

    replies: int = 0

    @property
    def _llm_type(self) -> str:
        return "aswe-offline-physical-poc"

    def bind_tools(self, tools, **kwargs):
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
    app = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider", "allow_host_bash": False}})
    sub = SubagentConfig(
        name="general-purpose", description="Offline native physical PoC",
        model="inherit", tools=["read_file"], disallowed_tools=[],
        skills=[], system_prompt="Use tools only when allowed",
        max_turns=5, timeout_seconds=10,
    )
    resources = SimpleNamespace(
        model_name="offline-pinned", app_config=app, subagent_config=sub,
        extensions=get_loaded_extensions(), node_id="node-poc",
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
    graph = await executor._create_agent(tools, deferred_setup=None, extensions=binding.resources.extensions)
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
    graph = await executor._create_agent(tools, deferred_setup=deferred, extensions=binding.resources.extensions)
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
        await executor._create_agent(tools, deferred_setup=None, extensions=binding.resources.extensions)


@pytest.mark.asyncio
async def test_pinned_builtin_rbac_authorizes_and_denies_real_tool_call():
    """Use the frozen vendor's concrete Principal/AuthzRequest/Rbac provider."""
    from deerflow.authz.provider import AuthzRequest, AuthzDecision
    from deerflow.authz.principal import build_principal_from_context
    from deerflow.authz.rbac import RbacAuthorizationProvider

    principal = build_principal_from_context(
        {"user_id": "verified-user", "user_role": "reader",
         "authz_attributes": {"tenant": "fixture"}},
        default_role="reader",
    )
    provider = RbacAuthorizationProvider(roles={
        "reader": {
            "models": {"allow": ["offline-pinned"]},
            "tools": {"allow": ["read_file"]},
        }
    })
    assert provider.filter_resources(principal, "model", ["offline-pinned"]) == ["offline-pinned"]
    assert provider.filter_resources(principal, "tool", ["read_file", "bash"]) == ["read_file"]
    assert (await provider.aauthorize(AuthzRequest(
        principal=principal, resource="model", action="use", target="offline-pinned"
    ))).allow is True
    assert (await provider.aauthorize(AuthzRequest(
        principal=principal, resource="tool", action="call", target="bash"
    ))).allow is False

    binding = physical_binding(execution_id="rbac-poc")
    binding.guard.principal = principal
    from aswe.integrations.deerflow.preparation import _digest
    binding.guard._principal_digest = _digest(principal)
    binding.guard.provider = provider
    binding.guard._pinned_provider = provider
    binding.guard.auth_enabled = True
    binding.guard._auth_enabled_anchor = True
    binding.guard.request_factory = AuthzRequest

    assembler, _ = native_assembler_with_offline_model()
    executor = assembler.build(binding)
    state, tools, deferred = await executor._build_initial_state("read README")
    graph = await executor._create_agent(tools, deferred_setup=deferred, extensions=None)
    identity = {
        "run_id": binding.invocation.run_id, "user_id": principal.user_id,
        "user_role": principal.role, "oauth_provider": None, "oauth_id": None,
        "channel_user_id": None, "is_internal": False,
        "authz_attributes": dict(principal.attributes),
    }
    output = []
    async for frame in graph.astream(state, context=identity, config={"recursion_limit": 20}):
        output.append(frame)
    assert output
    assert binding.guard._used_call_ids == {"native-pinned-tool-call-1"}
    assert any(getattr(msg,"content",None) == "fixture:README.md"
               for msg in output[-1]["messages"])

    # Change policy instance to a deny policy in a FRESH run. The concrete
    # tool remains visible in the artificial test binding, but the native
    # ToolCallRequest MUST never execute it without the Layer 2 verdict.
    forbidden = RbacAuthorizationProvider(roles={"reader": {
        "models": {"allow": ["offline-pinned"]},
        "tools": {"allow": []},
    }})
    denied = physical_binding(execution_id="rbac-denied-poc")
    denied.guard.principal = principal
    denied.guard._principal_digest = _digest(principal)
    denied.guard.provider = forbidden
    denied.guard._pinned_provider = forbidden
    denied.guard.auth_enabled = True
    denied.guard._auth_enabled_anchor = True
    denied.guard.request_factory = AuthzRequest

    executor2 = assembler.build(denied)
    state2, tools2, _ = await executor2._build_initial_state("read README")
    graph2 = await executor2._create_agent(tools2, deferred_setup=None, extensions=None)
    output2 = []
    prior_invocations = len(TOOL_INVOCATIONS)
    caught_denial = False
    try:
        async for frame in graph2.astream(state2, context=identity,
                                          config={"recursion_limit": 20}):
            output2.append(frame)
    except Exception as exc:
        assert "AUTHORIZATION_CALL_DENIED" in str(exc)
        caught_denial = True
    assert len(TOOL_INVOCATIONS) == prior_invocations
    assert caught_denial or any(
        "AUTHORIZATION_CALL_DENIED" in str(getattr(message, "content", ""))
        for frame in output2 for message in frame.get("messages", [])
    )
    assert denied.guard._used_call_ids == {"native-pinned-tool-call-1"}
    assert not any(
        getattr(msg, "content", None) == "fixture:README.md"
        for frame in output2 for msg in frame.get("messages", [])
    )


@pytest.mark.asyncio
async def test_live_graph_refuses_revoked_binding_before_model_or_tool_call():
    assembler, models = native_assembler_with_offline_model()
    binding = physical_binding(execution_id="native-revoked-poc")
    executor = assembler.build(binding)
    state, tools, _ = await executor._build_initial_state("Read README")
    graph = await executor._create_agent(tools, deferred_setup=None, extensions=None)
    binding.guard.close()
    with pytest.raises(NativeExecutionError, match="NATIVE_BINDING_REVOKED"):
        async for _ in graph.astream(state, context={}, config={"recursion_limit": 20}):
            pass
    assert binding.guard._used_call_ids == set()


@pytest.mark.asyncio
async def test_real_subagent_executor_aexecute_native_lifecycle_offline():
    """Full frozen _aexecute admission, graph streaming and terminalization."""
    assembler, _ = native_assembler_with_offline_model()
    binding = physical_binding(execution_id="native-execute-poc")
    executor = assembler.build(binding)
    result = await executor._aexecute("Read README.md")
    assert getattr(result.status, "value", "") == "completed", (
        "Native lifecycle status must be completed, not merely graph-compiled"
    )
    assert result.result == "offline-native-complete"
    assert binding.guard._used_call_ids == {"native-pinned-tool-call-1"}
