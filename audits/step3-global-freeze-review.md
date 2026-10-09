# Step 3 Global Design Freeze / Cross-Contract Audit

> **Historical review:** the blockers and NO-GO recommendations below describe the code *before* P0-A..D fixes. For the latest implementation disposition and direct tests, read [Step 3 P0 closure review](step3-freeze-closure.md). Step 3 is not 22/22 fully CLOSED.


**Date:** 2026-10-09  
**Decision at original audit:** **NO-GO** (historical). **Current scoped merge disposition:** see `audits/step3-freeze-closure.md` (P0-A..D closed; 5 P3 physical cases still PARTIAL).  
**Scope:** Independent comparison of active `AGENTS.md`, `specs/01-task-planning.md`, `specs/02-capability-provider-dag.md`, `specs/04-evidence-evaluation.md`, `plan/master-plan.md`, frozen `tests/poc-matrix.md` against PR #5 source, tests and CI.

This report is **not** an authorization to relax frozen specs, waive a PoC or begin real DeerFlow execution. It supersedes any informal inference that green CI or 17/22 PASS makes Step 3 formally CLOSED.

## Audit method and reproducibility

- Compared current `src/aswe/planning/{profile,analyzer,contracts,constraints,registry,compiler,planner,validator,acceptance}.py` with frozen §4.2–4.15, plus Step 4's authoritative source.
- Checked the existing Step-2 contract owner in `src/aswe/runtime/canonical_verifier.py` and the single `ContractVerdict` owner in `src/aswe/evaluation/contracts.py`.
- Checked [PR #5](https://github.com/wangd237/adaptive-swe-runtime/pull/5), frozen 22-case Step-3 inventory and the dual-Python GitHub Actions results.
- Added negative regressions for fake non-test Review evidence and stale terminal CanonicalVerifier revision. Added contract fingerprint binding to compiler ruleset/version and all loaded guidance content (even when no candidates extracted).
- At the implementation checkpoint `63591bbb8a7d22833d3b95b9a5a63631e91a9921`, Python 3.11/3.13 each passed **276 tests** (run 37881212222). Later audit-only/merge-reconciliation commits require their own CI.
- Source code is not independently reviewed merely because both test lanes are green.

## Audit findings and disposition

| Finding | Severity | Authoritative location | Observed code / gap | Merge disposition |
|---|---|---|---|---|
| DF3-01 — Missing deterministic RepositoryProfile collector and anchor search | **P0** | §4.2–4.3 | `planning/profile.py` defines `RepositoryProfile`/ `AnchorMatch` schema only. No Git tracked-inventory/tree/manifest/anchor collector, bound limits, or real Git profile-source tests | **BLOCK**: Step-3-owned behavior, not Step 4 |
| DF3-02 — Missing TaskAnalyzer/Rule Validation, Context Gate/Recon path | **P0** | §4.4–4.7 | `planning/analyzer.py` holds types/protocol only; no analyzer implementation, deterministic bug_fix/testing/risk/profile rules, read-only Recon trigger. `PlanningContext` currently differs from frozen fields: missing `recon_report`, `context_complete`, `unresolved_questions`, `fingerprint` | **BLOCK**: implement or explicitly Design Freeze reopen; do not silently substitute `recon_notes` |
| DF3-03 — Normal SWE user request does not produce authorized effect | **P0** | §4.8.8.1 / §4.8.18 | `ConstraintCompiler` recognizes structured standalone `deliverables.required: repository_mutation | ...` but ordinary source-authentic `Fix the connection leak` is only retained as semantic HARD, never repository-mutation grant. Fails the Spec's own natural-language example / practical TaskAnalyzer→ConstraintCompiler path | **BLOCK**: add source-faithful conservative semantic effect derivation with strong negative tests (analyze/quoted/negated/injected text), no hint-based escalation |
| DF3-04 — Arbitrary non-test EvidenceRef could mark HARD satisfied | **P0, mitigated** | §4.8.16 / §14.4 | `evaluate_compiled_contract` had authenticated test receipts, but other leaves accepted caller-supplied SATISFIED with any nonempty EvidenceRef. **Fixed fail closed:** absent a trusted non-test resolver, HARD/LOCKED SATISFIED and NOT_APPLICABLE resolve to UNVERIFIED. Added fake-review-ref test. Legitimate Review / changed-path evaluator remains a **later integration obligation** | **Patch accepted; no general Review/deliverable success claim** |
| DF3-05 — Stale canonical terminal receipt could be reused | **P0, mitigated** | §4.15 / §14.4 / WorkspaceRevision | `finalize_bound_task` did not fence attested receipt's observed revision to terminal Scheduler revision. **Fixed**; stale evidence now `VERIFICATION_PROOF_STALE` and has a direct negative test. Actual execution-time binding source still Step 4 | **Patch accepted; Step 4 must pin observed snapshot** |
| DF3-06 — Fingerprint lacked compiler rule-set version and irrelevant-guidance content | **P0, fixed** | §4.8.17 | Old `CompiledTaskContract` hash bound task, policy, Git base and output constraints, but not compiler version or loaded guidance with zero candidates. **Fixed:** `compiler_ruleset_fingerprint`, canonical `repository_guidance_hashes`, negative identity tests | **Patch accepted** |
| DF3-07 — Nested mutable containers inside frozen artifacts | **P1, open** | §4.8.12 / §4.14 | FrozenModel prevents field reassignment, not mutation of nested dict/Any in `CompiledConstraint.value`, `compiler_repairs`, `warnings`, `PlanRepair.details`. Hash checks run at model validation, not every read. A post-validation mutation may leave stale fingerprints | **BLOCK prior to formally accepting immutable compiled artifacts**; canonical deep-freeze / typed values + tamper regression |
| DF3-08 — Scope/Enforcement phase projection not implemented end-to-end | **Deferred, gated** | §4.8.14–15 / Step 4/5 | Step 3 Contract represents restrictions, but NodeExecutionPolicy PRE_TOOL_GUARD / POST_NODE_INVARIANT / final Git checks are not yet materialized. No model prose may count as actual sandbox enforcement | **Step 4 owns compile/policy; Step 5 owns DeerFlow guard adapter** |
| DF3-09 — Five frozen phase/physical PoCs remain partial | **Deferred, gated** | P3-01/02/03/04/11 | Semantic validators cover their own phases. Auto materialized phase edges, deterministic same-phase WRITE ordering and real bash/Git tester mutation detection remain absent | **Step 4/Runtime integration owners**; keep these PARTIAL, never claim stage-wide 22 PASS |
| DF3-10 — ExecutionContractBinding lacks real dispatch source | **Deferred, gated** | §4.13/4.15 / Step 4 | Step 3 produces a digest-sealed `ExecutionContractBinding`, but `observed_execution_binding_fingerprint` is provided by the caller, not a persisted/pinned Provider admission snapshot | **Step 4 must supply a Runtime-owned immutable dispatch binding** |
| DF3-11 — Native DeerFlow evidence semantics not proven | **Deferred, gated** | §4.15 / Step 5 | Local CanonicalVerifier ≠ pinned DeerFlow `tests_passed` which requires correct per-attempt `bash_executions`, `shell_persistent=False`, and pre-execution evidence collection | **Step 5 explicit Go/No-Go** |
| DF3-12 — Branch integration conflict and docs freshness | **Reconciled in parent merge; CI pending** | PR #5 / main | PR #5 initially reported `mergeable_state=dirty`. Main's README/Stage status is explicitly incorporated via merge-parent integration; stale branch status replaced with NO-GO audit gate | **Require GitHub mergeability recheck and latest-head CI; this does not authorize PR merge** |

## Frozen PoC inventory: do not confuse executable evidence with scoped completion

The 22 frozen Step-3 identifiers remain:
- **17 PASS:** C01–C10 and P3-05/06/07/08/09/10/12.
- **5 PARTIAL:** P3-01/02/03/04/11. These must be completed by the Step-4 DAG/Workspace layer, not relabeled based on SemanticPlanValidator tests.
- **0 GAP in the existing C/P3 matrix**, but DF3-01/02/03/07 are **real source-vs-Spec findings not represented adequately by that matrix**. Do not modify frozen tests to hide this missing coverage.

C09/C10 PASS is **scoped** to deterministic Acceptance commands, HMAC-attested local canonical check and same-contract TaskResult identity in FakeBackend/temporary Git. It does not prove that all non-test HARD constraints have a trusted evaluator or that real Provider/DeerFlow execution is bound to that fingerprint.

## PR #5 exact merge boundary / exit decision

**Current decision: NO-GO.** The following are the minimum Step-3-owned closure obligations before PR #5 may be considered for merge:

1. **P0-A**: deterministic real Git bounded RepositoryProfile + anchor tests; TaskAnalyzer output and §4.5 Rule Validation; §4.6 Context Gate with frozen PlanningContext fields and no unauthorized Recon tool. All upstream tests in FakeReasoningBackend.
2. **P0-B**: natural-language TaskRequest → candidate → authentic provenance → conservative, correct effect projection for **"Fix ..." vs "Analyze ..."**; explicit/negated/quoted/refusal/ambiguous cases, always fail closed on uncertainty.
3. **P0-C**: guarantee immutable recursive compiled artifacts and verify fingerprint/source ownership when artifacts cross Trust Boundaries; direct post-construction tamper negatives.
4. **P0-D**: independently re-review Step-3 source and C01–C10, P3 semantic subset; latest-head green Python 3.11/3.13; reconcile main conflict and canonical README/Implementation status.

**Permissible staged merge only after P0-A..D**: PR #5 may be merged as **Step-3 semantic/compiler baseline accepted for Step-4 consumption**, but *only with* frozen P3-01/02/03/04/11 explicitly deferred to Step 4 and no "Step 3 full 22-PoC CLOSED" label. If project policy insists Step 3 CLOSED requires all 22 PASS, defer formal Step 3 CLOSED until Step-4 materializer proves these cases. **No Design Freeze relaxation or silent PoC waiver.**

Do not pull physical DAG materialization or DeerFlow execution into PR #5 to make its stats look complete. Do not merge while GitHub reports unmergeable, any latest-head CI failure, or any P0 Step-3-owned item remains unresolved.

## Step 4 Go/No-Go and coding entry

See `plan/step4-implementation-entry.md`. Step 4 may be designed and isolated no-execution contract tests can be authored, but its `main`-based production PR must not use unmerged/unverified Step-3 output as executable authority.

**First permitted implementation:** pure `CapabilitySpec` / `CapabilityBinding` and `AgentProvider` typed registry, `ToolEffect` and static FakeBackendInventory, with no LLM/DeerFlow. Next comes conservative WorkspaceAccess, ProviderAssignment/preflight, TeamSpec, deterministic TaskDAG phase/materialization and policy-bound CompiledPlanDescriptor. Only then connect existing Scheduler, FakeBackend and Runtime pinning.

## Design Freeze disposition

No conflict between the authoritative specs has been proven that requires reopening Design Freeze. The confirmed issues are code incompleteness / boundary mismatches and incorrect success assumptions. Do not alter frozen Spec or `tests/poc-matrix.md` to make the implementation pass.

**Independent audit result:** Step-3A–3D source provides a useful partial compiler but does **not** yet meet its frozen implementation and integration exit criteria. Preserve Draft PR #5.
