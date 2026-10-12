# Step 7D-C — Tool Efficiency & Context Optimization

Status: **C1/C2 implemented; C3 safe, opt-in PoC only.** This change does
NOT declare Step 7D complete, a higher SWE issue success rate, or a measured
token reduction. The previously observed natural #565 still fails under
the prior baseline (timed out or turn capped).

## Why

- Optimized natural Boltons #524 used 26 guarded tools, **22 Bash**, and
  163,623 provider-reported total tokens. It passed the independent Tester.
- Natural Boltons #565 on optimized Step 7D-A: 20 model turns, 25 tools,
  **17 Bash**, 323,778 provider-reported tokens; native `timed_out`.
  As a result, no accepted Coder Handoff or independent DAG Tester.
- A raw Bash count does NOT establish redundant work. Need a host-observed
  per-tool breakdown, duration, and exact-repeat counts before policy changes.

## C1: Trusted observations, no new execution authority

- `ToolCallGuard` adds monotonic **per-call duration_ms** for async/sync
  tools, counted across authorization, execution and errors.
- An exact same name/arguments digest after a previously COMPLETED call
  is recorded as `repeated_exact_arguments=true`. This does **not**
  assert the workspace is unchanged: a Bash invocation may itself modify
  files, and nondeterministic tests must still run.
- Bash categories are limited, advisory labels: `test_like`,
  `search_like`, `other`, `unknown`. Complex shell expressions are
  conservatively `other`; no command text is emitted to trace.
- `aswe trace --summary` now includes tool duration totals/max/count,
  category totals, exact repeat counts, and repeated Bash counts.
- Actual tool receipts and their original trusted hashes remain unchanged.
  No raw arguments, file paths, shell output or credentials are exported.

## C2: Nonblocking, model-facing efficiency/finish hints

- The actual sandbox command is ALWAYS executed again. Its exit code,
  timeout status and independent receipts are NOT cached, fabricated or
  altered.
- Exact command repeats append a short efficiency suggestion. The tool
  result remains a fresh result, potentially different from the previous one.
- After a host-observed `str_replace`/`write_file` and a successful,
  conservatively classified single-command pytest/unittest run, the
  agent gets an *advisory* completion hint. It explicitly says only the
  agent-run check passed and that final verification belongs to the host.
- Hints are neither forced stopping nor self-reported test acceptance.
  Genuine failures must still reach the model and the independent Tester.
- No new Scheduler state, Repair shortcut or higher turn/timeout budgets.

## C3: Safely scoped context PoC (disabled by default)

`ControlledSWEWorkspace(compact_identical_bash=True)` enables a narrow
model-facing repeated-observation reduction:

1. Execute the sandbox command normally, every time.
2. Compare the complete host-computed SHA-256 stdout/stderr digest,
   actual exit status and timeout flag against the earlier **same command**
   within the same execution.
3. Only if all fields match, replace the *second model-facing duplicate
   output* with a short statement that the genuine fresh result matched
   the earlier observation. Keep exact legacy status header.
4. All actual Docker lifecycle checks, verified worktree evidence,
   ToolCallGuard receipts and original LangGraph AI/Tool message pairs
   remain intact. Never substitute a synthetic successful Tester receipt.
5. On a new output or unavailable digest, return the full bounded observation.

This deliberately does **not** prune historical LangGraph messages.
Deleting tool-call/ToolMessage pairs can break replay semantics, including
reasoning-aware providers. Safe paired message view compaction should only
be considered following a frozen-vendor physical integration test and
provider behavior review. Until then, opt-in duplicate-output compaction
is not enabled on real default model runs and does not count as a
demonstrated token saving.

## Verification and boundaries

Unit regression tests cover:
- Privacy: no command text in trace summary or export.
- Real execution of repeated tools and bounded measured durations.
- Conservative Bash categories and no hint from compound shell calls.
- Completion hint only after a local modification plus successful agent-run
  recognizable test (not independent verification).
- Opt-in identical output compaction without skipping command execution,
  and reverting to real bounded output whenever contents differ.
- PoC is off by default.

The pinned DeerFlow physical/native CI suite must remain green, including
real ToolNode, canonical Docker Tester, read-before-write denial recovery,
and two-round Repair. Do NOT infer lower cost or improvement in natural
#565 success rate without a true paid model comparison with all failures
reported. Paid workflows stay manual typed `RUN` only.
