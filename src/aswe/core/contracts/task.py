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
        for binding in self.verification_repair_bindings:
            if binding.dag_structure_fingerprint!=self.structure_fingerprint:
                raise ValueError("VerificationRepairBinding must bind TaskDAG.structure_fingerprint")
        return self
