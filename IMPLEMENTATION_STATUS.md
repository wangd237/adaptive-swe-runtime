## Step 5 Global Design Freeze Audit (2026-10-10)

**Verdict: NO-GO for global Step 5 closure or PR #7 merge as completed baseline.** This does not overturn 5F-D's evidence-backed real-model `Scoped GO`; nor does it reopen the user's deliberate deferral of native Sandbox Quiescence.

Independent source/CI review on `067c114d3baeadc8f44752b5d2cde351630d793c` found **three P0 closure blockers**: (1) no real 5C physical composition of selected Docker Bash tool because frozen DeerFlow filters native host Bash when `LocalSandboxProvider.allow_host_bash=False`; (2) `runtime/canonical_verifier.py` reverses Core → integration dependency direction; (3) `ExecutionEvidenceCollector` still hardcodes `mutating_tool_admitted=False` despite SWE WRITE allowance. P1 items cover test-file/Bash mutation authority, host canonical execution with live secrets, compiled Acceptance binding, full production entrypoint and reproducibility.

**Full audit and test closure criteria:** [`audits/step5-global-closure-review.md`](audits/step5-global-closure-review.md). Resolve P0s with offline installed-native negatives; no additional paid LLM call needed. Keep PR #7 Draft/Open until review.

## Step 5F-D — Real Model SWE Smoke (Real API Run Scoped GO) — 2026-10-10

- User reports adding GitHub Actions Secrets `SWE_LLM_API_KEY`, `SWE_LLM_BASE_URL`, `SWE_LLM_MODEL`. The actual values cannot be inspected through the GitHub connector and no external model HTTP request has yet been made.
- Added `live_smoke_config.py` for explicit manual Actions opt-in, sanitized HTTPS/model/key input validation and frozen `AppConfig` reconstruction. The real pinned `ChatOpenAI` factory reads `OPENAI_API_KEY` from runner environment; the key never enters the AppConfig snapshot, model prompt or Docker tool mount. Frozen `AppConfig._models_by_name` is rebuilt by full model validation, not stale list mutation.
- Added manual-only `.github/workflows/swe-real-model-smoke.yml` with a required `RUN` authorization input, no push/PR event, least-privilege checkout, pinned DeerFlow source, Python 3.12 and network-disabled Python Docker test container. JSON/redacted Step Summary emitted only after an actual run. Core/PR workflows never read these Secrets.
- Added `tests/integration/test_deerflow_live_swe_step5fd.py`: real hosted LLM `create_chat_model` (no scripted response), genuine Scheduler/5D/Native/LangGraph/isolated tool sequence, independent canonical unittest, exact Git diff. The live test intentionally skips in ordinary CI; **manual run #38018937188 completed successfully**, with independent canonical Python verification and the observed `calc.py` patch.
- Closed a live API credential leak risk: test code written by the model must not be imported into a host Python verifier that inherited the model key. Added `CanonicalVerifier.run_isolated_python` and opt-in Docker-isolated canonical testing through MVP runner, with HMAC evidence, full Docker output SHA-256, and pre/post host Git state. Added fake-key Docker physical denial checks and frozen-vendor ChatOpenAI factory tests with no network.
- Audited in `audits/step5fd-real-model-smoke-review.md`. **Manual workflow was registered to default `main` in commit `a57b80291f4c` without merging PR #7.** The user dispatched real-model run #38018937188 on the coding branch, which completed successfully with independent canonical tests and Git diff. **5F-D Scoped GO**; strict Scheduler quarantine remains as designed. Do not automatically rerun paid API calls.

## Step 5F-C-B — Committed end-to-end SWE MVP / Independent Canonical Verification (2026-10-10)

- `src/aswe/integrations/deerflow/mvp_task.py` introduces `MVPTaskRunner` and typed `MVPTaskReport` / `to_json()`. The Runner invokes **real SchedulerCore.claim/run_claim** with an execution probe; after native execution, but still under Scheduler WorkspaceAccess, it captures Git diff and post-state and performs independent exact `CanonicalVerifier.run()` plus `validate()` against the actual modified repo.
- Strict Scheduler stays fail-closed and quarantines when native Quiescence is unknown. MVP returns `tests_passed_scheduler_quarantined` when the separate HMAC-signed host regression passes, never `NodeHandoff ACCEPTED`, and distinguishes native failure, failed independent verification, unavailable checker, and missing evidence. Includes changed files, bounded patch, actual canonical EvidenceRef, verified returncode and advisory agent tool/command metrics.
- `tests/unit/test_deerflow_mvp_task_step5fcb.py` exercises actual Git, Scheduler commit and Runtime's independent Python unittest under Core 3.11/3.13; tamper/identity and negative verdicts are checked.
- `tests/integration/test_deerflow_mvp_e2e_step5fcb.py` physically composes installed source-pinned DeerFlow `SubagentExecutor`, real `NodeExecutionBindingStore.bind()` after genuine Scheduler Commit, LangGraph model/tool loop, **actual no-network Docker Bash** (failure → repair → success), and **real independent Python canonical unittest** (HMAC result, Git Diff) in one CI job. Offline model is scripted. A fixture-prepared test tool-source substitutes for the full 5C production provider/Inventory in this particular E2E: do not mislabel as complete production provider authorization.
- Added an installed-frozen-vendor CI stage to `.github/workflows/deerflow-pinned-native.yml`. Audit: `audits/step5fcb-e2e-mvp-task-review.md`.
- **5F-C-B offline physical Scoped GO only after latest SHA CI fully green**. Deferred: remote model/provider credentials, full 5C live inventoried tools as a single assembly, production quiescence, accepted DAG/TaskResult semantics, UI/API and benchmarks. PR #7 Draft/Open/unmerged.

