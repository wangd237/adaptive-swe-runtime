import pytest
from pydantic import ValidationError
from aswe.core.contracts import TaskNode, TaskDAG, VerificationRepairBinding, WorkKind, WorkspaceAccess
from aswe.core.dag_fingerprint import build_task_dag,structure_fingerprint,final_dag_fingerprint,deterministic_topological_order

def node(id:str,ordinal:int,dependencies=(),work_kind=WorkKind.IMPLEMENTATION):
    return TaskNode(id=id,objective=id,work_kind=work_kind,required_capabilities=("code_modification",),
        provider_id="coder",dependencies=dependencies,workspace_access=WorkspaceAccess.WRITE,
        planner_ordinal=ordinal,fingerprint=f"node-{id}")

def test_f05_two_stage_fingerprint_is_order_independent_and_not_recursive():
    a=node("a",0)
    b=node("b",1,("a",),WorkKind.VERIFICATION)
    fp=structure_fingerprint((b,a))
    binding=VerificationRepairBinding(verification_node_id="b",verification_check_id="check",
        candidate_write_node_ids=("a",),derivation="dag_business_writer_ancestors",
        dag_structure_fingerprint=fp,fingerprint="binding")
    d1=build_task_dag((a,b),(binding,))
    d2=build_task_dag((b,a),(binding,))
    assert d1.structure_fingerprint==d2.structure_fingerprint==fp
    assert d1.fingerprint==d2.fingerprint==final_dag_fingerprint(fp,(binding,))
    assert d1.topological_order==("a","b")
    assert d1.fingerprint!=build_task_dag((a,b)).fingerprint

def test_topological_order_rejects_backward_dependency():
    a,b=node("a",0),node("b",1,("a",))
    with pytest.raises(ValidationError,match="topological_order violates"):
        TaskDAG(nodes=(a,b),topological_order=("b","a"),
            structure_fingerprint="sf",fingerprint="df")

def test_cyclic_dag_fails_before_fingerprint():
    with pytest.raises(ValueError,match="cyclic"):
        deterministic_topological_order((node("a",0,("b",)),node("b",1,("a",))))

def test_duplicate_dependency_rejected():
    with pytest.raises(ValueError,match="duplicate dependencies"):
        deterministic_topological_order((node("a",0),node("b",1,("a","a"))))

def test_f05_binding_fails_if_using_old_structure():
    a=node("a",0)
    b=node("b",1,("a",),WorkKind.VERIFICATION)
    binding=VerificationRepairBinding(verification_node_id="b",verification_check_id="check",
        candidate_write_node_ids=("a",),derivation="dag_business_writer_ancestors",
        dag_structure_fingerprint="stale",fingerprint="binding")
    with pytest.raises(ValueError,match="binding must reference"):
        build_task_dag((a,b),(binding,))
