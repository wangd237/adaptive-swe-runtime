# Step 6G: Unified Developer Scheduling and Real Repair Acceptance

The Adaptive physical TaskDAG now has a single top-level developer controller
for dependency readiness, node attempts, canonical verification, and repair
budget. The native DeerFlow Coder still uses its internal strict
`SchedulerCore` and does **not** claim global strict multi-node acceptance.
This is a Developer MVP, not a production quiescence proof.

Repair diagnostics are now delivered from the **independently dispatched
Docker Tester** directly into the next real Coder model prompt, bounded and
redacted. The raw failure output does not enter the public Trace/report;
only its SHA-256 and byte length do.

## Real model repair acceptance

An explicitly paid Actions run uses existing `SWE_LLM_*` Secrets and calls
real LLM Planner, Explorer and native DeerFlow Coder. A controlled two-milestone
cross-module issue first asks for the inventory fix, then a legitimate full
regression suite tests order idempotence, with one authorized Repair attempt.
Unlike previous offline scripted tests, neither Coder pass is scripted; only
the source fixture and trusted canonical test requirements are defined by
the harness.

This is a **controlled staged task**, not proof that an arbitrary real-world
issue will fail on the first attempt and self-repair. The acceptance requires
a genuine first Docker FAIL, a real feedback fingerprint, a second genuine
native LLM edit, a second Docker PASS, and unchanged test sources. If the first
Coder solves everything, that is an ordinary pass but not a Repair acceptance.

The first paid run used a temporary explicit branch marker. The successful
run is complete and this workflow is now **manual `RUN` only** on `main`.


## First real repair attempt

[Run 38050394522](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38050394522)
observed two genuine native model rounds, a failed then passing
independent Docker check, and two modified implementation modules.
The Actions job still failed because the harness mixed the native tool
guard's `repair.feedback.available` events with the top-level canonical
tester's feedback event, and incorrectly required Explorer even when
the real adaptive planner validly chose a single Coder.

The assertions are now fixed to identify the exact canonical feedback
source and accept a legitimate minimum-sized team. A fresh paid run
will confirm a clean acceptance verdict. The first attempt is reported
as *observed repair behavior*, not a passing acceptance run.

## Two-tier verification refinement

A later live run
[38050590455](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38050590455)
fixed both defects on the first pass with a real model (no Repair needed),
showing natural nondeterminism even for a staged task. To test real
failure-driven Repair *reproducibly*, the developer workflow now supports
a narrower **first-pass Coder unit check** and a separate authoritative
**full DAG Tester check**. These are both actual Docker test executions,
not injected synthetic failure status. On Repair, the inner Coder also runs
the full suite.

The new real-model fixture adds `tests/test_inventory.py`:
Coder initially focuses on inventory stock restoration with the narrow
test; the independent Tester exercises the full order-cancellation suite.
The genuine idempotency failure, if still present, is passed as diagnostic
feedback to the next **real LLM** Coder. Both source modules and all tests
are checked for modifications at the end.

This is controlled progressive test coverage, not proof of spontaneous
Repair frequency on arbitrary GitHub Issues.

## Explicit final two-tier real-model run

This run uses a focused inventory unit test in the first genuine Coder pass,
then the authoritative full cancellation regression in the DAG Tester.
Both external coding rounds, when a Repair is needed, are real model calls.
Only GitHub Actions with existing Secrets may run it. No patch is injected.

## Final acceptance — PASSED (2026-10-10)

Successful external-model Actions run:
https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38050950435

The separately uploaded `aswe-real-llm-repair-result` artifact confirms:

| Requirement | Observed |
|---|---|
| Scripted models | No; genuine external LLM |
| Task DAG physically compiled | Yes |
| Adaptive selected team | Minimal `coder` for this task (valid) |
| DAG dispatch order | `coder → __aswe_verify → coder → __aswe_verify` |
| First Coder check | Focused inventory unittest — passed |
| First independent Tester | Full cancellation suite — **failed** |
| Failure feedback | SHA-256 `4494c21b811a179df3ff2839c2a0f55824af3fe297e89f5db5c84483c81a0bed` |
| Repair scheduling | 1 authorized Repair round |
| Second Coder | Real LLM; native execution completed |
| Second independent Tester | Full cancellation suite — **passed** |
| Coder attempts | 2 |
| Native model-turn events | 15 |
| Tool-call events | 24 |
| Modified code | `shop/inventory.py`, `shop/orders.py` |
| Test sources | Unchanged |
| Final outcome | **PASS** |

In this controlled progressive-testing scenario, the first Coder runs a
focused unit check, while the separately dispatched Tester runs the full
regression suite. The first genuinely failing full regression is not
injected or fabricated. Its diagnostics are supplied as *untrusted test
data* to the next real LLM, which fixes the outstanding cancellation issue.

Earlier attempts demonstrate why the new acceptance is necessary:
[38050394522](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38050394522)
observed genuine `failed → passed` Repair but the test harness mistakenly
counted child tool-guard feedback as top-level feedback and rejected valid
single-Coder team selection;
[38050590455](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38050590455)
saw the first real model fix both bugs immediately, so no Repair was needed.

This final passed run proves a **real-model bounded repair loop**, but does
not prove all real Issues repair themselves, or strict global SchedulerCore
NodeHandoff acceptance. The top-level developer scheduler owns the physical
DAG's scheduling and repair decisions; each native coding invocation still
uses its internal strict SchedulerCore to govern tool execution.
