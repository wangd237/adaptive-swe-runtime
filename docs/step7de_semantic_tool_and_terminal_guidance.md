# Step 7D-E1/E2 — Semantic Tool Observations and Budget-Aware Guidance

## Purpose

Genuine natural #565 used 24 model turns, 28 tool calls including 20 Bash
invocations, and ended `turn_capped`. Prior Step 7D-C exact argument
repetition detection found zero identical repeats. New changes focus on
**correctly interpreting** the tool/test history and helping an Agent
conclude within its original native budget; they are not a claim that
natural #565 has now been solved.

## E1 — Correct execution observations

1. A **shared, deterministic, conservative classifier** in
   `bash_intent.py` classifies only unambiguous simple shell commands as
   `test_like`, `search_like`, `inspect_like` or `other`.
   No LLM or untrusted command output determines this category.
2. In `ToolCallGuard`, a Bash command's success or failure produces
   `agent.test.observed` and agent-local `repair.feedback.available`
   **only if the command is test-like** and the trusted tool-status header
   can be parsed. A successful `ls`/`git diff` no longer counts as a
   passing test; a failed `grep` no longer generates fake test Repair
   feedback. Genuine independent Docker Tester verdicts and their trusted
   RepairFeedback are unchanged.
3. Compound commands (`&&`, pipes, shell redirection, substitutions,
   multiple lines), ambiguous arguments and test framework informational
   commands (`--collect-only`, `--help`) fail closed as `other`.
   Some real tests therefore lack an agent-local test observation. This
   deliberate **false-negative** is preferable to claiming an arbitrary
   successful Bash was a passing test.
4. Actual model request duration is measured at LangChain
   `on_chat_model_start/on_llm_start → on_llm_end/on_llm_error` boundaries
   using a bounded, content-free callback on the frozen DeerFlow native
   graph. Aggregates count observed requests, failed requests, total and
   maximum milliseconds. If callback timing is unavailable, it remains
   absent; no inferred latency is inserted. No prompts/responses/URLs,
   message text or credentials are persisted.
5. Model turns have one of four *host-observed* progress phases:
   `exploring`, `code_modified`, `agent_check_failed`,
   `agent_check_passed`; other values normalize to `unknown`.
   The phase comes from actual controlled file tool writes and
   **classified** agent-local test results and is strictly diagnostic.
   It is neither a Git diff, WorkspaceRevision nor independent canonical
   code-verification evidence.
6. The reliability trace aggregates phase counts and timer aggregates
   using the existing redacted summary contract.

## E2 — Trusted-input soft progress and terminal hints

The native streaming graph counts completed actual AI messages, not
self-reported model assertions. It reports the turn counter and
Scheduler-pinned `effective_max_turns` to its *own*
`ControlledSWEWorkspace`, after model turn completion.

After host-observed file-tool writes:

- After an identifiable, successful agent-run unittest/pytest command, a
  one-time completion hint asks the model to finish normally if ready.
  It explicitly defers acceptance to the host.
- A **mid-budget caution** appears when at least half the *configured*
  logical turns have been consumed. The frozen native graph counts super-
  steps and may cap before all nominal turns are observed. The hint says
  this rather than claiming exact time or remaining available turns.
- At four or fewer remaining nominal turns, a stronger one-time hint
  prioritizes a focused test and normal completion. When the latest
  recognized test failed, it tells the agent to repair that failure
  first; when it passed, it encourages returning control for independent
  verification.
- New tracked file-tool writes invalidate prior pass/failure state for
  hinting. Bash can also change files outside tracked file tools;
  no hint is evidence that the repository is unchanged.
- These hints are appended **only to actual fresh tool results**. No
  tool call is skipped, no result is cached, and no new privileged
  state transition or automatic termination is introduced. Native
  `turn_capped`, timeout and unsafe quiescence remain hard failures.
- The opt-in duplicate Bash output compaction PoC remains **disabled
  by default** and no LangGraph historical messages are removed.

## Verified scenarios

Unit tests assert:
- successful `ls`/`git diff`, failed `grep`, and `pytest
  --collect-only` never fabricate test outcomes or RepairFeedback;
- a failed genuine unittest creates one agent-local failed-test event,
  followed by a passing unittest, without promotion to independent Tester;
- model latency emits numeric-only completed/failed events with no text;
- host-observed phases are normalized and protect against arbitrary
  model-provided values;
- progress hints fire only after actual file-tool writes and bona fide
  host-counted model turns, and reset after new writes;
- a previously failed test cannot be advertised as a passing test.

Frozen DeerFlow physical integration verifies additive actual request
timings and progress phases alongside existing trusted tool receipts,
read-before-write and independent canonical test behavior. Python 3.11
and 3.13 unit CI remain required.

## Unproven / deliberately postponed

This work **does not** prove fewer model turns, lower Token cost, or
successful natural #565 completion. A live Issue #524/#565 matched
regression is a later **Step 7D-E3** evaluation, with explicit paid-run
authorization and the original Scheduler Handoff/Tester gates unchanged.

The next investigation should distinguish semantic near-duplicate shell
work from useful targeted checks. Exact repeat detection is already
known to be insufficient for #565; these changes improve diagnostic
truthfulness and guidance, but do not classify arbitrary compound Bash
with an additional LLM or introduce a new multi-agent policy service.
