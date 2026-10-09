"""Sealed Step-4 plan descriptor: never trust independent model fingerprints."""
from pydantic import model_validator
from aswe.core.contracts._base import FrozenModel
from aswe.core.fingerprint import fingerprint
from aswe.core.contracts.task import TaskDAG
from aswe.planning.acceptance import ExecutionContractBinding,CompiledAcceptancePlan,bind_execution_contract
from aswe.planning.contracts import CompiledTaskContract
from aswe.planning.validator import ValidatedWorkPlan
from aswe.providers.policy import (
    NodeExecutionPolicy,ProviderAssignment,TeamSpec,build_assignments,build_team)
from aswe.providers.resolver import ResolvedPlan
from aswe.providers.inventory import BackendInventorySnapshot
from aswe.planning.dag import materialize_task_dag

class DescriptorMismatch(ValueError):pass

class CompiledPlanDescriptor(FrozenModel):
    execution_contract_binding:ExecutionContractBinding
    task_contract_fingerprint:str
    validated_work_plan_fingerprint:str
    acceptance_fingerprint:str
    resolved_plan_fingerprint:str
    planning_inventory_fingerprint:str
    task_dag:TaskDAG
    policies:tuple[NodeExecutionPolicy,...]
    assignments:tuple[ProviderAssignment,...]
    team:TeamSpec
    fingerprint:str
    @model_validator(mode="after")
    def sealed(self):
        if self.fingerprint!=fingerprint(self.model_dump(mode="json",exclude={"fingerprint"})):
            raise ValueError("CompiledPlanDescriptor fingerprint mismatch")
        if (self.execution_contract_binding.task_contract_fingerprint!=self.task_contract_fingerprint
            or self.execution_contract_binding.validated_work_plan_fingerprint!=self.validated_work_plan_fingerprint
            or self.execution_contract_binding.acceptance_plan_fingerprint!=self.acceptance_fingerprint):
            raise ValueError("CompiledPlanDescriptor binding mismatch")
        by_node={p.node_id:p for p in self.policies}
        by_assignment={a.work_item_id:a for a in self.assignments}
        dag_nodes={n.id:n for n in self.task_dag.nodes}
        if (len(by_node)!=len(self.policies) or len(by_assignment)!=len(self.assignments)
                or set(by_node)!=set(dag_nodes) or set(by_assignment)!=set(by_node)):
            raise ValueError("CompiledPlanDescriptor policy mismatch")
        for node_id,p in by_node.items():
            n=dag_nodes[node_id]
            a=by_assignment[node_id]
            resources=a.resources
            if (n.provider_id!=p.provider_id
                or n.workspace_access!=p.workspace_access
                or n.required_capabilities!=p.required_capabilities
                or a.provider_id!=p.provider_id
                or a.policy_fingerprint!=p.fingerprint
                or a.provider_contract_fingerprint!=p.provider_contract_fingerprint
                or resources.required_capabilities!=p.required_capabilities
                or resources.required_tools!=p.required_business_tools
                or resources.required_sandbox_features!=p.required_sandbox_features
                or resources.preferred_skills!=p.preferred_skills
                or resources.optional_tools!=tuple(x for x in p.allowed_business_tools
                        if x not in p.required_business_tools)):
                raise ValueError("CompiledPlanDescriptor policy mismatch")
        roster={m.provider_id:set(m.selected_for_nodes) for m in self.team.members}
        if (len(roster)!=len(self.team.members)
            or roster!={pid:{n for n,p in by_node.items() if p.provider_id==pid}
                       for pid in {p.provider_id for p in self.policies}}):
            raise ValueError("CompiledPlanDescriptor team mismatch")
        return self

def compile_plan_descriptor(*,contract:CompiledTaskContract,plan:ValidatedWorkPlan,
                            acceptance:CompiledAcceptancePlan,resolved:ResolvedPlan,
                            inventory:BackendInventorySnapshot,
                            policies:tuple[NodeExecutionPolicy,...],
                            verification_check_ids:tuple[str,...]=()):
    binding=bind_execution_contract(contract=contract,plan=plan,acceptance=acceptance)
    if (resolved.contract_fingerprint!=contract.fingerprint
        or resolved.workplan_fingerprint!=plan.fingerprint
        or resolved.inventory_fingerprint!=inventory.fingerprint):
        raise DescriptorMismatch("EXECUTION_DESCRIPTOR_BOUNDARY_MISMATCH")
    by_id={p.node_id:p for p in policies}
    if len(by_id)!=len(policies) or set(by_id)!={i.id for i in plan.items}:
        raise DescriptorMismatch("EXECUTION_DESCRIPTOR_POLICY_COVERAGE")
    limits={c.key:c.value for c in contract.constraints}
    for r in resolved.nodes:
        p=by_id[r.node_id]
        if (p.allowed_paths!=limits.get("repo.paths.allowed")
            or p.forbidden_paths!=limits.get("repo.paths.forbidden",())
            or p.max_changed_files!=limits.get("change.max_files")
            or p.prohibited_actions!=tuple(sorted(limits.get("actions.forbidden",())))):
            raise DescriptorMismatch("EXECUTION_DESCRIPTOR_POLICY_DRIFT")
        if (p.task_contract_fingerprint!=contract.fingerprint
            or p.workplan_fingerprint!=plan.fingerprint
            or p.planning_inventory_fingerprint!=inventory.fingerprint
            or p.acceptance_fingerprint!=acceptance.fingerprint
            or p.required_capabilities!=next(item for item in plan.items if item.id==p.node_id).capability_hints
            or p.verification_exact_commands!=(
                tuple(x.bash_exact_allowlist_entry for x in acceptance.criteria)
                if next(item for item in plan.items if item.id==p.node_id).work_kind.value=="verification" else ())
            or p.canonical_check_policy_fingerprints!=(
                tuple(x.fingerprint for x in acceptance.canonical_policies)
                if next(item for item in plan.items if item.id==p.node_id).work_kind.value=="verification" else ())
            or p.provider_id!=r.provider_id
            or p.provider_contract_fingerprint!=r.provider_contract_fingerprint
            or not set(p.allowed_business_tools).issubset(r.allowed_tools)
            or not set(r.required_tools).issubset(p.allowed_business_tools)
            or p.workspace_access!=r.workspace_access):
            raise DescriptorMismatch("EXECUTION_DESCRIPTOR_POLICY_DRIFT")
    checks=tuple(sorted(command.id for command in acceptance.commands))
    if verification_check_ids and tuple(sorted(verification_check_ids))!=checks:
        raise DescriptorMismatch("VERIFICATION_REPAIR_COMMAND_DRIFT")
    dag=materialize_task_dag(plan=plan,resolved=resolved,inventory=inventory,
                             verification_check_ids=checks)
    assignments=build_assignments(policies)
    team=build_team(plan,policies)
    body=dict(execution_contract_binding=binding,
      task_contract_fingerprint=contract.fingerprint,
      validated_work_plan_fingerprint=plan.fingerprint,
      acceptance_fingerprint=acceptance.fingerprint,
      resolved_plan_fingerprint=resolved.fingerprint,
      planning_inventory_fingerprint=inventory.fingerprint,
      task_dag=dag,policies=policies,assignments=assignments,team=team)
    return CompiledPlanDescriptor(**body,fingerprint=fingerprint(body))
