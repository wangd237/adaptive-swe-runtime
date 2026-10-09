"""Step 5E: tightly bounded native DeerFlow SubagentExecutor integration.

This adapter reuses the FROZEN native executor's admission, event streaming
and cleanup, but replaces its two open-ended agent assembly hooks. This
prevents a second tool_search/Skills/MCP/extensions/provider discovery from
widening the 5D once-only binding after the Scheduler's dispatch commit.

The native graph feature is OFF by default. No successful native result is
called quiescent until Step 5F supplies an independently trusted proof.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from aswe.core.contracts.backend import (
    BackendTerminalStatus, BackendExecutionPhase, NodeExecutionInvocation,
    NodeExecutionPreparation,
)
from aswe.integrations.deerflow.tool_guard import (
    NodeExecutionBinding, NodeExecutionBindingStore, ToolBindingError,
    ToolPolicyMiddleware, make_langchain_tool_policy_middleware,
)
from aswe.integrations.deerflow.preparation import DeerFlowPreparationError


class NativeExecutionError(RuntimeError):
    """Non-secret stable code; neither native error text nor credentials escape."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class NativeExecutionRecord:
    execution_id: str
    node_id: str
    attempt: int
    terminal_status: BackendTerminalStatus
    execution_phase: BackendExecutionPhase
    mutation_evidence: str
    result: str | None
    error: str | None
    failure_kind: str | None
    # This is deliberately FALSE before the Step 5F independent proof.
    quiescent: bool = False


def _assert_owner(binding: NodeExecutionBinding) -> None:
    if binding.guard.closed:
        raise NativeExecutionError("NATIVE_BINDING_REVOKED")
    try:
        binding.guard._live()
        binding.resources.assert_intact()
    except (ToolBindingError, DeerFlowPreparationError) as exc:
        raise NativeExecutionError("NATIVE_BINDING_STALE") from None


def _real_tool_registry(graph: Any, *, tool_node_type: type | None) -> Mapping[str, Any]:
    """Use the *compiled* LangGraph ToolNode, not config or prompt names."""
    try:
        nodes = graph.get_graph().nodes
        tool_node = nodes.get("tools")
        obj = tool_node.data if tool_node is not None else None
        if obj is None:
            return {}
        if tool_node_type is None or not isinstance(obj, tool_node_type):
            raise NativeExecutionError("COMPILED_TOOL_NODE_UNATTESTED")
        actual = getattr(obj, "tools_by_name", None)
        if not isinstance(actual, Mapping):
            raise NativeExecutionError("COMPILED_TOOL_NODE_UNATTESTED")
        return actual
    except NativeExecutionError:
        raise
    except Exception:
        raise NativeExecutionError("COMPILED_TOOL_REGISTRY_UNREADABLE") from None


class _ReservedContextGraph:
    """Graph proxy enforcing Scheduler-stamped context on each astream.

    Native SubagentExecutor writes run_id itself but not A-SWE execution_id.
    The graph proxy supplies that reserved ID from the committed invocation,
    without changing global LangChain state or ambient provider singletons.
    """

    def __init__(self, graph: Any, binding: NodeExecutionBinding):
        self._graph = graph
        self._binding = binding

    def __getattr__(self, key: str) -> Any:
        return getattr(self._graph, key)

    async def astream(self, state: Any, *, config: Any = None,
                      context: Any = None, stream_mode: str = "values", **kwargs: Any):
        _assert_owner(self._binding)
        if not isinstance(context, Mapping):
            raise NativeExecutionError("NATIVE_RUNTIME_CONTEXT_MISSING")
        inv = self._binding.invocation
        if context.get("run_id") != inv.run_id:
            raise NativeExecutionError("NATIVE_RUNTIME_RUN_ID_MISMATCH")
        if "execution_id" in context and context["execution_id"] != inv.execution_id:
            raise NativeExecutionError("NATIVE_RUNTIME_EXECUTION_ID_SPOOF")
        principal = self._binding.guard.principal
        native_identity = {
            "user_id": getattr(principal, "user_id", None),
            "user_role": getattr(principal, "role", None),
            "oauth_provider": getattr(principal, "oauth_provider", None),
            "oauth_id": getattr(principal, "oauth_id", None),
            "channel_user_id": getattr(principal, "channel_user_id", None),
            "is_internal": getattr(principal, "is_internal", None) is True,
            "authz_attributes": getattr(principal, "attributes", {}),
        }
        for key, expected in native_identity.items():
            if context.get(key) != expected:
                raise NativeExecutionError("NATIVE_RUNTIME_PRINCIPAL_MISMATCH")
        sealed = dict(context)
        sealed["execution_id"] = inv.execution_id
        sealed["run_id"] = inv.run_id
        sealed["is_subagent"] = True
        sealed["agent_id"] = self._binding.resources.node_id
        # Own this exact dictionary: no caller may reuse a mutable request
        # context and overwrite reserved fields after graph dispatch.
        native_stream = self._graph.astream(
            state, config=config, context=sealed,
            stream_mode=stream_mode, **kwargs,
        )
        try:
            async for part in native_stream:
                _assert_owner(self._binding)
                yield part
        finally:
            close = getattr(native_stream, "aclose", None)
            if callable(close):
                await close()


