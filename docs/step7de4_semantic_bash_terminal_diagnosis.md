# Step 7D-E4 — Semantic Bash & Terminal Behavior Diagnosis

## Problem and evidence before instrumentation
Natural complete-spec Boltons Issue #565 still fails under the original
24 logical-turn / physical timeout limits. Step 7D-E3's controlled four-job
comparison is at
https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38216766755 :
- #565 pre-E1/E2: **failed** (turn_capped, 24 model turns, 15 Bash calls,
  352,373 provider-reported tokens), no accepted Coder Handoff / Tester.
- #565 post-E1/E2: **failed** (timed_out after 15 model turns, 20 Bash calls,
  183,853 provider-reported tokens), no accepted Handoff / Tester.
- E3's common simple-test proxy recognized **zero** simple test events,
  so no measured post-test waste rate exists. Zero proxy counts are NOT
  evidence that waste is absent.

## Scope: diagnosis, not behavioral change
1. Keep `classify_bash` as the strict, single-command E1 authority. Any
   compound, inline script or ambiguous command remains outside agent-local
   passing/failing test evidence. The host-owned independent Tester is
   never replaced.
2. Add a read-only, fixed-label shell *morphology* diagnostic to each
   ToolCallGuard Bash receipt: single / compound / unknown; bounded
   syntactic step count; test/search/inspect step **possibly present**;
   test-verdict-attributable; and a fixed family label (ordinary, inline
   Python, Python heredoc, nested shell, multiline, unknown).
   No commands, output, script bodies, paths or content-derived
   classifications are emitted. For compound Bash, overall exit code
   cannot tell which constituent command ran, let alone passed.
3. Aggregate host-observed event order only: recognized simple test passes
   following tracked file-tool edits; subsequent model turns, Bash calls,
   non-test Bash calls and edits up to the next edit; model turns that
   requested tools or no tools; last turn's tool count; bounded redacted
   semantic tail. Unknown or absent test denominator means **null**
   post-test metrics, not zero.
4. Keep Runtime budgets, model instructions, Agent prompts,
   ToolGuard authority, Workspace restrictions, native graph and
   Scheduler/Handoff/independent Tester acceptance untouched.
   `aswe.reliability.v1` retains its existing contract with additional
   bounded, redacted diagnostic properties.

## Preregistered natural #565 live diagnosis
- Single genuine model attempt, original `CASES["565"]` complete-spec task
  and frozen boltons source `4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d`.
- DeerFlow frozen at `c0895d295bba34f6e95188fca380f555dabed891`;
  isolated pinned Docker Python 3.12, existing model secrets.
- `adaptive=True`, `planner=llm`, `explorer_mode=llm`,
  `physical_dag=True`, `max_repairs=1`, original native cap/timeout.
- A valid success requires *all* original guarantees: failing host baseline,
  production change, untouched independent tests, normal native completion,
  accepted Practical Coder Handoff and passed independent DAG Tester.
  A failure remains failure regardless of apparently promising patch or
  reduced token spend.
- Report the new Bash-shape/family distribution and semantic execution tail,
  explicitly distinguishing observed from unknown. Do not infer human
  "waste" or counterfactual improvement from these categories alone.
- A one-time scoped paid push workflow, if run, must be deleted immediately
  after the evidence is collected; permanent paid jobs remain typed-RUN
  manual only. No automated paid jobs may land on main.

## Known measurement gaps
- Python inline code, heredocs and unparsed shell grammar are **opaque**;
  they cannot be trusted as a passing test. Recognizing their family only
  helps determine why E1 lacks observations.
- A simple recognized test pass is agent-local and may be invalidated by
  untracked Bash-side modifications, not just by file-tool writes.
- "Post-pass non-test tool count" is a **proxy**, not a waste label:
  checking a diff or fixing a newly discovered bug can be necessary.
- A timed_out/capped native status proves absence of normal Handoff, but
  alone does NOT reveal the model's hidden intentions or prove that a
  correct patch was ready.
- This is one case in one library and one stochastic model trajectory; do
  not generalize a measured success rate or causality from it.


## Executed real LLM diagnosis — 2026-10-12

