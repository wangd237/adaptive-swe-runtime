from enum import Enum
from typing import Literal
from pydantic import model_validator
from ._base import FrozenModel
from .workspace import WorkspaceAccess

class WorkKind(str, Enum):
    DISCOVERY="discovery"; IMPLEMENTATION="implementation"; VERIFICATION="verification"; REVIEW="review"

class TaskNode(FrozenModel):
    id: str
    objective: str
    work_kind: WorkKind
    required_capabilities: tuple[str,...]
    provider_id: str
    dependencies: tuple[str,...]
    workspace_access: WorkspaceAccess
    planner_ordinal: int
    runtime_owned: bool=False
    affected_paths: tuple[str,...]|None=None
    acceptance_criteria: tuple[str,...]=()
    fingerprint: str

class VerificationRepairBinding(FrozenModel):
    verification_node_id: str
    verification_check_id: str
    candidate_write_node_ids: tuple[str,...]
    derivation: Literal["dag_business_writer_ancestors","runtime_owned_gate"]
    dag_structure_fingerprint: str
    fingerprint: str

class TaskDAG(FrozenModel):
    nodes: tuple[TaskNode,...]
    topological_order: tuple[str,...]
    structure_fingerprint: str
    verification_repair_bindings: tuple[VerificationRepairBinding,...]=()
    fingerprint: str

    @model_validator(mode="after")
    def _validate_identity_and_binding_scope(self) -> "TaskDAG":
        from aswe.core.dag_fingerprint import (
            deterministic_topological_order,
            final_dag_fingerprint,
            structure_fingerprint,
        )

        node_ids=tuple(node.id for node in self.nodes)
        if len(set(node_ids))!=len(node_ids): raise ValueError("TaskDAG node ids must be unique")
        if len(set(self.topological_order))!=len(self.topological_order): raise ValueError("TaskDAG topological_order must not contain duplicates")
        if set(node_ids)!=set(self.topological_order): raise ValueError("TaskDAG topological_order must contain every node exactly once")
        known=set(node_ids)
        for node in self.nodes:
            unknown=set(node.dependencies)-known
            if unknown: raise ValueError(f"unknown dependencies for {node.id}: {sorted(unknown)}")
        position = {node_id: index for index, node_id in enumerate(self.topological_order)}
        for node in self.nodes:
            if len(set(node.dependencies)) != len(node.dependencies):
                raise ValueError(f"duplicate dependencies on {node.id}")
            if any(position[upstream] >= position[node.id] for upstream in node.dependencies):
                raise ValueError("topological_order violates a dependency")
        if self.topological_order != deterministic_topological_order(self.nodes):
            raise ValueError("TaskDAG topological_order is not deterministic canonical order")
        if self.structure_fingerprint != structure_fingerprint(self.nodes):
            raise ValueError("TaskDAG structure_fingerprint does not match nodes and edges")
        binding_keys: set[tuple[str, str]] = set()
        for binding in self.verification_repair_bindings:
            if binding.dag_structure_fingerprint != self.structure_fingerprint:
                raise ValueError("VerificationRepairBinding must bind TaskDAG.structure_fingerprint")
            key = (binding.verification_node_id, binding.verification_check_id)
            if key in binding_keys:
                raise ValueError("duplicate verification-check repair binding")
            binding_keys.add(key)
            if binding.verification_node_id not in known:
                raise ValueError("unknown verification node in repair binding")
            if any(w not in known for w in binding.candidate_write_node_ids):
                raise ValueError("unknown candidate writer in repair binding")
            if len(set(binding.candidate_write_node_ids)) != len(binding.candidate_write_node_ids):
                raise ValueError("duplicate writer candidate in repair binding")
        if self.fingerprint != final_dag_fingerprint(
            self.structure_fingerprint, self.verification_repair_bindings
        ):
            raise ValueError("TaskDAG fingerprint does not match structure and bindings")
        return self
