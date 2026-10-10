"""P0-01 physical chain: source-pinned DeerFlow inventory -> real 5C/5D -> Docker.

Only the offline LLM is scripted. No PhysicalPreparedToolSource or fake
source tool objects. Native host Bash stays filtered by DeerFlow.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from deerflow.config.app_config import AppConfig
from deerflow.subagents.config import SubagentConfig
from deerflow.tools.tools import get_available_tools
from deerflow.reflection import resolve_variable
from deerflow.extensions import get_loaded_extensions
from langchain.tools import BaseTool

from aswe.capabilities.effects import DEERFLOW_USE_BY_CONTRACT
from aswe.integrations.deerflow.inventory import (
    inventory_from_assembled_tools, assert_pinned_deerflow_source,
)
from aswe.integrations.deerflow.docker_bash_capability import (
    DockerBashCapability, compose_docker_bash_inventory,
    RuntimeDockerBashSource,
)
from aswe.integrations.deerflow.controlled_swe import (
    DockerCommandBackend, ControlledSWEWorkspace,
)
from aswe.integrations.deerflow.preparation import DeerFlowPreparationBackend
from aswe.integrations.deerflow.tool_guard import NodeExecutionBindingStore
from aswe.integrations.deerflow.native_execution import (
    NativeSubagentAssembler, NativeDeerFlowExecutionBackend,
)
from aswe.integrations.deerflow.mvp_task import MVPTaskRunner
from aswe.planning.compiler import project_execution_authority
from aswe.planning.acceptance import AcceptanceCompiler
from aswe.planning.descriptor import compile_plan_descriptor
from aswe.planning.dag import materialize_task_dag
from aswe.providers.contracts import provider, CapabilityBinding
from aswe.providers.resolver import resolve_workplan
from aswe.providers.policy import OperatorSurface, compile_policies
from aswe.repository import capture_repository_state
from aswe.runtime.canonical_verifier import CanonicalVerifier
from tests.unit.test_step4_physical_p3 import build
from tests.unit.test_scheduler_foundation import scheduler
from tests.unit.test_node_workspace_delta import rev
from tests.unit.test_deerflow_mvp_task_step5fcb import prepared_mvp
from tests.integration.test_deerflow_mvp_e2e_step5fcb import RealGraphScriptedRepairModel
from tests.integration.test_deerflow_docker_swe_step5fc import local_image_digest
from aswe.core.contracts.task import WorkKind


@pytest.mark.asyncio
async def test_real_5c_5d_frozen_deerflow_docker_canonical_e2e(prepared_mvp):
    repo, old_core, store, old_verifier, canonical = prepared_mvp
    root = Path(repo.repository_root)
    docker = DockerCommandBackend(workspace_root=root, image=local_image_digest())
    grant = DockerBashCapability.from_backend(docker)
    cfg = AppConfig.model_validate({
        "sandbox": {"use":"deerflow.sandbox.local:LocalSandboxProvider",
                    "allow_host_bash":False},
        "tools": [{"name":n,"group":"swe",
                   "use":DEERFLOW_USE_BY_CONTRACT[n]}
                  for n in ("read_file","str_replace","bash")],
        "models": [{"name":"offline-pinned",
                    "use":"langchain_openai:ChatOpenAI","model":"offline-pinned"}],
    })
    from deerflow.tools import tools as native_tools_module
    assert_pinned_deerflow_source(native_tools_module.__file__)
    def observe():
        return tuple(get_available_tools(
            app_config=cfg, extensions=get_loaded_extensions(),
            include_mcp=False,subagent_enabled=False,
            include_upload_tool=False,model_name="offline-pinned"))
    raw = observe()
    assert "bash" not in {t.name for t in raw}
    def sandbox():
        return SimpleNamespace(persistent_shell_sessions=False)
    def native_inventory():
        return inventory_from_assembled_tools(
            app_config=cfg, assembled_tools=observe(),
            resolve_implementation=lambda use: resolve_variable(use, BaseTool),
            active_agent_types=("general-purpose",),sandbox=sandbox())
    planning = compose_docker_bash_inventory(
        native=native_inventory(), backend=docker, grant=grant)
    assert planning.candidate_tools["bash"].source=="aswe-runtime-docker"

    contract, plan, _, _ = build(
        ("writer", WorkKind.IMPLEMENTATION,"code_modification"))
    providers=(provider("coder",(CapabilityBinding(
        capability_id="code_modification",
        required_tools=("read_file","str_replace"),
        optional_tools=("bash",),
    ),),role="general-purpose"),)
    resolved=resolve_workplan(
        plan=plan, contract=contract,
        authority=project_execution_authority(contract),
        inventory=planning,providers=providers,
        selected_optional_by_node={"writer":("bash",)})
    operator=OperatorSurface(
        provider_id="coder",allowed_tools=("read_file","str_replace","bash"),
        model_name="offline-pinned",max_turns=25,timeout_seconds=50)
    acceptance=AcceptanceCompiler().compile(contract=contract)
    policies=compile_policies(
        contract=contract,plan=plan,resolved=resolved,
        inventory=planning,providers=providers,
        operators=(operator,),acceptance=acceptance)
    descriptor=compile_plan_descriptor(
        contract=contract,plan=plan,resolved=resolved,
        inventory=planning,policies=policies,acceptance=acceptance)
    dag=materialize_task_dag(plan=plan,resolved=resolved,inventory=planning)
    core,_=scheduler(root,*dag.nodes)
    core.revision=rev(capture_repository_state(repo))
    assert descriptor.task_dag == dag
    policy=policies[0]
    assert policy.workspace_access.value=="write"

    def subagent(name,*,app_config):
        return SubagentConfig(name=name,description="pinned SWE native",
            model="inherit",tools=["read_file","str_replace","bash"],
            disallowed_tools=[],skills=[],system_prompt="Fix calc.answer",
            max_turns=25,timeout_seconds=50)
    preparer=DeerFlowPreparationBackend(
        task_id=core.task_id,descriptor=descriptor,policy=policy,
        planning_inventory=planning,config_supplier=lambda:cfg,
        operator_supplier=lambda:operator,sandbox_supplier=sandbox,
        extensions_supplier=get_loaded_extensions,
        subagent_resolver=subagent,
        model_resolver=lambda sub,parent_model,**kw: parent_model,
        tool_assembler=get_available_tools,
        implementation_resolver=lambda use:resolve_variable(use,BaseTool),
        source_verifier=lambda:assert_pinned_deerflow_source(native_tools_module.__file__),
        commit_checker=core.is_committed_invocation,
        docker_bash_backend=docker,docker_bash_grant=grant,
    )
    principal=SimpleNamespace(
        user_id="verified-local-operator",role="worker",
        oauth_provider=None,oauth_id=None,channel_user_id=None,
        is_internal=False,attributes={})
    def runtime(invocation,resources,policy):
        return ControlledSWEWorkspace(
            invocation=invocation,policy=policy,root=root,command_backend=docker)
    binding=NodeExecutionBindingStore(
        preparation_backend=preparer,principal_supplier=lambda _:principal,
        provider_supplier=lambda _:None,
        auth_request_factory=lambda **kwargs:kwargs,
        execution_live_checker=core.is_active_execution,
        swe_workspace_factory=runtime,expected_swe_workspace_root=root)
    native=NativeSubagentAssembler.from_deerflow()
    native=NativeSubagentAssembler(replace(
        native.seams,create_chat_model=lambda **_:RealGraphScriptedRepairModel()))
    backend=NativeDeerFlowExecutionBackend(
        binding_store=binding,assembler=native,
        task_renderer=lambda _: "Fix calc.answer to 42 and test",
        enable_native_execution=True,evidence_collector=None)
    verifier=CanonicalVerifier(
        task_id=core.task_id,runtime_data_dir=root.parent.parent/"release-private",
        evidence_store=store,binding=repo)
    report=await MVPTaskRunner(
        scheduler=core,backend=backend,repository=repo,
        verifier=verifier,policy=canonical).run_node("writer")
    assert report.native_status=="completed"
    assert report.verification_status=="passed"
    assert report.changed_files==("calc.py",)
    assert report.agent_dynamic_command_count==2
    assert report.workspace_status=="quarantined"
    assert preparer.pending_count==0
    assert binding.active_count==0
