"""Host-owned real Issue #565 Repair acceptance contract and paid-run gate."""
import ast
from pathlib import Path

from scripts.step7c_staged_real_repair_565 import (
    CASE_ID, ISSUE, TEST_CODE, TEST_PATH, CHECK, TASK,
)

def test_genuine_issue_and_behavioral_suite():
    assert CASE_ID=="boltons-565-multireplace-compiled-regex-flags"
    assert ISSUE=="https://github.com/mahmoud/boltons/issues/565"
    assert TEST_PATH=="tests/test_aswe_issue565.py"
    assert "tests.test_aswe_issue565" in CHECK
    assert "do not edit tests" in TASK.lower()
    ast.parse(TEST_CODE)
    for name in (
        "test_ignorecase_precompiled", "test_flags_are_scoped_per_branch",
        "test_multiline_precompiled", "test_dotall_precompiled",
        "test_verbose_precompiled", "test_ascii_precompiled_does_not_leak",
        "test_inline_leading_flags", "test_constructor_global_flags_still_work",
    ):
        assert name in TEST_CODE

def test_paid_repair_run_requires_explicit_manual_authorization():
    yml=Path(".github/workflows/swe-staged-repair565-step7c.yml").read_text()
    assert "workflow_dispatch:" in yml
    assert "inputs.authorization == 'RUN'" in yml
    assert "  push:" not in yml
    assert "pull_request:" not in yml
    assert "secrets.SWE_LLM_API_KEY" in yml
    assert "scripts/step7c_staged_real_repair_565.py" in yml