## Step 5F-C-A — Controlled SWE Coding Loop / Opt-in Docker Bash (2026-10-09)

- User-requested MVP priority shift: complete physical Quiescence Attestation deferred. Existing Core Scheduler UNKNOWN/quarantine is **not** falsely promoted to success. No blanket weakening of ToolCallGuard or hard Handoff verification.
- New `controlled_swe.py`: Runtime-bound developer tools `read_file/write_file/str_replace/bash`. READ-before-WRITE, Workspace root, no traversal/symlink, file counts, size budgets; dynamic Bash only through explicit network-disabled, read-only-root, disposable Docker image by resolved SHA-256 digest. Per-file/max-changed-file policies prohibit Bash where it could bypass their restrictions.
- `NodeExecutionBindingStore` exposes SWE runtime only via an opt-in postcommit host factory plus required Scheduler workspace root. The *original* 5C source tool objects remain sealed; freshly wrapped tool identities are checked in compiled LangGraph ToolNode; 5D AuthorizationProvider/liveness/replay guards still run per-call. Default path remains read-only.
- `NativeDeerFlowExecutionBackend` permits tool mutation only when the exact bound SWE runtime is present. It returns a clearly **non-certified** `SWEDevelopmentSummary` with changed-file tool observations and dynamic Bash exit status (not canonical TaskResult).
- Source-pinned DeerFlow Python 3.12 CI executes real native LangGraph multi-turn offline coding: read → wrong edit → failing test → re-read → correct edit → passing test → finish. Separate physical Docker CI actually executes dynamic Bash in no-network container against disposable mounted worktree.
- Tests + safety notes: `tests/unit/test_deerflow_controlled_swe_step5fc.py`, `tests/integration/test_deerflow_pinned_native_step5eb.py`, `tests/integration/test_deerflow_docker_swe_step5fc.py`, `audits/step5fc-controlled-swe-coding-review.md`.
- **5F-C-A scoped offline physical GO only after latest HEAD CI succeeds**. Not proven: one complete trusted Scheduler/5C/5D Writer through real model to independent Canonical pytest to final MVP TaskResult, real credentialed AuthorizationProvider, production Sandbox drain or real model API. PR #7 Draft/Open/unmerged.

## Step 5F-B2 — Native Lease Owner / Canonical HMAC Foreground Receipts (2026-10-09)

- Added `native_lease_supervisor.py` with Scheduler-derived native `SubagentResult.task_id` / `subagent:<task_id>` owner identity; real bounded `SubagentExecutor._aexecute` receives that host-generated result holder while keeping vendor admission/stream/teardown code. Runtime-scoped supervisor reads actual frozen `SandboxLeaseManager.binding_for`, and refuses positive quiescence without separate provider-release-completion and process-tree-drain proofs.
- Found and closed **false-positive lease release assumption**: frozen manager deletes owner binding before executing provider release, so missing `binding_for` may still mean `provider.release()` failed. Installed-vendor physical test verifies actual acquire/release and deliberately remains `complete=False` without production attestors. No production `release_completion_probe` or `process_tree_probe` yet.
- `ManagedForegroundVerifier` now captures real stdout/stderr into unlinked Runtime temp files outside worktree, hashes bytes, and runs independent finalizer and completion event through subprocess spawn/cancel/TERM/KILL/Git-observation phases. Fixed cancellation-wait deadlock. Existing native Bash/WRITE remains disabled.
- `CanonicalVerifier.attest_foreground_observation` issues and validates real HMAC `CanonicalCommandReceipt` only from bounded physical command observations matching policy/attempt/revision/cleanup; `ManagedForegroundVerifier.canonical_check_binding` maps signed EvidenceRef into existing Step 3D AcceptanceCompiler input. Timeout, cancellation and failed cleanup cannot sign HOLDS. This is a privileged Runtime-only handoff; no model-controlled signer.
- Core tests: canonical HMAC signer, tamper rejection, nonzero/timeout UNVERIFIED or FAILED, independent double-cancel drain, Lease Manager failures, missing release/process completion, wrong-run provenance. Python 3.12 installed DeerFlow verifies native holder task ID and actual LocalSandboxProvider lease manager; see `audits/step5fb2-native-lease-canonical-receipts.md`.
- **5F-B2-A scoped implementation only; complete native Sandbox quiescence, native bash receipt and production managed WRITE remain NO-GO.** Separate live model/auth preflight, process/lease completion attestor and automatic acceptance still pending. PR #7 Draft/Open, not merged.

## Step 5F-B1 — Managed Foreground / independent completion / evidence-to-attempt binding (2026-10-09)

