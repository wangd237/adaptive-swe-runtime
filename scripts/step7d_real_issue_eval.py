"""Step 7D: small, preregistered, non-mocked open-source Issue survey.

Every case uses frozen boltons source, external host-owned tests, real
Adaptive Planning -> Coder -> Practical Handoff -> independent Tester.
A diagnostic verification is never substituted for formal DAG acceptance.
No reference patch, mocked provider, scripted repair or test modification.
"""
from __future__ import annotations

import asyncio
import hashlib
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend
from aswe.integrations.deerflow.dev_workflow import execute_dev_workflow
from aswe.integrations.deerflow.live_smoke_config import LiveModelSettings
from aswe.trace.reliability import summarize_execution_trace
from scripts.live_adaptive_acceptance import (
    AcceptanceFailed, python_image_digest, require,
)
from scripts.step7_real_issue import UPSTREAM_URL, UPSTREAM_COMMIT, run_git
from scripts.step7c_staged_real_repair_565 import TEST_CODE as ISSUE565_TESTS


ISSUE551_TESTS = '''"""Host-owned independent tests: boltons Issue #551."""
import unittest
from collections import Counter
from boltons.iterutils import untyped_sorted

class Issue551(unittest.TestCase):
    def test_key_evaluated_once_per_element(self):
        seen=[]
        def record(value):
            seen.append(value)
            return value
        self.assertEqual(untyped_sorted([3,1,2],key=record),[1,2,3])
        self.assertEqual(Counter(seen),Counter([3,1,2]))
        self.assertEqual(len(seen),3)

    def test_singleton_key_exceptions_not_suppressed(self):
        def invalid(value):
            raise ZeroDivisionError("key deliberately fails")
        with self.assertRaises(ZeroDivisionError):
            untyped_sorted([1],key=invalid)

    def test_singleton_nonfailing_key_called_once(self):
        seen=[]
        self.assertEqual(untyped_sorted([7],key=lambda v:(seen.append(v),v)[1]),[7])
        self.assertEqual(seen,[7])

    def test_empty_input_does_not_call_key(self):
        def invalid(value):
            raise AssertionError("should not execute")
        self.assertEqual(untyped_sorted([],key=invalid),[])

    def test_reverse_still_evaluates_once(self):
        calls=[]
        self.assertEqual(untyped_sorted(
            [3,1,2],key=lambda x:(calls.append(x),x)[1],reverse=True
        ),[3,2,1])
        self.assertEqual(Counter(calls),Counter([3,1,2]))

    def test_mixed_type_order_and_stability(self):
        self.assertEqual(untyped_sorted(["b",2,1,"a"]),[1,2,"a","b"])
'''

ISSUE524_TESTS = '''"""Host-owned independent tests: boltons Issue #524."""
import unittest
from boltons.strutils import bytes2human

class Issue524(unittest.TestCase):
    def test_rounding_promotes_kilobytes_to_megabytes(self):
        self.assertEqual(bytes2human(1048575),"1M")

    def test_rounding_promotes_bytes_to_kilobytes(self):
        self.assertEqual(bytes2human(1023.5),"1K")

    def test_decimal_precision_also_promotes(self):
        self.assertEqual(bytes2human(1023.99,1),"1.0K")
        self.assertEqual(bytes2human(1048575,1),"1.0M")

    def test_negative_boundary_is_symmetric(self):
        self.assertEqual(bytes2human(-1048575),"-1M")

    def test_exact_powers_and_nearby_values_unchanged(self):
        self.assertEqual(bytes2human(1023),"1023B")
        self.assertEqual(bytes2human(1024),"1K")
        self.assertEqual(bytes2human(1024**2),"1M")

    def test_zero_and_precision_regression(self):
        self.assertEqual(bytes2human(0,2),"0.00B")
        self.assertEqual(bytes2human(1536,1),"1.5K")
'''

