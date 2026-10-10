"""Step 7 comparison: a DIFFERENT real boltons issue, unchanged SWE Runtime.

The upstream repo and commit, LLM settings, real Docker, task orchestration
and native DeerFlow are exactly the same as Step7 #500. Only the public Issue
and host-owned behavioral regression tests differ.

No model mocks, preloaded patches, synthetic terminal states or alterations
to the Runtime's read-before-write semantics.
"""
from __future__ import annotations

import asyncio
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
from scripts.live_adaptive_acceptance import (
    AcceptanceFailed, python_image_digest, require,
)
from scripts.step7_real_issue import UPSTREAM_URL, UPSTREAM_COMMIT, run_git

ISSUE="https://github.com/mahmoud/boltons/issues/553"
CASE_ID="boltons-553-falsey-callable-key"
CHECK=("python","-B","-m","unittest","tests.test_aswe_issue553","-q")
TEST_PATH="tests/test_aswe_issue553.py"
TASK=(
    "Resolve the genuine public upstream issue boltons #553 in the "
    "checked-out repository: redundant() accepts a callable key during "
    "argument validation, but when the callable has a false boolean value "
    "(via __bool__ or __len__), redundant ignores it, so duplicates are "
    "missed; inputs that depend on the key to be hashable can also raise "
    "TypeError. Behavior should agree with the documented complement of "
    "unique(). Explore the unfamiliar repository, diagnose root cause, "
    "fix the production implementation and verify the independent regression. "
    "Preserve the existing behavior for None and truthy callable keys. "
    "Do not modify any test or project configuration."
)
TEST_CODE='''"""External Issue #553 independent test, owned by the host harness."""
import unittest

from boltons.iterutils import redundant, unique


class FalseBoolKey:
    def __bool__(self):
        return False

    def __call__(self, obj):
        return str(obj).lower()


class ZeroLengthKey:
    def __len__(self):
        return 0

    def __call__(self, obj):
        return str(obj).lower()


class DictKey:
    def __bool__(self):
        return False

    def __call__(self, value):
        return value["id"]


class Issue553(unittest.TestCase):
    def test_false_bool_callable_matches_unique(self):
        values = ["a", "A", "b"]
        self.assertEqual(unique(values, key=FalseBoolKey()), ["a", "b"])
        self.assertEqual(redundant(values, key=FalseBoolKey()), ["A"])

    def test_false_bool_callable_groups(self):
        self.assertEqual(
            redundant(["a", "A", "a", "b"], key=FalseBoolKey(), groups=True),
            [["a", "A", "a"]])

    def test_zero_length_callable_is_still_used(self):
        self.assertEqual(
            redundant(["a", "A", "b"], key=ZeroLengthKey()), ["A"])

    def test_callable_converts_unhashable_values(self):
        values = [{"id": 1, "name": "a"}, {"id": 1, "name": "b"}]
        self.assertEqual(redundant(values, key=DictKey()), [values[1]])

    def test_standard_behavior_does_not_regress(self):
        self.assertEqual(redundant([1, 2, 1, 3, 2]), [1, 2])
        self.assertEqual(
            redundant(["hi", "HI"], key=str.lower), ["HI"])
'''

def prepare(root: Path) -> tuple[Path,str]:
    repo=root/"upstream"
    subprocess.run(["git","clone","--quiet",UPSTREAM_URL,str(repo)],
                   check=True,capture_output=True,timeout=120)
    run_git(repo,"checkout","--detach",UPSTREAM_COMMIT)
    original_sha=run_git(repo,"rev-parse","HEAD")
    require(original_sha==UPSTREAM_COMMIT,"UPSTREAM_SHA_MISMATCH")
    original_source=(repo/"boltons/iterutils.py").read_bytes()
    (repo/TEST_PATH).write_text(TEST_CODE,encoding="utf-8")
    run_git(repo,"add","--",TEST_PATH)
    run_git(repo,"-c","user.name=ASWE Acceptance",
            "-c","user.email=aswe-acceptance@example.invalid",
            "commit","-m","Host-owned Issue 553 acceptance tests")
    require(original_source==(repo/"boltons/iterutils.py").read_bytes(),
            "SOURCE_MODIFIED_BEFORE_MODEL")
    return repo,original_sha

