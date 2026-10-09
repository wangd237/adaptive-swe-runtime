"""Stale RepairFeedback never silently reuses old proof (R23 fallback)."""
import pytest

from aswe.runtime.dispatch import TaskDispatchGateState
from aswe.runtime.state import NodeLogicalStatus
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario
from tests.unit.test_scheduler_repair import fixture


@pytest.mark.asyncio
async def test_r23_stale_repair_feedback_without_refresh_fails_closed(tmp_path):
    core, manager, store, ref, _, attribution_ref = await fixture(tmp_path)
    await core.reopen_writer_from_verification(
        verification_ref=ref, attribution_ref=attribution_ref, evidence_store=store,
    )
    ticket = await core.claim("writer")

    class RevisionAdvancingBackend(FakeExecutionBackend):
        async def prepare_node(self, node):
            preparation = await super().prepare_node(node)
            core.revision = core.revision.model_copy(
                update={"generation": core.revision.generation + 1}
            )
            return preparation

    backend = RevisionAdvancingBackend([FakeExecutionScenario()])
    assert await core.run_claim(ticket, backend) is None
    assert core.gate.state is TaskDispatchGateState.CLOSED
    assert core.failed and manager.dispatch_closed
    assert "REPAIR_FEEDBACK_STALE" in core.failure_kinds
    assert core.states["writer"].logical_status is NodeLogicalStatus.BLOCKED
    assert len(core.states["writer"].attempts) == 1
    assert backend.records == []