CASES = {
    "565": {
        "issue": "https://github.com/mahmoud/boltons/issues/565",
        "source": "boltons/strutils.py",
        "test_path": "tests/test_aswe_issue565.py",
        "module": "tests.test_aswe_issue565",
        "tests": ISSUE565_TESTS,
        "task": (
            "Fix the original genuine boltons issue #565 naturally. "
            "MultiReplace loses the distinct compiled flags of re.Pattern "
            "inputs: IGNORECASE, MULTILINE, DOTALL, VERBOSE and ASCII. "
            "Keep each precompiled regex's flags scoped to its own branch, "
            "without leaking to adjacent branches; preserve leading inline "
            "flags, literal string and constructor flags behavior. "
            "Explore the actual pinned implementation, make a general "
            "production-only fix, run relevant tests and finish normally "
            "when the issue is addressed. The host will independently test "
            "all behavior. Do not modify tests, project metadata or .git."
        ),
    },
    "551": {
        "issue": "https://github.com/mahmoud/boltons/issues/551",
        "source": "boltons/iterutils.py",
        "test_path": "tests/test_aswe_issue551.py",
        "module": "tests.test_aswe_issue551",
        "tests": ISSUE551_TESTS,
        "task": (
            "Fix the genuine public boltons issue #551 in this pinned checkout. "
            "untyped_sorted calls a key function repeatedly during comparisons, "
            "and never invokes a key on singleton input, suppressing its error. "
            "Follow sorted()'s once-per-element key evaluation while preserving "
            "heterogeneous type ordering, stability and reverse behavior. "
            "Explore the implementation, modify production code only, test "
            "carefully, and do not change any tests or project metadata."
        ),
    },
    "524": {
        "issue": "https://github.com/mahmoud/boltons/issues/524",
        "source": "boltons/strutils.py",
        "test_path": "tests/test_aswe_issue524.py",
        "module": "tests.test_aswe_issue524",
        "tests": ISSUE524_TESTS,
        "task": (
            "Fix genuine boltons issue #524 in the pinned upstream checkout. "
            "bytes2human chooses its unit before decimal rounding and can "
            "return 1024K instead of 1M or 1024B instead of 1K. Promote "
            "rounded boundary values to the next unit with correct ndigits, "
            "preserving zero, exact unit powers, negative values and ordinary "
            "nonboundary formatting. Inspect code, make a small general "
            "production patch, run tests, and do not modify tests or metadata."
        ),
    },
}


def seed(root: Path, case: dict) -> Path:
    repository = root / "upstream"
    subprocess.run(
        ["git","clone","--quiet",UPSTREAM_URL,str(repository)],
        check=True,capture_output=True,timeout=120,
    )
    run_git(repository,"checkout","--detach",UPSTREAM_COMMIT)
    require(run_git(repository,"rev-parse","HEAD")==UPSTREAM_COMMIT,
            "EVAL_UPSTREAM_COMMIT_DRIFT")
    original=(repository/case["source"]).read_bytes()
    (repository/case["test_path"]).write_text(case["tests"],encoding="utf-8")
    run_git(repository,"add","--",case["test_path"])
    run_git(repository,"-c","user.name=ASWE Evaluation",
            "-c","user.email=aswe-evaluation@example.invalid",
            "commit","-m","Host-owned independent Issue regression")
    require(original==(repository/case["source"]).read_bytes(),
            "EVAL_SOURCE_MODIFIED_BEFORE_AGENT")
    return repository


def _redacted_failure_observations(home: Path) -> dict:
    """Best-effort safe post-failure metrics, never raw LLM/tool text."""
    tasks=home / "tasks"
    summaries=[]
    for trace in sorted(tasks.glob("task-*/events.jsonl")):
        try:
            records=[json.loads(line) for line in trace.read_text(
                encoding="utf-8").splitlines() if line.strip()]
            summaries.append(summarize_execution_trace(records))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    result={"failed_child_count":len(summaries)}
    if summaries:
        last=summaries[-1]
        for key in (
            "model_turns", "tool_calls", "tool_name_counts",
            "bash_category_counts", "repeated_exact_argument_calls",
            "repeated_bash_argument_calls", "tool_duration_total_ms",
            "tool_duration_observed_calls", "tool_duration_max_ms",
            "token_usage_reported", "native_stop_reason",
            "mvp_delivery_status", "peak_input_tokens_per_turn",
        ):
            if key in last:
                result[key]=last[key]
    return result


