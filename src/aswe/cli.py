"""Step 6 CLI: inspect durable task traces and verified MVP reports.

No fake task execution or implicit credential/backend initialization.
"""
from __future__ import annotations

import argparse
import json
import asyncio
import shlex
from pathlib import Path
import sys

from aswe.trace.minimal_events import LocalRuntimeEventSink


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aswe", description="Adaptive SWE Runtime developer CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    trace = sub.add_parser("trace", help="inspect runtime-owned JSONL events")
    trace.add_argument("task_id")
    trace.add_argument("--runtime-dir", type=Path, required=True)
    trace.add_argument("--json", action="store_true", help="emit one JSON object per line")
    trace.add_argument("--tail", type=int, default=0, help="last N events (0 = all)")
    run = sub.add_parser("run", help="execute a real coding task with pinned DeerFlow and Docker")
    run.add_argument("task", help="natural-language SWE task")
    run.add_argument("--repo", type=Path, required=True, help="local Git repository")
    run.add_argument("--runtime-dir", type=Path, required=True, help="private run artifacts outside repo")
    run.add_argument("--check-command", required=True,
                     help="independent Python test command, e.g. 'python -B -m unittest discover -s tests -q'")
    run.add_argument("--docker-image", required=True, help="existing Docker image pinned by @sha256 digest")
    run.add_argument("--ref", default="HEAD", help="Git reference to clone")
    run.add_argument("--env-file", type=Path, help="LLM settings file (default: .env in current directory)")
    workflow = sub.add_parser("workflow", help="Coder -> Tester -> Repair developer workflow")
    workflow.add_argument("task")
    workflow.add_argument("--repo", type=Path, required=True)
    workflow.add_argument("--runtime-dir", type=Path, required=True)
    workflow.add_argument("--check-command", required=True)
    workflow.add_argument("--docker-image", required=True)
    workflow.add_argument("--ref", default="HEAD")
    workflow.add_argument("--env-file", type=Path, help="LLM settings file (default: .env in current directory)")
    workflow.add_argument("--max-repairs", type=int, default=1)
    workflow.add_argument("--explorer", choices=("index","llm"), default="index",
                          help="optional independent read-only LLM Explorer")
    workflow.add_argument("--planner", choices=("rules","llm"), default="rules",
                          help="bounded developer team proposal; llm uses ASWE_MODEL")
    workflow.add_argument("--adaptive", action="store_true",
                          help="select minimum developer team and explore code when needed")
    report = sub.add_parser("report", help="inspect an existing MVPTaskReport JSON artifact")
    report.add_argument("path", type=Path)
    report.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    options = parser.parse_args(argv)
    try:
        if options.command == "workflow":
            from aswe.integrations.deerflow.dev_workflow import execute_dev_workflow
            from aswe.planning.acceptance import _validate_argv
            commands = tuple(shlex.split(options.check_command))
            _validate_argv(commands)
            result = asyncio.run(execute_dev_workflow(
                repository=options.repo, task=options.task,
                runtime_dir=options.runtime_dir, check_argv=commands,
                image=options.docker_image, ref=options.ref,
                max_repairs=options.max_repairs, adaptive=options.adaptive,
                planner=options.planner, env_file=options.env_file,
                explorer_mode=options.explorer))
            print(f"Workflow: {result.workflow_id}")
            print(f"Rounds: {result.round_count}")
            print(f"Canonical: {result.verification_status}")
            print(f"Report: {result.report_path}")
            print(f"Trace: {result.trace_path}")
            return 0 if result.verification_status == "passed" else 1
        if options.command == "run":
            from aswe.integrations.deerflow.developer_entry import execute_swe_task
            commands = tuple(shlex.split(options.check_command))
            # Admission occurs before external model invocations; user supplied
            # check command never comes from the model itself.
            from aswe.planning.acceptance import _validate_argv
            _validate_argv(commands)
            report_path, report, trace_path = asyncio.run(execute_swe_task(
                repository=options.repo,task=options.task,
                runtime_dir=options.runtime_dir,check_argv=commands,
                image=options.docker_image,ref=options.ref,
                env_file=options.env_file))
            print(f"Task: {report.task_id}")
            print(f"Report: {report_path}")
            print(f"Trace: {trace_path}")
            print(f"Native: {report.native_status} | Canonical: {report.verification_status}")
            print(f"Delivery: {report.delivery_status}")
            return 0 if report.verification_status == "passed" else 1
        if options.command == "trace":
            if options.tail < 0:
                raise ValueError("--tail cannot be negative")
            events = LocalRuntimeEventSink(options.runtime_dir, options.task_id).read_all()
            selected = events[-options.tail:] if options.tail else events
            for event in selected:
                if options.json:
                    print(event.model_dump_json())
                else:
                    print(f"{event.seq:05d} {event.timestamp.isoformat()} "
                          f"{event.event_type} node={event.node_id or '-'} "
                          f"{json.dumps(event.payload, ensure_ascii=False, sort_keys=True)}")
            return 0
        if options.command == "report":
            data = json.loads(options.path.read_text(encoding="utf-8"))
            required = ("task_id", "node_id", "native_status", "verification_status",
                        "delivery_status", "changed_files", "tests_passed")
            if not isinstance(data, dict) or any(k not in data for k in required):
                raise ValueError("invalid MVP report format")
            if options.json:
                print(json.dumps(data, ensure_ascii=False, sort_keys=True))
            else:
                print(f"Task: {data['task_id']} / {data['node_id']}")
                print(f"Native: {data['native_status']} | Canonical: {data['verification_status']}")
                print(f"Delivery: {data['delivery_status']}")
                print(f"Changed files: {', '.join(data['changed_files']) or '(none)'}")
                if data["delivery_status"] == "tests_passed_scheduler_quarantined":
                    print("NOTE: independent tests passed; strict Scheduler acceptance NOT proven")
            return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"aswe: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
