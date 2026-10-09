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
        if (tuple(x.id for x in self.task_dag.nodes)!=tuple(sorted(p.node_id for p in self.policies))
            or {a.policy_fingerprint for a in self.assignments}!={p.fingerprint for p in self.policies}
            or self.team.fingerprint is None):
            raise ValueError("CompiledPlanDescriptor policy mismatch")
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
    for r in resolved.nodes:
        p=by_id[r.node_id]
        if (p.task_contract_fingerprint!=contract.fingerprint
            or p.workplan_fingerprint!=plan.fingerprint
            or p.planning_inventory_fingerprint!=inventory.fingerprint
            or p.provider_id!=r.provider_id
            or not set(p.allowed_business_tools).issubset(r.allowed_tools)
            or not set(r.required_tools).issubset(p.allowed_business_tools)
            or p.workspace_access!=r.workspace_access):
            raise DescriptorMismatch("EXECUTION_DESCRIPTOR_POLICY_DRIFT")
    dag=materialize_task_dag(plan=plan,resolved=resolved,inventory=inventory,
                             verification_check_ids=verification_check_ids)
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
