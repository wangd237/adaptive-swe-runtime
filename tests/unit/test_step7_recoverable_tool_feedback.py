"""Step 7B: a denied file mutation can request a safe read/retry.

The native LangChain/DeerFlow packages are optional in ordinary unit CI.
The shim exercises the middleware contract; pinned-native CI checks imports.
"""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from aswe.integrations.deerflow.controlled_swe import SWEExecutionDenied
from aswe.integrations.deerflow.tool_guard import (
    ToolBindingError, make_langchain_tool_policy_middleware,
)
from tests.unit.test_deerflow_tool_guard_step5d import (
    bind_during_scheduler, record_async,
)


@pytest.fixture
def langchain_messages_stub(monkeypatch):
    root = ModuleType("langchain")
    root.__path__ = []
    agents = ModuleType("langchain.agents")
    agents.__path__ = []
    middleware = ModuleType("langchain.agents.middleware")
    middleware.AgentMiddleware = type("AgentMiddleware", (), {})
    core = ModuleType("langchain_core")
    core.__path__ = []
    messages = ModuleType("langchain_core.messages")

    class ToolMessage:
        def __init__(self, *, content, name, tool_call_id, status):
            self.content = content
            self.name = name
            self.tool_call_id = tool_call_id
            self.status = status

    messages.ToolMessage = ToolMessage
    for name, mod in (
        ("langchain", root), ("langchain.agents", agents),
        ("langchain.agents.middleware", middleware),
        ("langchain_core", core), ("langchain_core.messages", messages),
    ):
        monkeypatch.setitem(sys.modules, name, mod)
    return ToolMessage


def request(binding, tool, call_id):
    return SimpleNamespace(
        tool=tool,
        tool_call={"name": tool.name, "id": call_id, "args": {"path": "source.py"}},
        runtime=SimpleNamespace(context={
            "run_id": binding.invocation.run_id,
            "execution_id": binding.invocation.execution_id,
        }),
    )


async def _deny(code):
    raise SWEExecutionDenied(code)


def _deny_sync(code):
    raise SWEExecutionDenied(code)


@pytest.mark.asyncio
async def test_async_read_before_write_denial_is_observable_and_recoverable(
    tmp_path, langchain_messages_stub,
):
    data, store, _, _, _, _, _, _, invocation = await bind_during_scheduler(tmp_path)
    binding = data["binding"]
    tool = binding.tool_view.objects[0]
    middleware = make_langchain_tool_policy_middleware(binding)
    first = request(binding, tool, "denied-write")
    returned = await middleware.awrap_tool_call(
        first, lambda req: _deny("SWE_READ_BEFORE_WRITE_REQUIRED"))
    assert isinstance(returned, langchain_messages_stub)
    assert returned.status == "error"
    assert returned.tool_call_id == "denied-write"
    assert "Call read_file" in returned.content
    assert "bash does not satisfy" in returned.content
    receipts = binding.guard.receipt_snapshot()
    assert len(receipts) == 1
    assert receipts[0]["status"] == "denied"
    assert receipts[0]["failure_code"] == "SWE_READ_BEFORE_WRITE_REQUIRED"
    # A fresh call is still admitted: the first tool error did not tear
    # down the native execution binding or grant any write permission.
    following = await middleware.awrap_tool_call(
        request(binding, tool, "read-next"),
        lambda req: record_async([], "read-completed"),
    )
    assert following == "read-completed"
    assert [receipt["status"] for receipt in binding.guard.receipt_snapshot()] == [
        "denied", "completed",
    ]
    store.release(invocation.execution_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("exception", [
    SWEExecutionDenied("SWE_PATH_FORBIDDEN"),
    SWEExecutionDenied("SWE_SYMLINK_PATH_FORBIDDEN"),
    ToolBindingError("AUTHORIZATION_CALL_DENIED"),
])
async def test_other_denials_remain_fatal(
    tmp_path, langchain_messages_stub, exception,
):
    data, store, _, _, _, _, _, _, invocation = await bind_during_scheduler(tmp_path)
    binding = data["binding"]
    tool = binding.tool_view.objects[0]
    middleware = make_langchain_tool_policy_middleware(binding)

    async def fail(req):
        raise exception

    with pytest.raises(type(exception), match=str(exception)):
        await middleware.awrap_tool_call(request(binding, tool, "fatal"), fail)
    assert binding.guard.receipt_snapshot()[0]["status"] == "denied"
    store.release(invocation.execution_id)


@pytest.mark.asyncio
async def test_sync_recoverable_denial_has_same_semantics(
    tmp_path, langchain_messages_stub,
):
    data, store, _, _, _, _, _, _, invocation = await bind_during_scheduler(tmp_path)
    binding = data["binding"]
    tool = binding.tool_view.objects[0]
    middleware = make_langchain_tool_policy_middleware(binding)
    feedback = middleware.wrap_tool_call(
        request(binding, tool, "sync-recoverable"),
        lambda req: _deny_sync("SWE_READ_BEFORE_WRITE_REQUIRED"))
    assert isinstance(feedback, langchain_messages_stub)
    assert feedback.status == "error"
    assert feedback.tool_call_id == "sync-recoverable"
    assert binding.guard.receipt_snapshot()[0]["failure_code"] == (
        "SWE_READ_BEFORE_WRITE_REQUIRED")
    store.release(invocation.execution_id)