async def execute(summary: dict) -> None:
    require(
        os.environ.get("GITHUB_ACTIONS")=="true"
        and os.environ.get("ASWE_LIVE_SMOKE")=="1"
        and os.environ.get("ASWE_STEP7D_EVAL_ONCE")=="1",
        "EVAL_LIVE_NOT_AUTHORIZED",
    )
    case=CASES[os.environ["ASWE_EVAL_CASE"]]
    LiveModelSettings.from_environment()
    # Commit/model/test fingerprints support reproducibility without logging
    # secret-bearing provider arguments or model request/response bodies.
    summary["runtime_sha"]=subprocess.check_output(
        ["git","rev-parse","HEAD"],text=True,timeout=5).strip()
    summary["model_config_sha256"]=hashlib.sha256(
        os.environ.get("LLM_MODEL", "").encode("utf-8")
    ).hexdigest()
    summary["host_test_sha256"]=hashlib.sha256(
        case["tests"].encode("utf-8")
    ).hexdigest()
    image=python_image_digest()
    summary["pinned_docker_image"]=image
    cmd=("python","-B","-m","unittest",case["module"],"-q")
    with tempfile.TemporaryDirectory(prefix="aswe-step7d-eval-") as td:
        root=Path(td)
        repository=seed(root,case)
        original_code=(repository/case["source"]).read_bytes()
        initial=await DockerCommandBackend(
            workspace_root=repository,image=image,
        ).run(" ".join(cmd),timeout=45,max_output=1600)
        require(initial.exit_code not in (None,0) and not initial.timed_out,
                "EVAL_BASELINE_NOT_FAILING")
        summary["baseline_failed"]=True
        home=root/"runtime"
        try:
            outcome=await asyncio.wait_for(execute_dev_workflow(
                repository=repository,
                task=case["task"],runtime_dir=home,
                check_argv=cmd,image=image,
                adaptive=True,planner="llm",explorer_mode="llm",
                physical_dag=True,max_repairs=1,
            ),timeout=1100)
        except Exception:
            summary["failure_before_workflow_return"]=True
            summary["partial_child_observation"]=_redacted_failure_observations(home)
            summary["tail_host_event_types"]=[
                json.loads(line)["event_type"]
                for f in (home/"tasks").glob("workflow-*/events.jsonl")
                for line in f.read_text().splitlines() if line
            ][-15:]
            raise
        events=[json.loads(line) for line in outcome.trace_path.read_text().splitlines()
                if line]
        reports=[json.loads(p.read_text()) for p in outcome.round_reports]
        target=outcome.round_reports[-1].parent/"workspace"
        status=[e["payload"].get("status") for e in events
                if e["event_type"]=="dag.verification.executed"]
        handoff=[e["payload"].get("accepted") for e in events
                 if e["event_type"]=="dag.coder.handoff"]
        dispatch=[e.get("node_id") for e in events
                  if e["event_type"]=="dag.scheduler.dispatch"]
        counts=Counter(e["event_type"] for e in events)
        summary.update(
            workflow_verdict=outcome.verification_status,
            model_turns=counts["model.turn.finished"],
            tool_calls=counts["tool.call.finished"],
            repair_rounds=counts["workflow.repair.scheduled"],
            dag_tester_results=status,
            dispatch_order=dispatch,
            coder_rounds=len(reports),
            native_stops=[r.get("native_stop_reason") for r in reports],
            child_scheduler_states=[r.get("scheduler_node_status") for r in reports],
            accepted_coder_handoffs=handoff,
            handoff_fingerprints=[r.get("accepted_handoff_fingerprint") for r in reports],
            source_changed=((target/case["source"]).read_bytes()!=original_code),
            host_tests_unchanged=(
                (target/case["test_path"]).read_text(encoding="utf-8")
                ==case["tests"]),
            upstream_clean=not bool(run_git(repository,"status","--porcelain")),
            reliability=summarize_execution_trace(events,round_reports=reports),
        )
        if reports:
            summary["last_coder_state"]=reports[-1].get("scheduler_node_status")
            summary["last_native_status"]=reports[-1].get("native_status")
        require(
            summary["source_changed"]
            and summary["host_tests_unchanged"] and summary["upstream_clean"],
            "EVAL_PATCH_INTEGRITY_FAILED",
        )
        require(
            reports and all(
                r.get("acceptance_profile")=="practical"
                and r.get("scheduler_node_status")=="succeeded"
                and isinstance(r.get("accepted_handoff_fingerprint"),str)
                and len(r["accepted_handoff_fingerprint"])==64
                and r.get("native_stop_reason") is None
                for r in reports
            ) and len(handoff)==len(reports) and all(handoff),
            "EVAL_CODER_HANDOFF_NOT_ACCEPTED",
        )
        require(
            status[-1:] == ["passed"]
            and outcome.verification_status=="passed",
            "EVAL_INDEPENDENT_TESTER_NOT_PASSED",
        )


def save(summary: dict) -> None:
    output=Path(os.environ["ASWE_STEP7D_EVAL_REPORT_PATH"]).resolve()
    require(output.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve()),
            "EVAL_REPORT_PATH_FORBIDDEN")
    output.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a") as f:
            f.write(
                f"## Step 7D boltons #{summary['case_id']}\n\n"
                f"Outcome: {summary['outcome']}\n\n"
                f"Code: {summary.get('failure_code','none')}\n"
            )


def main() -> int:
    case_id=os.environ.get("ASWE_EVAL_CASE","unconfigured")
    summary={
        "case_id":case_id,
        "issue":CASES.get(case_id,{}).get("issue"),
        "upstream_commit":UPSTREAM_COMMIT,
        "model_mocked":False,
        "staged_specification":False,
        "outcome":"not_started",
    }
    try:
        asyncio.run(execute(summary))
        summary["outcome"]="passed"
        rc=0
    except Exception as exc:
        summary["outcome"]="failed"
        summary["failure_code"]=(
            exc.args[0] if isinstance(exc,AcceptanceFailed)
            else type(exc).__name__
        )
        rc=1
    save(summary)
    print(f"STEP7D_CASE_{case_id}_RESULT={summary['outcome']}")
    print(f"STEP7D_CASE_{case_id}_FAILURE={summary.get('failure_code','none')}")
    return rc


if __name__=="__main__":
    sys.exit(main())
