"""Operator-constrained immutable NodeExecutionPolicy and ProviderAssignment."""
from __future__ import annotations
from pydantic import Field,model_validator
from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts.task import WorkKind
from aswe.core.contracts.workspace import WorkspaceAccess
from aswe.core.fingerprint import fingerprint
from aswe.capabilities.effects import trusted_effect,access_for,ToolEffect
from aswe.providers.resolver import ResolvedPlan
from aswe.providers.contracts import AgentProvider
from aswe.providers.inventory import BackendInventorySnapshot
from aswe.planning.validator import ValidatedWorkPlan
from aswe.planning.contracts import CompiledTaskContract
from aswe.planning.acceptance import CompiledAcceptancePlan
from aswe.planning.immutable import deep_freeze

class AdmissionError(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

class OperatorSurface(FrozenModel):
    provider_id:str
    allowed_tools:tuple[str,...]|None=None
    denied_tools:tuple[str,...]=()
    model_name:str="fake"
    max_turns:int=Field(default=24,gt=0)
    timeout_seconds:float=Field(default=120.,gt=0)
    auth_enabled:bool=False
    authorized_tools:frozenset[str]=frozenset()
    authorized_models:frozenset[str]=frozenset()
    skill_allowed_tools:dict[str,tuple[str,...]|None]={}
    @model_validator(mode="after")
    def freeze_map(self):
        object.__setattr__(self,"skill_allowed_tools",deep_freeze(self.skill_allowed_tools))
        return self

class NodeExecutionPolicy(FrozenModel):
    node_id:str
    provider_id:str
    backend_agent_type:str
    provider_contract_fingerprint:str
    task_contract_fingerprint:str
    workplan_fingerprint:str
    planning_inventory_fingerprint:str
    required_capabilities:tuple[str,...]
    acceptance_fingerprint:str
    verification_exact_commands:tuple[str,...]
    canonical_check_policy_fingerprints:tuple[str,...]
    required_business_tools:tuple[str,...]
    allowed_business_tools:tuple[str,...]
    denied_tools:tuple[str,...]
    required_infrastructure_tools:tuple[str,...]
    infrastructure_tool_names:tuple[str,...]
    preferred_skills:tuple[str,...]
    required_sandbox_features:tuple[str,...]
    allowed_paths:tuple[str,...]|None
    forbidden_paths:tuple[str,...]
    prohibited_actions:tuple[str,...]
    max_changed_files:int|None
    model_name:str
    workspace_access:WorkspaceAccess
    max_turns:int=Field(gt=0)
    timeout_seconds:float=Field(gt=0)
    fingerprint:str
    @model_validator(mode="after")
    def sealed(self):
        if self.fingerprint!=fingerprint(self.model_dump(mode="json",exclude={"fingerprint"})):
            raise ValueError("NodeExecutionPolicy fingerprint mismatch")
        if (len(self.verification_exact_commands)!=len(self.canonical_check_policy_fingerprints)
                or self.verification_exact_commands and "bash" not in self.allowed_business_tools):
            raise ValueError("Acceptance Bash execution policy mismatch")
        if (not set(self.required_business_tools).issubset(self.allowed_business_tools)
                or set(self.allowed_business_tools).intersection(self.denied_tools)
                or not set(self.required_infrastructure_tools).issubset(self.infrastructure_tool_names)):
            raise ValueError("NodeExecutionPolicy authority mismatch")
        return self

class NodeResourceRequirements(FrozenModel):
    required_capabilities:tuple[str,...]
    required_tools:tuple[str,...]
    optional_tools:tuple[str,...]
    preferred_skills:tuple[str,...]
    required_sandbox_features:tuple[str,...]


class ProviderAssignment(FrozenModel):
    work_item_id:str
    provider_id:str
    provider_contract_fingerprint:str
    planning_inventory_fingerprint:str
    policy_fingerprint:str
    resources:NodeResourceRequirements
    preflight_status:str
    preflight_diagnostics:tuple[str,...]=()
    fingerprint:str
    @model_validator(mode="after")
    def sealed(self):
        if (self.preflight_status!="preflight_feasible"
                or self.fingerprint!=fingerprint(self.model_dump(mode="json",exclude={"fingerprint"}))):
            raise ValueError("ProviderAssignment identity mismatch")
        return self

class TeamMember(FrozenModel):
    provider_id:str
    capabilities:tuple[str,...]
    selected_for_nodes:tuple[str,...]
    selection_reason:str

class TeamSpec(FrozenModel):
    members:tuple[TeamMember,...]
    fingerprint:str
    @model_validator(mode="after")
    def sealed(self):
        if self.fingerprint!=fingerprint(self.model_dump(mode="json",exclude={"fingerprint"})):
            raise ValueError("TeamSpec fingerprint mismatch")
        return self

def _seal(cls,body):return cls(**body,fingerprint=fingerprint(body))

def compile_policies(*,contract:CompiledTaskContract,plan:ValidatedWorkPlan,
                     resolved:ResolvedPlan,inventory:BackendInventorySnapshot,
                     providers:tuple[AgentProvider,...],
                     operators:tuple[OperatorSurface,...],
                     acceptance:CompiledAcceptancePlan,
                     node_max_turns:int=24,node_timeout_seconds:float=120.
                     )->tuple[NodeExecutionPolicy,...]:
    if (contract.fingerprint!=plan.task_contract_fingerprint
        or resolved.contract_fingerprint!=contract.fingerprint
        or resolved.workplan_fingerprint!=plan.fingerprint
        or resolved.inventory_fingerprint!=inventory.fingerprint
        or acceptance.task_contract_fingerprint!=contract.fingerprint):
        raise AdmissionError("COMPILED_CONTRACT_DRIFT")
    if (len(set(p.id for p in providers))!=len(providers)
            or len(set(o.provider_id for o in operators))!=len(operators)):
        raise AdmissionError("DUPLICATE_PROVIDER_POLICY")
    by_provider={p.id:p for p in providers}
    op={o.provider_id:o for o in operators}
    resources={r.node_id:r for r in resolved.nodes}
    if acceptance.unresolved_check_keys:
        raise AdmissionError("REQUIRED_ACCEPTANCE_CHECK_UNRESOLVED")
    contract_requirements={c.key:c for c in contract.constraints}
    denied_actions=set(contract_requirements["actions.forbidden"].value
                       if "actions.forbidden" in contract_requirements else ())
    result=[]
    for item in plan.items:
        r=resources[item.id]
        p=by_provider.get(r.provider_id)
        o=op.get(r.provider_id)
        if (p is None or o is None or p.backend_agent_type not in inventory.candidate_agent_types
            or r.provider_contract_fingerprint!=p.fingerprint):
            raise AdmissionError("PROVIDER_STATIC_CONTRACT_MISMATCH")
        if not set(item.capability_hints).issubset(p.capability_bindings):
            raise AdmissionError("PROVIDER_CAPABILITY_CLOSURE_MISMATCH")
        expected_required=[]
        declared_optional=[]
        for cap in item.capability_hints:
            binding=p.capability_bindings[cap]
            for tool_id in binding.required_tools:
                if tool_id not in expected_required: expected_required.append(tool_id)
            for tool_id in binding.optional_tools:
                if tool_id not in declared_optional: declared_optional.append(tool_id)
        if (tuple(expected_required)!=r.required_tools
            or not set(r.selected_optional_tools).issubset(declared_optional)
            or set(r.selected_optional_tools).intersection(expected_required)
            or r.allowed_tools!=r.required_tools+r.selected_optional_tools):
            raise AdmissionError("PROVIDER_CAPABILITY_CLOSURE_MISMATCH")
        allow_set=set(o.allowed_tools) if o.allowed_tools is not None else set(r.allowed_tools)
        allow=tuple(t for t in r.allowed_tools
                    if t in allow_set and t not in o.denied_tools
                    and (not o.auth_enabled or t in o.authorized_tools))
        if set(r.required_tools).intersection(denied_actions) or "*" in denied_actions:
            raise AdmissionError("CONTRACT_TOOL_DENIED")
        if any(t in denied_actions for t in allow):
            raise AdmissionError("CONTRACT_TOOL_DENIED")
        if not set(r.required_tools).issubset(allow):
            raise AdmissionError("PROVIDER_STATIC_CONTRACT_MISMATCH")
        infos=tuple(inventory.candidate_tools.get(t) for t in allow)
        if any(t is None or trusted_effect(t) in (ToolEffect.UNKNOWN,ToolEffect.EXTERNAL_SIDE_EFFECT) for t in infos):
            raise AdmissionError("PROVIDER_TOOL_IDENTITY_MISMATCH")
        if access_for(item.capability_hints,infos)!=r.workspace_access:
            raise AdmissionError("WORKSPACE_EFFECT_AUTHORITY_MISMATCH")
        if not set(acceptance.required_sandbox_features).issubset(inventory.sandbox_features):
            raise AdmissionError("REQUIRED_SANDBOX_EVIDENCE_UNAVAILABLE")
        if o.model_name not in inventory.configured_model_names:
            raise AdmissionError("PROVIDER_MODEL_UNAVAILABLE")
        if o.auth_enabled and (not set(r.required_tools).issubset(o.authorized_tools)
                                or o.model_name not in o.authorized_models):
            raise AdmissionError("PROVIDER_AUTHORIZATION_DENIED")
        skills=[]
        for cap in item.capability_hints:
            for skill in p.capability_bindings[cap].preferred_skills:
                required_by_skill=o.skill_allowed_tools.get(skill)
                if (skill in inventory.candidate_skill_names
                    and (required_by_skill is None or set(r.required_tools).issubset(required_by_skill))
                    and skill not in skills):
                    skills.append(skill)
        infra=("submit_review_verdict",) if item.work_kind is WorkKind.REVIEW else ()
        if infra and (bool(set(infra).intersection(o.denied_tools))
                      or o.allowed_tools is not None and not set(infra).issubset(o.allowed_tools)
                      or o.auth_enabled and not set(infra).issubset(o.authorized_tools)):
            raise AdmissionError("REQUIRED_INFRASTRUCTURE_TOOL_DENIED")
        if node_max_turns<1 or node_timeout_seconds<=0:
            raise AdmissionError("INVALID_RUNTIME_BUDGET")
        exact=(tuple(c.bash_exact_allowlist_entry for c in acceptance.criteria)
               if item.work_kind is WorkKind.VERIFICATION else ())
        canonical=(tuple(c.fingerprint for c in acceptance.canonical_policies)
                   if item.work_kind is WorkKind.VERIFICATION else ())
        if exact and "bash" not in allow:
            raise AdmissionError("ACCEPTANCE_COMMAND_POLICY_MISMATCH")
        body=dict(node_id=item.id,provider_id=p.id,backend_agent_type=p.backend_agent_type,
          provider_contract_fingerprint=p.fingerprint,
          task_contract_fingerprint=contract.fingerprint,
          workplan_fingerprint=plan.fingerprint,
          planning_inventory_fingerprint=inventory.fingerprint,
          required_capabilities=item.capability_hints,
          acceptance_fingerprint=acceptance.fingerprint,
          verification_exact_commands=exact,
          canonical_check_policy_fingerprints=canonical,
          required_business_tools=r.required_tools,
          allowed_business_tools=allow,denied_tools=tuple(sorted(set(o.denied_tools))),
          required_infrastructure_tools=infra,infrastructure_tool_names=infra,
          preferred_skills=tuple(skills),required_sandbox_features=acceptance.required_sandbox_features,
          allowed_paths=(contract_requirements["repo.paths.allowed"].value
                         if "repo.paths.allowed" in contract_requirements else None),
          forbidden_paths=(contract_requirements["repo.paths.forbidden"].value
                           if "repo.paths.forbidden" in contract_requirements else ()),
          prohibited_actions=tuple(sorted(denied_actions)),
          max_changed_files=(contract_requirements["change.max_files"].value
                             if "change.max_files" in contract_requirements else None),
          model_name=o.model_name,workspace_access=r.workspace_access,
          max_turns=min(o.max_turns,node_max_turns),
          timeout_seconds=min(o.timeout_seconds,node_timeout_seconds))
        result.append(_seal(NodeExecutionPolicy,body))
    return tuple(result)

def build_assignments(policies):
    return tuple(_seal(ProviderAssignment,dict(
        work_item_id=p.node_id,provider_id=p.provider_id,
        provider_contract_fingerprint=p.provider_contract_fingerprint,
        planning_inventory_fingerprint=p.planning_inventory_fingerprint,
        policy_fingerprint=p.fingerprint,
        resources=NodeResourceRequirements(
            required_capabilities=p.required_capabilities,
            required_tools=p.required_business_tools,
            optional_tools=tuple(t for t in p.allowed_business_tools
                                 if t not in p.required_business_tools),
            preferred_skills=p.preferred_skills,
            required_sandbox_features=p.required_sandbox_features,
        ),preflight_status="preflight_feasible")) for p in policies)

def build_team(plan,policies):
    groups={}
    for item in plan.items:
        policy=next(p for p in policies if p.node_id==item.id)
        groups.setdefault(policy.provider_id,[]).append(item)
    members=tuple(TeamMember(provider_id=k,
        capabilities=tuple(sorted({cap for i in items for cap in i.capability_hints})),
        selected_for_nodes=tuple(i.id for i in items),
        selection_reason="feasible_reused_execution_carrier")
        for k,items in sorted(groups.items()))
    return _seal(TeamSpec,dict(members=members))
