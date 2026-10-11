# Step 7C — Reliability & Observability

Status: active, implemented on `coding/step7c-reliability-observability`.
Frozen runtime baseline: main `9e7fc6b3ee120a6b8fc7190d238dc1335e9e24f3`.
DeerFlow vendor remains frozen at `c0895d295bba34f6e95188fca380f555dabed891`.

## Purpose

Use actual open-source issue failures to strengthen the agent's ability to
understand failures and resume safely. **Do not** relax read-before-write,
quiescence, authorization, canonical verifier or the Task DAG contract to
make a benchmark pass. A model-produced successful-looking response is never
an independently verified coding outcome.

## 7C-A — Redacted trace diagnostics

- Per turn: count model turns and provider-reported token usage, when present.
- Per tool: record trusted receipt status and known stable error category,
  without prompt, raw tool arguments/results or secrets.
- Distinguish *agent-observed* Bash tests, independent canonical checks and
  Scheduler's Docker Tester.
- Per workflow: persist a deterministic `reliability` object with
  `aswe.reliability.v1`, event integrity flag, code-verifier status, native
  terminal status, stop reasons, repair rounds and failure category.
- Capped but code-verified is NOT a normally ended Agent run. Failure
  diagnosis is advisory; it does not override strict Scheduler acceptance.
- Missing tokens, costs and incomplete execution remain unknown/incomplete.
- Verify sensitive text never appears in exported summaries.

## 7C-B — Return to the ORIGINAL independent real issue

Upstream boltons #500 at the **same pinned commit**, no patch preload and
the exact host-owned date-iteration regression suite. Keep model, original
Docker image and Repair budget identical to the Step 7A environment.
Do not repurpose Issue #553 as proof that the original #500 is fixed.

Acceptance: baseline test fails; actual LLM decides its own changes; host
Tester independently passes; implementation changed; external test unchanged;
the original repo is untouched; Native completes without `turn_capped`.
Failure reports must include a scrubbed reliability view (even for a broken
workflow), so the next change can be based on genuine evidence.

## 7C-C — Reliability analysis / future issue suite

Use the same summary schema for each future manually authorized task.
Only after the original #500 result is understood, add a small diverse sample
of issues. For each report: issue/baseline identity, completion criterion,
model and tool turns, observed token usage, verifier verdict, native stop
reason, repair rounds and first causal failure category. Do not claim a
benchmark score with fewer than the planned tasks, or repeat runs as
independent tasks. No task-specific hard-coded reference patch is allowed.

## Release gate

- Offline unit CI on supported Python versions.
- Frozen vendor physical integration green.
- A real #500 live trace classified and documented (success or an honest
  failure with follow-up and explicit remaining blocker).
- Remove any temporary branch-scoped paid push marker before merging. The
  release workflow remains typed `workflow_dispatch RUN` only.
- PR review of safety invariants and clean base comparison.
