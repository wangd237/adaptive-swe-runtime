import pytest
from pydantic import ValidationError
from aswe.core.contracts import TaskDAG, TaskNode, VerificationRepairBinding, WorkKind, WorkspaceAccess

def _node(node_id:str,dependencies:tuple[str,...]=())->TaskNode:
    return TaskNode(id=node_id,objective=f"objective:{node_id}",work_kind=WorkKind.IMPLEMENTATION,required_capabilities=("code_modification",),provider_id="coder",dependencies=dependencies,workspace_access=WorkspaceAccess.WRITE,planner_ordinal=0,fingerprint=f"fp-{node_id}")

def test_task_node_is_immutable_and_has_no_runtime_status()->None:
    node=_node("implement")
    assert "status" not in type(node).model_fields
    with pytest.raises(ValidationError):
        node.objective="mutated"  # type: ignore[misc]

def test_task_dag_rejects_unknown_dependency()->None:
    with pytest.raises(ValidationError):
        TaskDAG(nodes=(_node("a",("missing",)),),topological_order=("a",),structure_fingerprint="structure",fingerprint="dag")

def test_repair_binding_must_match_structure_fingerprint()->None:
    node=_node("a")
    binding=VerificationRepairBinding(verification_node_id="verify",verification_check_id="check",candidate_write_node_ids=("a",),derivation="runtime_owned_gate",dag_structure_fingerprint="other",fingerprint="binding")
    with pytest.raises(ValidationError):
        TaskDAG(nodes=(node,),topological_order=("a",),structure_fingerprint="structure",verification_repair_bindings=(binding,),fingerprint="dag")