Actual [Actions #38220588467](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38220588467)
artifact: `step7de4-natural-565-redacted-evidence`, ID `11733714441`.
Same pinned upstream Boltons SHA, DeerFlow SHA, host tests SHA, provider
configuration fingerprint and Docker image digest as Step 7D-E3.
Runtime probe SHA: `68d3ddb60dc3c1fc83f8f355a5de92d644688ea9`.

**Real outcome: FAIL.** Host regression baseline failed (valid reproduction),
production source changed, host tests and upstream were unmodified.
Native **turn_capped**; Scheduler **failed**; accepted Handoff **absent**;
independent Tester **not dispatched**, no Repair round. One actual
`SWE_READ_BEFORE_WRITE_REQUIRED` tool denial was observed but was not
the terminal cause. No post-run diagnostic patch pass is counted.

| Observation | Actual |
| --- | ---: |
| Model turns / configured logical cap | **24 / 24** |
| Turns requesting at least one tool | **24** |
| Turns requesting no tools | **0** |
| Last model turn tool calls | **1** |
| Total guarded tools | **30** |
| Bash tools | **19** |
| Read file tools | **7** |
| str_replace attempts | **4** (one denied) |
| Bash shape: compound / unknown | **3 / 16** |
| Bash family: multiline / ordinary | **8 / 11** |
| Syntactically recognizable potential test-step calls | **0** |
| Agent-recognized test events / successful checks | **0 / 0** |
| Post-recognized-pass proxy | **null** (no valid denominator) |
| Exact repeated argument calls | **0** |
| Model phase turns: exploring / code_modified | **12 / 12** |
| First → last input tokens per model turn | **1,071 → 21,734** |
| Provider-reported total tokens | **349,911** |
| Measured model-request duration (24 requests) | **81,231 ms** |
| Measured guarded-tool duration (30 calls) | **8,614 ms** |
| Trace elapsed time | **104,879 ms** |

### Causal interpretation and limits

**Proven terminal behavior:** the model asked for tools in **every**
one of 24 recorded turns, including the last. The original native turn
cap then fired; no normal model final message or accepted Coder Handoff
was available for independent Tester dispatch. This is a terminal
decision failure under the existing budget, not a Tester failure. The
cap itself is functioning as intended and should not be bypassed.

**Strong diagnostic hint:** no standalone, recognized test-like Bash
command returned a trusted agent-local check event. Therefore E2's
**test-pass-dependent** completion hint could not be triggered in this
run. This does NOT prove no actual test ran: 16 Bash commands were
unparsed/opaque and 8 were multiline, and 3 were recognized as compound
command shapes. Their individual outcomes cannot be attributed safely.

**Not established:** whether the model had already produced a correct
patch when it continued; exactly how many operations were semantically
redundant; whether the near-budget hints were actually appended (the
current trace does not attest each hint emission); whether a different
prompt or a higher turn cap would have solved the issue. No self-reported
model intention, synthetic Handoff or post-hoc acceptance is inferred.

The most defensible working hypothesis is that a long sequence of
agent-selected Bash probes, with few safely recognizable test results
and continued tool-choice, leaves the model without a reliable stopping
checkpoint. The cap and safety gates are **not** identified as bugs.

### Recommendation — targeted next implementation, NOT part of E4

1. Trace **which existing E2 hints were actually emitted** (fixed boolean
   flags only) and whether the next model turn was final or another
   tool request. First determine whether hints were absent or ignored.
2. Encourage standalone, focused unittest/pytest commands when practical,
   while preserving opaque/compound calls as non-authoritative. This may
   improve recognition of agent-local test results, but cannot replace
   independent Tester.
3. Introduce a **narrow evaluation** of completion guidance after
   sufficient host-observed work, before proposing behavior changes.
   Keep the original cap, unchanged tools, and normal final response
   requirement; no forced completion, Handoff synthesis or Scheduler
   complexity. Prove any change with a matched full-spec #565 attempt.
4. If command-level semantic waste must be quantified, use an explicitly
   approved private, restricted trace analysis with safe retention.
   The present redacted public artifacts are intentionally insufficient
   to reconstruct raw shell instructions.
