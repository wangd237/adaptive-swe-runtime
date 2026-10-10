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
    invocation = SimpleNamespace(task_id="physical-task", node_id="node-poc",
                                 attempt=1, execution_id=execution_id, run_id="pinned-run")
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
    graph = await executor._create_agent(tools, deferred_setup=deferred, extensions=binding.resources.extensions)
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
    graph2 = await executor2._create_agent(tools2, deferred_setup=None, extensions=denied.resources.extensions)
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
    graph = await executor._create_agent(tools, deferred_setup=None, extensions=binding.resources.extensions)
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
    from aswe.integrations.deerflow.native_lease_supervisor import native_lease_task_id
    assert result.task_id == native_lease_task_id(binding.invocation)
    assert getattr(result.status, "value", "") == "completed", (
        "Native lifecycle status must be completed, not merely graph-compiled"
    )
    assert result.result == "offline-native-complete"
    assert binding.guard._used_call_ids == {"native-pinned-tool-call-1"}


@pytest.mark.asyncio
async def test_real_installed_native_graph_persists_guard_receipt_and_unknown_quiescence(tmp_path):
    """Real frozen vendor, real native graph/tool, *no fabricated sandbox proof*."""
    import subprocess
    from dataclasses import replace
    from aswe.repository import bootstrap_repository
    from aswe.evidence import LocalEvidenceStore
    from aswe.integrations.deerflow.execution_evidence import ExecutionEvidenceCollector
    from tests.unit.test_deerflow_execution_evidence_step5f import invocation
    from aswe.workspace.delta import MutationEvidence

    source=tmp_path/"origin"
    source.mkdir()
    def git(*args):
        subprocess.run(["git","-C",str(source),*args],check=True,
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    git("init","-b","main")
    git("config","user.name","Native Integration")
    git("config","user.email","native@example.invalid")
    (source/"README.md").write_text("fixture")
    git("add","-A")
    git("commit","-m","baseline")
    repo=bootstrap_repository(source,tmp_path/"workspace",requested_ref="main")
    actual_invocation=invocation(repo)
    evidence=ExecutionEvidenceCollector(
        repository=repo,
        evidence_store=LocalEvidenceStore(tmp_path/"protected-evidence",
                                          workspace_root=repo.repository_root),
        supervisor=None,
    )
    binding=physical_binding(execution_id=actual_invocation.execution_id)
    binding.guard.invocation=actual_invocation
    binding=replace(binding,invocation=actual_invocation)
    baseline=await evidence.begin(actual_invocation)
    assembler,_=native_assembler_with_offline_model()
    native=assembler.build(binding)
    result=await native._aexecute("Read the fake file")
    assert result.status.value=="completed"
    binding.guard.close()
    report=await evidence.finish(baseline,guard=binding.guard,
                                  native_task_done=True)
    assert report.quiescent is False
    assert report.mutation_evidence is MutationEvidence.UNKNOWN
    workspace=evidence.evidence_store.get(report.evidence_ref)
    ledger=evidence.evidence_store.get(report.tool_receipt_ref)
    assert workspace["quiescence_proven"] is False
    assert workspace["execution_id"] == actual_invocation.execution_id
    assert len(ledger["receipts"])==1
    assert ledger["receipts"][0]["status"]=="completed"
    assert ledger["receipts"][0]["tool_name"]=="read_file"
    assert ledger["receipts"][0]["tool_call_id"]=="native-pinned-tool-call-1"
    assert ledger["receipts"][0]["arguments_digest"]
    assert "README.md" not in str(ledger)


@pytest.mark.asyncio
async def test_vendor_real_lease_manager_reports_owner_until_async_release(tmp_path):
    """Physical Python 3.12 vendor lease manager, NOT just a simulated map.

    A lease manager's owner-release signal alone cannot certify subprocesses:
    process_tree_probe=None makes the native quiescence result NO-GO.
    """
    import subprocess
    from deerflow.sandbox.lease import get_sandbox_lease_manager
    from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider
    from aswe.integrations.deerflow.native_lease_supervisor import (
        NativeSandboxQuiescenceSupervisor, native_lease_owner)
    from aswe.repository import bootstrap_repository
    from tests.unit.test_deerflow_execution_evidence_step5f import invocation

    root=tmp_path/"lease-source"
    root.mkdir()
    def git(*args):
        subprocess.run(["git","-C",str(root),*args],check=True,
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    git("init","-b","main")
    git("config","user.name","Lease Integration")
    git("config","user.email","lease@example.invalid")
    (root/"README.md").write_text("fixture")
    git("add","-A")
    git("commit","-m","base")
    repo=bootstrap_repository(root,tmp_path/"lease-worktree",requested_ref="main")
    inv=invocation(repo)
    provider=LocalSandboxProvider()
    manager=get_sandbox_lease_manager(provider)
    finished={"value":False}
    observer=NativeSandboxQuiescenceSupervisor(
        initialized_provider=lambda:provider,
        manager_lookup=get_sandbox_lease_manager,
        process_tree_probe=None,
    )
    owner=observer.register_execution(inv,native_finished=lambda:finished["value"])
    assert owner == native_lease_owner(inv)
    sandbox_id=await manager.acquire_async(
        owner,thread_id="physical-5fb2",user_id="native-test")
    try:
        assert manager.binding_for(owner)==sandbox_id
        finished["value"]=True
        busy=await observer.inspect(task_id=inv.task_id,execution_id=inv.execution_id)
        assert not busy.complete
        assert not busy.sandbox_lease_released
    finally:
        await manager.release_async(owner)
    assert manager.binding_for(owner) is None
    observed=await observer.inspect(task_id=inv.task_id,execution_id=inv.execution_id)
    # The manager removed the owner, but does NOT give a signed completion
    # receipt for the underlying provider.release(). Never overclaim.
    assert observed.sandbox_lease_released is False
    assert observed.process_tree_drained is False
    assert observed.complete is False
    observer.release_execution(inv.execution_id)


@pytest.mark.asyncio
async def test_real_langgraph_swe_coding_loop_read_edit_test_fail_repair_pass(tmp_path):
    """5F-C: frozen installed DeerFlow + true compiled LangGraph ToolNode.

    The model and isolated ShellOutcome backend are deterministic fixtures.
    This proves native tool CALL integration and iterative repair, NOT real
    Docker isolation, deployed credentials, or Scheduler TaskResult acceptance.
    """
    import subprocess
    from aswe.repository import bootstrap_repository
    from aswe.core.fingerprint import fingerprint
    from aswe.integrations.deerflow.controlled_swe import ControlledSWEWorkspace, ShellOutcome
    from aswe.integrations.deerflow.tool_guard import BoundToolView, ToolCallGuard, NodeExecutionBinding
    from tests.unit.test_deerflow_controlled_swe_step5fc import policy
    from tests.unit.test_deerflow_execution_evidence_step5f import invocation as native_invocation

    origin=tmp_path/"coding-source"
    origin.mkdir()
    def git(*argv):
        subprocess.run(["git","-C",str(origin),*argv],check=True,
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    git("init","-b","main")
    git("config","user.name","SWE Offline")
    git("config","user.email","swe@example.invalid")
    (origin/"calc.py").write_text("def answer():\n    return 1\n")
    (origin/"README.md").write_text("Fix answer to 42")
    git("add","-A")
    git("commit","-m","baseline")
    repository=bootstrap_repository(origin,tmp_path/"coding-workspace",requested_ref="main")
    root=__import__("pathlib").Path(repository.repository_root)
    compiled_policy=policy()
    inv=native_invocation(repository).model_copy(update={
        "node_id":compiled_policy.node_id, "execution_id":"swe-loop-001",
        "task_id":"physical-coding-loop","run_id":"swe-loop-run"
    })

    class FakeIsolatedShell:
        isolation_kind="docker-no-network"
        workspace_root=root
        def __init__(self):self.commands=[]
        async def run(self,command,*,timeout,max_output):
            self.commands.append(command)
            assert command=="python -m unittest -q"
            source=(root/"calc.py").read_text()
            success="return 42" in source
            return ShellOutcome(exit_code=0 if success else 1,
                                output="OK" if success else "FAIL: expected 42")
    sandbox=FakeIsolatedShell()
    runtime=ControlledSWEWorkspace(
        invocation=inv,policy=compiled_policy,root=root,command_backend=sandbox
    )
    tools=runtime.make_tools(("read_file","str_replace","bash"))
    # A model-initiated write is allowed only through this exact runtime and
    # ToolCallGuard's committed, sealed tool-surface and identity checks.
    resources=SimpleNamespace(
        model_name="offline-pinned",
        app_config=AppConfig.model_validate({
            "sandbox":{"use":"deerflow.sandbox.local:LocalSandboxProvider",
                       "allow_host_bash":False}}),
        subagent_config=SubagentConfig(
            name="general-purpose",description="Offline repair",
            model="inherit",tools=[t.name for t in tools],
            disallowed_tools=[],skills=[],system_prompt="Fix calc.py",
            max_turns=25,timeout_seconds=20,
        ),
        extensions=get_loaded_extensions(),node_id=inv.node_id,
        effective_max_turns=50,effective_timeout_seconds=20,
        policy_fingerprint=compiled_policy.fingerprint,
        assert_intact=lambda:None,
    )
    principal=SimpleNamespace(user_id="trusted-swe-user",role="worker",
        oauth_provider=None,oauth_id=None,channel_user_id=None,
        is_internal=False,attributes={})
    view=BoundToolView(
        names=tuple(t.name for t in tools),objects=tools,
        object_seals=tuple(_tool_seal(t) for t in tools),
    )
    guard=ToolCallGuard(
        invocation=inv,resources=resources,view=view,principal=principal,
        provider=None,request_factory=None,auth_enabled=False,
        policy=compiled_policy,execution_live_checker=lambda _:True,
        swe_runtime=runtime,
    )
    binding=NodeExecutionBinding(
        execution_id=inv.execution_id,preparation_id="offline-swe-test",
        invocation=inv,resources=resources,tool_view=view,guard=guard,
        swe_runtime=runtime,
    )
    script=[
        ("read_file",{"path":"calc.py"}),
        ("str_replace",{"path":"calc.py","old_str":"return 1","new_str":"return 2"}),
        ("bash",{"command":"python -m unittest -q"}),
        ("read_file",{"path":"calc.py"}),
        ("str_replace",{"path":"calc.py","old_str":"return 2","new_str":"return 42"}),
        ("bash",{"command":"python -m unittest -q"}),
    ]
    class ScriptedRepairModel(BaseChatModel):
        turn:int=0
        @property
        def _llm_type(self):return "aswe-scripted-swe-repair"
        def bind_tools(self,tools,**kwargs):return self
        def _generate(self,messages,stop=None,run_manager=None,**kwargs):
            self.turn+=1
            if self.turn<=len(script):
                name, args=script[self.turn-1]
                response=AIMessage(content="",tool_calls=[{
                    "name":name,"args":args,"id":f"swe-{self.turn}"}])
            else:
                response=AIMessage(content="Fixed calc.answer with tests passing")
            return ChatResult(generations=[ChatGeneration(message=response)])

    assembler=NativeSubagentAssembler.from_deerflow()
    assembler=NativeSubagentAssembler(replace(
        assembler.seams,create_chat_model=lambda **kw: ScriptedRepairModel()
    ))
    native=assembler.build(binding)
    result=await native._aexecute("Fix answer and test until successful")
    assert result.status.value=="completed",result.status
    assert "return 42" in (root/"calc.py").read_text()
    assert sandbox.commands==["python -m unittest -q"]*2
    summary=runtime.development_summary(native_terminal_status="completed")
    assert summary.file_tool_changed_paths==("calc.py",)
    assert summary.dynamic_command_count==2
    assert summary.last_dynamic_command_exit_code==0
    assert summary.verification_level=="agent_observed_only"
    assert summary.acceptance_status=="not_evaluated"
    assert guard._used_call_ids=={f"swe-{i}" for i in range(1,7)}
    assert [x["status"] for x in guard.receipt_snapshot()]==["completed"]*6
    assert (root/"README.md").read_text()=="Fix answer to 42"


@pytest.mark.asyncio
async def test_step6_real_native_guard_writes_digest_only_tool_trace(tmp_path):
    from aswe.trace.minimal_events import LocalRuntimeEventSink
    from aswe.integrations.deerflow.preparation import _digest
    from aswe.integrations.deerflow.tool_guard import ToolCallGuard
    sink=LocalRuntimeEventSink(tmp_path,"physical-task")
    binding=physical_binding(execution_id="trace-real-native")
    binding.guard.trace_sink=sink
    assembler,_=native_assembler_with_offline_model()
    executor=assembler.build(binding)
    result=await executor._aexecute("Read fixture")
    assert result.status.value=="completed"
    events=sink.read_all()
    assert [e.event_type for e in events]==[
        "model.turn.finished","tool.call.finished","model.turn.finished"]
    assert [e.payload["round"] for e in events
            if e.event_type=="model.turn.finished"]==[1,2]
    event=events[1]
    assert event.event_type=="tool.call.finished"
    assert event.node_id=="node-poc"
    assert event.payload["tool_name"]=="read_file"
    assert event.payload["status"]=="completed"
    assert event.payload["arguments_digest"]
    assert "README.md" not in sink.path.read_text()