@dataclass(frozen=True)
class NativeAssemblySeams:
    """Trusted host wiring; only from_deerflow() loads the physical vendor."""
    subagent_executor_cls: type
    create_chat_model: Callable[..., Any]
    create_agent: Callable[..., Any]
    system_message_cls: type
    human_message_cls: type
    tool_node_cls: type
    tool_middleware_factory: Callable[[NodeExecutionBinding], Any]
    source_verifier: Callable[[], None]


class NativeSubagentAssembler:
    """Build real SubagentExecutor with bounded graph and exact ToolNode seal."""

    def __init__(self, seams: NativeAssemblySeams):
        self.seams = seams

    @classmethod
    def from_deerflow(cls):
        try:
            from deerflow.subagents.executor import SubagentExecutor
            from deerflow.subagents import executor as executor_module
            from deerflow.models import create_chat_model
            from deerflow.models import factory as factory_module
            from langchain.agents import create_agent
            from langchain_core.messages import SystemMessage, HumanMessage
            from langgraph.prebuilt import ToolNode
            from aswe.integrations.deerflow.inventory import assert_pinned_deerflow_source
        except ImportError as exc:
            raise NativeExecutionError("NATIVE_DEERFLOW_DEPENDENCY_UNAVAILABLE") from exc

        def verify():
            assert_pinned_deerflow_source(executor_module.__file__)
            assert_pinned_deerflow_source(factory_module.__file__)

        verify()
        return cls(NativeAssemblySeams(
            subagent_executor_cls=SubagentExecutor,
            create_chat_model=create_chat_model, create_agent=create_agent,
            system_message_cls=SystemMessage, human_message_cls=HumanMessage,
            tool_node_cls=ToolNode,
            tool_middleware_factory=make_langchain_tool_policy_middleware,
            source_verifier=verify,
        ))

    def build(self, binding: NodeExecutionBinding) -> Any:
        """Only return an executor when the graph's compiled ToolNode is sealed.

        A native subclass is needed because the frozen base independently
        loads Skills, deferred MCP, authz providers and middleware-declared
        tools in its two assembly hooks. It still uses native _aexecute()
        and _aexecute_admitted() for admission, streaming and teardown.
        """
        seams = self.seams
        seams.source_verifier()
        _assert_owner(binding)
        resources = binding.resources
        policy = ToolPolicyMiddleware(binding.tool_view)
        native_tools = binding.tool_view.objects
        if not native_tools:
            # Model-only native execution is valid when graph has no tools.
            pass
        policy.validate_build_inputs(tools=native_tools, middleware=())
        model_cls = seams.create_chat_model
        create_graph = seams.create_agent
        ToolNode = seams.tool_node_cls
        system_cls = seams.system_message_cls
        human_cls = seams.human_message_cls
        middleware_factory = seams.tool_middleware_factory
        NativeClass = seams.subagent_executor_cls
        if not all(callable(x) for x in (model_cls, create_graph, middleware_factory)):
            raise NativeExecutionError("NATIVE_ASSEMBLY_FACTORY_UNATTESTED")

        class BoundedNativeExecutor(NativeClass):
            async def _build_initial_state(self, task: str):
                # No second native Skill/Tool Search/MCP/Extension discovery.
                _assert_owner(binding)
                if not isinstance(task, str) or not task.strip():
                    raise NativeExecutionError("NATIVE_NODE_TASK_MISSING")
                if len(task) > 100000:
                    raise NativeExecutionError("NATIVE_NODE_TASK_EXCESSIVE")
                system = getattr(self.config, "system_prompt", "") or ""
                self._assembled_system_prompt = system
                self._assembled_skills = []
                self._available_skill_names = set()
                messages = []
                if system:
                    messages.append(system_cls(content=system))
                messages.append(human_cls(content=task))
                return {"messages": messages}, list(native_tools), None

            async def _create_agent(self, tools=None, *, deferred_setup=None, extensions=None):
                _assert_owner(binding)
                if deferred_setup is not None or extensions is not resources.extensions:
                    raise NativeExecutionError("NATIVE_DYNAMIC_ASSEMBLY_FORBIDDEN")
                if tools is None or len(tools) != len(native_tools) or any(
                    actual is not expected for actual, expected in zip(tools, native_tools)
                ):
                    raise NativeExecutionError("NATIVE_BASE_TOOL_LIST_CHANGED")
                # Model resolution must use copied AppConfig. The model cannot
                # select another name or provider from mutable global state.
                model = model_cls(
                    name=resources.model_name, app_config=resources.app_config,
                    thinking_enabled=False, attach_tracing=False,
                )
                middleware = middleware_factory(binding)
                policy.validate_build_inputs(
                    tools=tuple(tools), middleware=(middleware,),
                )
                agent = create_graph(
                    model=model, tools=list(tools),
                    middleware=[middleware], system_prompt=None,
                    checkpointer=False,
                )
                registry = _real_tool_registry(agent, tool_node_type=ToolNode)
                try:
                    policy.validate_compiled_registry(registry)
                except ToolBindingError as exc:
                    raise NativeExecutionError(exc.code) from None
                _assert_owner(binding)
                self._return_direct_tools = {
                    obj.name for obj in registry.values()
                    if getattr(obj, "return_direct", False)
                }
                # No native budget inflation. Recursion cap is conservative,
                # never above the compiled maximum turn ceiling.
                self._recursion_limit = resources.effective_max_turns
                return _ReservedContextGraph(agent, binding)

        principal = binding.guard.principal
        try:
            executor = BoundedNativeExecutor(
                config=deepcopy(resources.subagent_config),
                tools=list(native_tools),
                app_config=resources.app_config,
                parent_model=resources.model_name,
                user_id=getattr(principal, "user_id", None),
                user_role=getattr(principal, "role", None),
                oauth_provider=getattr(principal, "oauth_provider", None),
                oauth_id=getattr(principal, "oauth_id", None),
                channel_user_id=getattr(principal, "channel_user_id", None),
                is_internal=getattr(principal, "is_internal", None) is True,
                authz_attributes=deepcopy(getattr(principal, "attributes", {})),
                run_id=binding.invocation.run_id,
                extensions=resources.extensions,
                acceptance_criteria=[],
            )
            if (executor.app_config is not resources.app_config
                    or executor.extensions is not resources.extensions
                    or len(executor.tools) != len(native_tools)
                    or any(actual is not expected for actual, expected
                           in zip(executor.tools, native_tools))
                    or getattr(executor, "model_name", None) != resources.model_name):
                raise NativeExecutionError("NATIVE_EXECUTOR_BINDING_DRIFT")
        except NativeExecutionError:
            raise
        except Exception:
            raise NativeExecutionError("NATIVE_EXECUTOR_CONSTRUCTION_FAILED") from None
        return executor


