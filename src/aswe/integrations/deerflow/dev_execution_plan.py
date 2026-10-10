"""Step 6F: validated semantic work DAG for the developer orchestration.

This is a genuine ConstraintCompiler + SemanticPlanValidator result, not an
invented execution graph. Physical provider/tool compilation remains in the
native coding child task and is NOT claimed for the top-level stage plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from aswe.core.contracts import WorkKind
from aswe.planning.compiler import ConstraintCompiler, RuntimePolicyConfig, RuntimePolicyRule
from aswe.planning.contracts import make_task_request, CompiledTaskContract, TaskExecutionAuthority
from aswe.planning.planner import WorkItemProposal, WorkPlanProposal
from aswe.planning.validator import SemanticPlanValidator, ValidatedWorkPlan
from aswe.integrations.deerflow.adaptive_team import TeamDecision


@dataclass(frozen=True)
class DeveloperWorkPlan:
    plan: ValidatedWorkPlan
    contract_fingerprint: str
    contract: CompiledTaskContract
    authority: TaskExecutionAuthority

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(x.id for x in self.plan.items)

    def require_ready(self, node_id: str, completed: set[str]) -> None:
        matches = [x for x in self.plan.items if x.id == node_id]
        if len(matches) != 1:
            raise ValueError("DEV_WORK_NODE_UNKNOWN")
        if not set(matches[0].depends_on).issubset(completed):
            raise ValueError("DEV_WORK_DEPENDENCY_NOT_SATISFIED")

    def trace_nodes(self) -> list[dict]:
        return [
            {"id":item.id, "work_kind":item.work_kind.value,
             "depends_on":list(item.depends_on),
             "runtime_owned":item.runtime_owned,
             "capabilities":list(item.capability_hints)}
            for item in self.plan.items
        ]


def compile_developer_workplan(*, repository: Path, ref: str, task: str,
                               workflow_id: str, decision: TeamDecision,
                               coder_objective: str,
                               explorer_objective: str) -> DeveloperWorkPlan:
    baseline = subprocess.run(
        ["git","-C",str(repository),"rev-parse","--verify",f"{ref}^{{commit}}"],
        check=True,capture_output=True,text=True,timeout=15,
    ).stdout.strip()
    contract, authority = ConstraintCompiler(RuntimePolicyConfig(
        policy_id="aswe-dev-workflow",
        rules=(
            RuntimePolicyRule(key="deliverables.required",value={
                "effect":"repository_mutation","description":"implement SWE task"}),
            RuntimePolicyRule(key="verification.required",value=("unit",)),
        ),
    )).compile(
        request=make_task_request(request_id=workflow_id,raw_text=task),
        repository_base_sha=baseline,
    )
    grant=next(c.id for c in contract.constraints if c.key=="deliverables.required")
    explorer = decision.needs_exploration
    items=[]
    if explorer:
        items.append(WorkItemProposal(
            id="explorer",objective=explorer_objective,
            work_kind=WorkKind.DISCOVERY,
            capability_hints=("repo_exploration",)))
    items.append(WorkItemProposal(
        id="coder",objective=coder_objective,
        work_kind=WorkKind.IMPLEMENTATION,
        capability_hints=("code_modification",),
        depends_on=("explorer",) if explorer else (),
        coverage_claims=(grant,)))
    # The validator itself injects the independent verification gate,
    # rather than letting planner output authorize verification.
    plan = SemanticPlanValidator(max_work_items=4).validate(
        proposal=WorkPlanProposal(items=tuple(items),
            rationale="Minimal SWE developer team with canonical test gate"),
        contract=contract,authority=authority,
    )
    return DeveloperWorkPlan(plan=plan,contract_fingerprint=contract.fingerprint,
                             contract=contract, authority=authority)
