"""Real paid Repair workflow is always manually authorized on main."""
from pathlib import Path


def test_paid_repair_workflow_never_runs_automatically():
    workflow=Path(".github/workflows/swe-real-repair-e2e.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "  push:" not in workflow
    assert "  pull_request:" not in workflow
    assert "inputs.authorization == 'RUN'" in workflow
    assert "secrets.SWE_LLM_API_KEY" in workflow
    assert "secrets.SWE_LLM_MODEL" in workflow
    assert "secrets.SWE_LLM_BASE_URL" in workflow
    assert "ASWE_LIVE_REPAIR_ONCE: '1'" in workflow


def test_real_repair_fixture_has_a_focused_and_independent_full_suite():
    from scripts.live_repair_acceptance import FOCUSED_CHECK, CHECK, INVENTORY_TEST
    assert "tests.test_inventory" in FOCUSED_CHECK
    assert ("discover","-s","tests") == CHECK[4:7]
    assert FOCUSED_CHECK != CHECK
    assert "Inventory" in INVENTORY_TEST
