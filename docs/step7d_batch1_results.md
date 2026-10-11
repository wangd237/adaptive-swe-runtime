# Step 7D — first expanded natural-issue batch

Frozen runtime main: `bd9478adcd628262c0e01ea7862f7fa4f799bdba`.
Frozen upstream Boltons SHA: `4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d`.
Frozen DeerFlow: `c0895d295bba34f6e95188fca380f555dabed891`.

Two genuine public issues with independent host-owned failing regression baselines:
- [#551](https://github.com/mahmoud/boltons/issues/551) — key computation repeated; singleton key error not surfaced.
- [#524](https://github.com/mahmoud/boltons/issues/524) — byte unit promotion on rounding boundaries.

Cases and tests are fixed before any paid inference. Real Planner, Explorer,
Coder, Tester, bounded Repair; no pre-written patch or model mocks. Both
successes and failures are published through independent Actions artifacts.
Temporary paid exact-branch+marker workflow is removed after execution.
This survey is exploratory and has no statistically meaningful success rate.

## Executed natural first-attempt runs

Both additional natural full-spec cases completed successfully under the
unmodified Practical Runtime and were independently verified in
[GitHub Actions #38129653670](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38129653670).

| Case | Natural status | Turns | Tools | Provider tokens | Coder Handoff | DAG Tester | Repair |
| --- | --- | ---: | ---: | ---: | --- | --- | ---: |
| #551 — once-per-element key | PASSED | 20 | 21 | 154,255 | accepted | passed | 0 |
| #524 — rounding unit promotion | PASSED | 22 | 38 | 400,654 | accepted | passed | 0 |

For **both**: independent original baseline failed, model and tools were real,
source was modified in the isolated worktree, independent host-owned tests
and original upstream checkout were unchanged, native status ended normally
without `turn_capped`, child Scheduler `succeeded`, practical Handoff was
accepted, and independent DAG Tester returned `passed`.
Both raw artifacts are attached to that Actions run. Runtime code was not
changed to accommodate either Issue.

### First five DISTINCT Issue IDs (natural full specification only)

| Issue | Natural first attempt | Evidence |
| --- | --- | --- |
| #500 | PASS | [Run #38128289849](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38128289849) |
| #553 | PASS | [Run #38125554066](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38125554066) |
| #565 | FAIL — `turn_capped`, no Handoff or DAG Tester | [Run #38128598465](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38128598465) |
| #551 | PASS | [Run #38129653670](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38129653670) |
| #524 | PASS | [Run #38129653670](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38129653670) |

**Observed success: 4/5 distinct natural first attempts.** This is only a
small smoke sample, not a rigorous success-rate estimate: all five are in one
Python library, acceptance tests are task-specific and readable to the Agent,
and one model invocation per task cannot quantify stochastic variation.

Separately, real hosted-model **controlled staged-spec** #565 Repair passed in
[Run #38128977562](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38128977562).
Do NOT overwrite the natural #565 failed outcome with the staged result.

### Reliability implications

- High provider token spend remains an issue: natural #524 required **400,654**
  reported input+output tokens (379,787 input, 20,867 output) for a short
  rounding bug; the model completed 22 turns and 38 tool calls. Cost is not
  computed without a model-specific price.
- Natural #565 `turn_capped` before proper terminal conclusion despite a
  diagnostic-only test pass; improve end-of-task reasoning and stopping
  behavior, not Handoff bypasses.
- #500's actual denied read-before-write tool call recovered without user
  intervention; repeat safety remains meaningful.
- No production-grade claim or statistical SWE-bench comparison is made.

The temporary paid branch push workflow was deleted. The final eval
`.github/workflows/swe-step7d-manual.yml` is manually authorized by
`workflow_dispatch` and explicit `RUN` only, never by normal push/PR.
