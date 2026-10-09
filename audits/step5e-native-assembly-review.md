# Step 5E — Bounded Native SubagentExecutor Integration Audit

Date: 2026-10-09  
Target: PR #7 `coding/step5-deerflow-adapter`  
Disposition: **5E-A native API-shaped integration / guarded model-and-tool graph: CONDITIONAL GO (latest CI needed); native installed + credential execution: NO-GO.**

## Source checked

Pinned `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891`, specifically:

- `backend/packages/harness/deerflow/subagents/executor.py`: `SubagentExecutor.__init__`, `_build_initial_state`, `_create_agent`, `_aexecute`, `_aexecute_admitted`, and native cancellation/stream cleanup paths.
- `backend/packages/harness/deerflow/guardrails/middleware.py`: `ToolCallRequest.tool`, `tool_call.{name,id,args}`, `runtime.context`, and sync/async wrapper handler signatures.
- `backend/packages/harness/deerflow/authz/provider.py`: `Principal`, `AuthzRequest`, Layer 1 and Layer 2 provider contracts.
- `backend/packages/harness/deerflow/tools/builtins/tool_search.py` and `agents/middlewares/tool_declarations.py`: deferred discovery and middleware-declared tools.
- Existing A-SWE `AGENTS.md`, `specs/03-execution-runtime.md`, 5C snapshot and 5D authorization guard source.

## Coding changes

`src/aswe/integrations/deerflow/native_execution.py` introduces:

- `NativeSubagentAssembler.from_deerflow()`: imports actual pinned `SubagentExecutor`, `create_chat_model`, `create_agent`, `ToolNode` and messages; invokes tracked source pin verifier before integration.
- `BoundedNativeExecutor(SubagentExecutor)`: overrides **only** the two native assembly hooks that would otherwise do independent Skill/MCP/Tool Search/AuthorizationProvider discovery: `_build_initial_state` and `_create_agent`. Native `_aexecute` and `_aexecute_admitted` are retained for admission, stream lifecycle and cleanup; this is intentionally a restrictive adapter, not full native lead-agent behavior.
- Compiled `ToolNode.tools_by_name` must exactly match the 5D `BoundToolView` in names, concrete object identities and sealed schemas. Any injected, swapped, duplicate, unknown-type or removed tool aborts assembly **before graph streaming**. The guard is the sole custom middleware.
- `_ReservedContextGraph.astream`: validates native run ID, authenticated principal and reserved execution ID, then stamps the Scheduler invocation's `execution_id` into the runtime context. The tool guard rechecks the same run/execution ID on every ToolCallRequest; no global monkeypatching of `create_agent` or `get_app_config`.
- `NativeDeerFlowExecutionBackend`: delegates precommit preparation to 5C and postcommit once-only binding to 5D, owns its one native asyncio task, handles cancellation/timeout cleanup, disables native execution by default and returns a typed Core-compatible `NativeExecutionRecord`.
- This stage treats even a native `COMPLETED` return as **quiescent=False / mutation_evidence=unknown**. It does not manufacture Terminal Evidence, `NodeHandoff`, acceptance, workspace snapshot or sandbox proof.

## Adversarial deterministic tests

`tests/unit/test_deerflow_native_execution_step5e.py` exercises the native method shapes through explicit fake adapters (NOT an installed DeerFlow package):

1. Default feature gate refuses execution before 5C preparation is claimed.
2. Real Core Scheduler claim/Workspace lock/commit -> 5D binding -> simulated native `_aexecute` -> guarded `astream` -> tool authorization, correct server-stamped context and safe cleanup.
3. Compiled ToolNode tool-search injection and same-name different-object swap denied before model/tool graph starts.
4. Native constructor rebinding a tool under the same name denied.
5. Native principal/user identity spoof denied before tool execution.
6. Cancellation while native graph is blocked revokes tool guard, settles owned task, emits no read or mutation evidence.
7. Native model factory receives copied AppConfig and the pinned model identity, never an LLM-selected provider.

## Risk ledger / NOT proven

1. **Real Python package + Model API:** current CI installs only A-SWE and shape-compatible stubs. `from_deerflow()` has not been executed with a checked-out installed pinned harness, real model credentials or a real AuthorizationProvider identity.
2. **Graph middleware integration:** `create_agent` with the pinned LangChain version and real `ToolNode` must pass actual graph construction under frozen dependencies. We do not infer it from fake introspection. Native `SubagentExecutor`'s default middleware stack is intentionally replaced; any required native middleware behavior needs independent reintroduction with safe identity checks.
3. **Native result lifecycle:** upstream `_aexecute_admitted` may catch exceptions and return `FAILED` without raising. The experimental adapter conservatively normalizes failure and never trusts unverified native error/receipt text.
4. **Quiescence:** native tool processes, callbacks, sandbox leases and background descendants are not independently proved terminated. Cancellation cleanup and await of native task are not sufficient to certify sandbox quiescence; all outputs have `quiescent=False` and `mutation_evidence=unknown`. Scheduler must terminalize/quarantine appropriately. 5F owns the proof.
5. **Capability constraints:** 5D still denies non-read-only Bash/write/replace, path-restricted calls, Tool Search, MCP, Skill inheritance/evolution, and nonempty extension/plugin contributors. No bypass for these to get native execution green.
6. **Production gate:** `enable_native_execution=False` by default, and PR #7 must remain Draft/Open. Explicit opt-in is only for controlled physical PoC after the real dependency is installed and the attached ToolNode verified. No business TaskHandoff or automatic merge.

## Next gate

**5E-B / 5F:** run Python >=3.12, installed pinned DeerFlow with actual config and credentials; check `SubagentExecutor` constructor and compiled ToolNode, exact provider/principal identity and model tool-call path, cancellation and sandbox process teardown; implement trustworthy quiescence and workspace mutation receipts before enabling real Writer or claiming Step 5 complete.