- Implemented `src/aswe/integrations/deerflow/managed_foreground.py`: `ManagedForegroundVerifier` executes **only** one exact Runtime/Step 3D `VerificationCommand` bound to `CompiledAcceptancePlan` and selected `NodeExecutionPolicy` by fingerprints, after Scheduler liveness verification. Uses direct foreground argv (`shell=False`), Unix process group, bounded timeout and TERM/KILL drain. One-shot execution ID/command claim, independent post-cleanup completion signal, pre/post trusted Git observations, no raw output/credential recording. Known daemon/detach entrypoints and runtime inline-interpreter calls are denied; test-only inline Python is explicitly opt-in.
- Frozen vendor `NativeDeerFlowExecutionBackend` now adds an independent outer-`_aexecute` coroutine completion event, set inside the coroutine's `finally` after native unwind; cancellation waits for it, avoiding inference from a `Future.cancel()` flag. This does **not** establish native sandbox lease/process/tool-worker quiescence.
- `SchedulerCore.run_claim` optionally accepts a Runtime-owned `execution_evidence_store`; it verifies exactly provenance-bound durable native WORKSPACE_CHANGESET/TOOL_RECEIPT_LEDGER refs *outside* SchedulerStateMutex, then attaches verified refs atomically to the historical attempt. These diagnostics never promote Node to ACCEPTED without independent canonical acceptance/Handoff. Wrong-run evidence refuses and fail-closes.
- Deterministic tests `tests/unit/test_deerflow_managed_foreground_step5fb.py` cover actual local foreground subprocess success/timeout/cancel/drain, identity spoof, command injection, daemon, missing executable, revision drift, replay; native cancellation and evidence attribution tests extended. Independent source audit: `audits/step5fb-executor-managed-command-review.md`.
- **5F-B1 scoped deterministic progress only. 5F-B/full Step 5 NOT CLOSED.** Local foreground observation is **not** a frozen CanonicalVerifier HMAC receipt and is **not** a DeerFlow native Bash handler. Real AIO/LocalSandboxProvider lease/tool-worker quiescence, compiled Bash mapping, command receipts and final Acceptance contract remain NO-GO. PR #7 stays Draft/Open/unmerged.

## Step 5F-A — Execution Evidence / Workspace Mutation / Quiescence (2026-10-09)

- Coded `src/aswe/integrations/deerflow/execution_evidence.py` with runtime-owned pre/post `RepositoryStateDigest`, bounded `FilesystemSnapshot`, attempt-local `NodeWorkspaceDelta`, immutable `TOOL_RECEIPT_LEDGER` / `WORKSPACE_CHANGESET` writes to external `LocalEvidenceStore`, and read-after-write integrity checks.
- `ToolCallGuard` now maintains atomic call ID / pending tracking, records authorized completed/denied/failed/cancelled tool outcomes as hashed argument/output receipts. No raw credentials, model content or source arguments persisted. Receipts do not count as sandbox/Bash command proof.
- `NativeDeerFlowExecutionBackend` may receive an `ExecutionEvidenceCollector`; begins host scan after genuine Dispatch Commit, joins owned native task, closes guard, then collects evidence while Scheduler holds WorkspaceAccess. Default without collector remains `quiescent=False`, `mutation_evidence=unknown`.
- Quiescence gate requires a distinct Runtime-owned `ResourceSupervisor` with complete process/tool-worker/sandbox lease closure for the same task/execution, plus owned task termination and empty pending tool calls. No supervisor, stale claim, interrupted task or ledger failure fails closed. **No production real sandbox supervisor has yet been implemented**; positive deterministic witnesses are synthetic only.
- Snapshot scanner now treats excluded cache/build directories as incomplete, blocking false no-mutation proofs; authoritatively `UNKNOWN` on truncated evidence even when partial changed paths are observed.
- Deterministic `tests/unit/test_deerflow_execution_evidence_step5f.py` and pinned physical `tests/integration/test_deerflow_pinned_native_step5eb.py` include this seam; see `audits/step5f-execution-evidence-quiescence-review.md`.
- **5F-A scoped GO conditional on latest green CI; full 5F remains NO-GO.** Canonical controlled Bash/WRITE evidence, native sandbox/process supervisor, acceptance-verdict proof, automatic Scheduler attempt evidence attachment and live credentials not complete. **PR #7 Draft/Open/unmerged.**

## Step 5E-B — Installed pinned DeerFlow offline physical integration (2026-10-09)

- New `.github/workflows/deerflow-pinned-native.yml` physically checks out `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891` and runs Python 3.12 after installing the editable frozen Harness with its declared dependencies.
- Physical integration tests: `tests/integration/test_deerflow_pinned_native_step5eb.py` validate genuine `SubagentExecutor`, frozen `AppConfig/SubagentConfig/LoadedExtensions`, actual LangChain `create_agent`, compiled `ToolNode`, native `ToolCallRequest` path through `ToolCallGuard`, and full frozen `_aexecute` terminalization with a synthetic offline `BaseChatModel`.
- Real bundled `RbacAuthorizationProvider` permits and denies tool calls; denied synthetic handler is not invoked. Forged compiled same-name tool and already-revoked binding fail closed. No outbound model request or credentials involved.
- Core-only CI (Python 3.11/3.13) excludes installed-vendor tests, preserving clean separation. **Source-pinned physical 5E-B Scoped GO** when latest green dual CI is confirmed; initial physical run `37913740074`: **6 PASS**.
- Audit: `audits/step5eb-pinned-native-physical-poc.md`. Actual Scheduler-to-native external model credentials, deployed AuthorizationProvider identity, mutable workspace evidence, native subprocess/sandbox quiescence and dependency lockfile require separate 5F/5G gates. All native result records still `quiescent=False`, `mutation_evidence=unknown`.
- No real Writer/Bash mutation or production execution. **PR #7 remains Draft/Open and unmerged. Step 5 is not completed.**

