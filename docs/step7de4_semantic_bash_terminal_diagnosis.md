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
1. Keep \`classify_bash\` as the strict, single-command E1 authority. Any
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
   \`aswe.reliability.v1\` retains its existing contract with additional
   bounded, redacted diagnostic properties.

## Preregistered natural #565 live diagnosis
- Single genuine model attempt, original \`CASES["565"]\` complete-spec task
  and frozen boltons source \`4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d\`.
- DeerFlow frozen at \`c0895d295bba34f6e95188fca380f555dabed891\`;
  isolated pinned Docker Python 3.12, existing model secrets.
- \`adaptive=True\`, \`planner=llm\`, \`explorer_mode=llm\`,
  \`physical_dag=True\`, \`max_repairs=1\`, original native cap/timeout.
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
