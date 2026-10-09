"""Step-4 phase DAG materialization with physical WRITE ordering.

Step 3 preserved business semantics; this stage imposes deterministic *physical*
ordering without rewriting work items, phase types or acceptance authority.
"""
from __future__ import annotations
from aswe.core.contracts.task import TaskNode,TaskDAG,WorkKind,VerificationRepairBinding
from aswe.core.contracts.workspace import WorkspaceAccess
from aswe.core.dag_fingerprint import build_task_dag,structure_fingerprint
from aswe.core.fingerprint import fingerprint
from aswe.planning.validator import ValidatedWorkPlan,PHASE
from aswe.providers.resolver import ResolvedPlan

class MaterializationError(ValueError):
    pass

def materialize_task_dag(*,plan:ValidatedWorkPlan,resolved:ResolvedPlan,
                         verification_check_ids:tuple[str,...]=())->TaskDAG:
    if resolved.workplan_fingerprint!=plan.fingerprint:
        raise MaterializationError("WORKPLAN_BINDING_MISMATCH")
    loc={x.node_id:x for x in resolved.nodes}
    if set(loc)!={x.id for x in plan.items} or len(loc)!=len(resolved.nodes):
        raise MaterializationError("RESOURCE_ASSIGNMENTS_INCOMPLETE")
    ids={x.id:x for x in plan.items}
    # Planner ordinals are original and stable, independent of provider rank.
    ordered=sorted(plan.items,key=lambda x:(x.planner_ordinal,x.id))
    dependencies={x.id:set(x.depends_on) for x in ordered}
    for item in ordered:
        # Complete phase barriers: every earlier business phase must finish
        # before later-phase nodes regardless of READ/WRITE implementation.
        dependencies[item.id].update(
            other.id for other in ordered
            if PHASE[other.work_kind]<PHASE[item.work_kind]
        )
    # Physical same-phase WRITEs have exclusive linearization even when Planner
    # emitted no semantic edge. Guard against contradicting explicit direction.
    phase_writers={}
    for item in ordered:
        if loc[item.id].workspace_access is not WorkspaceAccess.WRITE:
            continue
        kind=item.work_kind
        previous=phase_writers.get(kind)
        if previous is not None:
            if item.id in dependencies[previous]:
                raise MaterializationError("PHASE_WRITE_ORDER_CONTRADICTION")
            dependencies[item.id].add(previous)
        phase_writers[kind]=item.id
    nodes=[]
    for item in ordered:
        res=loc[item.id]
        body=dict(id=item.id,objective=item.objective,
                  work_kind=item.work_kind,
                  required_capabilities=item.capability_hints,
                  provider_id=res.provider_id,
                  dependencies=tuple(sorted(dependencies[item.id])),
                  workspace_access=res.workspace_access,
                  planner_ordinal=item.planner_ordinal,
                  runtime_owned=item.runtime_owned,
                  affected_paths=None,
                  acceptance_criteria=item.acceptance_intent)
        nodes.append(TaskNode(**body,fingerprint=fingerprint(body)))
    s=structure_fingerprint(nodes)
    by_id={x.id:x for x in nodes}
    def ancestors(node_id):
        pending=list(by_id[node_id].dependencies)
        seen=set()
        while pending:
            dep=pending.pop()
            if dep in seen:continue
            seen.add(dep)
            pending.extend(by_id[dep].dependencies)
        return seen
    bindings=[]
    for item in ordered:
        if item.work_kind is not WorkKind.VERIFICATION:continue
        writer_ids=tuple(x.id for x in ordered
            if x.work_kind is WorkKind.IMPLEMENTATION and x.id in ancestors(item.id))
        for check_id in tuple(sorted(set(verification_check_ids))):
            b=dict(verification_node_id=item.id,verification_check_id=check_id,
                   candidate_write_node_ids=writer_ids,
                   derivation=("runtime_owned_gate" if item.runtime_owned
                               else "dag_business_writer_ancestors"),
                   dag_structure_fingerprint=s)
            bindings.append(VerificationRepairBinding(**b,fingerprint=fingerprint(b)))
    return build_task_dag(nodes,bindings)
