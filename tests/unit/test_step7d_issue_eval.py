"""Step 7D Issue survey must not use fake providers or mutable tests."""
import ast
from pathlib import Path
from scripts.step7d_real_issue_eval import CASES

def test_preregistered_issue_suite_and_host_owned_tests():
    assert set(CASES)=={"551","524"}
    for key,c in CASES.items():
        assert c["issue"].endswith("/issues/"+key)
        assert c["source"].startswith("boltons/")
        assert c["module"].endswith("issue"+key)
        assert len(c["tests"])>500
        ast.parse(c["tests"])
        assert "do not" in c["task"].lower()
    assert "test_singleton_key_exceptions_not_suppressed" in CASES["551"]["tests"]
    assert "test_rounding_promotes_kilobytes_to_megabytes" in CASES["524"]["tests"]

def test_paid_matrix_requires_manual_run_and_never_executes_in_normal_ci():
    yml=Path(".github/workflows/swe-step7d-manual.yml").read_text()
    assert "workflow_dispatch:" in yml
    assert "inputs.authorization == 'RUN'" in yml
    assert "  push:" not in yml
    assert "  pull_request:" not in yml
    assert "secrets.SWE_LLM_API_KEY" in yml
    assert "fail-fast: false" in yml
    assert "['551', '524']" in yml
