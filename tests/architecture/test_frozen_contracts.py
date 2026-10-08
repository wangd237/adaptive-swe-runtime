from aswe.core.contracts import EvidenceRef, NodeExecutionPreparation, NodeHandoff, TaskNode

def test_tasknode_does_not_own_mutable_runtime_lifecycle()->None:
    assert "status" not in TaskNode.model_fields
    assert "retry_policy" not in TaskNode.model_fields
    assert "repair_policy" not in TaskNode.model_fields

def test_handoff_is_not_an_evidence_ref()->None:
    assert not issubclass(NodeHandoff,EvidenceRef)

def test_preparation_does_not_allocate_attempt_execution_identity()->None:
    fields=NodeExecutionPreparation.model_fields
    assert "preparation_id" in fields
    assert "attempt" not in fields
    assert "execution_id" not in fields
    assert "run_id" not in fields