async def execute(summary: dict) -> None:
    require(os.environ.get("GITHUB_ACTIONS")=="true" and
            os.environ.get("ASWE_LIVE_SMOKE")=="1" and
            os.environ.get("ASWE_STEP7_SECOND_ONCE")=="1",
            "STEP7_SECOND_NOT_AUTHORIZED")
    LiveModelSettings.from_environment()
    image=python_image_digest()
    with tempfile.TemporaryDirectory(prefix="aswe-step7-second-") as td:
        root=Path(td)
        repo,sha=prepare(root)
        summary["upstream_commit"]=sha
        baseline=await DockerCommandBackend(
            workspace_root=repo,image=image).run(
            " ".join(CHECK),timeout=45,max_output=1800)
        require(baseline.exit_code not in (None,0) and not baseline.timed_out,
                "ISSUE_553_BASELINE_NOT_FAILING")
        summary["baseline_regression_failed"]=True
        home=root/"runtime"
        try:
            run=await asyncio.wait_for(execute_dev_workflow(
                repository=repo,task=TASK,runtime_dir=home,
                check_argv=CHECK,image=image,adaptive=True,
                planner="llm",explorer_mode="llm",physical_dag=True,
                max_repairs=1,
            ),timeout=1100)
        except Exception:
            summary["last_stage_event_types"]=[
                json.loads(line)["event_type"]
                for file in (home/"tasks").glob("workflow-*/events.jsonl")
                for line in file.read_text(encoding="utf-8").splitlines() if line
            ][-16:]
            raise

        events=[json.loads(line) for line in run.trace_path.read_text(
            encoding="utf-8").splitlines() if line]
        ev=Counter(e["event_type"] for e in events)
        dispatch=[e["node_id"] for e in events
                  if e["event_type"]=="dag.scheduler.dispatch"]
        checker=[e["payload"]["status"] for e in events
                 if e["event_type"]=="dag.verification.executed"]
        roles=next((e["payload"]["roles"] for e in events
                    if e["event_type"]=="team.selected"),[])
        failed_calls=[e for e in events if e["event_type"]=="tool.call.finished"
                      and e["payload"].get("status") in ("failed","denied")]
        child_reports=[json.loads(p.read_text()) for p in run.round_reports]
        final=run.round_reports[-1].parent/"workspace"
        altered=((repo/"boltons/iterutils.py").read_bytes() !=
                 (final/"boltons/iterutils.py").read_bytes())
        unchanged=((repo/TEST_PATH).read_bytes()==
                   (final/TEST_PATH).read_bytes())
        # Diagnostic-only Docker execution is permitted even on native
        # failed tasks; it is NOT substituted for strict DAG verification.
        diag=await DockerCommandBackend(
            workspace_root=final,image=image).run(
            " ".join(CHECK),timeout=45,max_output=1700)
        diag_pass=diag.exit_code==0 and not diag.timed_out
        summary.update(
            roles=roles,dispatch_order=dispatch,
            dagger_compiled=bool(any(e["event_type"]=="task_dag.compiled"
                                     for e in events)),
            native_model_turn_events=ev["model.turn.finished"],
            tool_event_count=ev["tool.call.finished"],
            tool_failed_count=len(failed_calls),
            failed_tool_names=sorted(set(e["payload"].get("tool","unknown")
                                         for e in failed_calls)),
            # Record stable category only; never serialize model/tool inputs.
            failed_tool_categories=sorted(set(e["payload"].get("failure_code","unspecified")
                                              for e in failed_calls)),
            independent_tester_statuses=checker,
            child_native_statuses=[x.get("native_status") for x in child_reports],
            repair_scheduled=ev["workflow.repair.scheduled"],
            production_changed=altered,
            external_test_unchanged=unchanged,
            diagnostic_code_test_passed=diag_pass,
            final_workflow_verdict=run.verification_status,
        )
        require("coder" in dispatch,"CODER_NOT_SCHEDULED")
        require(run.verification_status=="passed" and checker[-1:] == ["passed"],
                "ISSUE_553_NOT_SOLVED")
        require(altered and unchanged,"SOLUTION_INTEGRITY_NOT_PROVEN")
        require(ev["tool.call.finished"]>=2,"NO_REAL_NATIVE_TOOL_EXECUTION")

def persist(summary: dict) -> None:
    path=Path(os.environ["ASWE_STEP7_SECOND_REPORT_PATH"]).resolve()
    runner=Path(os.environ["RUNNER_TEMP"]).resolve()
    require(path.is_relative_to(runner),"REPORT_LOCATION_FORBIDDEN")
    path.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",
                    encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:
            f.write("## Real upstream boltons Issue #553 comparison\n\n"
                    f"Outcome: `{summary.get('outcome','unknown')}`\n\n"
                    f"Failure: `{summary.get('failure_code','none')}`\n\n"
                    f"Tool failures: `{summary.get('tool_failed_count','not reported')}`\n\n"
                    "Unmocked model. Same pinned upstream SHA as Issue #500.\n")

def main() -> int:
    data={"case_id":CASE_ID,"upstream_issue":ISSUE,
          "model_mocked":False,"outcome":"not_started"}
    try:
        asyncio.run(execute(data))
        data["outcome"]="passed"
        code=0
    except Exception as exc:
        data["outcome"]="failed"
        data["failure_code"]=(exc.args[0] if isinstance(exc,AcceptanceFailed)
                              else type(exc).__name__)
        code=1
    persist(data)
    print("STEP7_SECOND_ISSUE_RESULT="+data["outcome"])
    print("STEP7_SECOND_ISSUE_FAILURE="+str(data.get("failure_code","none")))
    return code

if __name__=="__main__":
    sys.exit(main())
