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


def test_f05_rejects_forged_structure_hash_on_direct_dag_construction():
    n = node("a", 0)
    with pytest.raises(ValidationError, match="structure_fingerprint does not match"):
        TaskDAG(nodes=(n,), topological_order=("a",),
                structure_fingerprint="spoof", fingerprint="spoof")

def test_f05_rejects_forged_final_hash_even_with_valid_structure():
    n = node("a", 0)
    structure = structure_fingerprint((n,))
    with pytest.raises(ValidationError, match="fingerprint does not match"):
        TaskDAG(nodes=(n,), topological_order=("a",),
                structure_fingerprint=structure, fingerprint="spoof")

def test_same_dependency_set_in_different_tuple_order_has_same_structure_fingerprint():
    a, b = node("a", 0), node("b", 1)
    c1 = node("c", 2, ("a", "b"))
    c2 = node("c", 2, ("b", "a"))
    assert structure_fingerprint((a, b, c1)) == structure_fingerprint((a, b, c2))
    assert build_task_dag((a, b, c1)).fingerprint == build_task_dag((a, b, c2)).fingerprint

def test_reject_duplicate_verification_bindings_for_one_check():
    a = node("a", 0)
    v = node("v", 1, ("a",), WorkKind.VERIFICATION)
    structure = structure_fingerprint((a, v))
    binding = VerificationRepairBinding(
        verification_node_id="v", verification_check_id="check",
        candidate_write_node_ids=("a",), derivation="dag_business_writer_ancestors",
        dag_structure_fingerprint=structure, fingerprint="b",
    )
    with pytest.raises(ValidationError, match="duplicate verification-check repair binding"):
        build_task_dag((a, v), (binding, binding))

def test_dag_copy_update_cannot_bypass_final_fingerprint_validation():
    original = build_task_dag((node("a", 0),))
    with pytest.raises(ValidationError, match="fingerprint does not match"):
        original.model_copy(update={"fingerprint": "forged"})

def test_reject_noncanonical_but_valid_topological_order():
    a, b = node("a", 0), node("b", 1)
    canonical = build_task_dag((a, b))
    with pytest.raises(ValidationError, match="not deterministic canonical order"):
        canonical.model_copy(update={"topological_order": ("b", "a")})
