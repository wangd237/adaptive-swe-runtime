"""5E bounded native-SubagentExecutor lifecycle tests.

The frozen real DeerFlow package is not installed by Python 3.11/3.13 CI.
These strict API-shaped fakes prove the native hooks, compiled ToolNode seal,
actual graph astream context, and cancellation/revocation boundaries.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
import pytest

from aswe.integrations.deerflow.native_execution import (
    NativeAssemblySeams, NativeSubagentAssembler,
    NativeDeerFlowExecutionBackend, NativeExecutionError,
)
from aswe.integrations.deerflow.tool_guard import (
    NodeExecutionBindingStore, ToolBindingError,
)
from tests.unit.test_deerflow_preparation_step5c import setup
from tests.unit.test_deerflow_tool_guard_step5d import (
    AuthRequest, Provider, record_async,
)
from tests.unit.test_scheduler_foundation import scheduler


class FakeToolNode:
    def __init__(self, names):
        self.tools_by_name = names


class FakeGraph:
    def __init__(self, *, tools, middleware, state):
        self.tools = tuple(tools)
        self.middleware = tuple(middleware)
        self.state = state
        self.last_context = None

    def get_graph(self):
        return SimpleNamespace(nodes={"tools": SimpleNamespace(
            data=FakeToolNode({t.name: t for t in self.tools}))} if self.tools else {})

    async def astream(self, state, *, config, context, stream_mode, **kwargs):
        self.last_context = dict(context)
        self.state["context"] = dict(context)
        self.state["stream_mode"] = stream_mode
        self.state["input"] = state
        if self.state.get("block") is not None:
            self.state["started"].set()
            await self.state["block"].wait()
        if self.state.get("invoke_tool") and self.tools:
            tool = self.tools[0]
            request = SimpleNamespace(
                tool=tool, runtime=SimpleNamespace(context=context),
                tool_call={"name":tool.name,"id":"g-call-1","args":{"path":"README.md"}}
            )
            await self.middleware[0].awrap_tool_call(
                request, lambda req: record_async(self.state["calls"],"read-ok")
            )
        yield {"messages": []}


class NativeFake:
    """Minimal signature-compatible shell for vendor _aexecute contract."""

    def __init__(self, config, tools, app_config=None, parent_model=None,
                 user_id=None, user_role=None, oauth_provider=None,
                 oauth_id=None, channel_user_id=None, is_internal=False,
                 authz_attributes=None, run_id=None, extensions=None,
                 acceptance_criteria=None, **kwargs):
        self.config=config
        self.tools=list(tools)
        self.app_config=app_config
        self.model_name=parent_model
        self.extensions=extensions
        self.user_id=user_id
        self.user_role=user_role
        self.oauth_provider=oauth_provider
        self.oauth_id=oauth_id
        self.channel_user_id=channel_user_id
        self.is_internal=is_internal
        self.authz_attributes=authz_attributes or {}
        self.run_id=run_id
        self._return_direct_tools=set()

    async def _aexecute(self, task):
        state,tools,deferred=await self._build_initial_state(task)
        agent=await self._create_agent(tools,deferred_setup=deferred,
                                        extensions=self.extensions)
        native_context={
            "run_id":self.run_id,
            "user_id":self.user_id,
            "user_role":self.user_role,
            "oauth_provider":self.oauth_provider,
            "oauth_id":self.oauth_id,
            "channel_user_id":self.channel_user_id,
            "is_internal":self.is_internal,
            "authz_attributes":self.authz_attributes,
        }
        async for _ in agent.astream(state, config={},context=native_context):
            pass
        return SimpleNamespace(status=SimpleNamespace(value="completed"),result="native-done")


def fake_assembler(state):
    def build_model(**kwargs):
        state["models"].append(kwargs)
        return SimpleNamespace(name=kwargs["name"])

    def make_graph(**kwargs):
        state["graphs"].append(kwargs)
        # The native graph fake keeps the actual tools registered by create_agent.
        names=kwargs["tools"]
        if state.get("impostor") and names:
            names=[SimpleNamespace(name=names[0].name)]
        if state.get("extra_tool"):
            names=[*names,SimpleNamespace(name="tool_search")]
        return FakeGraph(tools=names,middleware=kwargs["middleware"],state=state)

    class GuardMiddleware:
        def __init__(self,binding):
            self.binding=binding
            self.tools=[]
        async def awrap_tool_call(self,request,handler):
            binding=self.binding
            if (request.runtime.context.get("run_id")!=binding.invocation.run_id or
                    request.runtime.context.get("execution_id")!=binding.invocation.execution_id):
                raise ToolBindingError("TOOL_CALL_RUNTIME_CONTEXT_MISMATCH")
            return await binding.guard.ainvoke(
                tool=request.tool,tool_call_id=request.tool_call["id"],
                tool_input=request.tool_call["args"],
                handler=lambda:handler(request),
            )
    return NativeSubagentAssembler(NativeAssemblySeams(
        subagent_executor_cls=NativeFake,
        create_chat_model=build_model,
        create_agent=make_graph,
        system_message_cls=lambda content:("system",content),
        human_message_cls=lambda content:("human",content),
        tool_node_cls=FakeToolNode,
        tool_middleware_factory=GuardMiddleware,
        source_verifier=lambda:None,
    ))


def context(tmp_path,*,active=True,auth=False):
    prep,node,env,tool=setup()
    core,_=scheduler(tmp_path,node)
    prep.task_id=core.task_id
    prep.commit_checker=core.is_committed_invocation
    env["app"].authorization.enabled=auth
    store=NodeExecutionBindingStore(
        preparation_backend=prep,
        principal_supplier=lambda _:SimpleNamespace(
            user_id="host-user",role="worker",oauth_provider=None,oauth_id=None,
            channel_user_id=None,is_internal=False,attributes={}),
        provider_supplier=lambda _:Provider(),
        auth_request_factory=AuthRequest,
        execution_live_checker=core.is_active_execution,
    )
    trace={"models":[],"graphs":[],"calls":[],"invoke_tool":True}
    assembler=fake_assembler(trace)
    backend=NativeDeerFlowExecutionBackend(
        binding_store=store, assembler=assembler,
        task_renderer=lambda inv:"read the repository",
        enable_native_execution=active,
    )
    return backend,store,prep,core,node,env,tool,trace


@pytest.mark.asyncio
async def test_native_execution_default_off_does_not_consume_or_call(tmp_path):
    backend,store,prep,core,node,env,tool,trace=context(tmp_path,active=False)
    ticket=await core.claim(node.id)
    prepared=await backend.prepare_node(node)
    with pytest.raises(NativeExecutionError,match="NATIVE_EXECUTION_NOT_APPROVED"):
        await backend.execute_prepared(prepared,None)
    assert prep.pending_count==1
    assert not trace["models"] and not trace["graphs"]
    backend.release_preparation(prepared)
    await core.revoke(ticket.ticket_id)
    assert prep.pending_count==0


@pytest.mark.asyncio
async def test_native_graph_read_execution_is_context_sealed_and_not_quiescence_proof(tmp_path):
    backend,store,prep,core,node,env,tool,trace=context(tmp_path,auth=True)
    observed=[]
    class ProbeBackend:
        async def prepare_node(self,selected):
            return await backend.prepare_node(selected)
        async def execute_prepared(self,preparation,invocation):
            result=await backend.execute_prepared(preparation,invocation)
            observed.append((result,invocation))
            return result
        async def cancel_node(self,execution_id):
            await backend.cancel_node(execution_id)
        def release_preparation(self,prepared):
            backend.release_preparation(prepared)
    inv=await core.run_claim(await core.claim(node.id),ProbeBackend())
    assert inv is not None
    result,_=observed[0]
    assert result.terminal_status.value=="completed"
    assert result.quiescent is False and result.mutation_evidence=="unknown"
    assert trace["calls"]==["read-ok"]
    assert trace["models"][0]["name"]=="fake"
    assert trace["models"][0]["app_config"] is not env["app"]
    assert trace["context"]["execution_id"]==inv.execution_id
    assert trace["context"]["run_id"]==inv.run_id
    assert trace["context"]["user_id"]=="host-user"
    assert trace["stream_mode"]=="values"
    assert store.active_count==0
    assert not core.is_active_execution(inv)


@pytest.mark.asyncio
@pytest.mark.parametrize("attack",["impostor","extra_tool"])
async def test_compiled_registry_impostor_and_tool_search_injection_rejected(tmp_path,attack):
    backend,store,prep,core,node,env,tool,trace=context(tmp_path)
    trace[attack]=True
    class Probe:
        async def prepare_node(self,n):return await backend.prepare_node(n)
        async def execute_prepared(self,p,i):return await backend.execute_prepared(p,i)
        async def cancel_node(self,x):await backend.cancel_node(x)
    with pytest.raises(NativeExecutionError,match="COMPILED_TOOL_REGISTRY_DRIFT"):
        await core.run_claim(await core.claim(node.id), Probe())
    assert trace["models"] and trace["graphs"]
    assert trace["calls"]==[]
    assert store.active_count==0
    assert core.gate.state.value!="open"


@pytest.mark.asyncio
async def test_native_stream_cancel_revokes_guard_and_is_not_proven_quiescent(tmp_path):
    backend,store,prep,core,node,env,tool,trace=context(tmp_path)
    trace["started"]=asyncio.Event()
    trace["block"]=asyncio.Event()
    class Probe:
        async def prepare_node(self,n):return await backend.prepare_node(n)
        async def execute_prepared(self,p,i):return await backend.execute_prepared(p,i)
        async def cancel_node(self,x):await backend.cancel_node(x)
    ticket=await core.claim(node.id)
    runner=asyncio.create_task(core.run_claim(ticket,Probe()))
    await asyncio.wait_for(trace["started"].wait(),4)
    ids=tuple(store._active)
    assert len(ids)==1
    signal=backend._completion_events[ids[0]]
    assert not signal.is_set()  # the stream is blocked, future may be cancelled
    await backend.cancel_node(ids[0])
    assert signal.is_set()  # native outer coroutine truly left its finally
    with pytest.raises(asyncio.CancelledError):
        await runner
    assert store.active_count==0
    assert trace["calls"]==[]
    assert core.failed

@pytest.mark.asyncio
async def test_native_graph_runtime_principal_spoof_rejected_before_tool_call(tmp_path):
    from dataclasses import replace
    backend,store,prep,core,node,env,tool,trace=context(tmp_path)
    class SpoofNative(NativeFake):
        async def _aexecute(self,task):
            self.user_id="model-injected-user"
            return await super()._aexecute(task)
    backend.assembler.seams=replace(
        backend.assembler.seams,subagent_executor_cls=SpoofNative)
    class Probe:
        async def prepare_node(self,n):return await backend.prepare_node(n)
        async def execute_prepared(self,p,i):return await backend.execute_prepared(p,i)
        async def cancel_node(self,x):await backend.cancel_node(x)
    with pytest.raises(NativeExecutionError,match="NATIVE_RUNTIME_PRINCIPAL_MISMATCH"):
        await core.run_claim(await core.claim(node.id),Probe())
    assert trace["calls"]==[] and store.active_count==0


@pytest.mark.asyncio
async def test_native_executor_constructor_impostor_tool_rejected(tmp_path):
    from dataclasses import replace
    backend,store,prep,core,node,env,tool,trace=context(tmp_path)
    class RebindingNative(NativeFake):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.tools=[SimpleNamespace(name=t.name) for t in self.tools]
    backend.assembler.seams=replace(
        backend.assembler.seams,subagent_executor_cls=RebindingNative)
    class Probe:
        async def prepare_node(self,n):return await backend.prepare_node(n)
        async def execute_prepared(self,p,i):return await backend.execute_prepared(p,i)
        async def cancel_node(self,x):await backend.cancel_node(x)
    with pytest.raises(NativeExecutionError,match="NATIVE_EXECUTOR_BINDING_DRIFT"):
        await core.run_claim(await core.claim(node.id),Probe())
    assert trace["models"]==[] and store.active_count==0
