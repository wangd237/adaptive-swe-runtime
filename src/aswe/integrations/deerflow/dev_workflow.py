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
import shlex
from pathlib import Path
import subprocess
from typing import Any, Callable

from aswe.core.ids import new_safe_id
from aswe.trace.minimal_events import LocalRuntimeEventSink
from aswe.integrations.deerflow.developer_entry import execute_swe_task
from aswe.integrations.deerflow.adaptive_team import explore_repository
from aswe.integrations.deerflow.dev_team_planner import plan_developer_team
from aswe.integrations.deerflow.dev_execution_plan import compile_developer_workplan
from aswe.integrations.deerflow.dev_llm_explorer import execute_llm_explorer
from aswe.integrations.deerflow.dev_physical_dag import (
    compile_physical_developer_dag, DeveloperDagScheduler)
from aswe.llm_config import load_llm_settings
from aswe.integrations.deerflow.repair_context import (
    feedback_from_test_output, repair_prompt, RepairTestFeedback)


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
                               planner_factory: Callable[[], Any] | None = None,
                               env_file: Path | None = None,
                               explorer_mode: str = "index",
                               explorer_factory: Callable[[], Any] | None = None,
                               physical_dag: bool = False,
                               initial_coder_check_argv: tuple[str,...] | None = None) -> WorkflowResult:
    if initial_coder_check_argv is not None and not initial_coder_check_argv:
        raise ValueError("INITIAL_CODER_CHECK_INVALID")
    if not (0 <= max_repairs <= 3):
        raise ValueError("WORKFLOW_REPAIR_BUDGET_INVALID")
    if explorer_mode not in ("index", "llm"):
        raise ValueError("WORKFLOW_EXPLORER_MODE_INVALID")
    if explorer_mode == "llm" and not adaptive:
        raise ValueError("LLM_EXPLORER_REQUIRES_ADAPTIVE")
    if physical_dag and not adaptive:
        raise ValueError("PHYSICAL_DAG_REQUIRES_ADAPTIVE")
    workflow_id = new_safe_id("workflow")
    home = runtime_dir.expanduser().resolve()
    sink = LocalRuntimeEventSink(home, workflow_id, workspace_root=repository)
    source = repository
    source_ref = ref
    reports: list[Path] = []
    final_report = None
    last_verification_status: str | None = None
    failure_feedback: RepairTestFeedback | None = None
    if planner != "rules" and not adaptive:
        raise ValueError("LLM_PLANNER_REQUIRES_ADAPTIVE")
    planned = (await plan_developer_team(
        task=task, repository=repository, mode=planner,
        planner_factory=planner_factory, env_file=env_file) if adaptive else None)
    decision = planned.decision if planned else None
    semantic_plan = None
    dag_scheduler: DeveloperDagScheduler | None = None
    completed_nodes: set[str] = set()
    coding_task = planned.coder_objective if planned else task
    if decision is not None:
        semantic_plan = compile_developer_workplan(
            repository=repository, ref=ref,task=task,
            workflow_id=workflow_id, decision=decision,
            coder_objective=coding_task,
            explorer_objective=planned.explorer_objective)
        if physical_dag:
            physical=compile_physical_developer_dag(
                workplan=semantic_plan,repository=repository,
                image=image,model=load_llm_settings(env_file=env_file).model)
            dag_scheduler=DeveloperDagScheduler(physical,max_repairs=max_repairs)
            sink.emit("task_dag.compiled",payload={
                "task_dag_fingerprint":physical.dag.fingerprint,
                "inventory_fingerprint":physical.inventory_fingerprint,
                "resolved_fingerprint":physical.resolved_fingerprint,
                "topological_order":list(physical.dag.topological_order),
                "nodes":physical.display()})
        sink.emit("team.selected", payload={
            "roles":list(decision.roles),"reason":decision.reason,
            "complexity":decision.complexity,
            "planning_mode":planned.planning_mode,
            "matched_paths":list(decision.evidence_paths)})
        sink.emit("semantic_plan.validated", payload={
            "workplan_fingerprint":semantic_plan.plan.fingerprint,
            "contract_fingerprint":semantic_plan.contract_fingerprint,
            "nodes":semantic_plan.trace_nodes()})
        if decision.needs_exploration:
            if dag_scheduler is None:
                semantic_plan.require_ready("explorer",completed_nodes)
            if dag_scheduler is not None:
                attempt=dag_scheduler.dispatch("explorer")
                sink.emit("dag.scheduler.dispatch",node_id="explorer",payload={
                    "attempt":attempt,"provider_id":"explorer","execution":"read_only_explorer"})
            discovered = explore_repository(repository,planned.explorer_objective)
            sink.emit("semantic_node.started",node_id="explorer",
                      payload={"work_kind":"discovery","mode":explorer_mode})
            if explorer_mode == "llm":
                finding = await execute_llm_explorer(
                    repository=repository,ref=ref,
                    task=planned.explorer_objective,
                    env_file=env_file,explorer_factory=explorer_factory)
                discovered = tuple(dict.fromkeys(
                    finding.relevant_paths + tuple(discovered)))
                # Output from independent Explorer is advisory only.
                coding_task += (
                    "\n\nRead-only Explorer findings (verify independently):"
                    "\nRelevant files: " + ", ".join(finding.relevant_paths) +
                    "\nDiagnosis: " + finding.diagnosis +
                    "\nSuggested approach: " + finding.suggested_approach)
            coding_task += (
                "\n\nRepository exploration candidates (verify before editing): "
                + ", ".join(discovered))
            sink.emit("explorer.finished", node_id="explorer",
                      payload={"candidate_paths":list(discovered),
                               "source":"llm_readonly" if explorer_mode == "llm"
                                         else "git_index",
                               "read_only":True})
            sink.emit("semantic_node.finished",node_id="explorer",
                      payload={"work_kind":"discovery","status":"completed"})
            if dag_scheduler is None:
                completed_nodes.add("explorer")
            if dag_scheduler is not None:
                dag_scheduler.finish("explorer",verified=True)
    sink.emit("workflow.started", payload={"max_repairs":max_repairs})
    for number in range(max_repairs + 1):
        stage = "coder" if number == 0 else "repair"
        node_id = f"{stage}-{number}"
        sink.emit("workflow.stage.started", node_id=node_id,
                  payload={"stage":stage,"round":number+1})
        prompt = (coding_task if number == 0 else
                  repair_prompt(coding_task, failure_feedback))
        if semantic_plan is not None:
            if dag_scheduler is None:
                semantic_plan.require_ready("coder",completed_nodes)
            if dag_scheduler is not None:
                attempt=dag_scheduler.dispatch("coder")
                sink.emit("dag.scheduler.dispatch",node_id="coder",payload={
                    "attempt":attempt,"provider_id":"coder",
                    "execution":"native_deerflow_child_scheduler"})
            sink.emit("semantic_node.started",node_id="coder",payload={"round":number+1})
        # Fast inner Coder unit tests can be narrower than the DAG-owned
        # independent complete regression suite; Repair uses the full suite.
        child_check = (initial_coder_check_argv if number == 0 and
                       initial_coder_check_argv is not None else check_argv)
        path, report, trace = await execute_swe_task(
            repository=source, task=prompt, runtime_dir=home,
            check_argv=child_check, image=image, ref=source_ref,
            model_factory=model_factory, env_file=env_file)
        reports.append(path)
        verification_status = report.verification_status
        # Preserve both the per-run provenance and the overall task timeline.
        for event in LocalRuntimeEventSink(home, report.task_id).read_all():
            sink.emit(event.event_type, node_id=node_id,
                      payload={"child_task_id":event.task_id,
                               "child_node_id":event.node_id,
                               "child_seq":event.seq,
                               **event.payload})
        if semantic_plan is not None:
            if dag_scheduler is None and report.native_status == "completed":
                completed_nodes.add("coder")
            if dag_scheduler is not None:
                dag_scheduler.finish("coder",verified=report.native_status=="completed")
            sink.emit("semantic_node.finished",node_id="coder",payload={
                "round":number+1, "status":report.native_status})
            if report.native_status == "completed":
                if dag_scheduler is None:
                    semantic_plan.require_ready("__aswe_verify",completed_nodes)
                if dag_scheduler is not None:
                    attempt=dag_scheduler.dispatch("__aswe_verify")
                    sink.emit("dag.scheduler.dispatch",node_id="__aswe_verify",payload={
                        "attempt":attempt,"provider_id":"tester",
                        "execution":"isolated_docker_test"})
                sink.emit("semantic_node.started",node_id="__aswe_verify",
                          payload={"round":number+1})
                if dag_scheduler is not None:
                    from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend
                    # This is a separate, scheduler-dispatched Docker check
                    # after Coder terminates, not merely copied child evidence.
                    runner=DockerCommandBackend(workspace_root=path.parent / "workspace",
                                                image=image)
                    result=await runner.run(shlex.join(check_argv),timeout=90,
                                            max_output=6000)
                    verification_status=("passed" if result.exit_code==0
                                         and not result.timed_out else "failed")
                    if verification_status == "failed":
                        current_settings=load_llm_settings(env_file=env_file)
                        failure_feedback=feedback_from_test_output(
                            result.output,secrets=(current_settings.api_key,))
                        sink.emit("repair.feedback.available",node_id="__aswe_verify",
                                  payload={"round":number+1,
                                           "output_sha256":failure_feedback.output_sha256,
                                           "output_length":failure_feedback.output_length,
                                           "source":"independent_docker_tester"})
                    sink.emit("dag.verification.executed",node_id="__aswe_verify",
                              payload={"round":number+1,"exit_code":result.exit_code,
                                       "timed_out":result.timed_out,
                                       "status":verification_status,
                                       "child_verification_status":report.verification_status})
                sink.emit("semantic_node.finished",node_id="__aswe_verify",payload={
                    "round":number+1, "status":verification_status,
                    "source":("dag_scheduler_docker" if dag_scheduler is not None
                              else "child_canonical_verifier")})
                if dag_scheduler is not None:
                    dag_scheduler.finish("__aswe_verify",
                                         verified=verification_status=="passed")
        if report.native_status != "completed":
            verification_status = "unverified"
        last_verification_status = verification_status
        sink.emit("workflow.test.finished", node_id=f"tester-{number}",
                  payload={"round":number+1, "check_id":report.verification_check_id,
                           "verification_status":verification_status,
                           "execution_id":report.execution_id})
        sink.emit("workflow.stage.finished", node_id=node_id,
                  payload={"round":number+1,"native_status":report.native_status,
                           "verification_status":verification_status,
                           "changed_files":list(report.changed_files)})
        final_report = report
        if verification_status == "passed" and report.native_status == "completed":
            break
        if number == max_repairs or report.native_status != "completed":
            break
        # A failed canonical check is the only trigger for a new repair round.
        if verification_status != "failed":
            break
        if dag_scheduler is not None and not dag_scheduler.schedule_repair():
            sink.emit("workflow.repair.budget_exhausted",
                      payload={"round":number+1,"budget":max_repairs})
            break
        prior_workspace = path.parent / "workspace"
        await asyncio.to_thread(_checkpoint, prior_workspace)
        source = prior_workspace
        source_ref = "HEAD"
        sink.emit("workflow.repair.scheduled", node_id=f"repair-{number+1}",
                  payload={"from_task_id":report.task_id,"round":number+2,
                           "reason":"canonical_tests_failed"})
    assert final_report is not None
    status = last_verification_status or final_report.verification_status
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
        "semantic_plan_fingerprint":semantic_plan.plan.fingerprint if semantic_plan else None,
        "task_dag_fingerprint":dag_scheduler.physical.dag.fingerprint if dag_scheduler else None,
        "dag_dispatch_attempts":dict(dag_scheduler.attempts) if dag_scheduler else {},
        "repair_rounds_scheduled":dag_scheduler.repairs_scheduled if dag_scheduler else max(0,len(reports)-1),
        "last_failure_output_sha256":failure_feedback.output_sha256 if failure_feedback else None,
        "explorer_mode":explorer_mode if decision and decision.needs_exploration else None,
    },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return WorkflowResult(workflow_id,status,len(reports),destination,
                          sink.path,tuple(reports))
