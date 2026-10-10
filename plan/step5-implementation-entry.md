# Coding Step 5 — DeerFlow Execution Adapter Implementation Entry

**Status:** IN PROGRESS — 5A Inventory Identity and 5B Model-only Reasoning Adapter coded on `coding/step5-deerflow-adapter`. **Real shared mutable Workspace DeerFlow execution: NO-GO.** This entry preserves the pre-existing P0 Design Freeze; it grants no release waiver.

## Baseline and installation contract

- A-SWE Core accepted on `main` after PR #6, merge `e60491c4d34e69e387d6ac48d95b23e6afbe9134`.
- Frozen *DeerFlow implementation source* `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891` (2026-10-05); **do not silently follow main**. The working source MUST be the correct HEAD with a clean tracked `deerflow` harness package path; unpinned/wheel-only source cannot assert this contract.
- Its `backend/packages/harness/pyproject.toml` requires **Python >=3.12**, while A-SWE Core supports >=3.11. Keep base CI Python 3.11/3.13; actual import/DeerFlow integration lane MUST use Python 3.12/3.13 with the frozen checkout and its compatible dependencies, not assume Python 3.11 supports DeerFlow.
- `src/aswe/integrations/deerflow/` is the **only** DeerFlow-coupled Python namespace. No Scheduler/Planning imports of `deerflow`.
- No LLM/API key or network credentials are needed for 5A's deterministic contract tests. Real assembly/LLM smoke cannot pass until the pinned DeerFlow environment is installed and tested separately.

## Source entrypoints verified at the frozen commit

| Frozen source | Contract verified / use |
|---|---|
| `backend/packages/harness/deerflow/config/app_config.py` | `AppConfig.tools: list[ToolConfig]`, `models`, `sandbox` |
| `backend/packages/harness/deerflow/tools/tools.py` | `get_available_tools(..., app_config, include_mcp=False)` resolves `cfg.use` then deduplicates by *loaded Tool.name*; configurable name alone isn't identity |
| `backend/packages/harness/deerflow/reflection` | `resolve_variable(cfg.use, BaseTool)` is the implementation reference for config-loaded core tools |
| `backend/packages/harness/deerflow/subagents/registry.py` | `get_subagent_config(agent_type,app_config=...)` proves requested Agent type available |
| `backend/packages/harness/deerflow/subagents/config.py` | Resolved model / tools / disallowed / skills / timeout / max_turns, needed for 5B |
| `backend/packages/harness/deerflow/subagents/executor.py` | snapshot-scoped execution, tools, `_harvest_bash_executions`, cancellation/quiescence and result mapping in 5C+ |
| `backend/packages/harness/deerflow/sandbox/sandbox.py` | trusted Sandbox `persistent_shell_sessions` semantics; `None` cannot prove native tests_passed |

## 5A delivered (bounded inventory only)

1. Distinct `FakeBackend` identities (`config:read_file`) and **real DeerFlow** identities (`config:deerflow.sandbox.tools:read_file_tool`). Real effects are only trusted when config `ToolConfig.use`, routed exposed name, loaded tool object/callable, eager delivery and implementation effects align.
2. Candidate BackendInventory from **actual DeerFlow AppConfig + tool assembly output**, plus confirmed Subagent registry types. Same-name other config/plugin cannot prove READ. Missing/disallowed host bash does not appear as enabled.
3. Sandbox feature classification uses the passed **observed Sandbox** value `persistent_shell_sessions`: False enables `fresh_shell_per_command` and `deerflow_tests_passed_evidence`; True or None do not.
4. Identity fingerprints exclude observational `captured_at`; identical deployment sampled at two times does not falsely trigger `BACKEND_DRIFT_OBSERVED`.
5. On actual adapter import, fail closed for missing DeerFlow dependency, mismatched source Git HEAD, edited tracked harness source, or unknown requested Subagent type. **Git HEAD check occurs after module imports and is a compatibility tripwire, not a sandbox/security trust root.** Deployment still needs pinned dependencies and isolation.
6. Dedicated tests `tests/unit/test_deerflow_inventory_step5a.py` exercise 10+ deterministic positive/negative scenarios through exact API-shaped stubs. They are **not** live installed DeerFlow conformance tests.

