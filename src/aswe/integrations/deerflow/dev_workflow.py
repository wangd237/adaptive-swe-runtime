"""Lightweight developer Coder -> Tester -> Repair workflow.

Each coding round uses the real Step 6B app entry and independent Docker
canonical verifier. Repair starts from the previous round's actual Git diff,
committed only in a disposable runtime clone; never from the original repo.
This is explicitly NOT strict cross-node Scheduler acceptance.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any, Callable

from aswe.core.ids import new_safe_id
from aswe.trace.minimal_events import LocalRuntimeEventSink
from aswe.integrations.deerflow.developer_entry import execute_swe_task
from aswe.integrations.deerflow.adaptive_team import explore_repository
from aswe.integrations.deerflow.dev_team_planner import plan_developer_team


@dataclass(frozen=True)
class WorkflowResult:
    workflow_id: str
    verification_status: str
    round_count: int
    report_path: Path
    trace_path: Path
    round_reports: tuple[Path, ...]


def _checkpoint(workspace: Path) -> None:
    """Only record the disposable clone's tracked code changes for handoff."""
    subprocess.run(["git", "-C", str(workspace), "add", "-A"],
                   check=True, capture_output=True, timeout=15)
    changed = subprocess.run(
        ["git", "-C", str(workspace), "diff", "--cached", "--quiet"],
        check=False, capture_output=True, timeout=15,
    )
    if changed.returncode not in (0, 1):
        raise RuntimeError("WORKFLOW_GIT_DIFF_FAILED")
    if changed.returncode == 1:
        subprocess.run(
            ["git", "-C", str(workspace), "-c", "user.name=ASWE",
             "-c", "user.email=aswe@localhost", "commit", "-m",
             "ASWE development repair checkpoint"],
            check=True, capture_output=True, timeout=20,
        )


async def execute_dev_workflow(*, repository: Path, task: str, runtime_dir: Path,
                               check_argv: tuple[str, ...], image: str,
                               ref: str = "HEAD", max_repairs: int = 1,
                               model_factory: Callable[..., Any] | None = None,
                               adaptive: bool = False, planner: str = "rules",
                               planner_factory: Callable[[], Any] | None = None) -> WorkflowResult:
    if not (0 <= max_repairs <= 3):
        raise ValueError("WORKFLOW_REPAIR_BUDGET_INVALID")
    workflow_id = new_safe_id("workflow")
    home = runtime_dir.expanduser().resolve()
    sink = LocalRuntimeEventSink(home, workflow_id, workspace_root=repository)
    source = repository
    source_ref = ref
    reports: list[Path] = []
    final_report = None
    if planner != "rules" and not adaptive:
        raise ValueError("LLM_PLANNER_REQUIRES_ADAPTIVE")
    planned = (await plan_developer_team(
        task=task, repository=repository, mode=planner,
        planner_factory=planner_factory) if adaptive else None)
    decision = planned.decision if planned else None
    if decision is not None:
        sink.emit("team.selected", payload={
            "roles":list(decision.roles),"reason":decision.reason,
            "complexity":decision.complexity,
            "planning_mode":planned.planning_mode,
            "matched_paths":list(decision.evidence_paths)})
        if decision.needs_exploration:
            discovered = explore_repository(repository,planned.explorer_objective)
            sink.emit("explorer.finished", node_id="explorer-0",
                      payload={"candidate_paths":list(discovered),
                               "source":"git_index","read_only":True})
            # Advisory hints only; no changes to tool grants or runtime policy.
            task = (task + "\\n\\nRepository exploration candidates (verify before editing): "
                    + ", ".join(discovered))
    if planned is not None:
        task = planned.coder_objective
    sink.emit("workflow.started", payload={"max_repairs":max_repairs})
    for number in range(max_repairs + 1):
        stage = "coder" if number == 0 else "repair"
        node_id = f"{stage}-{number}"
        sink.emit("workflow.stage.started", node_id=node_id,
                  payload={"stage":stage,"round":number+1})
        prompt = (task if number == 0 else
            f"{task}\n\nThe previous coding pass failed independent tests. "
            "Inspect the current code and tests, diagnose remaining failures, "
            "make the smallest repair, and rerun tests.")
        path, report, trace = await execute_swe_task(
            repository=source, task=prompt, runtime_dir=home,
            check_argv=check_argv, image=image, ref=source_ref,
            model_factory=model_factory)
        reports.append(path)
        # Preserve both the per-run provenance and the overall task timeline.
        for event in LocalRuntimeEventSink(home, report.task_id).read_all():
            sink.emit(event.event_type, node_id=node_id,
                      payload={"child_task_id":event.task_id,
                               "child_node_id":event.node_id,
                               "child_seq":event.seq,
                               **event.payload})
        sink.emit("workflow.test.finished", node_id=f"tester-{number}",
                  payload={"round":number+1, "check_id":report.verification_check_id,
                           "verification_status":report.verification_status,
                           "execution_id":report.execution_id})
        sink.emit("workflow.stage.finished", node_id=node_id,
                  payload={"round":number+1,"native_status":report.native_status,
                           "verification_status":report.verification_status,
                           "changed_files":list(report.changed_files)})
        final_report = report
        if report.verification_status == "passed":
            break
        if number == max_repairs or report.native_status != "completed":
            break
        # A failed canonical check is the only trigger for a new repair round.
        if report.verification_status != "failed":
            break
        prior_workspace = path.parent / "workspace"
        await asyncio.to_thread(_checkpoint, prior_workspace)
        source = prior_workspace
        source_ref = "HEAD"
        sink.emit("workflow.repair.scheduled", node_id=f"repair-{number+1}",
                  payload={"from_task_id":report.task_id,"round":number+2,
                           "reason":"canonical_tests_failed"})
    assert final_report is not None
    status = final_report.verification_status
    sink.emit("workflow.finished",payload={
        "verification_status":status,"round_count":len(reports),
        "final_child_task_id":final_report.task_id})
    destination = home / "tasks" / workflow_id / "workflow-report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({
        "workflow_id":workflow_id,"verification_status":status,
        "round_count":len(reports),"round_reports":[str(p) for p in reports],
        "trace_path":str(sink.path),
        "selected_roles":list(decision.roles) if decision else ["coder","tester"],
    },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return WorkflowResult(workflow_id,status,len(reports),destination,
                          sink.path,tuple(reports))
