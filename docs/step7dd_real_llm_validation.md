# Step 7D-D: Genuine real-model efficiency and terminal reliability comparison

## Registered before paid invocation

**Runtime:** `0b49eaa5ac94e6f6d2d1092c2aa86de294219c2e`, with
**evaluation-only** instrumentation added to `scripts/step7d_real_issue_eval.py`
(no edits to Runtime, Planner, Coder, ToolCallGuard or Scheduler).

**Pinned source:** `mahmoud/boltons` commit
`4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d`.
**Pinned vendor:** DeerFlow
`c0895d295bba34f6e95188fca380f555dabed891`.
**Docker:** immutable image digest selected from `python:3.12-slim` at
execution time, recorded in the run artifact.
**Model configuration:** existing GitHub Secrets
`SWE_LLM_API_KEY`, `SWE_LLM_MODEL`, optional `SWE_LLM_BASE_URL`;
model identifier fingerprint recorded without the secret or endpoint.
Changes to model provider settings between historical runs cannot be ruled out.

Run two original **natural full-spec** upstream Issues (one invocation each):

- #524 — `bytes2human`, host-owned independent boundary test
- #565 — `MultiReplace`, same complete independent regex-flag test suite as
  prior **natural** trial, not the controlled staged-specification task

Fixed settings: `adaptive=True`, `planner=llm`, `explorer_mode=llm`,
`physical_dag=True`, `max_repairs=1`; existing native model turn
budget, native timeout and isolated Docker settings are **unchanged**.
The script prohibits fake model or patches, requires original baseline test
to fail, and on success checks stable workspace, accepted Practical Coder
Handoff, untouched host-owned tests/original upstream, and independent
DAG Tester pass. Post-run diagnostic-only passing tests do not count.

## Comparison controls

| Case | Reference | Natural outcome | Model turns | Tools | Provider total tokens |
| --- | --- | --- | ---: | ---: | ---: |
| #524 | [Step 7D-A optimized run #38194147927](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38194147927) | PASSED | 16 | 26 | 163,623 |
| #565 | [Step 7D-A natural run #38194620421](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38194620421) | FAILED — timed_out, no Handoff | 20 | 25 | 323,778 |

Also, pre-7D-A #524 had 400,654 tokens, 22 turns, 38 tools. These are
historical single observations and **not matched randomized experiments**.

For the new run, record exact issue/time/runtime/model/test fingerprints,
hosted provider-reported tokens, native status and stop reason, tool
counts/categories/durations/repeats, per-turn input growth, full Workflow
verdict and accepted Handoff/Taster result. This new telemetry has no
historical per-tool baseline; it can diagnose this run but cannot quantify
an exact-before/after percentage of duplicates without re-running the
historical version.

## Result interpretation and release gate

- **Task success:** Native normal completion AND accepted Scheduler Handoff
  AND independent DAG Tester passed (not just changed Git diff).
- **Efficiency:** one-run Token/call/time comparison is descriptive only.
  Randomness, model service availability, warm caches and model identity can
  influence results. No general cost reduction claims from this run.
- **Reliability:** if natural #565 fails, preserve the full failure record;
  do not replace it with controlled staged Repair success and do not relax
  terminal safety.
- The temporary paid GitHub Actions push workflow is **exact branch plus
  commit-marker guarded**, executes only these two tasks, and MUST be deleted
  before any PR merge. The retained permanent `main` workflows remain
  typed-`RUN` manual only.
