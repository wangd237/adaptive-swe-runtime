"""The paid Step7B recovery benchmark is gated and its fixture is auditable."""
import ast
from pathlib import Path


def test_recovery_script_and_paid_workflow_have_guarded_real_model_contract():
    source = Path("scripts/step7b_live_recovery.py").read_text()
    ast.parse(source)
    assert "InjectFirstWriteThenRealLLM" in source
    assert "SWE_READ_BEFORE_WRITE_REQUIRED" in source
    assert "model_factory=model_factory" in source
    assert "model_mocked" not in source or "subsequent_model_mocked" in source
    assert "genuine_llm_calls" in source
    assert "recoverable_sequence" in source
    assert "native_stop_reason" in source
    workflow = Path(".github/workflows/swe-real-recovery-step7b.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "inputs.authorization == 'RUN'" in workflow
    assert "pull_request:" not in workflow
    assert "  push:" not in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "secrets.SWE_LLM_API_KEY" in workflow
    assert "ASWE_STEP7B_RECOVERY_ONCE: '1'" in workflow
