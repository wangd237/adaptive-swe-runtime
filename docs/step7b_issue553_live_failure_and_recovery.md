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
