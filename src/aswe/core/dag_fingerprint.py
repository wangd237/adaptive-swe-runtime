"""Pure two-stage TaskDAG fingerprints: never hash the final DAG into itself."""
from __future__ import annotations
import heapq
from collections.abc import Sequence
from aswe.core.contracts.task import TaskDAG, TaskNode, VerificationRepairBinding
from aswe.core.fingerprint import fingerprint

def structure_fingerprint(nodes: Sequence[TaskNode]) -> str:
    ordered = sorted(nodes, key=lambda n: n.id)
    return fingerprint({
        "nodes": [node.model_dump(mode="json") for node in ordered],
        "edges": sorted((upstream, node.id) for node in ordered for upstream in node.dependencies),
    })

def final_dag_fingerprint(structure_fp: str, bindings: Sequence[VerificationRepairBinding]) -> str:
    ordered = sorted(bindings, key=lambda b: (b.verification_node_id, b.verification_check_id))
    return fingerprint({
        "structure_fingerprint": structure_fp,
        "verification_repair_bindings": [b.model_dump(mode="json") for b in ordered],
    })

def deterministic_topological_order(nodes: Sequence[TaskNode]) -> tuple[str, ...]:
    by_id = {n.id: n for n in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("duplicate node ids")
    successors: dict[str, set[str]] = {key: set() for key in by_id}
    indegree: dict[str, int] = {}
    for n in nodes:
        if n.id in n.dependencies:
            raise ValueError("self dependency")
        if any(dep not in by_id for dep in n.dependencies):
            raise ValueError("unknown dependency")
        if len(set(n.dependencies)) != len(n.dependencies):
            raise ValueError("duplicate dependencies")
        indegree[n.id] = len(n.dependencies)
        for dep in n.dependencies:
            successors[dep].add(n.id)
    heap = [(n.planner_ordinal, n.id) for n in nodes if indegree[n.id] == 0]
    heapq.heapify(heap)
    result: list[str] = []
    while heap:
        _, node_id = heapq.heappop(heap)
        result.append(node_id)
        for down in successors[node_id]:
            indegree[down] -= 1
            if indegree[down] == 0:
                n = by_id[down]
                heapq.heappush(heap, (n.planner_ordinal, n.id))
    if len(result) != len(nodes):
        raise ValueError("cyclic TaskDAG")
    return tuple(result)

def build_task_dag(
    nodes: Sequence[TaskNode],
    bindings: Sequence[VerificationRepairBinding] = (),
) -> TaskDAG:
    order = deterministic_topological_order(nodes)
    sfp = structure_fingerprint(nodes)
    if any(b.dag_structure_fingerprint != sfp for b in bindings):
        raise ValueError("binding must reference the compiled structure fingerprint")
    return TaskDAG(
        nodes=tuple(sorted(nodes, key=lambda n: n.id)),
        topological_order=order,
        structure_fingerprint=sfp,
        verification_repair_bindings=tuple(sorted(bindings, key=lambda b: (b.verification_node_id, b.verification_check_id))),
        fingerprint=final_dag_fingerprint(sfp, bindings),
    )
