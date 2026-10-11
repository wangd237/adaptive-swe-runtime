"""Outer physical TaskDAG must use Scheduler handoff, not model result."""
from types import SimpleNamespace

import pytest

from aswe.integrations.deerflow.dev_workflow import _accepted_coder_handoff


def fake(**kw):
    data=dict(
        accepted_handoff_fingerprint="1"*64,
        scheduler_node_status="succeeded",
        acceptance_profile="practical",
        native_status="completed",
        native_stop_reason=None,
    )
    data.update(kw)
    return SimpleNamespace(**data)


def test_practical_coder_handoff_unblocks_independent_tester():
    assert _accepted_coder_handoff(fake())


@pytest.mark.parametrize("overrides", [
    {"accepted_handoff_fingerprint": None},
    {"scheduler_node_status": "failed"},
    {"scheduler_node_status": "cancelled"},
    {"acceptance_profile": "strict"},
    {"native_status": "failed"},
    {"native_stop_reason": "turn_capped"},
])
def test_native_completed_alone_cannot_unlock_tester(overrides):
    assert not _accepted_coder_handoff(fake(**overrides))


def test_no_legacy_handoff_fields_fails_closed():
    assert not _accepted_coder_handoff(SimpleNamespace(
        native_status="completed", verification_status="passed"))
