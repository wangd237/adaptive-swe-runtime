"""5F-D CI permission regression: no paid model call from PR/push.

Pure text controls are deliberate: the core suite has no PyYAML dependency,
and the paid workflow remains manually triggered.
"""
from pathlib import Path


def test_live_smoke_workflow_manual_gate_and_env_scoped_secrets():
    yml=Path(".github/workflows/swe-real-model-smoke.yml").read_text(encoding="utf-8")
    assert "on:\n  workflow_dispatch:" in yml
    assert "  push:" not in yml
    assert "  pull_request:" not in yml
    assert 'Type RUN to authorize one real API-funded SWE smoke' in yml
    assert 'if [ "$ACK" != "RUN" ]; then' in yml
    assert "permissions:\n  contents: read" in yml
    assert "LLM_API_KEY: ${{ secrets.SWE_LLM_API_KEY }}" in yml
    assert "LLM_BASE_URL: ${{ secrets.SWE_LLM_BASE_URL }}" in yml
    assert "LLM_MODEL: ${{ secrets.SWE_LLM_MODEL }}" in yml
    assert "OPENAI_API_KEY:" not in yml
    assert "test_deerflow_live_swe_step5fd.py" in yml
    assert "RUNNER_TEMP" not in yml or "runner.temp" in yml


def test_core_pr_and_pinned_ci_have_no_live_model_secrets():
    for path in (".github/workflows/ci.yml", ".github/workflows/deerflow-pinned-native.yml"):
        source=Path(path).read_text(encoding="utf-8")
        assert "secrets.SWE_LLM_API_KEY" not in source
        assert "OPENAI_API_KEY:" not in source
        assert "test_deerflow_live_swe_step5fd.py" not in source
