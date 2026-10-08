import pytest
from pydantic import ValidationError
from aswe.runtime.state import NodeAttemptKind, NodeAttemptRecord, NodeAttemptStatus, NodeRuntimeState, NodeLogicalStatus
from aswe.core.contracts import NodeHandoff, HandoffEvidence, WorkspaceRevision, ExecutionCompleteness

def rev():
    return WorkspaceRevision(generation=0,base_sha="a"*40,head_sha="a"*40,
        head_matches_baseline=True,repository_state_fingerprint="digest",dirty=False)

def handoff(execution_id:str="exec")->NodeHandoff:
    return NodeHandoff(source_node_id="writer",source_execution_id=execution_id,source_attempt=1,
        source_provider_id="coder",observed_workspace_revision=rev(),self_report="done",
        evidence=HandoffEvidence(),backend_stop_reason=None,
        execution_completeness=ExecutionCompleteness.UNCAPPED,fingerprint="h1")

def attempt(h:NodeHandoff|None)->NodeAttemptRecord:
    return NodeAttemptRecord(node_id="writer",attempt=1,kind=NodeAttemptKind.INITIAL,
        execution_id="exec",pre_workspace_revision=rev(),post_workspace_revision=rev(),
        status=NodeAttemptStatus.ACCEPTED if h else NodeAttemptStatus.FAILED,
        failure_kind=None,handoff=h)

def test_empty_initial_node_has_no_accepted_authority():
    state=NodeRuntimeState(node_id="writer",logical_status=NodeLogicalStatus.PENDING,
        next_attempt=1,repair_count=0)
    assert state.accepted_handoff is None and state.accepted_attempt is None

def test_f04_only_accepted_historical_attempt_can_authorize_handoff():
    h=handoff()
    state=NodeRuntimeState(node_id="writer",logical_status=NodeLogicalStatus.SUCCEEDED,
        next_attempt=2,repair_count=0,accepted_attempt=1,accepted_handoff=h,attempts=(attempt(h),))
    assert state.accepted_handoff==h

def test_reject_handoff_without_accepted_attempt():
    with pytest.raises(ValidationError,match="set or cleared together"):
        NodeRuntimeState(node_id="writer",logical_status=NodeLogicalStatus.PENDING,
            next_attempt=2,repair_count=0,accepted_handoff=handoff())

def test_reject_handoff_from_wrong_execution():
    h=handoff(execution_id="other")
    with pytest.raises(ValidationError,match="identity mismatch"):
        NodeRuntimeState(node_id="writer",logical_status=NodeLogicalStatus.SUCCEEDED,
            next_attempt=2,repair_count=0,accepted_attempt=1,accepted_handoff=h,attempts=(attempt(h),))

def test_reopen_clears_current_authority_preserving_history():
    h=handoff()
    state=NodeRuntimeState(node_id="writer",logical_status=NodeLogicalStatus.REMEDIATION_PENDING,
        next_attempt=2,repair_count=1,acceptance_epoch=2,attempts=(attempt(h),))
    assert state.accepted_handoff is None
    assert state.attempts[0].handoff==h


def test_state_snapshot_is_immutable_after_publication():
    h = handoff()
    state = NodeRuntimeState(node_id="writer", logical_status=NodeLogicalStatus.SUCCEEDED,
        next_attempt=2, repair_count=0, accepted_attempt=1, accepted_handoff=h,
        attempts=(attempt(h),))
    with pytest.raises(ValidationError, match="frozen"):
        state.accepted_attempt = None
    assert state.accepted_attempt == 1 and state.accepted_handoff == h

def test_acceptance_cannot_be_spoofed_with_same_handoff_fingerprint():
    h = handoff()
    spoof = h.model_copy(update={"self_report": "fabricated"})
    with pytest.raises(ValidationError, match="exactly match"):
        NodeRuntimeState(node_id="writer", logical_status=NodeLogicalStatus.SUCCEEDED,
            next_attempt=2, repair_count=0, accepted_attempt=1,
            accepted_handoff=spoof, attempts=(attempt(h),))

def test_attempt_handoff_must_match_execution_even_when_historical():
    with pytest.raises(ValidationError, match="identity mismatch"):
        attempt(handoff(execution_id="wrong"))

def test_succeeded_node_requires_current_accepted_authority():
    with pytest.raises(ValidationError, match="SUCCEEDED must publish"):
        NodeRuntimeState(node_id="writer", logical_status=NodeLogicalStatus.SUCCEEDED,
            next_attempt=2, repair_count=0, attempts=(attempt(handoff()),))

def test_next_attempt_cannot_reuse_historical_identity():
    with pytest.raises(ValidationError, match="next_attempt must exceed"):
        NodeRuntimeState(node_id="writer", logical_status=NodeLogicalStatus.REMEDIATION_PENDING,
            next_attempt=1, repair_count=1, attempts=(attempt(handoff()),))

def test_unaccepted_attempt_may_not_persist_accepted_handoff():
    with pytest.raises(ValidationError, match="only ACCEPTED"):
        NodeAttemptRecord(node_id="writer", attempt=1, kind=NodeAttemptKind.INITIAL,
            execution_id="exec", pre_workspace_revision=rev(), post_workspace_revision=rev(),
            status=NodeAttemptStatus.FAILED, failure_kind="TEST_FAILED", handoff=handoff())

def test_reopen_snapshot_replaces_current_authority_atomically():
    h = handoff()
    succeeded = NodeRuntimeState(node_id="writer", logical_status=NodeLogicalStatus.SUCCEEDED,
        next_attempt=2, repair_count=0, acceptance_epoch=1, accepted_attempt=1,
        accepted_handoff=h, attempts=(attempt(h),))
    reopened = NodeRuntimeState.model_validate({**succeeded.model_dump(),
        "logical_status": "remediation_pending", "accepted_attempt": None,
        "accepted_handoff": None, "acceptance_epoch": 2, "repair_count": 1})
    assert reopened.accepted_handoff is None
    assert succeeded.accepted_handoff == h
    assert reopened.attempts[0].handoff == h

def test_state_copy_update_cannot_bypass_atomic_authority_validation():
    h = handoff()
    original = NodeRuntimeState(node_id="writer", logical_status=NodeLogicalStatus.SUCCEEDED,
        next_attempt=2, repair_count=0, accepted_attempt=1, accepted_handoff=h,
        attempts=(attempt(h),))
    with pytest.raises(ValidationError, match="set or cleared together"):
        original.model_copy(update={"accepted_handoff": None})
    assert original.accepted_handoff == h
