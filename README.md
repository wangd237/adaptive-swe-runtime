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

## Step 6B — Developer CLI coding entry (experimental)

With frozen DeerFlow installed (Python 3.12+), Docker available and a
digest-pinned Python image locally present, configure `OPENAI_API_KEY`,
`ASWE_MODEL` and optional `ASWE_BASE_URL` in the **host environment**.

```bash
aswe run "Fix the failing Python unit tests" \
  --repo /path/to/clean-git-repo \
  --runtime-dir /tmp/aswe-runs \
  --docker-image 'python@sha256:<local-image-digest>' \
  --check-command 'python -B -m unittest discover -s tests -q'
```

`aswe run` clones a pinned Git baseline into a new isolated worktree under
`--runtime-dir`, compiles the single Writer node, uses the actual model and
native DeerFlow graph with guarded Runtime tools, then runs an independent
Docker-isolated canonical Python test. It emits `report.json` and
`events.jsonl`. The original repository remains untouched. Model arguments
and patch contents are not included in JSONL trace.

**Initial limitations:** one compiled writer node; user supplies trusted
test argv and pre-pulled Docker digest. No automatic multi-agent DAG planning,
no production RBAC and no formal Sandbox Quiescence attestation. A passed
canonical test is reported separately from strict Scheduler acceptance.

## Step 6C — Correlated Execution Timeline

The existing `aswe trace TASK_ID --runtime-dir PATH --json` command now
presents a single append-only timeline combining compiled plan identity,
task lifecycle, Scheduler dispatch request/claim, committed
`execution_id`/`run_id`/`attempt`, **observed native LangGraph model
turns**, tool receipts, independent canonical verification and the
single-node MVP repair decision.

Model-turn events carry only ordinal and tool-call counts, not model
messages, prompts or provider credentials. Tool events carry digests,
not arguments or outputs. `repair.decision: not_scheduled` accurately
states that Step 6's one-writer CLI does not yet run a Scheduler repair
branch; it is not a fictitious Repair execution.

The CLI does not yet compile or run dynamic multi-node plans. Complex DAG
and real retry/repair timelines remain later Step 6 work.

## Step 6D — Multi-file repair and DAG status (initial scope)

Step 6D begins with a **physical two-file repair E2E**: the frozen
DeerFlow/LangGraph agent reads two files, corrects the first, encounters a
failed Docker check, corrects the second and passes independent Python
regressions. The resulting `events.jsonl` carries the model/tool/check
sequence and both modified paths. CI uses an offline scripted model; user
CLI continues to use the real provider.

A separate **real two-node Scheduler DAG** regression verifies the current
quarantine constraint: when a native writer finishes without independent
Quiescence attestation, its dependent verifier node is BLOCKED and receives
zero execution attempts. The Runtime records `scheduler.node.blocked`
rather than fabricating a successful dependency or repair.

**Not yet shipped:** automatic continuation of a multi-node native Coding
DAG or Scheduler-level Repair. Those need a developer-mode stage isolation
design, without weakening the existing strict Scheduler acceptance contract.

## Step 6D — Developer Coder / Tester / Repair workflow

`aswe workflow` is an opt-in lightweight multi-round task command. It
reuses the real frozen-DeerFlow `aswe run` coding entry for each round,
independent Docker canonical tests as the **Tester** stage, and performs a
bounded Repair round **only when the canonical check fails**.

```bash
aswe workflow "Fix the failing tests" \
  --repo /path/to/clean-repository \
  --runtime-dir /tmp/aswe-runs \
  --docker-image 'python@sha256:<local-digest>' \
  --check-command 'python -B -m unittest discover -s tests -q' \
  --max-repairs 1
```

Each round retains its own exact child task trace and report; a top-level
workflow trace links their events and records Coder, Tester, Repair and result.
A repair starts from the previous round's *disposable clone*, with its
changes committed as an intermediate development checkpoint. The original
repository remains untouched. Failed or unverified native executions do not
automatically qualify for repair; only an independently observed canonical
test failure does.

This is a developer workflow, **not** multi-node strict Scheduler acceptance
or a production multi-agent architecture. Each coding round still has a
separate Scheduler task and native quarantine semantics. The final verdict
is a canonical test result, not an `ACCEPTED TaskResult`.

## Step 6E — Adaptive minimum-team selection (first increment)

Use `aswe workflow ... --adaptive` to enable a bounded, developer-mode
topology selector. Small, clearly anchored edits select `coder`; multi-file,
cross-module, or unclear code locations select `explorer → coder → tester`.
The Explorer uses the real repository Git index to supply bounded candidate
paths to the existing native DeerFlow Coding Agent. The existing independent
Docker verification remains the Tester, and canonical failures may trigger
the existing limited Repair workflow.

`team.selected` and `explorer.finished` events record the selection basis
and actual inspected path candidates in the workflow Trace.

**Scope honesty:** this first increment uses a deterministic minimal-team
policy rather than an LLM SemanticPlanner; Explorer is read-only repository
discovery rather than a separate LLM agent. It does not yet dynamically
compile and dispatch a multi-node Scheduler DAG. This is a functional step
toward the original Adaptive Team Formation plan, not its completion.

## Step 6E — Optional LLM-guided developer team planning

`aswe workflow --adaptive --planner llm` uses the configured
`OPENAI_API_KEY`, `ASWE_MODEL` and optional `ASWE_BASE_URL` to ask an LLM
for a **structured minimum-team proposal** (Explorer needed or direct Coder,
plus bounded coding/exploration objectives). The user task remains in the
Coder objective. Runtime restricts available roles and continues to own the
actual tools, policy, Docker tests and bounded Repair decisions.

Example (same repository, image and check-command flags as `aswe workflow`):

```bash
aswe workflow "Investigate regression across orders and inventory" \
  --adaptive --planner llm \
  --repo /path/to/repository --runtime-dir /tmp/aswe-runs \
  --docker-image 'python@sha256:<digest>' \
  --check-command 'python -B -m unittest discover -s tests -q'
```

This is a developer **LLM topology proposal** connected to real repository
exploration and Coder/Tester execution, not yet a complete integration of
the frozen SemanticPlanner/PlanValidator/TaskDAG for independently executed
multi-agent nodes. Rules-based `--adaptive` remains the no-extra-LLM default.

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