## Step 5E — Native Execution Integration (2026-10-09)

- **5E-A guarded native assembly coded, deterministic API-shaped tests passing** (latest HEAD CI to be verified). Added `src/aswe/integrations/deerflow/native_execution.py` with `NativeSubagentAssembler`, `NativeDeerFlowExecutionBackend`, `_ReservedContextGraph`, and process-scoped native task/cancel management.
- Frozen DeerFlow `SubagentExecutor` constructor and native `_aexecute/_aexecute_admitted` lifecycle are used. The default, independently loading `_build_initial_state/_create_agent` hooks are replaced by a bounded subclass that uses exactly the 5D committed binding's AppConfig, model, tool identity and sole ToolCallGuard middleware. The compiled `ToolNode.tools_by_name` registry is checked before any graph stream. Model/ExecutionID and trusted principal are stamped into tool-request context by a guarded graph proxy.
- Native execution is **feature-disabled by default** and deliberately returns `quiescent=False` and `mutation_evidence=unknown` even after COMPLETED native graph results. It never certifies Handoff, acceptance, Bash/Workspace mutation proof or sandbox quiescence.
- Adversarial API-shaped tests in `tests/unit/test_deerflow_native_execution_step5e.py` cover native graph identity and context, injected Tool Search/ToolNode name collisions, foreign constructor-replaced tool, malicious identity override, blocked-stream cancellation and default feature refusal.
- Independent frozen-source audit: `audits/step5e-native-assembly-review.md`. **Stage 5E-A scoped deterministic GO** only; installed frozen DeerFlow, real credential/model/AuthorizationProvider, actual LangChain ToolNode and cancel/quiescence proofs remain **NO-GO**. PR #7 remains Draft / Open / unmerged; full Step 5 NOT complete.

## Step 5D — Tool Authority / Run Binding checkpoint (2026-10-09)

- Added `src/aswe/integrations/deerflow/tool_guard.py` with process-local `NodeExecutionBindingStore`, `BoundToolView`, strict `ToolPolicyMiddleware` build/compiled-registry gates, run-bound `ToolCallGuard`, and lazy native `make_langchain_tool_policy_middleware` wrapping LangChain `ToolCallRequest`.
- `NodeExecutionBindingStore.bind` consumes 5C preparation exactly once after real Scheduler commit, pins model/tool principal plus one `AuthorizationProvider`, rejects fail-open config, validates Layer 1 model/tool visibility and native `model/use` authorization. `ToolCallGuard` rechecks authority and live Scheduler execution on every sync/async call, using native `tool/call` authorization and atomic replay rejection.
- Dynamic `tool_search`, implicit Skill inheritance, Skill evolution, configured MCP servers and loaded/declared plugin/extension tools are explicitly refused. Middleware declaration and compiled ToolNode name/object changes are denied by 5D gates. No non-read-only or path-constrained call can execute in this stage.
- `SchedulerCore.is_active_execution` provides tool-call liveness without weakening original owner-bound `is_committed_invocation`. Native `SubagentConfig.skills=[]` is pinned before 5C seal. Principal is host-copied and sealed; provider-auth mutation and identity swaps are rejected.
- Added `tests/unit/test_deerflow_tool_guard_step5d.py` with role/model/tool visibility, replay and concurrent sync-call race, host provenance, extension/MCP/Skill/tool_search injection, exact native `ToolCallRequest` API shape, liveness after terminal, and mutating-tool hard-deny tests.
- Independent source consistency review: `audits/step5d-tool-authority-review.md`. **Stage outcome: 5D deterministic source-contract Scoped GO conditional on latest HEAD dual CI; native SubagentExecutor integration/AuthorizationProvider E2E is still NO-GO.**
- `execute_prepared` stays hard-disabled. Actual graph tool registry verification, server-stamped ToolCallRequest context propagation, provider single-instance consistency, native credential tests, WRITE/Bash receipts, cancellation/quiescence and sandbox isolation remain 5E–5G. PR #7 remains Draft/Open and unmerged.

## Step 5C deterministic/Design Freeze audit (2026-10-09)