## Coding sequence / next unimplemented checkpoints

| Sequence | What remains | Stop/go evidence |
|---|---|---|
| 5B | **CORE CODED / DETERMINISTIC TESTS PASS** — `DeerFlowReasoningBackend` / `ModelInvoker`, source-pinned model factory + live model-use auth | Exact role/name, no fallback/tool binding, JSON Schema strict output, timeout/cancel. **Real installed DeerFlow/LLM smoke pending**; not a production Go grant |
| 5C | `NodeExecutionPreparation` / immutable AppConfig + SubagentConfig + Tool + Extension snapshot, `ExecutionContractBinding` | precommit no execution ID; exact pinned resources reused at `execute_prepared`; no post-prepare config rescan |
| 5D | `NodeExecutionBindingStore`, Node tool-policy middleware and ToolCallGuard | required/effective/infra tools survive every model call, forbidden cannot leak; policy store miss fails closed in managed run; ordinary run pass-through |
| 5E | SubagentExecutor typed result mapping, quiescence, cancellation join / cleanup | no retry without independent quiescence; managed cancellation storage cleanup; proper dirty fail-close and Workspace read/write boundary |
| 5F | Canonical command receipt/evidence, review direct-return, AssemblyAttestation, fresh shell | test Bash receipts with `shell_persistent=False` and exact command policy; no model self-report promoted as authoritative |
| 5G | Actual DeerFlow integration Go/No-Go | Frozen POC-02/03/05/09, R34/35/36/38/50/51/69/70/73 and relevant P0-5 cases proven on exact pinned deployment |

No fork until a frozen requirement is proven impossible via the pinned public extension seam. No shared mutable Workspace/Writer execution is enabled for DeerFlow merely because its catalog was observed.

## POC disposition

`audits/step5-gate-audit.md` tracks exactly what 5A proves and what remains pending. **All real DeerFlow integration Go/No-Go tests still remain unpassed at this point.**

Reference: `plan/master-plan.md` Step 5, `audits/deerflow-source-audit.md` and immutable `tests/poc-matrix.md`.


## Step 5B model-only reasoning checkpoint (2026-10-09)

- `src/aswe/integrations/deerflow/model_invoker.py` implements Core's authoritative `ReasoningBackend.generate_structured` protocol without duplicating TaskSpec/WorkPlanProposal schemas.
- `ModelInvoker.from_deerflow()` lazily resolves *pinned source* `deerflow.models.create_chat_model(name, app_config, thinking_enabled=False, attach_tracing=False)`, LangChain System/HumanMessages, current config and current AuthorizationProvider. No default-model fallback.
- Runtime/operator-owned `role_models` selects an explicit configured model, not the LLM response or raw TaskRequest. Config ModelConfig digest rechecked after model-use AuthorizationProvider preflight; changed model/use/settings/auth config refuses call.
- Auth enabled: require trusted principal; provider `filter_resources(principal,"model",[name])` and fresh `AuthzRequest(resource="model", action="use", target=name)` both allow. Denial/provider failure fails closed, without logging credentials. Disabled auth follows trusted AppConfig setting.
- Only one JSON object per result, strictly validated with `Draft202012Validator`; reject duplicate keys, NaN/Infinity/overflows, wrong root type, unwanted schema fields, tool-call outputs. JSON Schema may reference only local `#/` definitions; external `$ref` and `$id` forbidden, size bounded.
- Invocation has fixed duration budget, cancellation propagates, model errors become typed `ModelInvocationError` with sanitized codes. Metrics are informational only; no model prose or emitted candidate earns execution authority.
- `tests/unit/test_deerflow_reasoning_step5b.py` exercises model API-shaped mocks, live model-use auth denial, reasoner/analyzer/validator crossover and no silent fallback. This does **not** prove actual remote model API availability/authorization or end-to-end DeerFlow Subagent operation.
- Independent review: `audits/step5b-model-invocation-review.md`. The next required implementation checkpoint is **5C immutable preparation + AppConfig/Tool/Model/Extensions pinning**.

