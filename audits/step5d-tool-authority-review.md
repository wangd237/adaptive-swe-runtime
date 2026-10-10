# Step 5D — Tool Authority / Binding Store Source Consistency Audit

**Date:** 2026-10-09  
**Branch:** `coding/step5-deerflow-adapter` (PR #7, Draft/Open).  
**Verdict:** **Deterministic source-contract GO (5D bounded scope), native SubagentExecutor execution NO-GO.** This is a code-level adversarial consistency review, **not** a claim of independently installed DeerFlow or real-credential end-to-end validation.

## Frozen source checkpoints

Cross-checked `AGENTS.md` §6.1–6.3, `specs/03-execution-runtime.md` §3.3/§3.4/§9.10, `plan/step5-implementation-entry.md`, and upstream `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891`:

- `deerflow.authz.provider.Principal / AuthzRequest / AuthorizationProvider`: Layer 1 `filter_resources(principal,"tool"/"model",names)`; Layer 2 `authorize/aauthorize(AuthzRequest(resource="tool",action="call",target=...,context=...))`.
- `deerflow.authz.principal.build_principal_from_context` and `deerflow.authz.runtime.resolve_authorization_provider` (instance creation without global cache).
- `deerflow.guardrails.middleware.GuardrailMiddleware.wrap_tool_call / awrap_tool_call`: native `ToolCallRequest.tool`, `tool_call.name/id/args`, `runtime.context` and handler signature.
- `deerflow.subagents.executor.SubagentExecutor`: captured `app_config`, tools, model, extensions; subsequent authorization, skill discovery, deferred tool assembly, middleware declarations, `create_agent`, compiled LangGraph `ToolNode`.
- `deerflow.tools.builtins.tool_search` and `deerflow.agents.middlewares.tool_declarations`: deferred MCP promotion and middleware-added tool shadowing can enlarge the ToolNode registry **after** ordinary config tool selection.

## Coded 5D authority path

1. 5C prepares explicit pinned AppConfig, selected Subagent/model tools, and LoadedExtensions generation; `execute_prepared` still refuses to run.
2. After Scheduler `_commit`, `NodeExecutionBindingStore.bind` consumes the 5C preparation token once and uses the exact Scheduler-owned `NodeExecutionInvocation`; no duplicate execution ID is accepted.
3. The host supplies the principal from a trusted identity source, deep-copied, stamped and checked against mutation. Enabled auth requires `fail_closed=True`; a provider instance is resolved from the pinned authorization config. Both model and tool visibility are intersected with the Core-selected candidate set. Required-tool visibility and model `use` authorization are mandatory.
4. `BoundToolView` seals model-visible object identities and schemas. `ToolPolicyMiddleware.validate_build_inputs` rejects unexpected declared middleware tools; `validate_compiled_registry` requires exact ToolNode registry identity and names. These are **explicit checks to be invoked by 5E**; no implicit inference that a native graph already uses them.
5. Native `make_langchain_tool_policy_middleware` provides LangChain `wrap_tool_call` and `awrap_tool_call` hooks, checking exact `request.tool` object identity, name, call ID, and server-issued run/execution context before forwarding to `ToolCallGuard`.
6. Every guarded sync/async invocation checks execution liveness through `SchedulerCore.is_active_execution`, identity/object seals, one-shot call-ID reservation across threads, per-call AuthzRequest and explicit allow, and liveness/authority again after awaited policy decisions. No supplied native handler is called on deny.
7. Opaque model/tool/extension rebindings, extra provider-returned names, nonempty plugin contributions, configured MCP servers, tool_search, skill evolution, and implicit unrestricted skill inheritance are denied. Native `SubagentConfig.skills` is narrowed to `[]` before sealing; optional mutating tools are removed from model visibility.
8. **Non-read-only tools and repo path-restricted calls remain disabled** until 5E/5F attach trusted Workspace/Sandbox command/path enforcement and receipts. No `bash`, `write_file`, `str_replace` execution is enabled by this phase.

## Deterministic adversarial test coverage

- `tests/unit/test_deerflow_tool_guard_step5d.py`: actual Scheduler-commit bridging, model/tool visibility filter and model-use authorization, policy-provider exceptions and fail-open rejection, wrong/absent principal, retained principal mutation, same-name impostors, native `ToolCallRequest` API-shaped interception, tool call deny and replay, close during async auth, Scheduler post-terminal liveness, async authorization race, sync-thread concurrent tool-call ID reservation, dynamic `tool_search`, Skill/MCP/Extensions/Plugin injection refusal, and mutation-tool hard deny.
- `tests/unit/test_deerflow_preparation_step5c.py`: preparation snapshot pinning, live Scheduler commit identity, revocable tickets, Workspace lock race, source/config mismatch, and captured Subagent skills narrowed before snapshot.
- CI runs Python 3.11/3.13 in core-only editable install. **These tests run shape-compatible stubs, not installed native DeerFlow.**

## Unclosed P0 / 5D→5E handoff

- **Native attachment not yet established.** The actual `SubagentExecutor._create_agent()` builds and normalizes its own Middleware stack and ToolNode. It currently does not receive our final ToolPolicyMiddleware hook, nor invoke our pre/post `create_agent` registered-tool verification. Passing raw `BoundToolView.objects` to an ungated agent would be unsafe. **Do not do this.**
- Native SubagentExecutor may resolve a separate `AuthorizationProvider` after its own `_build_initial_state`. 5E must force one run-bound provider/principal and prevent diverging model-visible, tool-execution and skill authorization decisions.
- Native hidden/late tools from guardrails/Skill/deferred discovery have not been shown absent in a compiled real ToolNode. Until the native graph verification is proven, no real tool dispatch is allowed.
- The supplied host context must carry server-stamped `run_id` and `execution_id` into native `ToolCallRequest.runtime.context`. 5E must verify no client-supplied context can spoof these reserved keys.
- AuthorizationProvider's live external policy endpoint/identity and actual execution-time `authorize/aauthorize` remain unproven with a real provider; dynamic RBAC changes may occur between check and execution. Denial is guaranteed for evaluated false/exception, not for changes after an allow decision.
- Native class/middleware order, provider construction loop-affinity, model tool schema projection, GraphRecursionError/cancel/quiescence, Sandbox path confinement and immutable mutation evidence require 5E–5F.
- Python object/process-local identity sealing does not attest arbitrary native closures, callback managers, or loaded extension `app_store` state; tool call guard requires trusted host composition.
- `_used` and tool call ledgers are process-local; future lifecycle needs a bounded cleanup and explicit quiescence result. `release` revokes future calls but does not prove an in-flight native handler is quiescent.

## GO / NO-GO

- **GO:** proceed from 5D's tested preparation/binding/guard contract to 5E's native graph assembly and execution once latest-head dual-version CI passes.
- **NO-GO:** actual DeerFlow graph/tool/model execution, native AuthorizationProvider end-to-end guarantee, write tool/Bash calls, production use, or merge of PR #7. Step 5 as a whole stays open.
