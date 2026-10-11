"""Step 7C: redacted, deterministic reliability view over trusted runtime events.

Never serialize prompt/response text, tool arguments/results, file paths, model
provider error strings, arbitrary error fields, or credentials. Inputs may
contain untrusted model data: only enum-like statuses, numeric counters,
recognized stable failure codes and trusted host event *types* are projected.

A trace summary is diagnostic evidence, NOT a Scheduler acceptance, test
receipt, proof of quiescence, or a replacement for the canonical verifier.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

SCHEMA_VERSION = "aswe.reliability.v1"
# Explicit host-recognized codes only. Arbitrary strings (even uppercase
# strings) must never be reflected from a purported trace as failure details.
_KNOWN_TOOL_FAILURES = frozenset((
    "SWE_READ_BEFORE_WRITE_REQUIRED", "SWE_PATH_FORBIDDEN",
    "SWE_PATH_NOT_ALLOWED", "SWE_PATH_OUTSIDE_WORKSPACE",
    "SWE_PATH_INVALID", "SWE_SYMLINK_PATH_FORBIDDEN",
    "SWE_CHANGED_FILE_LIMIT_EXCEEDED", "SWE_FILE_TOO_LARGE",
    "SWE_FILE_MISSING", "SWE_FILE_UNREADABLE", "SWE_WRITE_FAILED",
    "SWE_REPLACE_TARGET_NOT_FOUND", "SWE_REPLACE_AMBIGUOUS",
    "SWE_WRITE_POLICY_REQUIRED", "SWE_WORKSPACE_ROOT_DRIFT",
    "SWE_DOCKER_UNAVAILABLE", "SWE_DOCKER_CLEANUP_UNVERIFIED",
    "SWE_TOOL_NOT_IN_PROFILE", "SWE_COMMAND_INVALID",
    "AUTHORIZATION_CALL_DENIED", "AUTHORIZATION_CALL_FAILED",
    "TOOL_CANCELLED", "NATIVE_TOOL_FAILED", "EXECUTION_BINDING_CLOSED",
    "EXECUTION_BINDING_NOT_ACTIVE", "TOOL_CALL_REPLAY",
    "RUN_AUTHORITY_MUTATED", "TOOL_CALL_RUNTIME_CONTEXT_MISMATCH",
))
_TOOL_STATUSES = frozenset(("completed", "denied", "failed", "cancelled"))
_VERIFICATION = frozenset(("passed", "failed", "unverified", "not_run"))
_NATIVE_STATUS = frozenset(("completed", "failed", "cancelled", "timed_out"))
_NATIVE_STOPS = frozenset(("turn_capped", "token_capped", "loop_capped"))
_DELIVERY_STATUS = frozenset((
    "tests_passed_scheduler_quarantined", "tests_passed_unaccepted",
    "tests_failed", "unverified",
))
_SCHEDULER_STATUS = frozenset((
    "pending", "running", "completed", "failed", "blocked",
    "cancelled", "quarantined",
))


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _status(value: Any, allowed: frozenset[str], fallback: str) -> str:
    return value if type(value) is str and value in allowed else fallback


def _code(value: Any) -> str:
    return value if type(value) is str and value in _KNOWN_TOOL_FAILURES else "UNCLASSIFIED_FAILURE"


def _nonnegative(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def safe_model_usage(raw: Any) -> dict[str, int]:
    """Extract ONLY provider-reported nonnegative integer token counts.

    Do not infer missing totals, token prices, cache charges or model costs.
    Unknown keys, non-integers (including bools), and negative counts vanish.
    """
    if not isinstance(raw, Mapping):
        return {}
    usage = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        count = _nonnegative(raw.get(key))
        if count is not None:
            usage[key] = count
    return usage


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None else None


def summarize_execution_trace(
    events: Iterable[Any],
    *,
    round_reports: Iterable[Any] = (),
) -> dict[str, Any]:
    """Summarize original task-level events and optional child report metadata.

    The caller must provide the HOST runtime trace, not LLM-generated event
    descriptions. Tool retries are diagnostic counts only; without a trusted
    same-file read receipt correlation, do not assert safe recovery.
    """
    records = tuple(events)
    reports = tuple(round_reports)
    counts: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    denied: Counter[str] = Counter()
    attempts: Counter[str] = Counter()
    native_stops: Counter[str] = Counter()
    tokens: Counter[str] = Counter()
    token_reported_turns = 0
    verifier_results: list[str] = []
    dag_tester_results: list[str] = []
    canonical_verifier_results: list[str] = []
    repair_rounds = 0
    verification = "unverified"
    native = "unknown"
    stopped = None
    delivery = "unknown"
    scheduler_status = "unknown"
    quiescence_proven: bool | None = None
    finished = False
    last_mvp_payload: Mapping[str, Any] | None = None
    first_time = last_time = None
    trace_integrity = "verified"
    seen_ids: set[tuple[str, str]] = set()
    anomaly_timeline: list[dict[str, Any]] = []
    expected_seq = 1
    task_identity = None

    for record in records:
        event = _get(record, "event_type")
        payload = _get(record, "payload", {})
        payload = payload if isinstance(payload, Mapping) else {}
        if type(event) is not str:
            trace_integrity = "invalid"
            continue
        seq = _get(record, "seq")
        if seq is not None and (type(seq) is not int or seq != expected_seq):
            trace_integrity = "invalid"
        expected_seq += 1
        task_id = _get(record, "task_id")
        if task_id is not None:
            if task_identity is None:
                task_identity = task_id
            elif task_id != task_identity:
                trace_integrity = "invalid"
        at = _time(_get(record, "timestamp"))
        if at is not None:
            first_time = at if first_time is None else min(first_time, at)
            last_time = at if last_time is None else max(last_time, at)

        counts[event] += 1
        if event == "model.turn.finished":
            usage = safe_model_usage(payload.get("usage"))
            if usage:
                token_reported_turns += 1
                for key, value in usage.items():
                    tokens[key] += value
        elif event == "tool.call.finished":
            status = _status(payload.get("status"), _TOOL_STATUSES, "unknown")
            statuses[status] += 1
            if status in ("failed", "denied", "cancelled"):
                code = _code(payload.get("failure_code"))
                denied[code] += 1
                # Safe causal index only: not even the tool call ID, filepath
                # hash, argument/result content, or arbitrary provider text.
                tool_name = payload.get("tool_name")
                tool_name = tool_name if tool_name in (
                    "read_file", "write_file", "str_replace", "bash"
                ) else "other"
                anomaly_timeline.append({
                    "seq": expected_seq - 1,
                    "event": "tool_failure", "tool": tool_name,
                    "status": status, "code": code,
                })
            # Do not assert these retries were safe, only count repeat calls.
            tool_call_id = payload.get("tool_call_id")
            execution_id = payload.get("execution_id")
            if (type(tool_call_id) is str and type(execution_id) is str):
                key = (execution_id, tool_call_id)
                if key in seen_ids:
                    trace_integrity = "invalid"
                seen_ids.add(key)
        elif event == "workflow.repair.scheduled":
            repair_rounds += 1
            anomaly_timeline.append({
                "seq": expected_seq - 1, "event": "repair_scheduled",
            })
        elif event in ("dag.verification.executed", "verification.finished"):
            result = _status(payload.get("status"), _VERIFICATION, "unverified")
            verifier_results.append(result)
            if event == "dag.verification.executed":
                dag_tester_results.append(result)
            else:
                canonical_verifier_results.append(result)
            if result in ("failed", "unverified"):
                anomaly_timeline.append({
                    "seq": expected_seq - 1,
                    "event": ("dag_tester" if event == "dag.verification.executed"
                              else "canonical_verifier"),
                    "status": result,
                })
        elif event == "workflow.stage.finished":
            native = _status(payload.get("native_status"), _NATIVE_STATUS, "unknown")
            value = payload.get("native_stop_reason")
            stopped = _status(value, _NATIVE_STOPS, "") or None
            if stopped is not None:
                native_stops[stopped] += 1
                anomaly_timeline.append({
                    "seq": expected_seq - 1, "event": "native_cap",
                    "reason": stopped,
                })
        elif event == "mvp.task.finished":
            # Single-node developer CLI produces an MVP completion, not a
            # top-level multi-stage workflow.finished.
            last_mvp_payload = payload
            delivery = _status(payload.get("delivery_status"), _DELIVERY_STATUS, "unknown")
            if type(payload.get("quiescence_proven")) is bool:
                quiescence_proven = payload["quiescence_proven"]
        elif event == "workflow.finished":
            finished = True
            verification = _status(payload.get("verification_status"), _VERIFICATION, "unverified")
            value = payload.get("final_native_stop_reason")
            stopped = _status(value, _NATIVE_STOPS, "") or stopped

    if not counts["workflow.started"] and last_mvp_payload is not None:
        # A single-node MVP has a useful terminal diagnostic but STILL does
        # not mean strict Scheduler acceptance or proven quiescence.
        finished = True
        verification = _status(last_mvp_payload.get("verification_status"),
                               _VERIFICATION, "unverified")
        native = _status(last_mvp_payload.get("native_status"),
                         _NATIVE_STATUS, "unknown")
        stopped = _status(last_mvp_payload.get("native_stop_reason"),
                          _NATIVE_STOPS, "") or None
    if reports:
        last = reports[-1]
        native = _status(_get(last, "native_status"), _NATIVE_STATUS, "unknown")
        delivery = _status(_get(last, "delivery_status"), _DELIVERY_STATUS, delivery)
        scheduler_status = _status(
            _get(last, "scheduler_node_status"), _SCHEDULER_STATUS, "unknown")
        trust_quiescence = _get(last, "quiescence_proven")
        if type(trust_quiescence) is bool:
            quiescence_proven = trust_quiescence
        if not finished:
            # With a terminal top-level Docker Tester, the WORKFLOW verdict
            # outranks a child Coder's narrower canonical check.
            verification = _status(
                _get(last, "verification_status"), _VERIFICATION, "unverified")
        value = _get(last, "native_stop_reason")
        stopped = _status(value, _NATIVE_STOPS, "") or None
        # Stage events may already carry these reasons. Do not count twice:
        # prefer the complete report list when supplied by the host.
        native_stops.clear()
        for report in reports:
            reason = _status(_get(report, "native_stop_reason"), _NATIVE_STOPS, "")
            if reason:
                native_stops[reason] += 1
    if not reports and verifier_results and not finished:
        verification = verifier_results[-1]
    if stopped is not None and not native_stops[stopped]:
        native_stops[stopped] = 1

    # Classification is diagnostic, preserving *both* native and verifier
    # dimensions; code-verification passing does not imply normal termination.
    if trace_integrity != "verified":
        outcome = "TRACE_INTEGRITY_INVALID"
    elif not finished:
        outcome = "WORKFLOW_INCOMPLETE"
    elif stopped is not None:
        outcome = "VERIFIED_WITH_NATIVE_CAP" if verification == "passed" else "NATIVE_BUDGET_EXHAUSTED"
    elif native in ("failed", "cancelled", "timed_out"):
        outcome = "NATIVE_EXECUTION_INCOMPLETE"
    elif native != "completed":
        outcome = "NATIVE_TERMINAL_UNKNOWN"
    elif verification == "passed":
        outcome = "CODE_VERIFIED"
    elif counts["workflow.repair.budget_exhausted"]:
        outcome = "REPAIR_BUDGET_EXHAUSTED"
    elif verification == "failed":
        outcome = "CANONICAL_TESTS_FAILED"
    else:
        outcome = "UNVERIFIED"

    elapsed_ms = None
    if first_time is not None and last_time is not None and last_time >= first_time:
        elapsed_ms = int((last_time - first_time).total_seconds() * 1000)
    # The trace contains zero price authority. No "cost_usd" is emitted.
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "host_runtime_trace",
        "execution_kind": ("developer_workflow" if counts["workflow.started"]
                           else "single_node_mvp" if last_mvp_payload is not None
                           else "unknown"),
        "trace_integrity": trace_integrity,
        "event_count": len(records),
        "workflow_finished_observed": finished,
        "outcome_category": outcome,
        "result_scope": ("code_verification_only" if verification == "passed"
                         else "not_code_verified"),
        # This adapter produces MVP reports, not a strict Scheduler-ACCEPTED
        # handoff. Quarantined verification must never be presented as such.
        "strict_scheduler_acceptance": "not_attested_by_mvp",
        "mvp_delivery_status": delivery,
        "scheduler_node_status": scheduler_status,
        "quiescence_proven": quiescence_proven,
        "verification_status": verification,
        "native_status": native,
        "native_stop_reason": stopped,
        "elapsed_observed_ms": elapsed_ms,
        "model_turns": counts["model.turn.finished"],
        "token_reported_turns": token_reported_turns,
        "token_usage_reported": dict(sorted(tokens.items())),
        "tool_calls": counts["tool.call.finished"],
        "tool_status_counts": dict(sorted(statuses.items())),
        "tool_failure_code_counts": dict(sorted(denied.items())),
        "anomaly_timeline": anomaly_timeline[-32:],
        "repair_rounds_scheduled": repair_rounds,
        "repair_budget_exhaustions": counts["workflow.repair.budget_exhausted"],
        "native_stop_reason_counts": dict(sorted(native_stops.items())),
        "independent_verifier_results": verifier_results,
        "dag_tester_results": dag_tester_results,
        "child_canonical_verifier_results": canonical_verifier_results,
        "scheduler_dispatches": counts["dag.scheduler.dispatch"],
    }
