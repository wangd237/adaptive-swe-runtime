# Step 7B — boltons #553 repeated read-before-write failure and recovery trial

## Unmodified second-Issue execution

- Actual upstream Issue: https://github.com/mahmoud/boltons/issues/553
- Fixed boltons base: `4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d`
- Real paid-model workflow: https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38054664973
- Result: failed, `ISSUE_553_NOT_SOLVED`. No claim of upstream bug resolution.
- Independent CI and frozen DeerFlow integration: passed.
- Native stack: `ControlledSWEWorkspace.str_replace -> _write -> SWE_READ_BEFORE_WRITE_REQUIRED`.
- The LangGraph tool call raised out of the ToolNode, failing the native coder execution. It was not delivered as a recoverable model-visible tool result.
- Same failure family as the earlier independent Issue #500, despite the different production module.

## Runtime correction (not an Issue-specific patch)

- Keep the required, content-hash-backed `read_file` before any existing-file mutation.
- Return *only* `SWE_READ_BEFORE_WRITE_REQUIRED` as a LangChain `ToolMessage(status="error")` after its failed attempt is recorded by the trusted ToolCallGuard. Instruct the model to call `read_file` on the same path and retry.
- Never turn authorization, path escape, symlink, identity, revocation, or cancellation errors into recoverable messages.
- Preserve a denied receipt with the specific stable error code (not a fictitious successful write).
- Leave independent Docker verification and repair budgets unchanged.

## Acceptance

The next real model run checks whether the planner/explorer/coder can resume after a rejected write and independently fix the unmodified upstream bug; model feedback is not an accepted result on its own. If another error occurs, preserve the failure and report it rather than weakening the test.

## 2026-10-11 Step 7B test gate

- CI, Python 3.11/3.13, with explicit cap and report tests: passed.
- Frozen DeerFlow physical ToolNode scenario: real denial -> model-visible error -> read -> retry -> production mutation, deterministic offline model. The tool and graph are physical, not mocked.
- New live recovery benchmark intentionally injects exactly ONE initial str_replace tool call without a prior read. From the second turn onward the external model autonomously decides what to do. This is controlled fault injection, not independent Issue pass rate.
- Native turn budget now uses the frozen vendor's middleware-aware super-step converter; bounded vendor stop_reason is preserved in reports.
- A paid live acceptance is started by a one-shot branch marker and must be disabled before merge to main.

## Live fault injection trial 1

- Run: https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38111716097
- Failed honestly: the LLM provider rejected a synthetic first assistant tool-call turn without its required thinking-mode `reasoning_content`; this is a **harness protocol failure**, not a clean Agent recovery result.
- Updated the harness to run a genuine provider turn first and preserve its native reasoning metadata while replacing only the selected tool call with the injected write.
- No production Runtime policy change was made for this protocol issue.

## Live fault injection trial 2

- Run: https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38111804359
- The synthetic first turn now returned genuine provider thinking metadata but the compiled LangGraph ToolNode reported `No AIMessage found in input`. This is still a harness message-construction failure, not accepted recovery evidence.
- The third trial constructs a fresh `AIMessage` with only the genuine provider's protocol reasoning metadata and the injected tool request (without its original response ID or unrelated message fields).

## Live fault injection trial 3 and protocol-seam decision

- Run: https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38111882682
- A thinking-mode provider again refused the synthetic assistant tool-call history because its required hidden reasoning protocol could not be reconstructed in the ChatOpenAI abstraction.
- This is specific to **injected assistant history**, not evidence of an ordinary LLM call issue: previous genuine Issue #553 E2E ran successfully.
- Last controlled trial will keep the real ToolNode/guard denial and record it faithfully, but adapt ONLY the synthetic first assistant/tool pair into a trusted error observation before passing history to the genuine provider. Subsequent actual tool calls are not transformed.
- Interpret this as real-model behavioral recovery from a trusted refusal notice plus separate full-native ToolMessage coverage, not as proof that the provider natively replayed a synthetic tool-call exchange.

## Repeat genuine upstream Issue #553 after budget repair

Re-run the non-mocked upstream Issue #553 under the exact same pinned
boltons SHA and frozen DeerFlow baseline, now requiring both canonical
passing tests and a **normal (non-turn-capped)** native terminal status.
This run is separate from the synthetic recovery-fault benchmark.

## Final Step 7B live acceptance evidence (October 11, 2026)

**1. Physical ToolNode read-before-write recovery**:
`tests/integration/test_step7b_real_native_tool_recovery.py` passes using the
actual frozen DeerFlow/LangGraph ToolNode, trusted SWE workspace file guard,
and an offline deterministic model. The first `str_replace` is rejected
without mutation; the model receives `ToolMessage(status="error")`, then
calls `read_file`, retries `str_replace`, and changes only the permitted
source file. The guard writes a denied receipt with the stable error code.

**2. Controlled real LLM recovery**:
https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38111975541
- outcome passed; genuine provider calls 5; injected rejection count 1;
  successful `read_file` count 3; successful `str_replace` count 1.
- canonical independent verdict passed; only calc.py changed;
  test unchanged; native completed without a stop reason.
- The first unauthorized assistant tool call is harness-injected. Since the
  provider's thinking mode cannot replay an artificially generated assistant
  tool call with genuine hidden reasoning, the harness translates **only this
  injected first tool error exchange** into an equivalent trusted human error
  notification for the external model. Later real provider turns are
  unmodified. This tests real-model recovery behavior and is NOT a claim
  that the provider received the raw ToolMessage. The raw ToolMessage path
  is covered separately by the physical integration above.

**3. Original upstream Issue #553**:
https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38111990982
- non-mocked LLM, same frozen DeerFlow and pinned real boltons SHA
  `4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d`.
- baseline regression failed, independent regression passed after Agent fix;
  production changed, host-owned tests unchanged.
- roles explorer/coder/tester, DAG dispatch explorer -> coder -> __aswe_verify,
  12 model turns, 16 tool receipts; no tool denials this time.
- native terminal completed, **native_stop_reason = null**:
  the prior `GraphRecursionError/turn_capped` artifact did not recur after
  proper policy-turn to graph-superstep conversion.

**Security/semantics**: Existing-file writes still require a current
`read_file` hash snapshot. All other authority/path denial codes remain
fail-closed. Capped native outcomes are recorded separately from canonical
code correctness. Strict Scheduler quiescence is not inferred from an MVP
verification pass.

**Release hygiene**: Both paid model workflows are manual
`workflow_dispatch` / explicit `RUN` only; their temporary push triggers
were removed before PR and merge.