- Preparation-only Core scope: **SCOPED GO**, real DeerFlow execution **NO-GO**. PR #7 remains Draft/Open and unmerged.
- Dedicated independent source/Design Freeze consistency sweep: `audits/step5c-independent-consistency-review.md`.
- Fixed Python collection error, native Subagent tool allow/deny override, and insufficient snapshot integrity checks. `PinnedNodeResources.assert_intact()` revalidates copied AppConfig/SubagentConfig/ModelConfig, selected tool observable surfaces and frozen LoadedExtensions generation before future guarded use.
- Scheduler is the sole execution identity allocator after Workspace lock and commit. Live `SchedulerCore.is_committed_invocation` demands exact object, ticket COMMITTED, active owner and task/epoch. 5C claim requires trusted injected checker; unknown/malformed/checker failure fails closed. Opaque preparation is consumed at most once.
- Scheduler revocation, cancellation and precommit Workspace wait call frozen-spec `release_preparation`; LivePreflightBackend forwards resource cleanup. Adversarial runtime interleaving and model/tool/extension mutation tests are in `tests/unit/test_deerflow_preparation_step5c.py`.
- Baseline test evidence: `c6fba6fc` GitHub Actions 37906425502: Python 3.11 **394 passed**, Python 3.13 **394 passed**. Latest HEAD, including checker-error negative, requires fresh green CI before final closure.
- **Not proven:** arbitrary native Python callable closure/ExtensionData immutability, real DeerFlow package import, live AuthorizationProvider, actual model API invocation, tool-call middleware, execution quiescence, sandbox/Bash receipts, or real shared mutable Workspace. 5D–5G remain open.

## Step 5C pinned preparation checkpoint (2026-10-09)

- PR #7 remains Draft/Open. New `src/aswe/integrations/deerflow/preparation.py` introduces `DeerFlowPreparationBackend`, opaque `PinnedNodeResources` and one-shot `claim_for_execution` as an explicitly **5C-only, execution-disabled** seam.
- Preparation validates authoritative Descriptor/NodeExecutionPolicy identity, creates a deep-copied AppConfig/SubagentConfig, resolves explicit model, assembles eager config tools with pinned LoadedExtensions, revalidates live inventory/operator restrictions, seals tool object and callable identities, and records a content-addressed backend snapshot ID.
- Required tool identity drift, unrecognized models, changed subagent model, missing infrastructure tools/skills and untrusted configs fail closed. Optional changed implementations are dropped rather than rebound. Prepared resources are held only in memory; `discard_preparation`/`discard_all` are available for revocation.
- **Important limitations:** native loaded extension internals and tool closure internals are not recursively immutable; their mutation/use-time authorization requires Step 5D ToolCallGuard. `execute_prepared` refuses with `REAL_DEERFLOW_EXECUTION_NOT_ENABLED`. No actual DeerFlow model/subagent/Workspace execution or credential test has run. Snapshot tests are deterministic API-shaped stubs only; GitHub Actions latest-head completion pending.
- 5D/5E must implement real execution and cleanup without rereading AppConfig, SubagentConfig, tool assembly, model selection, or extensions after prepare. No PR merge or production GO.

## Step 5B deterministic reasoning adapter checkpoint (2026-10-09)

- PR #7 Draft / OPEN: `DeerFlowReasoningBackend` and `ModelInvoker` implemented under `src/aswe/integrations/deerflow/model_invoker.py`.
- Operator-specified role→model mapping, pinned source checked on each call, explicit `create_chat_model` args, current model-use Authz, config drift, strict local-only JSON Schema, error/timeout/cancel are covered by deterministic tests.
- Analyzer/Planner output remains non-authoritative. Unauthorized code-modification proposal is rejected by the existing Validator in a model-adapter cross-chain test.
- Current scope: **Step 5B Core contract implemented, actual DeerFlow import/API/credential/model smoke still PENDING**; no real managed ExecutionBackend/Workspace GO.
- Next: 5C pinned `NodeExecutionPreparation` + AppConfig/Tool/Model/Extensions snapshot.
- Audit: `audits/step5b-model-invocation-review.md`.

## Coding Step 5 — DeerFlow Adapter (2026-10-09)

- **IN PROGRESS**, Stage 5A pinned source/Inventory Adapter code in `coding/step5-deerflow-adapter`; actual DeerFlow execution remains **NO-GO**.
- Frozen DeerFlow `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891` inspected, including real tool loader, SubagentConfig, models, sandbox constraints.
- Real `config:<ToolConfig.use>` tool identity is now distinct from FakeBackend `config:<contract-id>` and never implied by routing name; source/loaded callable contract proof required.
- Source checkout HEAD/clean tracked harness check and runtime eager tool assembly inventory collector present. Wall-clock-only inventory snapshots no longer cause meaningless fingerprint drift.
- Step 5A deterministic tests do **not** prove a live DeerFlow model/credential/sandbox deployment. DeerFlow itself requires Python >=3.12. Step 5B–5G remain planned; see `plan/step5-implementation-entry.md`, `audits/step5-gate-audit.md`.
- **Frozen Go/No-Go still OPEN:** POC-02/03/05/09, R34/R35/R36/R38/R50/R51/R69/R70/R73. Do not enable real shared mutable Workspace execution.

## Step 4 independent Design Freeze audit (2026-10-09)

