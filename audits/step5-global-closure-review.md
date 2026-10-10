# Coding Step 5 — Global Consistency Sweep / Design Freeze Closure Audit

**Audit date:** 2026-10-10
**Reviewed implementation commit:** `067c114d3baeadc8f44752b5d2cde351630d793c` (PR #7: `coding/step5-deerflow-adapter`)
**Frozen DeerFlow:** `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891`
**Scope:** 5A inventory → 5B model reasoning → 5C pinned preparation → 5D authority/tool binding → 5E native LangGraph integration → 5F evidence/quiescence/managed commands → 5F-C real SWE tools → 5F-C-B MVP results → 5F-D real credentialed model.
**Audit method:** GitHub source-to-freeze comparison; exact pinned DeerFlow source inspection; PR diff inventory; CI/log and one credentialed manual Actions run verification. No new paid model call, no code execution in this audit, and no claim of new negative PoC runs.

## Executive verdict

| Scope | Verdict | Meaning |
|---|---|---|
| 5F-C-B and 5F-D constrained SWE smoke | **Scoped GO** | Real Scheduler commit, 5D postcommit guarded native graph, real Docker command, independent containerized Python test, bounded Git diff, HMAC canonical receipt and model-driven repair have physical evidence |
| Step 5 architectural/semantic Design Freeze closure | **NO-GO (3 P0)** | See P0-01/02/03; no production 5C → 5D → Native proof, a reversed Core dependency and a conditional false no-mutation declaration |
| PR #7 as **fully completed Step 5 baseline** | **NO-GO now / CONDITIONAL GO after P0 closure** | Keep Draft/Open/unmerged until evidence-backed P0 fixes. An experimental/demo-only merge would require explicitly different scope approval; it must not be represented as full Stage-5 implementation |
| Production-grade accepted SWE TaskResult | **NO-GO, deliberately deferred** | Quiescence, 5C production authorization, full Acceptance and downstream DAG gates have not been proven; do not reinterpret MVP test success as strict ACCEPTED |

This audit **does not** reverse the user's decision to defer formal Sandbox Quiescence. Deferral alone is **not** a new MVP P0: native WRITE remains `quiescent=False`, Core fails closed, workspace is quarantined, and no accepted NodeHandoff or completed TaskResult is forged. However, unrelated correctness bugs may not be waived by this deferral.

## Independently verified evidence

1. **PR #7:** 59 changed files, about 9,442 additions and 33 deletions at audit start; no vendor fork. All listed checks on `067c114d3baeadc8f44752b5d2cde351630d793c` were successful. Core GitHub Actions run `38019190974`: **487 passed** each on Python 3.11 and 3.13. Frozen installed DeerFlow Python 3.12 native/Docker run `38019190984`: **11 + 1 + 1 + 2 = 15 passing tests** in its four commands. Source: [Core CI](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38019190974), [vendor CI](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38019190984).
2. **Manual true-model run:** `workflow_dispatch`, `coding/step5-deerflow-adapter` at `1cc3567eeed4550254b0cff35f9f2183bcbefe59`, [run #38018937188](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38018937188) SUCCESS; preflight, model invocation, test and report upload succeeded. Artifact `swe-live-mvp-report` / ID `11657392376` was retrieved in the preceding acceptance review. The reported patch was `calc.py: return 1 → return 42` only; `native_status=completed`, `verification_status=passed`, `verified_returncode=0`, `agent_dynamic_command_count=2`, signed Canonical Receipt present. It also correctly reports `scheduler_failed=true`, `workspace_status=quarantined`, `quiescence_proven=false`.
3. **Truthful limits:** The live test uses `PhysicalPreparedToolSource` (a test fixture), not production 5C. No real model tool-by-tool transcript persisted, so the live run proves a read/edit/tool/test path, **not** a real-model failed-test→repair loop. The latter has a separate *scripted offline* LangGraph/Docker integration test.
4. **Source of truth:** [AGENTS.md](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/AGENTS.md) §§3,5,6,7,9,10,11; frozen specs 01–04, Step 4 audit and frozen source SHA. A green Core test that omits a boundary or lacks a real provider connection does not prove that property.

## Stage-by-stage assessment

| Stage | Evidence | Closure |
|---|---|---|
| 5A — tool inventory/effects | Real `ToolConfig.use` discrimination, eager assembly, hashed immutable inventories, source-pinned policy; many negative unit tests | **Scoped GO**; cannot infer deployed 5C Bash availability |
| 5B — ModelInvoker | Frozen create_chat_model signatures, roles, JSON Schema, Authz failure/timeout tests; actual native ChatOpenAI client construction via fake key | **Scoped GO**; 5B full planning path has not been run with the real remote model |
| 5C — prepared source snapshot + live inventory | `DeerFlowPreparationBackend` implements deep snapshot/policy revalidation/tool seals and commit-time claim | **Unit GO, physical integration NO-GO** (P0-01) |
| 5D — tool policy/Authz guard | Real `NodeExecutionBindingStore.bind()`, middleware and immutable bound ToolNode, real mounted tool calls; unit negative scenarios | **Scoped GO**; physical live E2E uses fake 5C `assert_intact=lambda: None` and disabled external Authz |
| 5E — frozen DeerFlow Native | Installed `SubagentExecutor` and real LangGraph graph, reserved run principal, completion/cancel safeguards, exact source pin | **Scoped GO**; external worker/sandbox quiescence unproven |
| 5F-A/B — evidence, leases, foreground | HMAC receipts, Git snapshots, deterministic lease tests, process groups for trusted foreground; current Native event cleanup | **Scoped only**; positive native Quiescence remains deferred; P0-03 future WRITE misclassification risk |
| 5F-C — coding + Docker | Actual `read_file/str_replace/bash` isolated runtime tools and real Docker; read-before-write restrictions for file tools | **MVP GO**; unrestricted Bash still writable across repository incl tests/.git; policy interaction P1-01 |
| 5F-C-B — MVP report | Real Scheduler commit, independent python test, Git diff, execution identities, signed receipt; strict quarantine | **MVP GO**; `MVPTaskReport` is not `TaskResult`, acceptance binding incomplete |
| 5F-D — paid model | One actual manual Actions run passed; credentials absent from Docker; JSON report | **One-sample Scoped GO**; no trace, benchmarking, or production provider Authz |

## P0 — blockers for GLOBAL Step 5 closure / full-baseline PR merge

### P0-01 — Production 5C → 5D → Native tool identity/host Bash contradiction is unproven

**Evidence:**
- Production `DeerFlowPreparationBackend.prepare_node()` calls native `get_available_tools()`, constructs `live.candidate_tools`, and only permits selected tools found in that assembled native list: [preparation.py L295–342](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/src/aswe/integrations/deerflow/preparation.py#L295-L342).
- In frozen upstream DeerFlow, `get_available_tools()` filters its `bash` ToolConfig when `is_host_bash_allowed(config)` is false: [pinned tools.py L154–166](https://github.com/bytedance/deer-flow/blob/c0895d295bba34f6e95188fca380f555dabed891/backend/packages/harness/deerflow/tools/tools.py#L154-L166); for `LocalSandboxProvider`, that value depends on `allow_host_bash` [pinned security.py L35–45](https://github.com/bytedance/deer-flow/blob/c0895d295bba34f6e95188fca380f555dabed891/backend/packages/harness/deerflow/sandbox/security.py#L35-L45).
- **Actual live E2E** sets `LocalSandboxProvider / allow_host_bash=False` and manually fabricates a prepared source-tool list containing `bash` as a `SimpleNamespace`, with `assert_intact=lambda: None`: [test_deerflow_mvp_e2e_step5fcb.py L72–115](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/tests/integration/test_deerflow_mvp_e2e_step5fcb.py#L72-L115), used by [live smoke L114–150](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/tests/integration/test_deerflow_live_swe_step5fd.py#L114-L150). The native 5D store and actual Docker execution *are* real, but its authoritative 5C provenance is synthetic.
- In checked-in production modules, there is no tested composition of `DeerFlowPreparationBackend.from_deerflow` → `NodeExecutionBindingStore.from_deerflow` → Native backend → SWE Bash, with the compiled descriptor and active Authz.

**Risk:** Directly switching the demo to the production 5C source with the existing `LocalSandboxProvider/allow_host_bash=False` may drop the required `bash` tool before the 5D Docker wrapper is allowed to be installed. Setting `allow_host_bash=True` globally just to let 5C discover the tool could expose unintended native host Bash elsewhere; do not quietly do this. No general impossibility is asserted for other sandbox/provider designs, only that **the current supported physical path has not been demonstrated**.

**Closure:** Explicitly design and attest a *trusted, non-host-Bash* logical Bash contract or another isolation-preserving selection mechanism, with an actual installed source inventory. Run one no-credentials physical E2E proving `CompiledPlanDescriptor`/policy fingerprint → real 5C → actual 5D → committed Native → real Docker → independent Canonical. Include a negative test for host Bash filtered/unintended exposure. If resolving it changes the frozen capability/tool implementation contract, use the AGENTS.md Design Freeze reopen procedure rather than inventing authority.

### P0-02 — Core Runtime imports DeerFlow Adapter types (reverse dependency)

**Evidence:** `CanonicalVerifier.run_isolated_python()` imports `DockerCommandBackend` from `aswe.integrations.deerflow.controlled_swe`; `attest_foreground_observation()` imports `ForegroundReceipt` from `aswe.integrations.deerflow.managed_foreground`: [runtime/canonical_verifier.py L163–182](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/src/aswe/runtime/canonical_verifier.py#L163-L182), [same module L235–266](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/src/aswe/runtime/canonical_verifier.py#L235-L266).

**Conflict:** AGENTS.md §5.1 requires dependencies `Core ← Backend Protocol ← integrations/deerflow`, never the reverse. [Architecture test](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/tests/architecture/test_no_deerflow_in_core.py) only rejects direct imports whose root is literally `deerflow`; it does not reject `from aswe.integrations.deerflow...`, allowing this violation to pass 487 tests.

**Closure:** Move DeerFlow/Docker-specific binding/adaptation to the integration layer, passing a provider-neutral, Runtime-owned command/outcome contract into `CanonicalVerifier`; retain Runtime signing/receipt validation authority. Extend the architecture test to reject imports of `aswe.integrations.*` from protected Core/Runtime modules. Verify no source dependency inversion and preserve existing receipt tests.

### P0-03 — ExecutionEvidenceCollector hardcodes `mutating_tool_admitted=False` even for WRITE profile

**Evidence:** [execution_evidence.py L183–202](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/src/aswe/integrations/deerflow/execution_evidence.py#L183-L202) always calls `derive_node_workspace_delta(...,mutating_tool_admitted=False)`, retaining a comment that native tools cannot mutate. But `NativeDeerFlowExecutionBackend` now explicitly permits mutation when `binding.swe_runtime is not None`: [native_execution.py L375–383](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/src/aswe/integrations/deerflow/native_execution.py#L375-L383). The frozen delta derivation can mark a clean complete snapshot `PROVEN_NONE` when this parameter is false: [workspace/delta.py L55–75](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/src/aswe/workspace/delta.py#L55-L75).

**Risk:** If a caller later supplies a positive resource supervisor with the SWE WRITE profile, an execution allowed to mutate and restore files could incorrectly get `PROVEN_NONE` from this false capability assertion. The currently exercised WRITE smoke supplies no collector/supervisor and **still quarantines**, so **no current false ACCEPTED outcome was observed**.

**Closure:** Derive `mutating_tool_admitted` from the sealed bound runtime/tool policy rather than a hardcoded constant; or explicitly refuse `ExecutionEvidenceCollector` in mutable SWE profile until this evidence contract exists. Add the adversarial `WRITE admitted → files reverted → complete scan → NOT PROVEN_NONE` case. Do not use a fake positive quiescence supervisor as production proof.

## P1 — scoped limitations / hardening needed before broader use

### P1-01 — Model-selected Bash can edit tests/.git; independent tests do not generically validate immutable test authority

`ControlledSWEWorkspace` *correctly* rejects fine-grained `allowed_paths` or `max_changed_files` with Bash because the whole repo is mounted: [controlled_swe.py L165–190](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/src/aswe/integrations/deerflow/controlled_swe.py#L165-L190). The general MVP probe checks Git fingerprint/head stability and runs the policy test, **not** whether the original regression tests were modified or whether the changed-file set complied with the approved TaskContract: [mvp_task.py L116–168](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/src/aswe/integrations/deerflow/mvp_task.py#L116-L168). The real-model *fixture* separately asserts tests unchanged and only `calc.py` modified: [live test L163–189](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/tests/integration/test_deerflow_live_swe_step5fd.py#L163-L189).

**Risk:** An Agent can change tests using unrestricted Bash, then pass those changed tests; `CanonicalVerifier` would faithfully attest *the current altered worktree's tests*, not the original Acceptance requirements. No such attack was observed in run #38018937188; this is a code-path trust limitation, not a demonstrated exploit. Add independent post-execution admissible-changeset and protected-test baseline checks before announcing generic repair success. For stronger isolation, mount tests/.git read-only or outside Bash-write boundary.

### P1-02 — Default MVP canonical execution remains host-side and inherits live runner environment

`MVPTaskRunner(isolated_canonical_container=None)` uses the host `CanonicalVerifier.run()`, which launches the exact policy argv with `env={**os.environ,...}`: [mvp_task.py L143–157](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/src/aswe/integrations/deerflow/mvp_task.py#L143-L157), [runtime/canonical_verifier.py L111–133](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/src/aswe/runtime/canonical_verifier.py#L111-L133). Once code has been modified by the Agent, running a Python regression on the host with inherited `OPENAI_API_KEY` would expose the key to code under test. **The real 5F-D smoke explicitly uses `isolated_canonical_container` and passes a fake-key Docker isolation canary**, so no leak has been observed in that live execution. Make isolated verification mandatory for credentialed SWE and redact env in all non-Docker checks; regression-test the default-deny behavior.

### P1-03 — Test-command authority and strict Acceptance are not bound to the MVP report

`MVPTaskRunner` accepts a caller-supplied `CanonicalCommandPolicy` but does not validate its `check_id/fingerprint/argv` against the authoritative `CompiledPlanDescriptor` / `CompiledAcceptancePlan` for this node: [mvp_task.py L178–224](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/src/aswe/integrations/deerflow/mvp_task.py#L178-L224). The live test creates `make_command_policy()` directly: [live L105–115](https://github.com/wangd237/adaptive-swe-runtime/blob/067c114d3baeadc8f44752b5d2cde351630d793c/tests/integration/test_deerflow_live_swe_step5fd.py#L105-L115). It is a **separate MVP diagnostic**, not full TaskContract compliance or `TaskResult`. Before promoting to general use, bind independent checks to the real compiled Acceptance plan. Do **not** bypass current strict Scheduler acceptance.

### P1-04 — Production composition, model/trace and task-level workflow still test-oriented

There is no shipped operator CLI/API runner that loads a real user TaskSpec, invokes 5B reasoning/3C planning + 4D descriptor, invokes full 5C physical preparation, dispatches a DAG, and emits a frozen accepted TaskResult. The live smoke imports fixture builders from `tests.unit` and `tests.integration`; its `physical_binding_store` uses a `SimpleNamespace` with `assert_intact=lambda:None`. Tool summaries are aggregate; full secret-redacted model/tool trace, per-call token usage and cost evidence are not persisted. Mark this as *integration test harness*, not deployable service.

### P1-05 — Source/dependency reproducibility and cancellation boundaries

DeerFlow git SHA is pinned and checked, good. However CI pulls `python:3.12-slim` and `alpine:3.20` as mutable tags before converting to local digests, and dependencies installed with version ranges instead of a checked-in lock; an equal repository SHA may resolve different images/packages later. The Docker execution backend has best-effort timeout cleanup, **not** a formal externally attested process/lease drain. This is explicitly a future hardening/operations gate, not retroactive invalidation of the one physical smoke.

## P2 — polish / coverage

- PR #7 title still says “Coding Step 5A–5B … (live adapter pending)” although Step 5F-D was developed; update title and summary only when the merge boundary is determined.
- Verify live-model repair on a second, nontrivial fixture **only on explicit cost approval**. One run does not establish reliability, pass@k, tool-selection robustness, or SWE-bench performance.
- Persist a bounded, credential-redacted tool-call trace and model token/cost counters; preserve independent Runtime evidence rather than treating a model-produced log as authoritative.
- Keep source-vs-Test and authorization/sandbox policy drift negatives explicit in physical CI. Current full native vendor test count is small compared with the Core fake suite; do not conflate them.

## Priority closure sequence

1. **P0-01 first:** compile/preflight real tool inventory with the frozen upstream host-Bash filter and demonstrate a valid *non-host* Docker Bash capability path. If required, explicitly reopen the frozen source mapping and update specs/tests/audits; do not silently switch `allow_host_bash=True`.
2. **P0-02:** remove Runtime → integrations/deerflow imports, extend the architecture CI to cover transitive local layer violations.
3. **P0-03:** correct/prohibit the mutable evidence path before any collection of positive `PROVEN_NONE` or positive Quiescence from WRITE is authorized.
4. Re-run Core 3.11/3.13 + pinned vendor/native 3.12, plus one **offline actual 5C** worktree repair chain and its failure/adversarial cases. **No paid LLM rerun needed** to close P0-01/02/03.
5. Review P1-01/P1-02/P1-03 as *deployment admission requirements*. For an explicitly labeled MVP developer-only release, allow documented deferral only where the default executable path remains fail closed.
6. Audit resulting exact HEAD and decide PR #7 as **Step 5 scoped baseline** vs **production-grade release**. Quiescence remains future 5G unless user reopens the agreement.

## Final verdict

- **Functional result:** REAL-model SWE minimal smoke **PASS** with genuine patch and independent tests.
- **P0:** 3 open; 5C actual tool-source integration, Core boundary and mutable execution evidence.
- **P1/P2:** documented; not all require resolution before a scope-labeled experimental merge.
- **Global Design Freeze:** **NO-GO**.
- **PR #7 as full Step 5 baseline:** **DO NOT MERGE YET**.
- **After three P0s + positive installed-native/physical CI:** **CONDITIONAL GO** for a clearly marked *developer/MVP Step 5 adapter* PR, not for full Quiescence-verified production TaskResult.

**Audit is source-based on reviewed HEAD; this document does not claim to have changed application code or run new negative integration experiments.**
