"""Step 6 CLI: inspect durable task traces and verified MVP reports.

No fake task execution or implicit credential/backend initialization.
"""
from __future__ import annotations

import argparse
import json
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
    report = sub.add_parser("report", help="inspect an existing MVPTaskReport JSON artifact")
    report.add_argument("path", type=Path)
    report.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    options = parser.parse_args(argv)
    try:
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
