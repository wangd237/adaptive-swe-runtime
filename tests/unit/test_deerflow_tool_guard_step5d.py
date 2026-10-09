"""Step 5D deterministic Model/Tool visibility and per-call authorization.

Native DeerFlow/LLM is intentionally NOT launched. API-shaped provider stubs
exercise the frozen AuthzRequest(resource/action/target/context) semantics.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
import pytest

from aswe.integrations.deerflow.tool_guard import (
    NodeExecutionBindingStore, ToolBindingError, ToolPolicyMiddleware,
)
from tests.unit.test_deerflow_preparation_step5c import setup, StubLoadedExtensions
from tests.unit.test_scheduler_foundation import scheduler, accept
from tests.fakes.backend import FakeExecutionBackend, FakeExecutionScenario


@dataclass
class Decision:
    allow: bool


@dataclass
class AuthRequest:
    principal: object
    resource: str
    action: str
    target: str
    context: dict = field(default_factory=dict)


class Provider:
    def __init__(self):
        self.filters: list[tuple[str, tuple[str, ...]]] = []
        self.requests = []
        self.visible_models = True
        self.visible_tools = True
        self.allow_model = True
        self.allow_tool = True
        self.throw = False
        self.started = None
        self.resume = None

    def filter_resources(self, principal, resource, names):
        self.filters.append((resource, tuple(names)))
        if self.throw:
            raise RuntimeError("secret provider token")
        if resource == "model" and not self.visible_models:
            return []
        if resource == "tool" and not self.visible_tools:
            return []
        return names

    def authorize(self, request):
        self.requests.append(request)
        if self.throw:
            raise RuntimeError("secret provider token")
        return Decision(self.allow_tool if request.resource == "tool" else self.allow_model)

    async def aauthorize(self, request):
        self.requests.append(request)
        if self.started is not None:
            self.started.set()
        if self.resume is not None:
            await self.resume.wait()
        if self.throw:
            raise RuntimeError("secret provider token")
        return Decision(self.allow_tool if request.resource == "tool" else self.allow_model)


async def bind_during_scheduler(tmp_path, *, configure=None, provider=None,
                                liveness_checker=None):
    """Drive real _commit under Workspace lock; no native model/tool runs."""
    backend, node, env, tool = setup()
    core, _ = scheduler(tmp_path, node)
    backend.task_id = core.task_id
    backend.commit_checker = core.is_committed_invocation
    provider = provider or Provider()
    if configure:
        configure(env)
    auth = env["app"].authorization
    store = NodeExecutionBindingStore(
        preparation_backend=backend,
        principal_supplier=lambda resources: SimpleNamespace(user_id="host-uid", is_internal=False),
        provider_supplier=lambda config: provider,
        auth_request_factory=AuthRequest,
        execution_live_checker=liveness_checker or (lambda invocation: True),
    )
    fake = FakeExecutionBackend([FakeExecutionScenario()])
    result = {}

    class Bridge:
        async def prepare_node(self, actual):
            return await backend.prepare_node(actual)

        async def execute_prepared(self, preparation, invocation):
            result["committed"] = core.is_committed_invocation(invocation)
            try:
                result["binding"] = await store.bind(preparation=preparation, invocation=invocation)
            except ToolBindingError as exc:
                result["error"] = exc.code
            raw = await fake.prepare_node(node)
            return await fake.execute_prepared(raw, invocation)

        def release_preparation(self, preparation):
            backend.release_preparation(preparation)

        async def cancel_node(self, execution_id):
            await fake.cancel_node(execution_id)

    invocation = await core.run_claim(await core.claim(node.id), Bridge(), accept=accept)
    return result, store, backend, core, node, env, tool, provider, invocation


@pytest.mark.asyncio
async def test_authorized_binding_model_visibility_and_tool_call_permit(tmp_path):
    def enabled(env):
        env["app"].authorization.enabled = True
    result, store, backend, core, node, env, tool, provider, invocation = (
        await bind_during_scheduler(tmp_path, configure=enabled))
    assert result["committed"] and invocation is not None
    binding = result["binding"]
    assert binding.invocation is invocation
    assert binding.resources.tools == (tool,)
    assert binding.tool_view.names == ("read_file",)
    assert provider.filters == [("model", ("fake",)), ("tool", ("read_file",))]
    assert [(x.resource, x.action, x.target) for x in provider.requests] == [
        ("model", "use", "fake")]
    assert store.lookup(invocation.execution_id) is binding
    visible = binding.tool_view
    policy = ToolPolicyMiddleware(visible)
    policy.validate_build_inputs(tools=(tool,), middleware=())
    policy.validate_compiled_registry({"read_file": tool})
    invoked = []
    out = await binding.guard.ainvoke(
        tool=tool, tool_call_id="call-1", tool_input={"path": "README.md"},
        handler=lambda: record_async(invoked, "ok"))
    assert out == "ok" and invoked == ["ok"]
    assert provider.requests[-1].resource == "tool"
    assert provider.requests[-1].action == "call"
    assert provider.requests[-1].target == "read_file"
    assert provider.requests[-1].context["tool_input"] == {"path": "README.md"}
    assert provider.requests[-1].context["run_id"] == invocation.run_id
    with pytest.raises(ToolBindingError, match="TOOL_CALL_REPLAY"):
        await binding.guard.ainvoke(tool=tool, tool_call_id="call-1",
            tool_input={}, handler=lambda: record_async(invoked, "replayed"))
    assert invoked == ["ok"]
    store.release(invocation.execution_id)
    assert store.active_count == 0
    with pytest.raises(ToolBindingError, match="EXECUTION_BINDING_CLOSED"):
        await binding.guard.ainvoke(tool=tool, tool_call_id="call-2",
            tool_input={}, handler=lambda: record_async(invoked, "closed"))


async def record_async(calls, item):
    calls.append(item)
    return item


@pytest.mark.asyncio
@pytest.mark.parametrize(("change","code"),[
    ("model_hidden","MODEL_VISIBILITY_DENIED"),
    ("tool_hidden","REQUIRED_TOOL_VISIBILITY_DENIED"),
    ("model_denied","MODEL_AUTHORIZATION_DENIED"),
    ("provider_error","AUTHORIZATION_VISIBILITY_FAILED"),
    ("fail_open","AUTHORIZATION_FAIL_OPEN_FORBIDDEN"),
])
async def test_provider_visibility_and_model_permission_fail_closed(tmp_path, change, code):
    provider = Provider()
    def configure(env):
        env["app"].authorization.enabled = True
        if change == "model_hidden": provider.visible_models = False
        if change == "tool_hidden": provider.visible_tools = False
        if change == "model_denied": provider.allow_model = False
        if change == "provider_error": provider.throw = True
        if change == "fail_open": env["app"].authorization.fail_closed = False
    result, store, backend, core, node, env, tool, _, invocation = (
        await bind_during_scheduler(tmp_path, configure=configure, provider=provider))
    assert result["error"] == code
    assert "binding" not in result
    assert store.active_count == 0
    assert backend.pending_count == 0
    assert len(core.states[node.id].attempts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("change","code"),[
    ("tool_search","DYNAMIC_TOOL_DISCOVERY_UNSUPPORTED"),
    ("skill_evolution","SKILL_EVOLUTION_UNSUPPORTED"),
    ("plugin","DYNAMIC_EXTENSIONS_UNSUPPORTED"),
    ("mcp_use","DYNAMIC_TOOL_PROVENANCE_FORBIDDEN"),
])
async def test_dynamic_skill_mcp_plugin_provenance_refused(tmp_path, change, code):
    def configure(env):
        if change == "tool_search": env["app"].tool_search.enabled = True
        if change == "skill_evolution": env["app"].skill_evolution.enabled = True
        if change == "plugin":
            object.__setattr__(env["extensions"], "plugins", (("plugin", object()),))
        if change == "mcp_use":
            env["app"].tools[0].use = "foreign.mcp:read_file"
    backend, node, env, tool = setup()
    core, _ = scheduler(tmp_path, node)
    backend.task_id = core.task_id
    backend.commit_checker = core.is_committed_invocation
    configure(env)
    if change == "mcp_use":
        # 5C itself must refuse foreign implementation before binding.
        with pytest.raises(Exception):
            await backend.prepare_node(node)
        assert backend.pending_count == 0
        return
    store = NodeExecutionBindingStore(
        preparation_backend=backend,
        principal_supplier=lambda _: SimpleNamespace(user_id="host", is_internal=False),
        provider_supplier=lambda _: None,
        auth_request_factory=AuthRequest,
        execution_live_checker=lambda invocation: True,
    )
    fake = FakeExecutionBackend([FakeExecutionScenario()])
    error = None

    class B:
        async def prepare_node(self, n):
            return await backend.prepare_node(n)
        async def execute_prepared(self, p, invocation):
            nonlocal error
            with pytest.raises(ToolBindingError) as caught:
                await store.bind(preparation=p, invocation=invocation)
            error = caught.value.code
            raw = await fake.prepare_node(node)
            return await fake.execute_prepared(raw, invocation)
        async def cancel_node(self, x):
            await fake.cancel_node(x)

    await core.run_claim(await core.claim(node.id), B(), accept=accept)
    assert error == code and store.active_count == 0



@pytest.mark.asyncio
async def test_model_visible_surface_and_middleware_collision_rejected(tmp_path):
    result, store, backend, core, node, env, tool, _, invocation = (
        await bind_during_scheduler(tmp_path))
    binding = result["binding"]
    gate = ToolPolicyMiddleware(binding.tool_view)
    with pytest.raises(ToolBindingError, match="MODEL_TOOL_SURFACE_DRIFT"):
        gate.validate_build_inputs(
            tools=(SimpleNamespace(name="read_file"),), middleware=())
    with pytest.raises(ToolBindingError, match="MIDDLEWARE_TOOL_DECLARATION_FORBIDDEN"):
        gate.validate_build_inputs(tools=(tool,),
            middleware=(SimpleNamespace(tools=(SimpleNamespace(name="stealth"),)),))
    with pytest.raises(ToolBindingError, match="COMPILED_TOOL_REGISTRY_DRIFT"):
        gate.validate_compiled_registry({"read_file": SimpleNamespace(name="read_file")})
    with pytest.raises(ToolBindingError, match="COMPILED_TOOL_REGISTRY_DRIFT"):
        gate.validate_compiled_registry({"read_file": tool, "tool_search": tool})


@pytest.mark.asyncio
async def test_runtime_tool_call_deny_sync_async_and_object_spoof(tmp_path):
    def enabled(env):
        env["app"].authorization.enabled = True
    provider = Provider()
    result, store, backend, core, node, env, tool, _, invocation = (
        await bind_during_scheduler(tmp_path, configure=enabled, provider=provider))
    gate = result["binding"].guard
    calls = []
    provider.allow_tool = False
    with pytest.raises(ToolBindingError, match="AUTHORIZATION_CALL_DENIED"):
        await gate.ainvoke(tool=tool, tool_call_id="call-denied",
            tool_input={"path":"a"}, handler=lambda: record_async(calls, "bad"))
    with pytest.raises(ToolBindingError, match="AUTHORIZATION_CALL_DENIED"):
        gate.invoke(tool=tool, tool_call_id="sync-denied",
            tool_input={"path":"a"}, handler=lambda: calls.append("bad"))
    assert not calls
    provider.allow_tool = True
    impostor = SimpleNamespace(name=tool.name, func=tool.func)
    with pytest.raises(ToolBindingError, match="UNBOUND_TOOL_OBJECT"):
        await gate.ainvoke(tool=impostor, tool_call_id="spoof",
            tool_input={}, handler=lambda: record_async(calls, "bad"))
    with pytest.raises(ToolBindingError, match="TOOL_CALL_ID_REQUIRED"):
        await gate.ainvoke(tool=tool, tool_call_id="", tool_input={},
            handler=lambda: record_async(calls, "bad"))
    assert gate.invoke(tool=tool, tool_call_id="sync-pass", tool_input="str",
        handler=lambda: calls.append("sync-ok")) is None
    assert calls == ["sync-ok"]


@pytest.mark.asyncio
async def test_close_during_authz_await_never_launches_tool(tmp_path):
    def enabled(env): env["app"].authorization.enabled = True
    provider=Provider()
    result, store, backend, core, node, env, tool, _, invocation=(
        await bind_during_scheduler(tmp_path, configure=enabled, provider=provider))
    guard=result["binding"].guard
    started=asyncio.Event()
    resume=asyncio.Event()
    provider.started=started
    provider.resume=resume
    executed=[]
    task=asyncio.create_task(guard.ainvoke(tool=tool, tool_call_id="slow",
        tool_input={"path":"a"}, handler=lambda: record_async(executed, "bad")))
    await asyncio.wait_for(started.wait(), 2)
    store.release(invocation.execution_id)
    resume.set()
    with pytest.raises(ToolBindingError, match="EXECUTION_BINDING_CLOSED"):
        await task
    assert executed == []


@pytest.mark.asyncio
async def test_untrusted_principal_and_missing_auth_provider(tmp_path):
    backend, node, env, tool = setup()
    core, _ = scheduler(tmp_path, node)
    backend.task_id=core.task_id
    backend.commit_checker=core.is_committed_invocation
    env["app"].authorization.enabled=True
    store=NodeExecutionBindingStore(
        preparation_backend=backend,
        principal_supplier=lambda _: SimpleNamespace(user_id=None, is_internal=False),
        provider_supplier=lambda _: None,
        auth_request_factory=AuthRequest,
        execution_live_checker=lambda invocation: True)
    fake=FakeExecutionBackend([FakeExecutionScenario()])
    seen=[]
    class B:
        async def prepare_node(self, node):
            return await backend.prepare_node(node)
        async def execute_prepared(self,p,i):
            with pytest.raises(ToolBindingError) as e:
                await store.bind(preparation=p,invocation=i)
            seen.append(e.value.code)
            raw=await fake.prepare_node(node)
            return await fake.execute_prepared(raw,i)
        async def cancel_node(self,x): await fake.cancel_node(x)
    await core.run_claim(await core.claim(node.id), B(), accept=accept)
    assert seen == ["HOST_PRINCIPAL_UNTRUSTED"] and store.active_count==0


@pytest.mark.asyncio
async def test_never_dispatches_provider_returned_extra_tool(tmp_path):
    provider=Provider()
    provider.filter_resources=lambda principal,resource,names: names+["tool_search"]
    def enabled(env): env["app"].authorization.enabled=True
    result,store,*_=await bind_during_scheduler(tmp_path,configure=enabled,provider=provider)
    assert result["error"]=="AUTHORIZATION_VISIBILITY_INVALID"
    assert store.active_count==0

@pytest.mark.asyncio
@pytest.mark.parametrize(("kind","code"),[
    ("plugins","CONFIGURED_PLUGINS_UNSUPPORTED"),
    ("mcp","MCP_EXTENSION_CONFIG_FORBIDDEN"),
    ("mcp_broken","MCP_EXTENSION_CONFIG_UNATTESTED"),
])
async def test_dynamic_configured_plugin_mcp_server_cannot_enter_model_view(tmp_path,kind,code):
    def cfg(env):
        if kind=="plugins":
            env["app"].plugins=[SimpleNamespace(enabled=True,use="bad:install")]
        if kind=="mcp":
            env["app"].extensions.mcp_servers={"remote":SimpleNamespace(enabled=True)}
        if kind=="mcp_broken":
            env["app"].extensions.mcp_servers=["remote"]
    result,store,*_=await bind_during_scheduler(tmp_path,configure=cfg)
    assert result["error"]==code
    assert store.active_count==0


@pytest.mark.asyncio
async def test_langchain_middleware_shaped_interceptor_checks_actual_tool_and_run_identity(tmp_path,monkeypatch):
    import sys
    from types import ModuleType
    from aswe.integrations.deerflow.tool_guard import make_langchain_tool_policy_middleware
    # This is an API-shaped test, not a real installed LangChain/DeerFlow run.
    for key in ("langchain", "langchain.agents", "langchain.agents.middleware"):
        mod=ModuleType(key)
        if key!="langchain.agents.middleware": mod.__path__=[]
        monkeypatch.setitem(sys.modules,key,mod)
    sys.modules["langchain.agents.middleware"].AgentMiddleware=type("AgentMiddleware",(),{})
    provider=Provider()
    def cfg(env): env["app"].authorization.enabled=True
    result,store,backend,core,node,env,tool,_,invocation=(
        await bind_during_scheduler(tmp_path,configure=cfg,provider=provider))
    binding=result["binding"]
    middleware=make_langchain_tool_policy_middleware(binding)
    executed=[]
    runtime=SimpleNamespace(context={
        "run_id":invocation.run_id,
        "execution_id":invocation.execution_id,
    })
    request=SimpleNamespace(
        tool_call={"id":"native-call-1","name":"read_file","args":{"path":"x"}},
        tool=tool,runtime=runtime,
    )
    assert await middleware.awrap_tool_call(request,lambda _: record_async(executed,"ok"))=="ok"
    assert executed==["ok"]
    forged=SimpleNamespace(
        tool_call={"id":"impostor-id","name":"read_file","args":{"path":"x"}},
        tool=SimpleNamespace(name="read_file"),runtime=runtime)
    with pytest.raises(ToolBindingError,match="UNBOUND_TOOL_OBJECT"):
        await middleware.awrap_tool_call(forged,lambda _: record_async(executed,"bad"))
    broken=SimpleNamespace(tool_call=request.tool_call,tool=tool,
        runtime=SimpleNamespace(context={"run_id":"another","execution_id":invocation.execution_id}))
    with pytest.raises(ToolBindingError,match="TOOL_CALL_RUNTIME_CONTEXT_MISMATCH"):
        await middleware.awrap_tool_call(broken,lambda _: record_async(executed,"bad"))
    renamed=SimpleNamespace(tool_call={"id":"renamed","name":"tool_search","args":{}},
        tool=tool,runtime=runtime)
    with pytest.raises(ToolBindingError,match="TOOL_CALL_NAME_OBJECT_MISMATCH"):
        middleware.wrap_tool_call(renamed,lambda _: executed.append("bad"))
    direct=SimpleNamespace(tool_call={"id":"sync-pass","name":"read_file","args":{"path":"x"}},
        tool=tool,runtime=runtime)
    assert middleware.wrap_tool_call(direct,lambda _: executed.append("sync")) is None
    assert executed==["ok","sync"]
    store.release(invocation.execution_id)
    with pytest.raises(ToolBindingError,match="EXECUTION_BINDING_CLOSED"):
        await middleware.awrap_tool_call(
            SimpleNamespace(tool_call={"id":"closed","name":"read_file","args":{}},
                            tool=tool,runtime=runtime),
            lambda _: record_async(executed,"bad"))

@pytest.mark.asyncio
async def test_real_scheduler_liveness_rejects_stale_binding_after_attempt(tmp_path):
    backend,node,env,tool=setup()
    core,_=scheduler(tmp_path,node)
    backend.task_id=core.task_id
    backend.commit_checker=core.is_committed_invocation
    store=NodeExecutionBindingStore(
        preparation_backend=backend,
        principal_supplier=lambda _:SimpleNamespace(user_id="verified",is_internal=False),
        provider_supplier=lambda _:None,
        auth_request_factory=AuthRequest,
        execution_live_checker=core.is_active_execution,
    )
    fake=FakeExecutionBackend([FakeExecutionScenario()])
    received=[]
    class B:
        async def prepare_node(self,n): return await backend.prepare_node(n)
        async def execute_prepared(self,p,i):
            assert core.is_active_execution(i)
            binding=await store.bind(preparation=p,invocation=i)
            received.append(binding)
            assert await binding.guard.ainvoke(
                tool=tool,tool_call_id="inside-commit",tool_input={"path":"x"},
                handler=lambda:record_async([], "inside"))=="inside"
            raw=await fake.prepare_node(node)
            return await fake.execute_prepared(raw,i)
        async def cancel_node(self,x): await fake.cancel_node(x)
    inv=await core.run_claim(await core.claim(node.id), B(),accept=accept)
    assert inv is not None and not core.is_active_execution(inv)
    with pytest.raises(ToolBindingError,match="EXECUTION_BINDING_NOT_ACTIVE"):
        store.lookup(inv.execution_id)
    with pytest.raises(ToolBindingError,match="EXECUTION_BINDING_NOT_ACTIVE"):
        await received[0].guard.ainvoke(
            tool=tool,tool_call_id="after-terminal",tool_input={"path":"x"},
            handler=lambda:record_async([], "fail"))
    store.release(inv.execution_id)


@pytest.mark.asyncio
async def test_async_authorization_liveness_rechecked_after_await(tmp_path):
    def enabled(env): env["app"].authorization.enabled=True
    provider=Provider()
    state={"live":True}
    result,store,backend,core,node,env,tool,_,inv=(
        await bind_during_scheduler(tmp_path,configure=enabled,provider=provider,
                                    liveness_checker=lambda _:state["live"]))
    gate=result["binding"].guard
    provider.started=asyncio.Event()
    provider.resume=asyncio.Event()
    called=[]
    pending=asyncio.create_task(gate.ainvoke(tool=tool,tool_call_id="race",
        tool_input={"path":"x"},handler=lambda:record_async(called,"bad")))
    await asyncio.wait_for(provider.started.wait(),2)
    state["live"]=False
    provider.resume.set()
    with pytest.raises(ToolBindingError,match="EXECUTION_BINDING_NOT_ACTIVE"):
        await pending
    assert not called

@pytest.mark.asyncio
async def test_inherited_native_skills_are_narrowed_in_pinned_snapshot(tmp_path):
    backend,node,env,tool=setup()
    core,_=scheduler(tmp_path,node)
    backend.task_id=core.task_id
    backend.commit_checker=core.is_committed_invocation
    def inherit(name,**kwargs):
        from tests.unit.test_deerflow_preparation_step5c import Sub
        return Sub(name=name,skills=None)
    backend.subagent_resolver=inherit
    prepared=await backend.prepare_node(node)
    pinned=backend._pending[prepared.preparation_id][1]
    assert pinned.subagent_config.skills == []
    assert pinned.app_config.authorization.enabled is False
    backend.release_preparation(prepared)

@pytest.mark.asyncio
async def test_same_tool_call_id_concurrent_sync_threads_runs_at_most_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    result,store,backend,core,node,env,tool,provider,inv=(
        await bind_during_scheduler(tmp_path))
    gate=result["binding"].guard
    side_effects=[]
    def call():
        try:
            gate.invoke(tool=tool,tool_call_id="same-call-id",
                tool_input={"path":"x"},handler=lambda:side_effects.append("ran"))
            return "ok"
        except ToolBindingError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:call(),range(2)))
    assert sorted(responses)==["TOOL_CALL_REPLAY","ok"]
    assert side_effects==["ran"]


@pytest.mark.asyncio
async def test_guard_denies_mutating_tool_even_if_host_view_injected(tmp_path):
    from aswe.integrations.deerflow.tool_guard import BoundToolView,ToolCallGuard
    from aswe.integrations.deerflow.preparation import _tool_seal
    result,store,backend,core,node,env,tool,provider,inv=(
        await bind_during_scheduler(tmp_path))
    pinned=result["binding"].resources
    # A hostile adapter that tries to add a mutating tool to a view cannot
    # authorize its execution; this is independent of normal static filtering.
    bash=SimpleNamespace(name="bash",func=lambda:None,coroutine=None,args_schema=None)
    view=BoundToolView(names=("bash",),objects=(bash,),object_seals=(_tool_seal(bash),))
    policy=SimpleNamespace(fingerprint=pinned.policy_fingerprint,
        allowed_business_tools=("bash",),denied_tools=(),
        prohibited_actions=(),allowed_paths=None,forbidden_paths=())
    gate=ToolCallGuard(invocation=inv,resources=pinned,view=view,
        principal=SimpleNamespace(user_id="host",is_internal=False),
        provider=None,request_factory=AuthRequest,auth_enabled=False,
        policy=policy,execution_live_checker=lambda _:True)
    ran=[]
    with pytest.raises(ToolBindingError,match="MUTATING_TOOL_EXECUTION_NOT_ENABLED"):
        await gate.ainvoke(tool=bash,tool_call_id="unsafe",tool_input={"command":"rm -rf /"},
            handler=lambda:record_async(ran,"bad"))
    assert not ran

@pytest.mark.asyncio
async def test_principal_and_authentication_state_tampering_rejected_at_tool_call(tmp_path):
    def enabled(env):env["app"].authorization.enabled=True
    provider=Provider()
    result,store,backend,core,node,env,tool,_,inv=(
        await bind_during_scheduler(tmp_path,configure=enabled,provider=provider))
    guard=result["binding"].guard
    forbidden=[]
    guard.principal.user_id="other-user"
    with pytest.raises(ToolBindingError,match="RUN_AUTHORITY_MUTATED"):
        await guard.ainvoke(tool=tool,tool_call_id="identity-tampered",
            tool_input={},handler=lambda:record_async(forbidden,"bad"))
    guard.principal.user_id="host-uid"
    guard.auth_enabled=False
    with pytest.raises(ToolBindingError,match="RUN_AUTHORITY_MUTATED"):
        guard.invoke(tool=tool,tool_call_id="auth-disabled",
            tool_input={},handler=lambda:forbidden.append("bad"))
    guard.auth_enabled=True
    guard.provider=Provider()
    with pytest.raises(ToolBindingError,match="RUN_AUTHORITY_MUTATED"):
        guard.invoke(tool=tool,tool_call_id="provider-swapped",
            tool_input={},handler=lambda:forbidden.append("bad"))
    assert forbidden==[]
