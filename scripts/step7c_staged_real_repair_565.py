"""Step 7C: controlled staged specification on a genuine upstream boltons Issue.

The upstream repo and commit, LLM settings, real Docker, task orchestration
and native DeerFlow are exactly the same as Step7 #500. Only the public Issue
and host-owned behavioral regression tests differ.

The first Coder instruction is deliberately narrow to elicit real independent
Tester feedback. The model/tools/patch are genuine, but this is not a natural
unmodified first-pass Issue benchmark. No mocked patch or Tester verdict.
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
from aswe.integrations.deerflow.practical_acceptance import PracticalAcceptanceDenied
from aswe.trace.reliability import summarize_execution_trace
from aswe.integrations.deerflow.live_smoke_config import LiveModelSettings
from scripts.live_adaptive_acceptance import (
    AcceptanceFailed, python_image_digest, require,
)
from scripts.step7_real_issue import UPSTREAM_URL, UPSTREAM_COMMIT, run_git

ISSUE="https://github.com/mahmoud/boltons/issues/565"
CASE_ID="boltons-565-multireplace-compiled-regex-flags"
CHECK=("python","-B","-m","unittest","tests.test_aswe_issue565","-q")
TEST_PATH="tests/test_aswe_issue565.py"
TASK=(
    "This is a CONTROLLED STAGED-SPEC Repair acceptance on the genuine public "
    "boltons issue #565 (MultiReplace loses flags on precompiled regex). "
    "On the FIRST Coder attempt only, implement a minimal production patch "
    "for preserving IGNORECASE on re.compile('cat',re.I), including isolation "
    "from adjacent plain-string branches. Then STOP the native Agent normally: "
    "do not attempt other regex flags or extended refactoring during the "
    "initial Coder attempt. The independent host-owned Tester (not the model) "
    "will run the complete unchanged upstream issue #565 behavioral suite. "
    "If a later attempt includes actual 'test_failure_output' / RepairFeedback, "
    "then address ALL independently failing behaviors, including MULTILINE, "
    "DOTALL, VERBOSE, ASCII, leading inline flags and constructor flags, "
    "and finish with a correct general fix. The agent selects its own tools "
    "and production patch on both rounds; do not modify any test or metadata. "
    "This staged initial specification is intentionally controlled to "
    "test the real Tester -> Repair -> Coder closed loop, not a natural "
    "first-attempt Issue success-rate measurement."
)
TEST_CODE=r'''"""Host-owned independent regression for upstream boltons issue #565."""
import re
import unittest
from boltons.strutils import MultiReplace, multi_replace

class Issue565(unittest.TestCase):
    def test_ignorecase_precompiled(self):
        repl=MultiReplace([(re.compile("cat",re.I),"dog")])
        self.assertEqual(repl.sub("CAT cat"),"dog dog")

    def test_flags_are_scoped_per_branch(self):
        repl=MultiReplace([(re.compile("cat",re.I),"dog"),("BIRD","eagle")])
        self.assertEqual(repl.sub("CAT bird BIRD"),"dog bird eagle")

    def test_multiline_precompiled(self):
        repl=MultiReplace([(re.compile(r"^fox",re.M),"wolf")])
        self.assertEqual(repl.sub("fox\nfox"),"wolf\nwolf")

    def test_dotall_precompiled(self):
        repl=MultiReplace([(re.compile("a.b",re.S),"X")])
        self.assertEqual(repl.sub("a\nb"),"X")

    def test_verbose_precompiled(self):
        repl=MultiReplace([(re.compile("c a t # ignore trailing comment",re.X),"dog")])
        self.assertEqual(repl.sub("cat"),"dog")

    def test_ascii_precompiled_does_not_leak(self):
        repl=MultiReplace([(re.compile(r"\w+",re.A),"ascii"),
                           (re.compile("é"),"unicode")])
        self.assertEqual(repl.sub("é"),"unicode")

    def test_inline_leading_flags(self):
        repl=MultiReplace([(re.compile("(?i)cat"),"dog"),
                           ("BIRD","eagle")])
        self.assertEqual(repl.sub("CAT bird BIRD"),"dog bird eagle")

    def test_constructor_global_flags_still_work(self):
        repl=MultiReplace([("cat","dog"),("FOX","wolf")],flags=re.I)
        self.assertEqual(repl.sub("CAT fox"),"dog wolf")

    def test_plain_strings_still_literal(self):
        repl=MultiReplace([("a.b","X"),("cat","dog")])
        self.assertEqual(repl.sub("a.b a-b cat"),"X a-b dog")

    def test_multi_replace_helper(self):
        self.assertEqual(multi_replace(
            "CAT",[(re.compile("cat",re.I),"dog")]),"dog")
