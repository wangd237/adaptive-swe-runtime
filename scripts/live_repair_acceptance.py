"""Manual-gated REAL LLM Tester-failure -> Repair -> Tester acceptance.

The deliberately staged issue is a legitimate two-defect repo: stage 1
addresses inventory restoration; independent regression tests expose a
separate idempotence defect. Stage 2 is not a scripted patch: real LLM
receives the failed Docker assertion and repairs remaining logic.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import sys
import tempfile

from aswe.integrations.deerflow.dev_workflow import execute_dev_workflow
from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend
from aswe.integrations.deerflow.live_smoke_config import LiveModelSettings
from scripts.live_adaptive_acceptance import (
    CHECK, AcceptanceFailed, python_image_digest, require, seed_repository,
)

TASK = (
    "Investigate the cross-module order cancellation regression across "
    "shop/inventory.py and shop/orders.py. This is a TWO-MILESTONE repair: "
    "IN THE FIRST CODING PASS, fix ONLY the stock-release accounting in "
    "shop/inventory.py; do NOT change shop/orders.py in that initial pass, "
    "even if other tests reveal a second issue. The independent Runtime "
    "Tester intentionally checks the complete order cancellation behavior. "
    "AFTER TESTER FAILS and Runtime schedules a Repair pass, fix the "
    "remaining idempotency/refund bug in shop/orders.py, using the actual "
    "test-failure output. Do not edit any test files. Both milestones "
    "must pass the full unittest regression suite to finish the task."
)


async def run_acceptance(summary: dict) -> None:
    require(
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("ASWE_LIVE_SMOKE") == "1"
        and os.environ.get("ASWE_LIVE_REPAIR_ONCE") == "1",
        "LIVE_REPAIR_AUTHORIZATION_REQUIRED")
    LiveModelSettings.from_environment()
    image=python_image_digest()
    with tempfile.TemporaryDirectory(prefix="aswe-repair-live-") as temp:
        root=Path(temp)
        source=root/"repository"
        seed_repository(source)
        initial=await DockerCommandBackend(
            workspace_root=source,image=image).run(
            " ".join(CHECK), timeout=45,max_output=2500)
        require(initial.exit_code not in (None,0) and not initial.timed_out,
                "REPAIR_FIXTURE_NOT_FAILING")
        summary["baseline_tests_failed"]=True
        runtime=root/"runtime"
        try:
            result=await asyncio.wait_for(execute_dev_workflow(
                repository=source,task=TASK,runtime_dir=runtime,
                check_argv=CHECK,image=image,
                adaptive=True,planner="llm",explorer_mode="llm",
                physical_dag=True,max_repairs=1,
            ),timeout=1100)
        except Exception:
            # Names only, never prompt/secret/trace content.
            summary["stages_before_failure"]=[
                json.loads(line)["event_type"]
                for file in (runtime/"tasks").glob("workflow-*/events.jsonl")
                for line in file.read_text().splitlines() if line
            ][-22:]
            raise
        events=[json.loads(line) for line in result.trace_path.read_text().splitlines() if line]
        counts=Counter(e["event_type"] for e in events)
        dispatches=[e["node_id"] for e in events
                    if e["event_type"]=="dag.scheduler.dispatch"]
        verifier=[e["payload"]["status"] for e in events
                  if e["event_type"]=="dag.verification.executed"]
        # Native Coder tool-guard can also emit repair.feedback.available;
        # count only the *independent top-level Docker Tester* evidence.
        failures=[e["payload"]["output_sha256"] for e in events
                  if e["event_type"]=="repair.feedback.available"
                  and e["node_id"]=="__aswe_verify"
                  and e["payload"].get("source")=="independent_docker_tester"
                  and "output_sha256" in e["payload"]]
        child=[json.loads(path.read_text()) for path in result.round_reports]
        final_workspace=result.round_reports[-1].parent/"workspace"
        unchanged_tests=all(
            (source / path).read_bytes()==(final_workspace / path).read_bytes()
            for path in ("tests/__init__.py","tests/test_cancellation.py"))
        changed_modules=[
            path for path in ("shop/inventory.py","shop/orders.py")
            if (source / path).read_bytes()!=(final_workspace / path).read_bytes()
        ]
        summary.update(
            verdict=result.verification_status,
            round_count=result.round_count,
            physical_dag=bool(next((e for e in events
                                    if e["event_type"]=="task_dag.compiled"),None)),
            selected_roles=next((e["payload"]["roles"] for e in events
                                if e["event_type"]=="team.selected"),[]),
            dispatch_nodes=dispatches,
            tester_statuses=verifier,
            repair_scheduled=counts["workflow.repair.scheduled"],
            repair_feedback_output_sha256=failures[-1] if failures else None,
            native_model_turn_events=counts["model.turn.finished"],
            native_tool_call_events=counts["tool.call.finished"],
            child_native_statuses=[r.get("native_status") for r in child],
            child_verification_statuses=[r.get("verification_status") for r in child],
            changed_modules=changed_modules,
            test_files_unchanged=unchanged_tests,
        )
        require(result.round_count==2 and counts["workflow.repair.scheduled"]==1,
                "REAL_REPAIR_ROUND_NOT_EXECUTED")
        require(verifier==["failed","passed"],"REAL_TESTER_FAIL_TO_PASS_NOT_OBSERVED")
        require(len(failures)==1 and isinstance(failures[0],str)
                and len(failures[0])==64,"REAL_FAILURE_CONTEXT_NOT_CAPTURED")
        require(dispatches.count("coder")==2
                and dispatches.count("__aswe_verify")==2
                and (dispatches.count("explorer")==1
                     if "explorer" in summary["selected_roles"] else
                     dispatches.count("explorer")==0),
                "UNIFIED_SCHEDULER_DISPATCH_INCORRECT")
        # Adaptive Planning may legitimately select the minimal Coder team.
        # The previous live E2E already proved the Explorer role, while this
        # scenario specifically establishes genuine Repair behavior.
        require(summary["selected_roles"] in (
            ["coder"],["explorer","coder","tester"]),
            "REAL_ADAPTIVE_TEAM_INVALID")
        require(all(r=="completed" for r in summary["child_native_statuses"]),
                "NATIVE_EXECUTION_INCOMPLETE")
        require(result.verification_status=="passed","FINAL_REPAIR_NOT_PASSED")
        require(changed_modules==["shop/inventory.py","shop/orders.py"],
                "MULTIMODULE_REPAIR_INCOMPLETE")
        require(unchanged_tests,"REPAIR_MODIFIED_TEST_FILES")


def persist(summary:dict)->None:
    dest=Path(os.environ["ASWE_LIVE_REPAIR_REPORT_PATH"]).resolve()
    temp=Path(os.environ["RUNNER_TEMP"]).resolve()
    require(dest.is_relative_to(temp),"REPORT_OUTSIDE_RUNNER_TEMP")
    dest.write_text(json.dumps(summary,sort_keys=True,indent=2)+"\n")
    summary_path=os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path,"a") as file:
            file.write("## Real LLM Repair E2E\n\n"
                       f"Result: {summary.get('outcome','unknown')}\n\n"
                       f"Tester rounds: {summary.get('tester_statuses',[])}\n\n"
                       f"Repair scheduled: {summary.get('repair_scheduled',0)}\n\n"
                       f"Failure: {summary.get('error_code','none')}\n")


def main()->int:
    summary={"scenario":"genuine_two_milestone_cross_module_repair",
             "model_mocked":False,"outcome":"not_started"}
    try:
        asyncio.run(run_acceptance(summary))
        summary["outcome"]="passed"
        status=0
    except Exception as exc:
        summary["outcome"]="failed"
        summary["error_code"]=(exc.args[0] if isinstance(exc,AcceptanceFailed)
                               else type(exc).__name__)
        status=1
    persist(summary)
    print("ASWE_REAL_REPAIR_RESULT="+summary["outcome"])
    print("ASWE_REAL_REPAIR_ERROR="+str(summary.get("error_code","none")))
    return status


if __name__=="__main__":
    sys.exit(main())
