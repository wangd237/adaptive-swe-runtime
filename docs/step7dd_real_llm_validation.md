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

## Evidence: genuine #524, Step 7D-C1/C2

[GitHub Actions run #38210671064](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38210671064),
artifact `aswe-step7d-issue-524-evidence` (ID `11728899134`).

This is one real-model unmocked natural-spec run. All host-owned baseline,
production-modification and independent-testing checks passed:

| Metric | Earlier Step 7D-A #524 | Current Step 7D-C #524 |
| --- | ---: | ---: |
| Provider-reported total tokens | 163,623 | **96,873** |
| Input tokens | 150,918 | **92,670** |
| Output tokens | 12,705 | **4,203** |
| Model turns | 16 | **13** |
| Guarded tool calls | 26 | **13** |
| Bash calls | 22 | **8** |
| Native termination | normal | normal |
| Scheduler accepted Handoff | yes | yes |
| Independent DAG Tester | passed | passed |
| Repair rounds | 0 | 0 |

This single comparison has an observed 66,750 total-token difference
(about 40.8% fewer), 3 fewer model turns and 13 fewer guarded tools.
The earlier 7D-A output changes and new 7D-C behavior changes are not
causally separated in this stochastic comparison; do not generalize this
effect size without repeated matched trials.

Current-only **new** tool diagnostics (historical run did not provide the
same metrics): 13 completed calls; `bash=8`, `read_file=4`,
`str_replace=1`; `bash_category_counts.other=8`, conservatively including
compound shell expressions. No identical tool arguments repeated.
Measured guarded tool time totaled 2,336ms with a maximum call of 641ms,
which does not account for hosted model latency or other runtime overhead.
Provider first-to-last per-turn input tokens were 863→10,472;
peak was 10,472. Trace observed roughly 34.98s total elapsed, but historical
run does not have a matched new-schema duration baseline.

The evidence identifies the exact model-configuration fingerprint,
host-test hash, immutable Docker digest, and runtime evaluation branch SHA,
while core Runtime files remain identical to merged main
`0b49eaa5ac94e6f6d2d1092c2aa86de294219c2e`.

## Evidence: natural full-spec #565, still FAILED

The same [GitHub Actions run #38210671064](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38210671064)
has an **independently failed** `real-issues (565)` job. The always-uploaded
`aswe-step7d-issue-565-evidence` artifact is ID `11728859516`.

| Metric | Earlier Step 7D-A natural #565 | Current Step 7D-C natural #565 |
| --- | ---: | ---: |
| Provider-reported total tokens | 323,778 | **313,458** |
| Input tokens | 307,164 | **300,388** |
| Output tokens | 16,614 | **13,070** |
| Model turns | 20 | **24** |
| Guarded tool calls | 25 | **28** |
| Bash calls | 17 | **20** |
| Native exit | **timed_out** | **turn_capped** |
| Coder Scheduler state | failed | failed |
| Accepted Coder Handoff | NO | NO |
| Independent DAG Tester | not run | not run |

This was **not successful**, and 10,320 fewer reported tokens cannot
be interpreted as better delivery efficiency: the number of turns and
tools increased, termination changed from native timeout to model-turn cap,
and no independent Tester was scheduled. The allowed maximum model turns
and Repair budget were unchanged. Source was modified and host-owned tests
were untouched, but that is not task acceptance. The independent baseline
regression failed as required.

Current-only newly instrumented observations:

- `tool_name_counts = {bash:20, read_file:5, str_replace:3}`.
- `repeated_exact_argument_calls = 0`; `repeated_bash_argument_calls=0`.
  **Zero exact repeats is NOT zero semantically redundant work.** The
  repeated-argument hint cannot address unique-but-similar shell commands.
- 20 Bash invocations were conservatively labeled `other`: complex shell
  strings are intentionally not classified as safe `test_like`, and raw
  commands are not exposed to trace or report.
- Across 28 observed guard calls, total duration was 14,862ms, maximum
  9,016ms. Total trace elapsed ~153.43s includes model time and overhead;
  do not equate their difference exclusively with model inference latency.
- Model input tokens per turn climbed from 1,410 to 20,906, with peak
  20,906; notable context growth remains.
- A real `SWE_READ_BEFORE_WRITE_REQUIRED` denial occurred once, but this
  was not the final failure. `NATIVE_BUDGET_EXHAUSTED` at `turn_capped`
  was terminal. The Coder never emitted an accepted Practical Handoff,
  `dag_tester_results=[]`, `repair_rounds=0`.
- Provider model config fingerprints and Docker digest match the concurrent
  #524 run, so the two cases in this batch used the same configured provider
  identity and resolved Docker image. **Historical** provider identity and
  image might differ; a paired randomized trial was not performed.

## Step 7D-D result and decision

**Validation executed and complete for these two cases; efficiency and
reliability optimization itself remains OPEN.** Both tasks used genuine
upstream natural specifications on the merged Step 7D-C Runtime, unchanged
turn budgets, real external LLM, real host-owned regression and authentic
Scheduler/Tester acceptance conditions.

- #524: task correctness preserved with descriptively lower total tokens,
  fewer turns and calls, and accepted Scheduler Handoff.
- #565: **still failed**; no Handoff or independent Tester. Repeated-shell
  hint exact-match detection reported zero repeats. Do not label the model
  more reliable on natural #565 or treat the 565 staged-spec Repair witness
  as a natural pass.
- C3 opt-in identical-Bash compaction was **disabled** during both real
  runs; no effectiveness evidence for context compaction exists yet.
- Next candidate is **7D-E: semantic tool-workflow and stopping diagnosis**.
  First determine whether 20 Bash calls reflect independent necessary
  checks or repeated near-equivalent searches, tests and environment probes.
  Avoid changing authorization or coercing Native status to completed.

Both artifacts preserve success and failure. The temporary
`.github/workflows/swe-step7dd-live-temp.yml` one-shot paid push
workflow was deleted after the results. Permanent paid workflows remain
manual `workflow_dispatch` with typed `RUN` only. No additional
automatic paid job is introduced by this PR.
