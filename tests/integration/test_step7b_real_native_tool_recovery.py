"""Physical Step 7B regression: real pinned LangGraph ToolNode and SWE file
operations, with a deterministic offline model (NOT claimed as live LLM).
The first write must genuinely fail in _write; the graph must continue.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from aswe.integrations.deerflow.native_execution import (
    NativeSubagentAssembler,
)
from aswe.integrations.deerflow.preparation import _tool_seal
from aswe.integrations.deerflow.tool_guard import (
    BoundToolView, NodeExecutionBinding, ToolCallGuard,
)
from tests.integration.test_deerflow_pinned_native_step5eb import physical_binding
from tests.unit.test_node_workspace_delta import repository as repository_fixture
from tests.unit.test_deerflow_controlled_swe_step5fc import env


class OfflineRecoveryModel(BaseChatModel):
    turns: int = 0
    original_path: str
    denied_seen: bool = False
    read_seen: bool = False

    @property
    def _llm_type(self) -> str:
        return "aswe-offline-recovery-physical"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.turns += 1
        if self.turns == 1:
            name = "str_replace"
            args = {"path": "step7b_target.py",
                    "old_str": "return 0", "new_str": "return 42"}
        elif self.turns == 2:
            # A real tool rejection happened, but no mutation was admitted.
            assert Path(self.original_path).read_text() == (
                "def answer():\n    return 0\n")
            self.denied_seen = any(
                getattr(m, "status", None) == "error"
                and "SWE_READ_BEFORE_WRITE_REQUIRED"
                in str(getattr(m, "content", ""))
                for m in messages
            )
            assert self.denied_seen
            name = "read_file"
            args = {"path": "step7b_target.py"}
        elif self.turns == 3:
            self.read_seen = any(
                getattr(m, "type", None) == "tool"
                and "def answer():" in str(getattr(m, "content", ""))
                for m in messages
            )
            assert self.read_seen
            name = "str_replace"
            args = {"path": "step7b_target.py",
                    "old_str": "return 0", "new_str": "return 42"}
        else:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content="offline recovery sequence complete"))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="", tool_calls=[{"name": name, "args": args,
                                      "id": f"step7b-physical-{self.turns:02d}"}],
        ))])


@pytest.mark.asyncio
async def test_physical_tool_reject_read_retry_succeeds(repository_fixture):
    root = Path(repository_fixture.repository_root)
    target = root / "step7b_target.py"
    target.write_text("def answer():\n    return 0\n")
    workspace, _ = env(repository_fixture,
                       tools=("read_file", "str_replace"), runner=False)
    tools = workspace.make_tools(("read_file", "str_replace"))
    base = physical_binding(execution_id="step7b-real-native")
    resources = base.resources
    resources.node_id = workspace.invocation.node_id
    resources.policy_fingerprint = workspace.policy.fingerprint
    resources.effective_max_turns = 12
    resources.subagent_config.max_turns = 12
    resources.subagent_config.tools = ["read_file", "str_replace"]
    view = BoundToolView(
        names=("read_file", "str_replace"), objects=tuple(tools),
        object_seals=tuple(_tool_seal(t) for t in tools),
    )
    guard = ToolCallGuard(
        invocation=workspace.invocation, resources=resources, view=view,
        principal=base.guard.principal, provider=None, request_factory=None,
        auth_enabled=False, policy=workspace.policy,
        execution_live_checker=lambda _: True, swe_runtime=workspace,
    )
    binding = NodeExecutionBinding(
        execution_id=workspace.invocation.execution_id,
        preparation_id="step7b-physical", invocation=workspace.invocation,
        resources=resources, tool_view=view, guard=guard,
        swe_runtime=workspace,
    )
    model = OfflineRecoveryModel(original_path=str(target))
    vendor = NativeSubagentAssembler.from_deerflow()
    assembler = NativeSubagentAssembler(
        replace(vendor.seams, create_chat_model=lambda **kwargs: model))
    executor = assembler.build(binding)
    state, native_tools, deferred = await executor._build_initial_state(
        "Repair the original file safely.")
    graph = await executor._create_agent(
        native_tools, deferred_setup=deferred,
        extensions=binding.resources.extensions)
    assert executor._recursion_limit >= 24
    p = guard.principal
    context = {
        "run_id": workspace.invocation.run_id,
        "user_id": p.user_id, "user_role": p.role,
        "oauth_provider": p.oauth_provider, "oauth_id": p.oauth_id,
        "channel_user_id": p.channel_user_id,
        "is_internal": p.is_internal, "authz_attributes": p.attributes,
    }
    states = []
    async for snapshot in graph.astream(
        state, context=context, stream_mode="values",
        config={"recursion_limit": executor._recursion_limit},
    ):
        states.append(snapshot)
    assert states and model.turns == 4
    assert model.denied_seen and model.read_seen
    assert target.read_text() == "def answer():\n    return 42\n"
    receipts = guard.receipt_snapshot()
    assert [(x["tool_name"], x["status"]) for x in receipts] == [
        ("str_replace", "denied"),
        ("read_file", "completed"),
        ("str_replace", "completed"),
    ]
    assert receipts[0]["failure_code"] == "SWE_READ_BEFORE_WRITE_REQUIRED"
    assert all(x["failure_code"] == "" for x in receipts[1:])