- Source-level independent audit complete: `audits/step4-independent-freeze-review.md` with frozen P0-5 machine coverage in `audits/step4-poc-coverage.json`.
- **Scoped GO** for Stage-4 Core/Provider/DAG/Live-Preflight/FakeBackend baseline; **not** a claim that real DeerFlow adapter is accepted.
- All four requested deliverables implemented: `providers/policy.py` (NodeExecutionPolicy + ProviderAssignment/TeamSpec), `providers/preflight.py` (precommit LiveInventory drift + pinned execution), `planning/descriptor.py` (CompiledPlanDescriptor and exact Acceptance identity), plus independent audit.
- Independent P0 blockers closed: ProviderContract identity, self-signed dropped required bash, exact Acceptance command fingerprint, Contract global deny scopes, singleton model identity and Backend snapshot.
- Latest **implementation** dual CI at `ca15d8e2` ran **335 passed** on Python 3.11 and Python 3.13. Audit-only updates must get green latest-head CI before merge.
- P0-5 + R/F audit: **13 Core PASS / 5 PARTIAL / 12 STEP5-OWNED**; don't mark real DeerFlow integration all-pass.
- Frozen Stage-3 semantic and physical C/P3 audit remains **22 PASS / 0 PARTIAL / 0 GAP** on PR #6 branch; new physical proofs await merge to appear on main.
- Recommendation: merge PR #6 as *scoped Step-4 Core baseline* when latest-head CI + branch mergeability pass; Step 5 owns live assembly/tool surface/AuthorizationProvider/Skill middleware.

## Step 4 physical P3 integration checkpoint (2026-10-09)

- PR #5 **MERGED** into `main` at `584c1eae`, accepting Step-3 semantic compiler baseline only.
- Step-4 branch `coding/step4-capability-provider-dag` implements canonical CapabilitySpec vocabulary, trusted static FakeBackendInventory/AgentProvider, ToolEffect / WorkspaceAccess, deterministic TaskDAG Materializer and real Git post-node Tester guard.
- Five Step-3 deferred P3 cases are **PASS on this branch**: P3-01/02/03/04/11, with actual Scheduler and Git tests; frozen P3/C inventory now **22/22 scenario PASS**, awaiting PR #6 review/merge before main is updated.
- Implementation CI `29cc2aef`: Python 3.11 and 3.13 **305 passed** each (run 37895498872).
- **Step 4 is NOT CLOSED:** remaining provider preflight / live inventory / execution policy / descriptor / stage-4 P0-5 PoCs require separate review and coding. No DeerFlow adapter executed.
- See `audits/step4-physical-poc-audit.md`.

## Step 3 P0 closure and Step 4 handoff (2026-10-09)

- Scoped **GO** recommendation after P0-A..D source/negative test review. See `audits/step3-freeze-closure.md`.
- Real pinned Git RepositoryProfile, source-validating TaskAnalyzer, read-only Context Gate, conservative natural-language mutation authority, recursive frozen compiled payloads are implemented.
- CI at implementation `4e76a9c9`: Python 3.11 = 297 passed, Python 3.13 = 297 passed.
- **Do not confuse a scoped Stage-3 compiler merge with frozen 22/22 final acceptance.** P3-01/02/03/04/11 remain assigned to Step 4.
- Next: approve/merge PR #5 only after latest-head CI, then establish Step 4 branch from accepted main.

# Implementation Status

## Stage status

