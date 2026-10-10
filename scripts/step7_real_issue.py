"""Step 7A: real upstream open-source Issue E2E, pinned and reproducible.

Clones the ACTUAL upstream boltons repository at a fixed immutable commit.
Only an independent reproduction/acceptance test is added before the agent
starts. The application implementation is never pre-modified or scripted.
Real LLM Planner, Explorer and DeerFlow Coder run against the unfamiliar repo.
This is a paid manual (or explicit one-shot) GitHub Actions job only.
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

UPSTREAM_URL="https://github.com/mahmoud/boltons.git"
UPSTREAM_COMMIT="4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d"
UPSTREAM_ISSUE="https://github.com/mahmoud/boltons/issues/500"
CASE_ID="boltons-500-monthly-daterange"
TEST_FILE="tests/test_aswe_issue500.py"
CHECK=("python","-B","-m","unittest","tests.test_aswe_issue500","-q")

# Issue-specific acceptance choice: clamp overflowing dates and preserve the
# clamped day when subsequent months are long enough ("drift"), matching the
# issue reporter's preferred Option 1. The maintainer has NOT approved it.
TASK=(
    "Please fix the following real open-source issue in the checked-out "
    "repository. boltons issue #500: When daterange() advances in months "
    "from a late-month date such as January 31st, the next month may not "
    "contain that day and iteration crashes with 'day is out of range "
    "for month'. Reproduction: list(daterange(date(2020,1,31), "
    "date(2020,6,30),step=(0,1,0),inclusive=True)). For this acceptance, "
    "implement the issue author's suggested option 1: clamp an invalid "
    "day to the target month's last day and keep that clamped day for "
    "subsequent increments (do not snap back to original month end). "
    "Retain normal dates, non-month steps and negative month increments. "
    "Explore the actual upstream repository, make the smallest production "
    "code change, run the repository-local regression test, and do not "
    "alter tests, project metadata or check configuration."
)

INDEPENDENT_REGRESSION='''"""Independent boltons #500 behavioral check; host-owned, do not edit."""
import unittest
from datetime import date, datetime

from boltons.timeutils import daterange


class TestRealUpstreamIssue500(unittest.TestCase):
    def test_leap_year_january_31_clamps_and_then_drifts(self):
        self.assertEqual(
            list(daterange(date(2020, 1, 31), date(2020, 6, 30),
                           step=(0, 1, 0), inclusive=True)),
            [date(2020, 1, 31), date(2020, 2, 29),
             date(2020, 3, 29), date(2020, 4, 29),
             date(2020, 5, 29), date(2020, 6, 29)])

    def test_nonleap_year_february_clamps_to_28(self):
        self.assertEqual(
            list(daterange(date(2021, 1, 31), date(2021, 4, 30),
                           step=(0, 1, 0), inclusive=True)),
            [date(2021, 1, 31), date(2021, 2, 28),
             date(2021, 3, 28), date(2021, 4, 28)])

    def test_negative_month_increment(self):
        self.assertEqual(
            list(daterange(date(2020, 3, 31), date(2020, 1, 1),
                           step=(0, -1, 0), inclusive=True)),
            [date(2020, 3, 31), date(2020, 2, 29),
             date(2020, 1, 29)])

    def test_non_overflowing_months_are_unchanged(self):
        self.assertEqual(
            list(daterange(date(2020, 1, 15), date(2020, 4, 15),
                           step=(0, 1, 0), inclusive=True)),
            [date(2020, 1, 15), date(2020, 2, 15),
             date(2020, 3, 15), date(2020, 4, 15)])

    def test_datetime_time_component_survives(self):
        self.assertEqual(
            list(daterange(datetime(2020, 1, 31, 13, 15),
                           datetime(2020, 3, 31, 13, 15),
                           step=(0, 1, 0), inclusive=True)),
            [datetime(2020, 1, 31, 13, 15),
             datetime(2020, 2, 29, 13, 15),
             datetime(2020, 3, 29, 13, 15)])