class NativeDeerFlowExecutionBackend:
    """5E experimental adapter, with hard opt-in and no false quiescence claims.

    Caller MUST construct preparation/backend/store/assembler from trusted
    Runtime composition. Core still owns Scheduler commit, Workspace lock and
    acceptance; this adapter never manufactures Handoff or evidence.
    """

    def __init__(self, *, binding_store: NodeExecutionBindingStore,
                 assembler: NativeSubagentAssembler,
                 task_renderer: Callable[[NodeExecutionInvocation], str],
                 enable_native_execution: bool = False):
        self.store = binding_store
        self.assembler = assembler
        self.task_renderer = task_renderer
        self.enable_native_execution = enable_native_execution
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    async def prepare_node(self, node: Any) -> NodeExecutionPreparation:
        return await self.store.preparation_backend.prepare_node(node)

    def release_preparation(self, preparation: NodeExecutionPreparation) -> None:
        self.store.preparation_backend.release_preparation(preparation)

    async def execute_prepared(self, preparation: NodeExecutionPreparation,
                               invocation: NodeExecutionInvocation) -> NativeExecutionRecord:
        if not self.enable_native_execution:
            raise NativeExecutionError("NATIVE_EXECUTION_NOT_APPROVED")
        if not isinstance(invocation, NodeExecutionInvocation):
            raise NativeExecutionError("NATIVE_INVOCATION_UNATTESTED")
        if invocation.execution_id in self._tasks:
            raise NativeExecutionError("NATIVE_EXECUTION_REPLAY")
        binding = await self.store.bind(preparation=preparation, invocation=invocation)
        try:
            _assert_owner(binding)
            executor = self.assembler.build(binding)
            task_text = self.task_renderer(invocation)
            if not isinstance(task_text, str) or not task_text.strip():
                raise NativeExecutionError("NATIVE_NODE_TASK_MISSING")
            if len(task_text) > 100000:
                raise NativeExecutionError("NATIVE_NODE_TASK_EXCESSIVE")
            # Actual native _aexecute is run as an owned task. The outer
            # Scheduler's task still owns the authoritative attempt.
            async def run_native():
                return await executor._aexecute(task_text)

            child = asyncio.create_task(run_native())
            self._tasks[invocation.execution_id] = child
            try:
                try:
                    native_result = await asyncio.wait_for(
                        child, timeout=binding.resources.effective_timeout_seconds
                    )
                except asyncio.TimeoutError:
                    return NativeExecutionRecord(
                        execution_id=invocation.execution_id, node_id=invocation.node_id,
                        attempt=invocation.attempt, terminal_status=BackendTerminalStatus.TIMED_OUT,
                        execution_phase=BackendExecutionPhase.STARTED, mutation_evidence="unknown",
                        result=None, error=None, failure_kind="NATIVE_EXECUTION_TIMEOUT",
                    )
                status = getattr(getattr(native_result, "status", None), "value", None)
                if status is None:
                    status = str(getattr(native_result, "status", ""))
                mapped = {
                    "completed": BackendTerminalStatus.COMPLETED,
                    "failed": BackendTerminalStatus.FAILED,
                    "cancelled": BackendTerminalStatus.CANCELLED,
                    "timed_out": BackendTerminalStatus.TIMED_OUT,
                }.get(status, BackendTerminalStatus.FAILED)
                raw_result = getattr(native_result, "result", None)
                return NativeExecutionRecord(
                    execution_id=invocation.execution_id, node_id=invocation.node_id,
                    attempt=invocation.attempt, terminal_status=mapped,
                    execution_phase=BackendExecutionPhase.STARTED, mutation_evidence="unknown",
                    result=raw_result if isinstance(raw_result, str) else None,
                    error=None, failure_kind=(None if mapped is BackendTerminalStatus.COMPLETED
                                              else "NATIVE_EXECUTION_FAILED"),
                )
            finally:
                # wait_for may raise cancellation: only release a guard after
                # the native task has reached a terminal state. Do not claim
                # independent tool handler/sandbox quiescence.
                if not child.done():
                    child.cancel()
                    await asyncio.gather(child, return_exceptions=True)
                self._tasks.pop(invocation.execution_id, None)
        finally:
            self.store.release(invocation.execution_id)

    async def cancel_node(self, execution_id: str) -> None:
        # No ownership of foreign execution ID; do not enumerate global
        # DeerFlow background tasks or interrupt other work.
        self.store.release(execution_id)
        task = self._tasks.get(execution_id)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
