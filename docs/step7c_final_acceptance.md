# Step 7C — Reliability & Observability: Mechanism Acceptance Closure

**Date:** 2026-10-11  
**Baseline:** main `2361185e4675ba2a451a3598f8e36bd47a865cec`  
**Scope:** bounded, single-owner Practical SWE acceptance (NOT strict
multi-tenant sandbox quiescence, and NOT a statistical benchmark).

## Decision

Step 7C **mechanism acceptance** is complete on this frozen implementation.
A reproducible, provider-backed real open-source Issue produced a natural
read-before-write tool rejection and recovered; an independent physical DAG
accepted a real host-owned Coder Handoff; and a genuine second Issue in a
**controlled staged specification** demonstrated an independent failed
Tester followed by a real LLM Repair and second accepted Handoff.

**Do not infer reliable repair frequency or real-world success rate.**
The next workstream is a larger, fixed-budget, diverse, pre-registered Issue
suite, tracking all attempts (including failures and timeouts).

## Acceptance ledger

| Gate | Result | Evidence |
| --- | --- | --- |
| Baseline reproducible, original code unmodified | PASS | Actual host-owned boltons #500 / #553 / #565 baseline tests |
| Recoverable real tool policy denial | PASS | #500 had 1 actual `SWE_READ_BEFORE_WRITE_REQUIRED`; Agent finished correctly |
| Native terminal semantics | PASS | No `turn_capped` on successful #500 and #553; rejected cap on natural #565 |
| Host-owned Practical NodeHandoff and Scheduler | PASS | #500 and #553 child `succeeded`, independent DAG Tester `passed` |
| Real model multi-round Repair mechanism | PASS (controlled staging) | #565 staged: Tester failed → Repair scheduled → Coder edited again → Tester passed |
| Failed/partial native result cannot bypass Handoff | PASS | Natural #565: diagnostic regression passed but native `turn_capped`, no Handoff, DAG Tester did not start |
| Python 3.11/3.13 and pinned DeerFlow physical graph | PASS | PR #25 checks and merged-main CI |
| Evidence provenance and fail-closed resource lifecycle | PASS (bounded profile) | Host guard, live Docker, workspace fingerprint and tampered-proof negative tests |
| Unscripted natural Repair occurrence rate | NOT MEASURED | Control was staged; do not count as spontaneous Repair success |
| Statistical reliability across 5–10 Issues | NOT YET MEASURED | Begin expanded evaluation separately |
| Strict full process-tree/historical-side-effect quiescence | OUT OF SCOPE | Practical intentionally differs from Strict |

## 1. Genuine natural Issue #500 — cross-Issue Practical success

- [Run #38128289849](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38128289849)
- Upstream: `mahmoud/boltons#500`, pinned source
  `4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d`.
- Real LLM model turns **16**, actual tool calls **24**, of which 1 was
  rejected by read-before-write guard and 23 completed.
- Scheduler `succeeded`; `practical_scheduler_handoff=true`,
  `quiescence_proven=true`; nonempty accepted Handoff fingerprint.
- Independent DAG Tester passed; normal uncapped native exit, one Coder round.
- Source patched, independent regression untouched, upstream original clean.
- Provider-reported tokens: 121,602 input, 5,436 output, 127,038 total.
  No inferred dollar cost.

## 2. Genuine natural Issue #553 — cross-Issue Practical success

- [Run #38125554066](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38125554066)
- Real Explorer → Coder → independent Tester, Scheduler child
  `succeeded`; accepted Handoff and final independent Tester passed.
- 18 model turns, 23 guarded tool calls, zero Repair rounds.
- Same pinned upstream source; actual model changed production, host-owned
  regression remains unmodified.

## 3. Genuine natural Issue #565 — useful FAILURE

- [Run #38128598465](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38128598465)
- Full Issue specification, 24 model turns, 28 tools; `turn_capped`
  before normal Coder completion. Its changed final filesystem passed a
  separate **diagnostic-only** test, which is NOT a Scheduler Handoff or
  the scheduled independent Tester.
- Correct fail-closed behavior: child Scheduler failed, no Handoff, no
  formal independent DAG Tester, no Repair. This is **not** a resolved
  natural Issue. It motivates observing terminal-budget efficiency.

## 4. Genuine Issue #565 with CONTROLLED first-stage specification

- [Run #38128977562](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38128977562)
- Same source and all ten host-owned independent regression tests from the
  beginning. The **first Coder task specification is intentionally restricted
  to IGNORECASE**. Upon genuine `test_failure_output`, further flags are
  included in the requested Repair scope; no model tool result, patch or
  Tester response is mocked.
- First Coder normal completion and Handoff: `succeeded`; independent
  Tester **failed**.
- Scheduler actually scheduled **1 Repair**, invoked a real external LLM
  for the second Coder with real feedback, generated a **different** new
  Handoff (`succeeded`), and independent Tester **passed**.
- 36 total model turns, 42 guarded tool receipts (one denied), two Coder
  rounds, preserved original source and host-owned tests.
- This passes the **real-model Repair mechanism** gate; controlled staging
  means it cannot measure spontaneous Repair frequency.

## Trust boundary and operational hygiene

- `Practical` attests real host-controlled tools, bounded native task drain,
  Docker command lifecycle, current Git-visible post-state, and persisted
  evidence. Excluded cache/build histories are not claimed complete.
- `Strict` retains its original stronger fail-closed checks; reports never
  present a Practical Handoff as strict acceptance.
- Positive Coder Handoff is about a stable edit, not successful tests.
  Independent Tester owns code correctness and Repair scheduling.
- Both one-off paid push triggers were **deleted** from their acceptance
  branches after execution; preserved reproducible scenarios on `main`
  must require explicit `workflow_dispatch authorization=RUN`.
- The benchmark suite is separate and must report every selected Issue and
  attempt (including failures) without cherry-picking.

**Outcome:** Close Step 7C as bounded runtime-mechanism acceptance; proceed
to expanded multi-Issue reliability evaluation. Do not label the runtime
production-grade or SWE-bench validated.