'''

def run_git(repo: Path, *arguments: str) -> str:
    p=subprocess.run(
        ["git","-C",str(repo),*arguments],check=True,
        capture_output=True,text=True,timeout=90)
    return p.stdout.strip()


def prepare_real_repository(root: Path) -> tuple[Path,str]:
    repo=root/"upstream"
    subprocess.run(["git","clone","--quiet",UPSTREAM_URL,str(repo)],
                   check=True,capture_output=True,timeout=120)
    run_git(repo,"checkout","--detach",UPSTREAM_COMMIT)
    sha=run_git(repo,"rev-parse","HEAD")
    require(sha==UPSTREAM_COMMIT,"UPSTREAM_COMMIT_DRIFT")
    original=(repo/"boltons/timeutils.py").read_bytes()
    (repo/TEST_FILE).write_text(INDEPENDENT_REGRESSION,encoding="utf-8")
    run_git(repo,"add","--",TEST_FILE)
    run_git(repo,"-c","user.name=ASWE Acceptance",
            "-c","user.email=aswe-acceptance@example.invalid",
            "commit","-m","Add independent Issue 500 regression acceptance")
    # Make the repository's test baseline reproducible; application code
    # remains exactly the public upstream version.
    require(original==(repo/"boltons/timeutils.py").read_bytes(),
            "UPSTREAM_APPLICATION_MODIFIED_BEFORE_AGENT")
    return repo,sha


async def execute_case(summary: dict) -> None:
    require(os.environ.get("GITHUB_ACTIONS")=="true" and
            os.environ.get("ASWE_LIVE_SMOKE")=="1" and
            os.environ.get("ASWE_STEP7_LIVE_ONCE")=="1",
            "STEP7_PAID_RUN_NOT_AUTHORIZED")
    LiveModelSettings.from_environment()
    image=python_image_digest()
    with tempfile.TemporaryDirectory(prefix="aswe-step7-real-") as td:
        root=Path(td)
        repo,original_sha=prepare_real_repository(root)
        summary["upstream_commit"]=original_sha
        baseline=await DockerCommandBackend(
            workspace_root=repo,image=image).run(
            " ".join(CHECK),timeout=45,max_output=2200)
        require(baseline.exit_code not in (None,0) and not baseline.timed_out,
                "UPSTREAM_BUG_NOT_REPRODUCED")
        summary["upstream_issue_reproduced"]=True
        # Keep the *real* user issue and independent tests as the only agent
        # inputs; do not give reference patches or upstream historical PR.
        home=root/"runtime"
        try:
            result=await asyncio.wait_for(execute_dev_workflow(
                repository=repo,task=TASK,runtime_dir=home,
                check_argv=CHECK,image=image,
                adaptive=True,planner="llm",explorer_mode="llm",
                physical_dag=True,max_repairs=1,
            ),timeout=1100)
        except Exception:
            summary["stages_before_failure"]=[
                json.loads(line)["event_type"]
                for file in (home/"tasks").glob("workflow-*/events.jsonl")
                for line in file.read_text(encoding="utf-8").splitlines() if line
            ][-20:]
            raise
        events=[json.loads(line) for line in result.trace_path.read_text(
            encoding="utf-8").splitlines() if line]
        kinds=Counter(e["event_type"] for e in events)
        roles=next((e["payload"].get("roles",[]) for e in events
                    if e["event_type"]=="team.selected"),[])
        dag=next((e["payload"] for e in events
                  if e["event_type"]=="task_dag.compiled"),{})
        dispatched=[e["node_id"] for e in events
                    if e["event_type"]=="dag.scheduler.dispatch"]
        checks=[e["payload"].get("status") for e in events
                if e["event_type"]=="dag.verification.executed"]
        final_root=result.round_reports[-1].parent/"workspace"
        source_changed=((repo/"boltons/timeutils.py").read_bytes() !=
                        (final_root/"boltons/timeutils.py").read_bytes())
        test_unchanged=((repo/TEST_FILE).read_bytes()==
                        (final_root/TEST_FILE).read_bytes())
        upstream_unchanged=not bool(run_git(repo,"status","--porcelain"))
        child_reports=[json.loads(path.read_text(encoding="utf-8"))
                       for path in result.round_reports]
        summary.update(
            verdict=result.verification_status,
            selected_roles=roles,
            physical_dag_compiled=bool(dag.get("task_dag_fingerprint")),
            dag_topological_order=dag.get("topological_order",[]),
            scheduler_dispatches=dispatched,
            independent_tester_results=checks,
            repair_scheduled=kinds["workflow.repair.scheduled"],
            coder_rounds=result.round_count,
            native_model_turns=kinds["model.turn.finished"],
            tool_call_events=kinds["tool.call.finished"],
            original_upstream_repo_unchanged=upstream_unchanged,
            independent_tests_unchanged=test_unchanged,
            implementation_changed=source_changed,
            child_native_statuses=[r.get("native_status") for r in child_reports],
            child_canonical_statuses=[r.get("verification_status") for r in child_reports],
        )
        require(dag.get("task_dag_fingerprint"),"NO_PHYSICAL_DAG")
        require(dispatched.count("coder")>=1 and
                dispatched.count("__aswe_verify")>=1,
                "NO_CODER_TESTER_DAG_EXECUTION")
        require(result.verification_status=="passed" and checks[-1]=="passed",
                "UPSTREAM_BUG_NOT_FIXED")
        require(source_changed,"NO_PRODUCTION_CODE_FIX")
        require(test_unchanged,"INDEPENDENT_TEST_CHANGED")
        require(upstream_unchanged,"UPSTREAM_SOURCE_MUTATED")
        require(kinds["tool.call.finished"]>=2,"NO_NATIVE_TOOL_CALLS")


def save_summary(summary: dict) -> None:
    path=Path(os.environ["ASWE_STEP7_REPORT_PATH"]).resolve()
    temporary=Path(os.environ["RUNNER_TEMP"]).resolve()
    require(path.is_relative_to(temporary),"STEP7_REPORT_PATH_INVALID")
    path.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",
                    encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:
            f.write("## Step 7A: actual boltons Issue #500\n\n"
                    f"Outcome: {summary.get('outcome','unknown')}\n\n"
                    f"Canonical: {summary.get('verdict','unknown')}\n\n"
                    f"Failure: {summary.get('failure_code','none')}\n\n"
                    "Model was not mocked; source was actual upstream Git.\n")


def main() -> int:
    summary={"case_id":CASE_ID,"upstream_issue":UPSTREAM_ISSUE,
             "model_mocked":False,"outcome":"not_started"}
    try:
        asyncio.run(execute_case(summary))
        summary["outcome"]="passed"
        code=0
    except Exception as exc:
        summary["outcome"]="failed"
        summary["failure_code"]=(exc.args[0]
                                  if isinstance(exc,AcceptanceFailed)
                                  else type(exc).__name__)
        code=1
    save_summary(summary)
    print("STEP7_REAL_ISSUE_RESULT="+summary["outcome"])
    print("STEP7_REAL_ISSUE_FAILURE="+str(summary.get("failure_code","none")))
    return code


if __name__=="__main__":
    sys.exit(main())
