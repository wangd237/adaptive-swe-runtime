# Adaptive SWE Runtime

Implementation repository for **Adaptive Agent Runtime for Software Engineering (A-SWE Runtime)**.

> **A-SWE is the control plane. DeerFlow is an execution plane.**

## Current status — Developer MVP (2026-10-10)

**Coding Steps 0–5 have been merged to `main`.** Step 5 DeerFlow integration was merged via [PR #7](https://github.com/wangd237/adaptive-swe-runtime/pull/7) (merge `1fa6e5858cdb3f06253cd5c2e40370a308440e3c`).

A-SWE is a **developer-oriented, task-adaptive Software Engineering Agent Runtime**, not a production hosted-agent platform. Core owns task planning, capability/provider policy, compiled Task DAG, Scheduler/Workspace/Evidence, repair and canonical verification. The DeerFlow adapter executes a controlled SWE coding loop through an exact pinned [DeerFlow](https://github.com/bytedance/deer-flow/tree/c0895d295bba34f6e95188fca380f555dabed891) implementation. Runtime-owned Docker Bash is distinct from the upstream host Bash tool.

**Demonstrated:** an offline scripted model with the actual pinned DeerFlow/LangGraph runtime, real Scheduler commit and 5C/5D admission, actual isolated Docker coding commands, Git changes and independent canonical Python tests ([native CI](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38032079301)); also one separately triggered real-model smoke with a successful code change and independent test ([run](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38018937188)). These are engineering smoke tests, not a benchmark or broad task-success claim.

**Known limitation:** native Sandbox Quiescence is not formally attested. The strict Scheduler may quarantine a coding attempt even when separate canonical tests pass. The MVP report states this distinction; it must not be represented as a strictly `ACCEPTED TaskResult`.

**Next: Step 6 — SWE Agent Usability & Observability.** Focus on a usable CLI/task entrypoint, execution trace, multi-file coding tasks, and richer task/DAG/repair demonstrations. Full formal sandbox quiescence, production RBAC, distributed scheduling/Workspace and enterprise platform features are **out of scope**, not deferred release blockers. Keep existing correctness checks; do not weaken Scheduler evidence or silently claim production guarantees.

## Step 6 — CLI & Execution Trace (first increment)

Install for local inspection: `pip install -e .`.

```bash
aswe trace TASK_ID --runtime-dir ./runtime-data --json
aswe trace TASK_ID --runtime-dir ./runtime-data --tail 20
aswe report ./mvp-report.json
aswe report ./mvp-report.json --json
```

The MVP Runner can now emit append-only `mvp.task.started` and
`mvp.task.finished` events through an optional `LocalRuntimeEventSink`.
Events contain bounded status/identity metadata rather than prompts, command
output or patch bodies. Canonical verdict and strict Scheduler quarantine
remain distinct.

**Scope:** this first CLI increment inspects existing runs; it does *not*
yet submit a new coding task, initialize a model, or create a native
DeerFlow execution session. An actual `aswe run` entrypoint and per-tool /
per-node tracing are next, not already delivered.

## Accepted implementation

- Provider-neutral frozen contracts and two-stage deterministic TaskDAG identity (Step 0).
- Local immutable attempt/task EvidenceStore and minimal trace events.
- Git bootstrap to pinned SHA; isolated temporary-index working tree digest and per-attempt patch attribution.
- Workspace snapshots/revision evidence, reader/writer access, quiescence-gated FROZEN vs QUARANTINED lifecycle.
- Scheduler on FakeBackend: deterministic dispatch, Retry/Repair/Reverify, provenance-bound canonical feedback, cancellation/race gates and TaskResult four-axis finalization (Step 2).

Step 1 reviewed in [PR #2](https://github.com/wangd237/adaptive-swe-runtime/pull/2). Step 2 accepted through [PR #4](https://github.com/wangd237/adaptive-swe-runtime/pull/4) and [final source review](audits/step2-finalization-review.md).

## Architecture and design authority

- [AGENTS.md](AGENTS.md): coding constitution / no silent design drift.
- [Master Plan](plan/master-plan.md): mandatory Coding Step 0–8 order.
- [Frozen Specs](specs/): implementation contracts.
- [Step 0 Review](audits/step0-implementation-review.md) / [Step 1 Review](audits/step1-implementation-review.md).
- [Implementation Status](IMPLEMENTATION_STATUS.md): current progress and next gate.
- Frozen design pin: [PLAN_SOURCE](design/PLAN_SOURCE.md).

## Tests

Install dev requirements and run:

    python -m pip install -e ".[dev]"
    python -m pytest

No DeerFlow dependency or LLM integration has been added.


## Step 4 physical integration (historical milestone)

- Canonical provider-neutral Capability registry, FakeBackend Inventory, ToolEffect and WorkspaceAccess resolution, materialized phase TaskDAG / exclusive WRITEs, real Git Tester post-node guard.
- Frozen Stage-3 P3 physical scenarios 01/02/03/04/11 PASS on Step-4 branch, but the complete Step-4 adapter / live preflight / policy descriptor is **not yet accepted**.
- Review: [Step-4 physical PoCs](audits/step4-physical-poc-audit.md).


## Coding Step 5 — DeerFlow Adapter (historical implementation notes)

- Isolated adapter namespace: `src/aswe/integrations/deerflow/`. First slice captures source-attested candidate BackendInventory from pinned DeerFlow `AppConfig`, actual eager tools, Subagent registry and observed Sandbox features.
- Exact pinned upstream: `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891`. The DeerFlow harness requires Python >=3.12. A-SWE Core unit CI remains Python 3.11/3.13.
- Historical pre-release status; Step 5 Developer MVP merged with its documented non-production limitations. [Stage 5 entry](plan/step5-implementation-entry.md) · [source audit](audits/step5-gate-audit.md).


### Step 5B — Model-only reasoning adapter

- `DeerFlowReasoningBackend` implements Core `ReasoningBackend`; `ModelInvoker` selects a trusted explicit model from pinned AppConfig, applies current model-use AuthorizationProvider policy and validates strict JSON Schema outputs.
- No tool-binding/Scheduler attempts and no model-supplied execution grants. [Step 5B audit](audits/step5b-model-invocation-review.md) records exact test and native-provider verification limits.