## Step 5C implementation checkpoint (2026-10-09)

- Implemented a fail-closed, **execution-disabled** NodeExecutionPreparation facade in `src/aswe/integrations/deerflow/preparation.py`; unit test scenarios in `tests/unit/test_deerflow_preparation_step5c.py`.
- Frozen AppConfig deep copy, selected SubagentConfig, explicit resolved ModelConfig, eager config-tool objects, LoadedExtensions object reference, semantic policy/Descriptor/Inventory identities and effective ceilings produce a content-addressed opaque backend snapshot and preparation token. `claim_for_execution` is a future 5D/5E trusted handoff (not called by 5C execution). No execution ID allocated during preparation.
- Security boundary: tool object seals cover identity/callables/schema, not arbitrary mutable closure state; loaded extension generation is referenced, not internally frozen. 5D must enforce runtime tool call guard and bind run extension context. Imported source checkout is a compatibility check, not a full supply-chain attestation.
- Real execution remains disabled; required review output and selected skills intentionally refuse until 5D–5F supply trusted bindings. Deterministic test suite is not native installed DeerFlow integration, and latest-head CI still needs verification. PR #7 stays Draft/Open.

## Step 5C adversarial verification / handoff (2026-10-09)

- `audits/step5c-independent-consistency-review.md` independently checks the source against AGENTS §6.1–6.3 and frozen Spec 03 §3.3/§9.10. Scoped 5C deterministic preparation GO only, pending latest-head CI.
- `NodeExecutionPreparation` creates no `execution_id`, `attempt` or Workspace mutation; `SchedulerCore._commit` allocates execution identity only after physical lock. The exact `NodeExecutionInvocation` is checked against active Scheduler state and owning asyncio Task before once-only resource claim.
- Revoked or cancelled preparation is released through `release_preparation` (with backward-compatible `discard_preparation`); LivePreflightBackend forwards this hook so nested bindings cannot leak.
- Snapshot AppConfig/SubagentConfig/ModelConfig copies, selected native tool objects, extensions generation reference and effective policy are sealed. `PinnedNodeResources.assert_intact()` may be called again after claim. Native SubagentConfig allow/deny restrictions are never widened. `binding_digest` includes in-process object identity and must not be called a cross-process portable provenance digest.
- LoadedExtensions plugin bodies, mutable ExtensionData stores, callable closure contents and use-time Authz are **not** certified recursively immutable. 5D must enforce model/tool authority for every invocation and bind extension generation into the run context; 5E must handle in-flight lifecycle and cleanup. 5C still hard-disables real DeerFlow execution.
- Keep PR #7 Draft/Open, do not merge, and do not assert complete Step 5.

## Step 5D coding / handoff checkpoint (2026-10-09)

- Added `src/aswe/integrations/deerflow/tool_guard.py`: `NodeExecutionBindingStore` (once-only post-commit binding), `BoundToolView` (exact model-visible tool identities), `ToolPolicyMiddleware` (input/compiled ToolNode registry checks), `ToolCallGuard` (sync/async native tool-call authorization + replay/liveness), and lazy LangChain ToolCallRequest-shaped guard middleware factory. No real subagent execution is enabled.
- `AuthorizationProvider.filter_resources(principal,"model"|"tool",candidates)` restricts visibility; `AuthzRequest(principal,resource="model",action="use")` precedes binding and `AuthzRequest(resource="tool",action="call")` is required **per actual guarded invocation**. Provider errors, fail-open flags, absent principal, role mutation, provider instance swaps and stale executions deny.
- Disabled at this boundary: implicit Skill inheritance (captured `sub.skills=[]`), tool_search, Skill evolution, configured MCP servers, plugins/LoadedExtensions contributions, middleware tool declarations, non-read-only/bare Bash tools and unverified path-limited tool invocations. The tool registry must match exactly before native graph invocation.
- Source and adversarial test evidence in `audits/step5d-tool-authority-review.md` and `tests/unit/test_deerflow_tool_guard_step5d.py`. Source-only GO must be distinguished from physical native integration.
- **Next 5E**: inject this exact native guard into the pinned `SubagentExecutor` at both Layer 1 and Layer 2, prove middleware/ToolNode registration matches permitted model view, propagate reserved server context and *same* provider identity, ensure cancellation cleanup/quiescence, and run frozen installed DeerFlow integration tests. Hard execution NO-GO and PR #7 Draft/Open until those proofs exist.