- Step 0 — CLOSED / ACCEPTED
- Step 1 — CLOSED / ACCEPTED
- Step 2 — CLOSED / ACCEPTED (PR #4 merged as `3d19541bb9f0f7e345ec0f4fb8af3a5415b5ed53`)
- Step 3 — **Scoped baseline GO / PR #5 final merge gate**: P0-A..D closed and dual CI green; **17 PASS / 5 PARTIAL / 0 GAP**; remaining five physical PoCs are Step 4-owned. See `audits/step3-freeze-closure.md`.
- Step 4 and later — NOT STARTED

## Step 2 accepted implementation (PR #4 merged)

- [x] Runtime CanonicalVerifier: exact compiled argv as foreground subprocess, no shell, bounded timeout
- [x] Before/after exact Git state comparison; nonzero -> deterministic FAIL, zero -> HOLDS, mutation/timeout -> UNVERIFIED
- [x] Persist attempt-scoped canonical command receipt with signed checksum outside Agent Workspace
- [x] Strict Repair Attribution refuses untrusted fixture receipts by default; fake-only test bypass requires explicit opt-in
- [x] Typed RepairFeedback with frozen source, target, revision, failed checks, VerificationResult/Attribution EvidenceRefs and ReceiptRefs
- [x] Writer repair dispatch validates typed feedback freshness while holding Workspace lock
- [x] ContractLeafVerdict/ContractVerdict with HARD/LOCKED blocking invariants and compiler fingerprint expectation
- [x] RootFailureRecord/TaskResult with four independent axes: status, Workspace, Repository and Patch
- [x] Deterministic FROZEN Git state / patch materialization through task-scoped TaskEvidenceRefs
- [x] QUARANTINED terminal path never inspects current Workspace, retains only validated historical attempt evidence
- [x] Residual unaccepted patch on failed/cancelled task; no success without full contract authority
- [x] LocalTaskResultStore durable exactly-once terminal publication, restart recovery and tamper detection
- [x] Task normal-completion gate and distinct task-wide user cancellation handling
- [x] Full 65-case PoC inventory with direct test-symbol links and honesty guard

## Full frozen PoC exit audit

- Audited cases: 65 (R16–R26, R75–R128)
- PASS: 65
- PARTIAL: 0
- GAP: 0
- Step 2 is formally **CLOSED / ACCEPTED** at merge commit `3d19541b`; scope is deterministic FakeBackend Runtime.

## Step 2 final acceptance evidence

- Frozen inventory: 65 PASS / 0 PARTIAL / 0 GAP; exact one-row-per-PoC Markdown audit is built from machine-readable manifest.
- Final source review: `audits/step2-finalization-review.md`. Race condition in cancellation-versus-COMPLETED addressed with regression tests.
- Merged PR #4 HEAD `aa34fb50e11761b56d386fa6d2f570b6f2fe3173`: Python 3.11 **202 passed**, Python 3.13 **202 passed**; merge commit `3d19541bb9f0f7e345ec0f4fb8af3a5415b5ed53`.
- No Step 5 DeerFlow sandbox/integration certification claimed.

## High-priority remaining P0 blockers

- [x] Local Node cancellation (R21), including running join and descendant propagation
- [x] Verification-triggered stale RepairFeedback refresh (R23/R25/R26): canonical fresh check, fresh refs/fingerprint, no redundant repair on HOLDS
- [x] Own AcceptanceFailure stale deterministic recheck R24: Runtime canonical check + typed acceptance verdict, restricted to mutated WRITE and bounded repair
- [x] Multi-writer ambiguity / non-attribution tests R76–R83, R86–R88
- [x] R84/R85 physical tracked mutation and real backend crash refusal tests
- [x] R89 real Git intervening Writer and Runtime-owned post-digest capture
- [x] R101/R102 actual mutated WRITE acceptance → bounded repair → repair budget exhausted, residual patch terminal proof
- [x] R91/R94/R95/R99/R123/R128 physical dirty-failure, quarantine and fail-close cancellation result integration
- [x] R100 trusted typed ReviewGate REQUEST_CHANGES callback + persisted attempt REVIEW_VERDICT; FakeBackend-only API, integration with DeerFlow remains Step 5
- [x] R103 typed TaskLogicalStatus FAILED/CANCELLED publication within Scheduler mutex transaction
- [x] P0-D deterministic concurrency barriers R119–R121/R125–R126, including noncommitted physical Workspace join and timeout quarantine
- [x] All 65 audit PoCs have test evidence and independent source/Design Freeze consistency sweep is documented
- [x] GitHub latest-head CI, PR #4 merged, Step 2 CLOSED publication

## P0-B incremental status

- Verified with actual Scheduler Writer attempts: singleton multi-check, two business Writers, same Provider distinct writers, last-writer heuristic, changed_paths/prose non-attribution, no-owner poison, split-check attribution, retry accepted attempt2, physical WRITE verifier exclusion.
- R89 now PASS: physical Writer B tracked mutation + Scheduler actual Git digest + attested Verification Result give SCOPE_INVALIDATED.
- R24 now PASS in mutated WRITE, canonical-check-proven own AcceptanceFailure with stale revision; no clean failed execution can silently become own Repair. HOLDS suppresses redundant repair, without fabricating success.

## P0-C terminal closeout (2026-10-09)

- Repair exhausted Writer final status: FAILED, FROZEN with proven quiescence; real tracked modifications become RESIDUAL_UNACCEPTED, never ACCEPTED.
- Runtime preserves the **new attested AcceptanceVerdict EvidenceRef on exhausted attempt**, not just its predecessor.
- Fail-close cancelled Consumer is CANCELLED rather than another business FAILED root; its observed mutation is a secondary diagnostic and appears in final repository patch.
- Unsafe/quiescence-unknown consumer or user cancellation causes QUARANTINED, so terminalizer does not probe current Git.
- R100 and R103 now PASS for deterministic Step-2 FakeBackend scenarios; real DeerFlow reviewer adapter remains out of scope.

## P0-D concurrency closeout (2026-10-09)

- Deterministic asyncio.Event/physical-lock interleaving tests now cover R119/R120/R121/R125/R126.
- Real bug repaired: fail-close now joins active physical Workspace holders as well as committed backend attempts before declaring FROZEN. Timeout quarantines safely.
- Slow synchronous EvidenceChecker is dispatched via asyncio.to_thread instead of blocking Scheduler's event loop, with final ticket authority rechecked before dispatch.
- Implementation HEAD `2b4061d`: Python 3.11 and 3.13 each 199 passed. Frozen PoC matrix 65 PASS / 0 PARTIAL / 0 GAP.
- **Step 2 CLOSED:** independent source/Design Freeze consistency sweep documented, latest-head CI verified, PR #4 merged.

## Step 3 Global Design Freeze (2026-10-09)

- Independent review: **PR #5 NO-GO** despite passing unit tests. `audits/step3-global-freeze-review.md` is authoritative audit disposition.
- Required before scoped Step-3 merge: deterministic Git RepositoryProfile, TaskAnalyzer/Rule Validation/Context Gate, ordinary SWE natural-language effect provenance, recursive compiled-artifact immutability, and independent latest-head review.
- Mitigated in PR: forged non-test HARD EvidenceRef now remains UNVERIFIED; stale final receipt rejected; compiler version and loaded Repository Guidance are included in contract hash.
- Frozen 22-case Step-3 inventory: **17 PASS / 5 PARTIAL / 0 GAP**. P3-01/02/03/04/11 have explicit Step-4 physical DAG ownership, not waived.
- Step 4 entry scope: `plan/step4-implementation-entry.md`; no real DeerFlow permission. Step 3 not CLOSED, PR #5 stays DRAFT.

## Step 3C semantic planning checkpoint

- `WorkPlanProposal` remains untrusted; `SemanticPlanValidator` issues immutable normalized `ValidatedWorkPlan` bound to TaskContract fingerprint.
- Runtime-owned mandatory Verification/Review gates, dependency dedupe and PlanRepair/PlanCoverage evidence tested.
- Stage 3 22-case frozen audit: **17 PASS / 5 PARTIAL / 0 GAP**; see `audits/step3-poc-coverage.json`.
- P3-01/02/03/04/11 retain physical/phase DAG obligations for Step 4. C09/C10 now PASS direct Step 3D tests with attested CanonicalVerifier and terminal fingerprint binding.
- Do not merge PR #5 or label Step 3 CLOSED.

## Step 3D Acceptance checkpoint

- `VerificationCommand` is compiler-owned and immutable; `tests_passed:<command>`, Bash exact allowlist, and CanonicalCommandPolicy derive from one identity. Only TEST commands may compile to tests_passed; BUILD/IMPORT/STATIC fail closed.
- Local authenticated canonical receipts drive trusted verification leaves; HARD/LOCKED UNVERIFIED and unproven NOT_APPLICABLE block Task success.
- `ExecutionContractBinding` ties contract, validated work plan, acceptance policy, and Git base; `finalize_bound_task` rejects a changed observed execution stamp.
- Step 3D real Git/CanonicalVerifier terminal test completed; Python 3.11 and 3.13 **273 passed** on `2a4b952c` (run 37880285730).
- Current frozen Step 3 inventory: **17 PASS / 5 PARTIAL / 0 GAP**. Remaining cases need Step 4 physical DAG integration.
- Do not merge PR #5 or mark Step 3 CLOSED until independent review and remaining physical PoCs.

## Step 3 next coding gate

- Implement the frozen `specs/01-task-planning.md` Task/Constraint/Planning compiler in `src/aswe/planning/` on an isolated coding branch.
- First: compiler-owned immutable Request/Provenance contracts; then Constraint merge algebra POC-C01–C06; then PlanValidator/Normalizer and Acceptance compiler.
- Step 3 must satisfy POC-P3-01..12 and POC-C01..10, with deterministic FakeReasoningBackend tests, before its own closure.
- Step 4 DAG/Provider compilation and Step 5 DeerFlow integration remain out of scope.

## Strict limits

- CanonicalVerifier is a **local, Runtime-owned foreground checker**, not the DeerFlow native acceptance/checker/CommandPolicy adapter (Step 5).
- The persisted HMAC deters accidental forgery/tamper inside the Runtime trust boundary; it is not protection against a process with arbitrary Runtime-data access.
- P1 Runtime is still FakeBackend-first. No autonomous LLM/Agent/DeerFlow path is certified.
- Future finalization must consume the compiled contract fingerprint from the authoritative planner/compiler; it may not be inferred from model prose.

See audits/step2-poc-audit.md, audits/step2-poc-coverage.json and audits/step2-finalization-review.md.


## 5F-D Live Model Run #38018937188 — Verified (2026-10-10)

- **Real live result: Scoped GO** for *one actual paid-model autonomous coding smoke*, on commit `1cc3567eeed4550254b0cff35f9f2183bcbefe59`; GitHub Actions run: https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38018937188. This was a `workflow_dispatch` on `coding/step5-deerflow-adapter`. Workflow conclusion `success`; no retries recorded.
- Actual model stage `One real LLM autonomous repair and canonical verification` succeeded. GitHub Actions credentials preflight succeeded; the run uploaded artifact `swe-live-mvp-report` (ID `11657392376`), retrieved and parsed independently.
- Report: `native_status=completed`, `verification_status=passed`, `verified_returncode=0`, `tests_passed=true`, canonical check `mvp-python-regression-container`, nonempty canonical EvidenceRef bound to this execution, `agent_dynamic_command_count=2`, `agent_last_dynamic_command_exit_code=0`, `agent_tool_changed_paths=["calc.py"]`, `changed_files=["calc.py"]`, `git_diff_truncated=false`. Exact observed patch: `calc.py` `return 1` → `return 42`; regression test file was not modified.
- **Not strict ACCEPTED**: report honestly states `scheduler_failed=true`, `scheduler_node_status=failed`, `workspace_status=quarantined`, `quiescence_proven=false`, `delivery_status=tests_passed_scheduler_quarantined`. Full Sandbox Quiescence remains deferred and no strict NodeHandoff/TaskResult was signed.
- Limits: script includes instructions to inspect specified files and run unittest, but **model tool calls were not hardcoded**. Only aggregated command counts and patch are stored; no full per-tool/model transcript, so **the real-model run does not independently prove a failing-test→repair retry or reasoning trajectory**. No repeatability study, unknown token/cost, no provider stress/benchmark, no production 5C inventory/Authz single physical composition. The test fixed only a trivial Python regression; do not claim general SWE-bench capability.
- Decision: **5F-D minimal real-model smoke accepted, within expressly limited scope**. PR #7 remains Draft/Open/unmerged. Before full Step 5 Design Freeze consider optional per-tool structured trace without secrets, reliable provider cost counters, and a harder multi-step bug. Do NOT replay paid API calls automatically.
