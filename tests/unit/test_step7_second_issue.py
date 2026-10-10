"""Second public Issue uses exactly the same upstream revision and runtime."""
import ast
from pathlib import Path

from scripts.step7_real_issue import UPSTREAM_COMMIT
from scripts.step7_second_issue import (
    CASE_ID, ISSUE, TEST_CODE, TEST_PATH, CHECK, TASK,
)


def test_second_issue_is_distinct_real_upstream_reproduction():
    assert CASE_ID == "boltons-553-falsey-callable-key"
    assert ISSUE == "https://github.com/mahmoud/boltons/issues/553"
    assert len(UPSTREAM_COMMIT)==40
    assert TEST_PATH=="tests/test_aswe_issue553.py"
    assert "tests.test_aswe_issue553" in CHECK
    ast.parse(TEST_CODE)
    for test in ("test_false_bool_callable_matches_unique",
                 "test_false_bool_callable_groups",
                 "test_zero_length_callable_is_still_used",
                 "test_callable_converts_unhashable_values",
                 "test_standard_behavior_does_not_regress"):
        assert test in TEST_CODE
    assert "str_replace" not in TASK
    assert "Do not modify any test" in TASK


def test_paid_workflow_is_not_triggered_by_normal_push_or_pr():
    yml=Path(".github/workflows/swe-real-second-issue-step7.yml").read_text()
    assert "workflow_dispatch:" in yml
    assert "inputs.authorization == 'RUN'" in yml
    assert "pull_request:" not in yml
    # Temporary one-off branch trigger requires *both* exact branch and
    # the unique commit marker. It must be removed before merge to main.
    assert "coding/step7-second-issue-comparison" in yml
    assert "[run-live-step7-second]" in yml
    assert "secrets.SWE_LLM_API_KEY" in yml
