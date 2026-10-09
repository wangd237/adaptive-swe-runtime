"""Deterministic provider feasibility and physical WorkspaceAccess projection."""
from pydantic import Field,model_validator
from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts.workspace import WorkspaceAccess
from aswe.core.fingerprint import fingerprint
from aswe.capabilities.registry import CAPABILITIES,CapabilityAuthorityClass
from aswe.capabilities.effects import trusted_effect,access_for,ToolEffect
from aswe.providers.contracts import AgentProvider
from aswe.providers.inventory import BackendInventorySnapshot
from aswe.planning.compiler import project_execution_authority
from aswe.planning.contracts import CompiledTaskContract,TaskExecutionAuthority
from aswe.planning.validator import ValidatedWorkPlan

class ProviderFeasibilityError(ValueError):
    pass

class NodeResources(FrozenModel):
    node_id:str
    provider_id:str
    required_tools:tuple[str,...]
    selected_optional_tools:tuple[str,...]
    allowed_tools:tuple[str,...]
    workspace_access:WorkspaceAccess
    policy_fingerprint:str=Field(pattern=r"^[0-9a-f]{64}$")
    @model_validator(mode="after")
    def validate_policy_hash(self):
        if self.policy_fingerprint!=fingerprint(self.model_dump(mode="json",exclude={"policy_fingerprint"})):
            raise ValueError("NodeResources policy fingerprint mismatch")
        if self.allowed_tools!=tuple(dict.fromkeys(self.required_tools+self.selected_optional_tools)):
            raise ValueError("noncanonical effective tool allowlist")
        return self

class ResolvedPlan(FrozenModel):
    contract_fingerprint:str
    workplan_fingerprint:str
    inventory_fingerprint:str
    nodes:tuple[NodeResources,...]
    fingerprint:str
    @model_validator(mode="after")
    def validate_hash(self):
        if self.fingerprint!=fingerprint(self.model_dump(mode="json",exclude={"fingerprint"})):
            raise ValueError("ResolvedPlan fingerprint mismatch")
        return self

def resolve_workplan(*,plan:ValidatedWorkPlan,contract:CompiledTaskContract,
                     authority:TaskExecutionAuthority,inventory:BackendInventorySnapshot,
                     providers:tuple[AgentProvider,...],required_sandbox_features:tuple[str,...]=(),
                     selected_optional_by_node:dict[str,tuple[str,...]]|None=None):
    if (plan.task_contract_fingerprint!=contract.fingerprint
            or authority!=project_execution_authority(contract)):
        raise ProviderFeasibilityError("PLAN_CONTRACT_AUTHORITY_MISMATCH")
    if not set(required_sandbox_features).issubset(inventory.sandbox_features):
        raise ProviderFeasibilityError("REQUIRED_SANDBOX_EVIDENCE_UNAVAILABLE")
    selection=selected_optional_by_node or {}
    if set(selection)-{x.id for x in plan.items}:
        raise ProviderFeasibilityError("UNKNOWN_OPTIONAL_SELECTION_NODE")
    result=[]
    for item in plan.items:
        possible=[]
        for provider in sorted(providers,key=lambda p:p.id):
            if provider.backend_agent_type not in inventory.candidate_agent_types:
                continue
            if not set(item.capability_hints).issubset(provider.capability_bindings):
                continue
            required=[]
            declared_optional=[]
            for cap in item.capability_hints:
                spec=CAPABILITIES.get(cap)
                if spec is None:raise ProviderFeasibilityError("UNKNOWN_CAPABILITY")
                if spec.authority_class is CapabilityAuthorityClass.REPOSITORY_MUTATION:
                    if not authority.repository_mutation_allowed:
                        raise ProviderFeasibilityError("CAPABILITY_AUTHORITY_VIOLATION")
                for contract_id in provider.capability_bindings[cap].required_tools:
                    if contract_id not in required:required.append(contract_id)
                for contract_id in provider.capability_bindings[cap].optional_tools:
                    if contract_id not in declared_optional:declared_optional.append(contract_id)
            choice=tuple(dict.fromkeys(selection.get(item.id,())))
            if not set(choice).issubset(declared_optional):
                raise ProviderFeasibilityError("OPTIONAL_TOOL_NOT_DECLARED")
            optional=tuple(t for t in choice if t not in required)
            infos=[inventory.candidate_tools.get(t) for t in required+list(optional)]
            if any(x is None or trusted_effect(x) is ToolEffect.UNKNOWN
                   or x.effect is ToolEffect.EXTERNAL_SIDE_EFFECT for x in infos):
                continue
            physical=access_for(item.capability_hints,tuple(infos))
            body=dict(node_id=item.id,provider_id=provider.id,
              required_tools=tuple(required),selected_optional_tools=optional,
              allowed_tools=tuple(required)+optional,workspace_access=physical)
            possible.append(NodeResources(**body,policy_fingerprint=fingerprint(body)))
        if not possible:
            raise ProviderFeasibilityError("PROVIDER_UNAVAILABLE:"+item.id)
        result.append(possible[0])
    body=dict(contract_fingerprint=contract.fingerprint,
              workplan_fingerprint=plan.fingerprint,
              inventory_fingerprint=inventory.fingerprint,nodes=tuple(result))
    return ResolvedPlan(**body,fingerprint=fingerprint(body))
