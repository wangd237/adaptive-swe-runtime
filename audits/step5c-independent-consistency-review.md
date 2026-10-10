# Step 5C — Independent Source/Design-Freeze Consistency Sweep

**Date:** 2026-10-09  
**Scope:** PR #7 branch `coding/step5-deerflow-adapter`, 5C only.  
**Disposition:** **SCOPED GO for deterministic *preparation-only* semantics, subject to latest-head dual-lane CI. REAL DEERFLOW EXECUTION: NO-GO.** This is a separate adversarial source-level consistency pass, **not** an independent external reviewer or a native installed-DeerFlow integration audit.

## Frozen authority consulted

- `AGENTS.md` §6.1–6.3: revocable precommit, no execution/attempt identity during preparation, commit linearization.
- `specs/03-execution-runtime.md` §3.3 and §9.10: `prepare_node` no side effects, `release_preparation` explicit lifecycle seam, Scheduler-only invocation/attempt creation.
- `plan/step5-implementation-entry.md`: unchanged 5A/5B limits, one AppConfig/Tool/Model/Extension generation captured in 5C; 5D/5E own execution and tool-call authorization.
- `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891`: `AppConfig`, `SubagentConfig`, `get_subagent_config(app_config=...)`, `get_available_tools(app_config=...,extensions=...,include_mcp=False)`, `resolve_subagent_model_name`, `LoadedExtensions`, and `SubagentExecutor(config,tools,app_config,extensions,parent_model,...)`.

## Adversarial findings and disposition

| Finding | Severity | Resolution | Deterministic evidence |
|---|---|---|---|
| Initial syntax error prevented pytest collection on both Python lanes | BLOCKER | Fixed; first green baseline `b91430a6` (386 tests/lane) | GitHub Actions 37905388382 |
| Frozen dataclass did not imply deep immutable native objects | P0 | Seal AppConfig, SubagentConfig, exact ModelConfig, loaded tool schemas/callables/visible fields, extension generation; `assert_intact()` rechecks before downstream assembly | `test_app_tool_extension_tamper_rejected_on_claim`, `test_real_scheduler_commit_gates_one_shot_claim` |
| Preparation silently overwrote native SubagentConfig tool restrictions | P0 | Preserve native `tools` upper bound and `disallowed_tools`; refuse missing mandatory tools | `test_native_agent_required_tool_deny_and_allowlist_fail_closed` |
| Typed invocation alone could be fabricated outside Scheduler commit | P0 | Require explicit trusted `SchedulerCore.is_committed_invocation` callback; exact active object, ticket COMMITTED, owning asyncio Task, task/epoch identity | `test_uncommitted_invocation_denied_and_consumed_once`, `test_real_scheduler_commit_gates_one_shot_claim` |
| Revoked preparations could retain memory/tool/extension references | P0 | Scheduler finally calls provider-neutral `release_preparation`; optional legacy `discard_preparation` for existing adapters; LivePreflightBackend forwards cleanup | `test_scheduler_precommit_revoke_releases_preparation`, `test_precommit_waiting_workspace_revoke_drains_snapshot`, `test_precommit_waiting_workspace_cancel_drains_snapshot`, `test_preflight_wrapper_precommit_revoke_cleans_raw_mapping` |
| Already consumed preparation could be replayed | P0 | Atomically remove opaque token before checking claim; both invalid and valid claims one-shot, execution IDs not allocated in prepare | `test_uncommitted_invocation_denied_and_consumed_once`, `test_real_scheduler_commit_gates_one_shot_claim` |
| Snapshot binder may accidentally re-read hot-reloaded Config/Tools | P0 | Keep copied AppConfig, exact resolved Subagent/model/tool objects and extensions ref in private pending store; no supplier call in claim; re-check seals and pinned source | `test_preparation_pins_copied_config_and_tool_objects_no_execution`, `test_preparation_model_and_tool_are_not_implicitly_rebound` |
| Required review infrastructure or selected Skill route not implemented in 5C | P0 (unimplemented) | Explicit `INFRASTRUCTURE_BINDING_NOT_IMPLEMENTED` / `SKILL_BINDING_NOT_IMPLEMENTED`; no implicit exposure | Source inspection |

## Contract / trust boundary assessment

1. **Precommit:** `prepare_node` materializes only `NodeExecutionPreparation` and process-local `PinnedNodeResources`. No agent, tool, Workspace, attempt or execution identity is issued. `release_preparation` clears the private pending store when the Scheduler revokes or cancels before commit.
2. **Dispatch commit:** `SchedulerCore._commit` remains the sole attempt/ExecutionID creator while WorkspaceAccess is held and the Scheduler mutex linearizes. The short-lived `is_committed_invocation` assertion checks exact object identity, active invocation, ticket state and owner; post-finish claims are invalid.
3. **One shot:** `claim_for_execution` consumes its preparation token exactly once. Identity mismatch, stale ticket, different task/provider, source or content mutation all fail closed. A forged lookalike cannot make an execution attempt.
4. **Prepared snapshot:** AppConfig and SubagentConfig are independent copies; live tool objects and frozen `LoadedExtensions` generations are captured by reference. Observable config and tool surface are sealed and rechecked. **This is verified snapshot integrity, not an assertion that arbitrary third-party callable closures or ExtensionData stores are physically immutable.**
5. **Native API caveat:** actual DeerFlow's executor may internally filter tools, apply skill policy and live AuthorizationProvider; none of this is bypassed or certified by 5C. Managed `execute_prepared` remains hard-disabled with `REAL_DEERFLOW_EXECUTION_NOT_ENABLED`.

## Remaining release blockers

- **Step 5D:** `NodeExecutionBindingStore`, strict tool-surface middleware and use-time `ToolCallGuard` must prevent dynamic tool search, MCP, Skill, extension/plugin and authorization expansion, even if arbitrary Python objects change after claim. Extension contribution closures and `LoadedExtensions.app_store` are not deeply immutable by reference.
- **Step 5D–5E:** `SchedulerCore.is_committed_invocation` must be injected exclusively by trusted Runtime assembly, not by an untrusted caller. The reference-held resources need cleanup when execution finishes or is cancelled; 5C only implements precommit release.
- **Step 5E–5F:** real `SubagentExecutor`, quiescence, native tools/Bash receipts, exact acceptance policy, sandbox session semantics and real auth remain unproven.
- **Step 5G:** pinned Python >=3.12 DeerFlow harness actual install/import, live Model/AuthorizationProvider identities, and frozen real integration PoC matrix still pending.
- Snapshot `binding_digest` deliberately includes process-local Python object identity to detect generation swaps; it is **not** a reproducible cross-process persistent fingerprint or a security supply-chain attestation.
- `source_verifier` checks checkout HEAD/dirty tracked code but not every loaded dependency or extension byte. Native actual installed conformance remains pending.
- `_claimed_execution_ids` is process-local and retains consumed IDs for the lifetime of this preparation backend; bounded task lifetime is assumed, future 5E cleanup/lifecycle must be reviewed.

## Go / No-Go

- **GO:** continue to 5D only after latest HEAD Python 3.11/3.13 CI succeeds, while retaining strict execution-disabled behavior in 5C.
- **NO-GO:** real shared mutable Workspace execution, production DeerFlow execution, automatic model/tool rebinding, treating tool/extension references as deeply immutable, merging PR #7, or declaring full Step 5 accepted.