## Step 5E-A bounded native SubagentExecutor entry (2026-10-09)

- Use `NativeSubagentAssembler.from_deerflow()` to create a Source-Pinned native `SubagentExecutor` subclass without process-global monkeypatches. Only replace the upstream `_build_initial_state` and `_create_agent` hooks, because upstream re-resolves tool-search/Skills/extensions/provider on its own. Native `_aexecute` handles execution, streaming, admission and teardown.
- `NodeExecutionBindingStore.bind` remains the post-commit entrance; no model/tool is assembled before a real Scheduler Invocation. `BoundToolView` exactly matches the compiled `ToolNode.tools_by_name` by key, object identity and seal; make_langchain_tool_policy_middleware is the only custom runtime tool middleware. `_ReservedContextGraph` carries Scheduler-owned execution_id and run_id into ToolCallRequest context alongside pinned Principal identity.
- `NativeDeerFlowExecutionBackend` enables no execution by default; explicit PoC opt-in does NOT confer accepted TaskResult or quiescence. All NativeExecutionRecord outcomes report `quiescent=False,mutation_evidence=unknown` pending Step 5F's trusted sandbox, process and Workspace proof.
- See `audits/step5e-native-assembly-review.md` and `tests/unit/test_deerflow_native_execution_step5e.py`. **5E installed-vendor/credential proof pending**; no PR merge / production GO.

## Step 5E-B physical integration checkpoint (2026-10-09)

- Added separate required `deerflow-pinned-native.yml` CI job (Python 3.12) with exact upstream source checkout and real harness install; incompatible Core-only CI 3.11/3.13 excludes these integration files.
- Physical `tests/integration/test_deerflow_pinned_native_step5eb.py`: real native `SubagentExecutor`, AppConfig/SubagentConfig/LoadedExtensions, LangChain `create_agent`/compiled `ToolNode`, model → actual guarded synthetic read tool → model loop, source verifier, native `_aexecute` admission/stream/terminal lifecycle, bundled RBAC deny/allow and revocation.
- All model activity is a host-local offline `BaseChatModel` fixture. The test does **not** contain model credentials, invoke remote API endpoints or access a real mutable workspace/sandbox.
- Independent details and residual limitations: `audits/step5eb-pinned-native-physical-poc.md`. Scoped installed-vendor offline GO must **not** substitute for live credentialed model/auth integration, full Scheduler-to-native signed binding, lockfile-proven dependency reproducibility or 5F trusted sandbox/evidence/quiescence.
- PR #7 stays Draft/Open. Next: 5F evidence/mutation/quiescence + explicit 5G external credentialed preflight before full Step 5 close.

## Step 5F-A host-owned readonly workspace evidence checkpoint (2026-10-09)

- `execution_evidence.py`: begin under committed Scheduler WorkspaceAccess, compare Git state against Invocation revision, pre/post filesystem + Git snapshot, call trusted resource-supervisor after owned native task completes and guard is revoked, derive attempt-local `NodeWorkspaceDelta`, persist guarded hash-only TOOL_RECEIPT_LEDGER and WORKSPACE_CHANGESET refs outside workspace.
- `ToolCallGuard` emits authoritative run-local handler invocation receipts, **not** native sandbox effect proofs. False/no mutation requires complete bounded scanner plus denial of all mutating/UNKNOWN tools, no pending handler, trustworthy independent supervisor scope. Excluded scan directories are incomplete; truncated authoritative mutation is UNKNOWN.
- No external `ResourceSupervisor` shipped yet, so absent or fake-only sandbox witness cannot promote production quiescence. Real native 5E-B offline installed Harness verifies failure-closed evidence with no witness, not a positive process drain. See `audits/step5f-execution-evidence-quiescence-review.md`.
- **5F-B still required:** real executor-owned completion/lease/tool-worker supervision and canonical foreground Bash command start/finish receipts & acceptance-verdict integration. Explicit 5G model/Authz real-credentials E2E after this. PR #7 remains Draft/Open.