'''

def prepare(root: Path) -> tuple[Path,str]:
    repo=root/"upstream"
    subprocess.run(["git","clone","--quiet",UPSTREAM_URL,str(repo)],
                   check=True,capture_output=True,timeout=120)
    run_git(repo,"checkout","--detach",UPSTREAM_COMMIT)
    original_sha=run_git(repo,"rev-parse","HEAD")
    require(original_sha==UPSTREAM_COMMIT,"UPSTREAM_SHA_MISMATCH")
    original_source=(repo/"boltons/strutils.py").read_bytes()
    (repo/TEST_PATH).write_text(TEST_CODE,encoding="utf-8")
    run_git(repo,"add","--",TEST_PATH)
    run_git(repo,"-c","user.name=ASWE Acceptance",
            "-c","user.email=aswe-acceptance@example.invalid",
            "commit","-m","Host-owned Issue 565 acceptance tests")
    require(original_source==(repo/"boltons/strutils.py").read_bytes(),
            "SOURCE_MODIFIED_BEFORE_MODEL")
    return repo,original_sha

async def execute(summary: dict) -> None:
    require(os.environ.get("GITHUB_ACTIONS")=="true" and
            os.environ.get("ASWE_LIVE_SMOKE")=="1" and
            os.environ.get("ASWE_STEP7_REPAIR565_ONCE")=="1",
            "STEP7_REPAIR565_NOT_AUTHORIZED")
    LiveModelSettings.from_environment()
    image=python_image_digest()
    with tempfile.TemporaryDirectory(prefix="aswe-step7-repair565-") as td:
        root=Path(td)
        repo,sha=prepare(root)
        summary["upstream_commit"]=sha
        baseline=await DockerCommandBackend(
            workspace_root=repo,image=image).run(
            " ".join(CHECK),timeout=45,max_output=1800)
        require(baseline.exit_code not in (None,0) and not baseline.timed_out,
                "ISSUE_565_BASELINE_NOT_FAILING")
        summary["baseline_regression_failed"]=True
        home=root/"runtime"
        try:
            run=await asyncio.wait_for(execute_dev_workflow(
                repository=repo,task=TASK,runtime_dir=home,
                check_argv=CHECK,image=image,adaptive=True,
                planner="llm",explorer_mode="llm",physical_dag=True,
                max_repairs=2,
            ),timeout=1100)
        except Exception:
            summary["last_stage_event_types"]=[
                json.loads(line)["event_type"]
                for file in (home/"tasks").glob("workflow-*/events.jsonl")
                for line in file.read_text(encoding="utf-8").splitlines() if line
            ][-16:]
            # Child diagnostic is collected before TemporaryDirectory is
            # destroyed; only safe normalized counters are serialized.
            child_traces=sorted((home/"tasks").glob("task-*/events.jsonl"))
            if child_traces:
                latest=[
                    json.loads(line) for line in child_traces[-1].read_text(
                        encoding="utf-8").splitlines() if line
                ]
                summary["child_failure_reliability"]=summarize_execution_trace(latest)
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
        altered=((repo/"boltons/strutils.py").read_bytes() !=
                 (final/"boltons/strutils.py").read_bytes())
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
            child_native_stop_reasons=[x.get("native_stop_reason") for x in child_reports],
            child_delivery_statuses=[x.get("delivery_status") for x in child_reports],
            child_scheduler_statuses=[x.get("scheduler_node_status") for x in child_reports],
            child_handoff_fingerprints=[x.get("accepted_handoff_fingerprint") for x in child_reports],
            practical_handoff_events=[
                e["payload"].get("accepted") for e in events
                if e["event_type"] == "dag.coder.handoff"
            ],
            repair_scheduled=ev["workflow.repair.scheduled"],
            production_changed=altered,
            external_test_unchanged=unchanged,
            diagnostic_code_test_passed=diag_pass,
            final_workflow_verdict=run.verification_status,
        )
        require(dispatch.count("coder")>=2 and
                dispatch.count("__aswe_verify")>=2,
                "NO_PHYSICAL_REPAIR_DAG_DISPATCH")
        require("coder" in dispatch,"CODER_NOT_SCHEDULED")
        require(all(
            x.get("acceptance_profile") == "practical"
            and x.get("scheduler_node_status") == "succeeded"
            and isinstance(x.get("accepted_handoff_fingerprint"), str)
            and len(x["accepted_handoff_fingerprint"]) == 64
            for x in child_reports
        ), "PRACTICAL_CODER_HANDOFF_NOT_ACCEPTED")
        require(
            summary["practical_handoff_events"]
            and all(summary["practical_handoff_events"]),
            "PHYSICAL_DAG_HANDOFF_NOT_ACCEPTED",
        )
        # The point of this benchmark is a *real* failed independent Tester
        # followed by a genuine LLM Repair attempt, not merely a first-pass fix.
        require(len(child_reports) >= 2
                and summary["repair_scheduled"] >= 1
                and "failed" in checker[:-1],
                "REAL_LLM_REPAIR_NOT_EXERCISED")
        require(run.verification_status=="passed" and checker[-1:] == ["passed"],
                "ISSUE_565_NOT_SOLVED")
        require(all(x.get("native_stop_reason") is None for x in child_reports),
                "ISSUE_565_NATIVE_STOP_REASON_NOT_NORMAL")
        require(altered and unchanged,"SOLUTION_INTEGRITY_NOT_PROVEN")
        require(ev["tool.call.finished"]>=2,"NO_REAL_NATIVE_TOOL_EXECUTION")
        require(len(set(summary["child_handoff_fingerprints"])) >= 2,
                "REPAIR_NEW_HANDOFF_NOT_PROVEN")

def persist(summary: dict) -> None:
    path=Path(os.environ["ASWE_STEP7_REPAIR565_REPORT_PATH"]).resolve()
    runner=Path(os.environ["RUNNER_TEMP"]).resolve()
    require(path.is_relative_to(runner),"REPORT_LOCATION_FORBIDDEN")
    path.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",
                    encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:
            f.write("## Real upstream boltons Issue #565 actual Repair challenge\n\n"
                    f"Outcome: `{summary.get('outcome','unknown')}`\n\n"
                    f"Failure: `{summary.get('failure_code','none')}`\n\n"
                    f"Tool failures: `{summary.get('tool_failed_count','not reported')}`\n\n"
                    "Unmocked model; real independent Tester failure and new Scheduler Handoff required.\n")

def main() -> int:
    data={"case_id":CASE_ID,"upstream_issue":ISSUE,
          "model_mocked":False,"staged_specification":True,
          "first_round_guidance":"IGNORECASE_only_then_wait_for_tester",
          "outcome":"not_started"}
    try:
        asyncio.run(execute(data))
        data["outcome"]="passed"
        code=0
    except Exception as exc:
        data["outcome"]="failed"
        data["failure_code"]=(exc.args[0] if isinstance(
                                  exc,(AcceptanceFailed,PracticalAcceptanceDenied))
                              else type(exc).__name__)
        code=1
    persist(data)
    print("STEP7_REPAIR565_ISSUE_RESULT="+data["outcome"])
    print("STEP7_REPAIR565_ISSUE_FAILURE="+str(data.get("failure_code","none")))
    return code

if __name__=="__main__":
    sys.exit(main())
