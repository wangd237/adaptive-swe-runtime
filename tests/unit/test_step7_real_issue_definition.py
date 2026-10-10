"""Regression specification is independent of upstream production code."""
import ast
from pathlib import Path

from scripts.step7_real_issue import (
    CASE_ID,UPSTREAM_URL,UPSTREAM_COMMIT,UPSTREAM_ISSUE,CHECK,TASK,
    TEST_FILE,INDEPENDENT_REGRESSION,
)


def test_reproducible_real_upstream_issue_contract():
    assert CASE_ID=="boltons-500-monthly-daterange"
    assert UPSTREAM_URL=="https://github.com/mahmoud/boltons.git"
    assert UPSTREAM_ISSUE.endswith("/issues/500")
    assert len(UPSTREAM_COMMIT)==40
    assert all(c in "0123456789abcdef" for c in UPSTREAM_COMMIT)
    assert "tests.test_aswe_issue500" in CHECK
    assert TEST_FILE=="tests/test_aswe_issue500.py"
    assert "clamp" in TASK
    assert "last day" in TASK
    assert "do not" in TASK.lower()
    ast.parse(INDEPENDENT_REGRESSION)
    for behavior in ("leap_year", "nonleap_year", "negative_month",
                     "non_overflowing", "datetime_time"):
        assert behavior in INDEPENDENT_REGRESSION


def test_paid_upstream_issue_is_not_normal_ci():
    workflow=Path(".github/workflows/swe-real-issue-step7.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "  push:" not in workflow
    assert "  pull_request:" not in workflow
    assert "inputs.authorization == 'RUN'" in workflow
    assert "secrets.SWE_LLM_API_KEY" in workflow
    assert "secrets.SWE_LLM_MODEL" in workflow
    assert "pull_request:" not in workflow
    assert "aswe-step7-real-issue-result" in workflow
