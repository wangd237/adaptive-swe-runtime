"""Typed revision-scoped feedback; no model-authored remediation authority."""
import pytest
from pydantic import ValidationError

from aswe.runtime.feedback import (
    RepairFeedback, RepairTriggerKind, build_verification_repair_feedback,
)
from aswe.runtime.repair import VerificationResult
from tests.unit.test_scheduler_repair import fixture


@pytest.mark.asyncio
async def test_feedback_binds_source_attempt_revision_and_receipts(tmp_path):
    core, _, store, vref, attribution, aref = await fixture(tmp_path)
    result = VerificationResult.model_validate(store.get(vref))
    fb = build_verification_repair_feedback(
        source=result, source_ref=vref, attribution=attribution, attribution_ref=aref
    )
    assert fb.trigger_kind is RepairTriggerKind.DOWNSTREAM_VERIFICATION
    assert fb.target_write_node_id == "writer" and fb.target_write_attempt == 1
    assert fb.verification_result == vref and fb.repair_attribution == aref
    assert fb.receipt_refs and fb.failed_check_ids == ("unit-tests",)
    assert fb.observed_workspace_revision == result.observed_workspace_revision
    assert "unit-tests" in fb.bounded_projection()
    with pytest.raises(ValidationError, match="fingerprint"):
        fb.model_copy(update={"target_write_node_id": "forged"})


@pytest.mark.asyncio
async def test_scheduler_reopen_materializes_typed_feedback_until_dispatch_commit(tmp_path):
    core, _, store, ref, _, attribution_ref = await fixture(tmp_path)
    await core.reopen_writer_from_verification(
        verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store
    )
    feedback = core._typed_repair_feedback["writer"]
    assert isinstance(feedback, RepairFeedback)
    assert feedback.receipt_refs
    assert feedback.verifier_report is None