## Step 5F-B1 bounded compiler-approved foreground evidence (2026-10-09)

- Reuse Step 3D sealed `CompiledAcceptancePlan` and `VerificationCommand` exactly; do not accept strings invented by LLM nor rewrite shell syntax. Local `ManagedForegroundVerifier` supports one foreground command per attempt, process-group TERM/KILL+drain, cancellation completion signal, task/node/ExecutionID check, and conservative in-memory command observation (NOT canonical receipt).
- Native `_aexecute` outer coroutine gets an independent completion event, checked in `cancel_node` and evidence collector, but this alone cannot certify native sandbox leases, remote shell processes or spawned descendants.
- Native 5F-A EvidenceRefs can now be validated against trusted LocalEvidenceStore outside Scheduler mutex and attached atomically to historical attempts. They are diagnostics, not acceptance. Fake/cross-execution references fail-close.
- Full 5F-B still requires real provider-specific Sandbox/tool worker quiescence and canonical run-bound Bash tool-start/command receipts with HMAC-backed verifier and mandatory Acceptance Compiler mapping. See `audits/step5fb-executor-managed-command-review.md`. PR #7 remains Draft/Open.

## Step 5F-B2-A installed Native Lease & Canonical Command Evidence (2026-10-09)

- Frozen DeerFlow `SubagentResult.task_id` is now host-generated from committed execution identity so actual `SandboxLeaseManager` owner `subagent:<id>` is auditable. A source-pinned `NativeSandboxQuiescenceSupervisor` requires independently proven provider release AND process-tree drain before accepting the observed owner absence; no such production probes have been installed. `binding_for=None` does not imply successful `provider.release`.
- Runtime-managed exact Step-3D `VerificationCommand` foreground process captures actual stdout/stderr SHA-256 outside the repo, uses a cancellation-independent drain finalizer, and bridges its completed observation to the existing HMAC `CanonicalVerifier.validate` and `CanonicalCheckBinding`. The signed evidence is not a native DeerFlow Bash tool receipt and cannot bypass Acceptance Compiler.
- Installed Python 3.12 vendor tests include real `_aexecute` host-chosen lease owner and `LocalSandboxProvider` lease acquire/release; Core 3.11/3.13 negatives cover cancellation, signer tamper, timeout/nonzero, actor/lease mismatch. See `audits/step5fb2-native-lease-canonical-receipts.md`.
- Full 5F-B2 remains NO-GO until a trusted provider-release completion receipt + external process/cgroup/shell-session/worker drain supervisor is implemented and tested, with actual native Bash tool invocation binding, HMAC evidence → historical Attempt/Acceptance, and real model/Authz E2E. PR #7 remains Draft/Open.

## 5F-C — MVP Controlled SWE Coding Entry (2026-10-09)

- Separate model-controlled `SWE Agent Bash` from Runtime's compiler-owned canonical test command. Only an opt-in Docker-backed, no-network, ephemeral isolated command backend may handle dynamically generated shell text; no native DeerFlow default host bash.
- WRITE/str_replace tools are source-pinned by 5C and selectively wrapped by `NodeExecutionBindingStore.swe_workspace_factory` after real Scheduler Commit; the original resources remain sealed, compiled ToolNode and ToolCallGuard preserve exact execution identity. Explicit Scheduler workspace root required. File edits require current read and refuse symlink/traversal.
- Separate test levels: full installed DeerFlow/LangGraph offline model repair loop with synthetic command outcomes, and real physical Docker command smoke with test Workspace. Neither substitutes for credentialed real-model / complete Scheduler+Acceptance E2E. Model's command exit codes only generate `agent_observed_only` development summaries.
- Original strict Scheduler quiescence fail-closed remains. The user approved deferring complete process/lease attestation; next MVP increment should expose a separate honest `unverified / canonical_tests_passed / failed` TaskReport, not falsely sign `quiescent=True` or `TaskResult.ACCEPTED`.
- Independent scope audit: `audits/step5fc-controlled-swe-coding-review.md`. PR #7 Draft/Open/unmerged.

