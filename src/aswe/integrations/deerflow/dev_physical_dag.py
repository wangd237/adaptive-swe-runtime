"""Physical Step-6F developer DAG: observed DeerFlow + provisioned Docker.

All provider/tool resources are resolved against a *real* pinned-native tool
inventory, not a fabricated FakeInventory. A minimal developer scheduler
operates the resulting immutable TaskDAG; the existing single-node
SchedulerCore remains authoritative for each native Coder attempt.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from aswe.core.contracts.task import TaskDAG
from aswe.core.contracts.workspace import WorkspaceAccess
from aswe.integrations.deerflow.dev_execution_plan import DeveloperWorkPlan
from aswe.planning.dag import materialize_task_dag
from aswe.providers.contracts import CapabilityBinding, provider
from aswe.providers.resolver import resolve_workplan


@dataclass(frozen=True)
class PhysicalDeveloperDag:
    dag: TaskDAG
    inventory_fingerprint: str
    resolved_fingerprint: str

    def display(self) -> list[dict]:
        return [
            {"id":node.id,"provider":node.provider_id,
             "work_kind":node.work_kind.value,
             "dependencies":list(node.dependencies),
             "workspace_access":node.workspace_access.value}
            for node in self.dag.nodes
        ]


def compile_physical_developer_dag(
    *, workplan: DeveloperWorkPlan, repository: Path,
    image: str, model: str,
) -> PhysicalDeveloperDag:
    """Probe actual frozen DeerFlow tools and host-issued Docker Bash grant.

    Read-only Explorer has *only* read_file; Coder has read_file/str_replace
    and optional isolated Docker Bash; the verifier is the Runtime-owned
    Docker Bash capability, not an LLM tester. We do not activate upstream
    host Bash.
    """
    from deerflow.config.app_config import AppConfig
    from deerflow.config.model_config import ModelConfig
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
    from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend

    assert_pinned_deerflow_source(vendor_tools.__file__)
    cfg = AppConfig.model_validate({
        "sandbox":{"use":"deerflow.sandbox.local:LocalSandboxProvider",
                   "allow_host_bash":False},
        "tools":[{"name":name,"group":"swe",
                  "use":DEERFLOW_USE_BY_CONTRACT[name]}
                 for name in ("read_file","str_replace")],
        "models":[ModelConfig(name="aswe-cli-model",
            use="langchain_openai:ChatOpenAI",model=model).model_dump(mode="python")],
    })
    tools = tuple(get_available_tools(
        app_config=cfg,extensions=get_loaded_extensions(),
        include_mcp=False,subagent_enabled=False,
        include_upload_tool=False,model_name="aswe-cli-model"))
    native = inventory_from_assembled_tools(
        app_config=cfg,assembled_tools=tools,
        resolve_implementation=lambda use:resolve_variable(use,BaseTool),
        active_agent_types=("general-purpose",),
        sandbox=SimpleNamespace(persistent_shell_sessions=False))
    docker=DockerCommandBackend(workspace_root=repository,image=image)
    inventory=compose_docker_bash_inventory(
        native=native,backend=docker,grant=DockerBashCapability.from_backend(docker))
    providers=(
        provider("explorer",(
            CapabilityBinding(capability_id="repo_exploration",required_tools=("read_file",)),
        ),role="general-purpose"),
        provider("coder",(
            CapabilityBinding(capability_id="code_modification",
                              required_tools=("read_file","str_replace"),
                              optional_tools=("bash",)),
        ),role="general-purpose"),
        provider("tester",(
            CapabilityBinding(capability_id="regression_testing",required_tools=("bash",)),
        ),role="general-purpose"),
    )
    optional={"coder":("bash",)}
    resolved=resolve_workplan(
        plan=workplan.plan,contract=workplan.contract,
        authority=workplan.authority,inventory=inventory,
        providers=providers,selected_optional_by_node=optional)
    dag=materialize_task_dag(
        plan=workplan.plan,resolved=resolved,inventory=inventory,
        verification_check_ids=("cli-regression",))
    if tuple(dag.topological_order) not in (
        ("coder","__aswe_verify"),
        ("explorer","coder","__aswe_verify"),
    ):
        raise ValueError("DEV_DAG_TOPOLOGY_UNSUPPORTED")
    assignments={node.id:node for node in dag.nodes}
    if (assignments["coder"].provider_id!="coder"
            or assignments["coder"].workspace_access is not WorkspaceAccess.WRITE
            or assignments["__aswe_verify"].provider_id!="tester"):
        raise ValueError("DEV_DAG_ASSIGNMENT_MISMATCH")
    if "explorer" in assignments and (
        assignments["explorer"].provider_id!="explorer"
        or assignments["explorer"].workspace_access is not WorkspaceAccess.READ
    ):
        raise ValueError("DEV_DAG_EXPLORER_NOT_READ_ONLY")
    return PhysicalDeveloperDag(dag=dag,
        inventory_fingerprint=inventory.fingerprint,
        resolved_fingerprint=resolved.fingerprint)


class DeveloperDagScheduler:
    """Minimal sequential scheduler for a physically compiled developer DAG.

    This is not SchedulerCore's strict NodeHandoff acceptance: a tool-driven
    Coder run owns its own real SchedulerCore, native workspace and canonical
    verifier. This scheduler uses actual physical TaskDAG edges and verifies
    outcomes before activating dependents; it never fabricates handoffs.
    """

    def __init__(self, physical: PhysicalDeveloperDag):
        self.physical=physical
        self.nodes={n.id:n for n in physical.dag.nodes}
        self.completed: set[str]=set()
        self.attempts: dict[str,int]={}

    def dispatch(self,node_id:str)->int:
        if node_id not in self.nodes:
            raise ValueError("DEV_DAG_NODE_UNKNOWN")
        node=self.nodes[node_id]
        if not set(node.dependencies).issubset(self.completed):
            raise ValueError("DEV_DAG_UPSTREAM_INCOMPLETE")
        if node_id in self.completed and node_id=="explorer":
            raise ValueError("DEV_DAG_DISCOVERY_ALREADY_COMPLETED")
        self.attempts[node_id]=self.attempts.get(node_id,0)+1
        return self.attempts[node_id]

    def finish(self,node_id:str,*,verified:bool)->None:
        if self.attempts.get(node_id,0)==0:
            raise ValueError("DEV_DAG_NODE_NOT_DISPATCHED")
        if verified:
            self.completed.add(node_id)
        else:
            self.completed.discard(node_id)

    def reset_for_repair(self)->None:
        self.completed.discard("coder")
        self.completed.discard("__aswe_verify")
