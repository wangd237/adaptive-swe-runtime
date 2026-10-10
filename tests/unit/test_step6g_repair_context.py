"""Bounded real-failure RepairFeedback and unified DAG scheduler behavior."""
import pytest

from aswe.integrations.deerflow.repair_context import (
    feedback_from_test_output,repair_prompt)
from tests.unit.test_step6f_physical_dag_scheduler import compiled


def test_real_assertion_output_is_passed_to_repair_and_secrets_redacted():
    output = ("traceback\n" + "test_calc.py:12: AssertionError: 41 != 42\n"
              + "Authorization: Bearer-secret-value\n"
              + "test-key-secret-123\n")
    feedback=feedback_from_test_output(
        output,secrets=("test-key-secret-123",),max_chars=200)
    prompt=repair_prompt("Fix calc",feedback)
    assert "AssertionError: 41 != 42" in prompt
    assert "test-key-secret-123" not in prompt
    assert "Bearer-secret-value" not in prompt
    assert "test_failure_output" in prompt
    assert len(feedback.output_sha256)==64
    assert feedback.output_length==len(output)


def test_feedback_is_bounded_and_fingerprint_covers_complete_original():
    message="x"*10000+"\nAssertionError: expected 42"
    summary=feedback_from_test_output(message,max_chars=300)
    assert "AssertionError: expected 42" in summary.prompt_excerpt
    assert len(summary.prompt_excerpt)<=300
    assert summary.output_length==len(message)


def test_single_dag_scheduler_requires_real_failed_verifier(tmp_path):
    core=compiled(tmp_path)
    with pytest.raises(ValueError,match="DEV_REPAIR_REQUIRES_FAILED_VERIFICATION"):
        core.schedule_repair()
    assert core.dispatch("explorer")==1
    with pytest.raises(ValueError,match="DEV_DAG_NODE_NOT_READY"):
        core.dispatch("explorer")
    core.finish("explorer",verified=True)
    assert core.dispatch("coder")==1
    core.finish("coder",verified=True)
    assert core.dispatch("__aswe_verify")==1
    core.finish("__aswe_verify",verified=False)
    with pytest.raises(ValueError,match="DEV_DAG_REPAIR_NOT_SCHEDULED"):
        core.dispatch("__aswe_verify")
    assert core.schedule_repair()
    assert core.repairs_scheduled==1
    assert core.dispatch("coder")==2
    core.finish("coder",verified=True)
    assert core.dispatch("__aswe_verify")==2
    core.finish("__aswe_verify",verified=False)
    assert core.schedule_repair() is False
    assert core.repairs_scheduled==1


def test_passing_dag_cannot_schedule_repair(tmp_path):
    core=compiled(tmp_path,need_explorer=False)
    core.dispatch("coder")
    core.finish("coder",verified=True)
    core.dispatch("__aswe_verify")
    core.finish("__aswe_verify",verified=True)
    assert core.terminal
    with pytest.raises(ValueError,match="DEV_REPAIR_REQUIRES_FAILED_VERIFICATION"):
        core.schedule_repair()
    with pytest.raises(ValueError,match="DEV_DAG_TERMINAL"):
        core.dispatch("coder")