## 5F-C-B — End-to-end SWE MVP Result (2026-10-10)

- Runtime `MVPTaskRunner` wraps one actual Scheduler claim/commit and executes the native agent, then separately captures Git diff and runs HMAC-backed exact canonical Python tests while the WRITE workspace lock remains held. JSON report includes native status, independent tests, changed files, bounded patch, signed receipt, explicit quarantine and agent-visible diagnostic counts.
- Installed Python 3.12 CI physically executes the combined workflow: scripted offline LLM → real frozen DeerFlow/LangGraph native graph → 5D binding Store after Scheduler Commit → actual dynamically chosen Bash in no-network Docker → model repairs after failed check → actual Runtime Python unittest/HMAC evidence → report. See `audits/step5fcb-e2e-mvp-task-review.md`.
- Full installed 5C source inventory and genuine remote model/Authz preflight, production quiescence and strict accepted TaskResult remain unproven. Per the user, quiescence and advanced Acceptance hardening remain deferred; **MVP test passed != Core Node ACCEPTED**. Next: real-model smoke and user-facing runnable workflow; PR #7 stays Draft.

## 5F-D — Manual Real Model Smoke (2026-10-10)

- Operator added three GitHub Actions Secrets: `SWE_LLM_API_KEY`, `SWE_LLM_MODEL`, and optional HTTPS `SWE_LLM_BASE_URL`. Never inspect, print, persist or pass these to an Agent Bash container.
- New `LiveModelSettings` rebuilds full frozen DeerFlow `AppConfig` with one ChatOpenAI provider to refresh `_models_by_name`; API key supplied via scoped runner environment. Separate no-network Docker runs are used for Agent commands **and** Runtime canonical Python regression to prevent model-written imports reading host credentials. Runtime independently seals Git-consistent output with HMAC.
- `.github/workflows/swe-real-model-smoke.yml` uses `workflow_dispatch` only, with explicit `RUN` confirmation. The live test is gated by `ASWE_LIVE_SMOKE=1` and `GITHUB_ACTIONS=true`, skipped in normal PR CI. Frozen installed 3.12 dry-factory test, Core input/workflow safety tests and physical fake-key Docker canonical checks are separate.
- **Remaining gate:** the workflow must be registered on default main (prefer workflow-only bootstrap after review, *not* PR #7 merge); current GitHub connector has no workflow-dispatch write action. No live model call has been made yet. See `audits/step5fd-real-model-smoke-review.md`. Quiescence/full TaskResult/production 5C+Authz remain deferred and cannot be claimed by a successful model smoke.

## Step 5 Global Closure Review (2026-10-10)

**NO-GO for closing all Step 5 / merging PR #7 as complete.** Source/CI freeze sweep finds three actionable P0 items: production 5C inventory cannot select Docker Bash under the tested local `allow_host_bash=False` source-filter path (real 5C→5D→Native untested); Runtime `canonical_verifier.py` imports the DeerFlow integration layer (frozen dependency inversion); and the evidence collector's `mutating_tool_admitted=False` is stale for a SWE WRITE execution. See [`audits/step5-global-closure-review.md`](../audits/step5-global-closure-review.md). Full native Quiescence is still deferred by agreement and is **not** an added MVP P0. Fix the three source/contract defects, run frozen-vendor no-credentials 5C physical chain and negative checks, then re-evaluate PR merge; do not rerun paid LLM by default.
