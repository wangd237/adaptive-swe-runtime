# Step 7D proposal — pre-registered small real-Issue reliability suite

This is an **evaluation plan** and not a claim that these tasks have
been successfully executed. Run only on host-owned pinned original sources,
with no pre-applied patch, no model mocks, no mid-run test modification.

## Motivation

Step 7C proved runtime mechanisms using two natural, independently passing
boltons Issues and one real-model **staged-specification** Repair exercise.
A third natural Issue (#565) hit `turn_capped`, and passed only a separate
post-run diagnostic test. Evaluating real SWE reliability requires counting
that case as a **failed natural attempt**.

## Pre-register candidate tasks and expected verification behavior

| Case | Subsystem | Issue | Independent acceptance focus |
| --- | --- | --- | --- |
| B500 | timeutils | [#500](https://github.com/mahmoud/boltons/issues/500) | Month-end clamping, leap years, negative increments |
| B553 | iterutils | [#553](https://github.com/mahmoud/boltons/issues/553) | Falsy callable key consistency |
| B565 | strutils | [#565](https://github.com/mahmoud/boltons/issues/565) | Per-regex flags remain isolated; historically capped |
| B551 | iterutils | [#551](https://github.com/mahmoud/boltons/issues/551) | Key once per element, singleton key failure, stable heterogeneous sort |
| B524 | strutils | [#524](https://github.com/mahmoud/boltons/issues/524) | Rounded unit boundary promotion |
| B510 | funcutils | [#510](https://github.com/mahmoud/boltons/issues/510) | Positional-only wrapper signatures, keyword collisions |
| B480 | fileutils | [#480](https://github.com/mahmoud/boltons/issues/480) | Revoking permission bits |
| B479 | fileutils | [#479](https://github.com/mahmoud/boltons/issues/479) | rotate_file keep count, generation retention |

Start with **five distinct tasks** B500/B553/B565/B551/B524; only widen
to B510/B480/B479 after first five results have auditable baselines and
failure diagnostics. Avoid re-running an Issue multiple times and counting
those repeats as independent tasks.

## Frozen controls

- Pin upstream Git source SHA **per case**; for first five evaluate the
  baseline `4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d`, after verifying
  the bug actually occurs at that SHA. Select a different SHA explicitly
  if the behavior was introduced after that point.
- Freeze A-SWE merge SHA, DeerFlow vendor SHA, model ID, Docker image digest,
  first-attempt `max_turns`, Repair budget and test command.
- Verify host-owned test **fails before** any Agent executes; forbid edits to
  test files, metadata, original upstream checkout and hidden test code.
- Run natural full-spec Issue only for benchmark counts. Controlled staged
  specification runs are a **different experiment category**.
- Each live run requires an explicit authorized invocation or a one-shot
  branch-and-commit-gated workflow deleted before main merge. No paid
  normal push or PR jobs.

## Result schema

For each case record: {case_id, upstream_sha, runtime_sha, vendor_sha,
model_id, original_baseline_failed, native_stop_reason,
strict_vs_practical_acceptance, coder_handoff_count, DAG Tester verdict,
repair_rounds, tool_failures_by_code, model_turns, reported_input_tokens,
reported_output_tokens, reported_total_tokens, code_changed,
external_tests_unchanged, original_repo_unchanged, outcome,
attempt_count, limitation_or_first_failure}.

Success requires **all**: normal terminal, accepted practical Coder Handoff,
independent DAG Tester `passed`, code change when required, and untouched
host-owned tests/original upstream checkout. A diagnostic-only passed test
is never success. Do not infer money cost from tokens without model pricing.

## Reporting

- Publish a per-Issue evidence link even on failure or timeout.
- Aggregate natural first-attempt task success across distinct Issue IDs;
  distinguish `turn_capped`, failure of guard recovery, missing Handoff,
  failed independent Tester, exhausted Repair and environment exceptions.
- Report median/quantiles of per-task calls/turns/tokens only over recorded
  and comparable runs; don't silently drop failed tasks.
- Include confidence caveat: n=5–8 is a **smoke reliability survey**, not
  statistically meaningful SWE-bench performance.
