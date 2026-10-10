"""Developer CLI real SWE task submission; no pytest fixture or synthetic model.

A single compiled writer node is the first supported CLI execution topology.
The user task is the native agent prompt; policy, tool and verification
authority are separately host-compiled.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from dataclasses import replace
from typing import Callable, Any
from types import SimpleNamespace

from aswe.core.ids import new_safe_id
from aswe.core.contracts import WorkspaceRevision, WorkKind
from aswe.planning.compiler import ConstraintCompiler, RuntimePolicyConfig, RuntimePolicyRule, project_execution_authority
from aswe.planning.contracts import make_task_request
from aswe.planning.planner import WorkItemProposal, WorkPlanProposal
from aswe.planning.validator import SemanticPlanValidator
from aswe.planning.acceptance import AcceptanceCompiler
from aswe.planning.dag import materialize_task_dag
from aswe.planning.descriptor import compile_plan_descriptor
from aswe.providers.contracts import provider, CapabilityBinding
from aswe.providers.resolver import resolve_workplan
from aswe.providers.policy import OperatorSurface, compile_policies
from aswe.repository import bootstrap_repository, capture_repository_state
from aswe.workspace import WorkspaceLifecycle, WorkspaceSession, WorkspaceSessionStatus, WorkspaceAccessManager
from aswe.runtime.scheduler import SchedulerCore
from aswe.runtime.canonical_verifier import CanonicalVerifier, make_command_policy
from aswe.evidence import LocalEvidenceStore
from aswe.trace.minimal_events import LocalRuntimeEventSink


class RunConfigurationError(ValueError):
    pass


async def execute_swe_task(*, repository: Path, task: str, runtime_dir: Path,
                           check_argv: tuple[str, ...], image: str,
                           ref: str = "HEAD",
                           model_factory: Callable[..., Any] | None = None):
    """Clone an immutable base, then execute the real frozen DeerFlow graph.

    Requires installed pinned vendor, Docker and host-supplied OPENAI_API_KEY.
    Does not permit secret-bearing workspace files to become provider env.
    """
    if not task.strip() or not check_argv or len(task) > 12000:
        raise RunConfigurationError("TASK_OR_CHECK_INVALID")
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("ASWE_MODEL"):
        raise RunConfigurationError("ASWE_MODEL_OR_OPENAI_API_KEY_MISSING")
    from deerflow.config.app_config import AppConfig
    from deerflow.subagents.config import SubagentConfig
    from deerflow.tools.tools import get_available_tools
    from deerflow.tools import tools as vendor_tools
    from deerflow.extensions import get_loaded_extensions
    from deerflow.reflection import resolve_variable
    from langchain.tools import BaseTool
    from aswe.capabilities.effects import DEERFLOW_USE_BY_CONTRACT
    from aswe.integrations.deerflow.inventory import (
        assert_pinned_deerflow_source, inventory_from_assembled_tools)
    from aswe.integrations.deerflow.docker_bash_capability import (
        DockerBashCapability,compose_docker_bash_inventory)
    from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend,ControlledSWEWorkspace
    from aswe.integrations.deerflow.preparation import DeerFlowPreparationBackend
    from aswe.integrations.deerflow.tool_guard import NodeExecutionBindingStore
    from aswe.integrations.deerflow.native_execution import (
        NativeSubagentAssembler, NativeDeerFlowExecutionBackend)
    from aswe.integrations.deerflow.mvp_task import MVPTaskRunner

    assert_pinned_deerflow_source(vendor_tools.__file__)
    task_id = new_safe_id("task")
    home = runtime_dir.expanduser().resolve()
    original = repository.expanduser().resolve(strict=True)
    if home == original or home.is_relative_to(original):
        raise RunConfigurationError("RUNTIME_DIR_MUST_BE_OUTSIDE_SOURCE_REPOSITORY")
    root = home / "tasks" / task_id / "workspace"
    repo = bootstrap_repository(original, root, requested_ref=ref)
    root = Path(repo.repository_root)
    runtime_root = home / "tasks" / task_id
    model = os.environ["ASWE_MODEL"]
    url = os.environ.get("ASWE_BASE_URL")
    config = AppConfig.model_validate({
        "sandbox":{"use":"deerflow.sandbox.local:LocalSandboxProvider","allow_host_bash":False},
        "tools":[{"name":name,"group":"swe","use":DEERFLOW_USE_BY_CONTRACT[name]}
                 for name in ("read_file","write_file","str_replace","bash")],
    })
    from deerflow.config.model_config import ModelConfig
    params=dict(name="aswe-cli-model",use="langchain_openai:ChatOpenAI",
                model=model,timeout=90,max_retries=0)
    if url:
        params["base_url"]=url
    payload=config.model_dump(mode="python")
    payload["models"]=[ModelConfig(**params).model_dump(mode="python")]
    config=AppConfig.model_validate(payload)
    docker=DockerCommandBackend(workspace_root=root,image=image)
    grant=DockerBashCapability.from_backend(docker)

    def observe():
        return tuple(get_available_tools(
            app_config=config,extensions=get_loaded_extensions(),
            include_mcp=False,subagent_enabled=False,
            include_upload_tool=False,model_name="aswe-cli-model"))
    native=inventory_from_assembled_tools(
        app_config=config,assembled_tools=observe(),
        resolve_implementation=lambda use:resolve_variable(use,BaseTool),
        active_agent_types=("general-purpose",),
        sandbox=SimpleNamespace(persistent_shell_sessions=False))
    planning=compose_docker_bash_inventory(native=native,backend=docker,grant=grant)
    contract,authority=ConstraintCompiler(RuntimePolicyConfig(
        policy_id="aswe-cli",rules=(RuntimePolicyRule(
            key="deliverables.required",
            value={"effect":"repository_mutation","description":"implement requested coding task"}
        ),)
    )).compile(request=make_task_request(request_id=task_id,raw_text=task),
               repository_base_sha=repo.resolved_base_sha)
    mutation_grant=next(c.id for c in contract.constraints if c.key=="deliverables.required")
    proposal=WorkPlanProposal(items=(WorkItemProposal(
        id="writer",objective=task,work_kind=WorkKind.IMPLEMENTATION,
        capability_hints=("code_modification",),coverage_claims=(mutation_grant,),
    ),),rationale="Single-node developer SWE coding task")
    plan=SemanticPlanValidator().validate(proposal=proposal,contract=contract,authority=authority)
    providers=(provider("coder",(CapabilityBinding(
        capability_id="code_modification",required_tools=("read_file","str_replace"),
        optional_tools=("bash",)),),role="general-purpose"),)
    resolved=resolve_workplan(plan=plan,contract=contract,authority=authority,
        inventory=planning,providers=providers,
        selected_optional_by_node={"writer":("bash",)})
    operator=OperatorSurface(provider_id="coder",
        allowed_tools=("read_file","str_replace","bash"),
        model_name="aswe-cli-model",max_turns=40,timeout_seconds=240)
    acceptance=AcceptanceCompiler().compile(contract=contract)
    policies=compile_policies(contract=contract,plan=plan,resolved=resolved,
        inventory=planning,providers=providers,operators=(operator,),acceptance=acceptance)
    descriptor=compile_plan_descriptor(contract=contract,plan=plan,acceptance=acceptance,
        resolved=resolved,inventory=planning,policies=policies)
    dag=materialize_task_dag(plan=plan,resolved=resolved,inventory=planning)
    snapshot=capture_repository_state(repo)
    revision=WorkspaceRevision(generation=0,base_sha=snapshot.base_sha,
        head_sha=snapshot.head_sha,head_matches_baseline=snapshot.head_matches_baseline,
        repository_state_fingerprint=snapshot.fingerprint,dirty=snapshot.dirty_vs_base)
    life=WorkspaceLifecycle(WorkspaceSession(
        task_id=task_id,thread_id=new_safe_id("thread"),user_id="local-operator",
        workspace_root=str(root),status=WorkspaceSessionStatus.BOOTSTRAPPING))
    life.mark_ready(repo)
    life.transition(WorkspaceSessionStatus.ACTIVE)
    core=SchedulerCore(task_id=task_id,dag=dag,workspace=WorkspaceAccessManager(life),
        initial_revision=revision,evidence_checker=lambda _handoff:False)
    policy=policies[0]
    def subagent(name,*,app_config):
        return SubagentConfig(name=name,description="SWE developer CLI",
            model="inherit",tools=["read_file","str_replace","bash"],
            disallowed_tools=[],skills=[],
            system_prompt=("You are a software engineering agent. Inspect code and tests "
                "before editing. Use read_file then str_replace. Run tests with the "
                "isolated bash tool and repair failures. Do not change .git or tests "
                "unless explicitly requested. The host will verify independently."),
            max_turns=40,timeout_seconds=240)
    prep=DeerFlowPreparationBackend(
        task_id=task_id,descriptor=descriptor,policy=policy,
        planning_inventory=planning,config_supplier=lambda:config,
        operator_supplier=lambda:operator,
        sandbox_supplier=lambda:SimpleNamespace(persistent_shell_sessions=False),
        extensions_supplier=get_loaded_extensions,subagent_resolver=subagent,
        model_resolver=lambda _sub,parent_model,**_kw:parent_model,
        tool_assembler=get_available_tools,
        implementation_resolver=lambda use:resolve_variable(use,BaseTool),
        source_verifier=lambda:assert_pinned_deerflow_source(vendor_tools.__file__),
        commit_checker=core.is_committed_invocation,
        docker_bash_backend=docker,docker_bash_grant=grant)
    principal=SimpleNamespace(user_id="local-operator",role="worker",
        oauth_provider=None,oauth_id=None,channel_user_id=None,
        is_internal=False,attributes={})
    trace=LocalRuntimeEventSink(home,task_id,workspace_root=root)
    trace.emit("plan.compiled",node_id="writer",payload={
        "descriptor_fingerprint":descriptor.fingerprint,
        "inventory_fingerprint":planning.fingerprint,"nodes":["writer"]})
    binding=NodeExecutionBindingStore(
        preparation_backend=prep,principal_supplier=lambda _:principal,
        provider_supplier=lambda _:None,auth_request_factory=lambda **kwargs:kwargs,
        execution_live_checker=core.is_active_execution,
        swe_workspace_factory=lambda invocation,resources,p:ControlledSWEWorkspace(
            invocation=invocation,policy=p,root=root,command_backend=docker),
        expected_swe_workspace_root=root,trace_sink=trace)
    assembler=NativeSubagentAssembler.from_deerflow()
    # Internal test seam only: CLI never exposes model_factory. Normal runs
    # always call the frozen DeerFlow native model factory.
    if model_factory is not None:
        assembler=NativeSubagentAssembler(replace(
            assembler.seams,create_chat_model=model_factory))
    backend=NativeDeerFlowExecutionBackend(
        binding_store=binding,assembler=assembler,
        task_renderer=lambda _node:task,enable_native_execution=True,
        evidence_collector=None)
    evidence=LocalEvidenceStore(home/"evidence",workspace_root=root)
    verifier=CanonicalVerifier(task_id=task_id,runtime_data_dir=home,
        evidence_store=evidence,binding=repo)
    check=make_command_policy("cli-regression",check_argv,timeout_seconds=90)
    runner=MVPTaskRunner(scheduler=core,backend=backend,repository=repo,
        verifier=verifier,policy=check,trace_sink=trace,
        isolated_canonical_container=docker)
    report=await asyncio.wait_for(runner.run_node("writer"),timeout=360)
    report_path=runtime_root/"report.json"
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(report.to_json()+"\n",encoding="utf-8")
    return report_path, report, trace.path
