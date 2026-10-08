from aswe.core.contracts import NodeExecutionInvocation, NodeExecutionPreparation

def test_execution_identity_exists_only_post_commit_invocation()->None:
    preparation=set(NodeExecutionPreparation.model_fields)
    invocation=set(NodeExecutionInvocation.model_fields)
    assert {"attempt","execution_id","run_id"}.isdisjoint(preparation)
    assert {"attempt","execution_id","run_id"}.issubset(invocation)
