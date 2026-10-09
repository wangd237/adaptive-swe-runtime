# Coding Step 3C — Semantic Planning / PlanValidator / Normalizer Review

**Checkpoint:** Step 3C semantic validation is implemented and has executable tests. **Stage 3 stays IN PROGRESS**; Step 4 physical DAG semantics remain unverified; Step 3D Acceptance has its own completed checkpoint.

## Frozen design authority

- `specs/01-task-planning.md` §§4.8.13, 4.10–4.14.
- `specs/02-capability-provider-dag.md` capability authority versus physical WorkspaceAccess.
- `tests/poc-matrix.md` frozen P3-01–P3-12 and C01–C10 expectations.
- Source: `src/aswe/planning/{planner,validator}.py`; tests: `tests/unit/test_semantic_plan_step3c.py`.
- Machine-readable truth: `audits/step3-poc-coverage.json`.

## Verified implementation

1. Planner may return a provider-neutral, immutable `WorkPlanProposal` from structured ReasoningBackend. It cannot return trusted `ValidatedWorkPlan` or a `TaskDAG` and never receives Provider roster / Backend-specific tool authority.
2. `SemanticPlanValidator` rejects repeated/reserved IDs, dangling/self/cyclic dependencies, phase inversions, unknown semantic capability IDs, mixed Review/Implementation authority, mutation without contract grant/coverage and unknown/negative-only coverage claims.
3. Runtime injects only *mandatory, contract-derived* `__aswe_verify` and `__aswe_review` gates with fixed capabilities. Existing valid independent gates are reused; invalid/decorative gates cannot satisfy hard obligations. Reviewer gate must also follow newly inserted verifier. Reserve gate slots against the hard WorkItem limit before analyzing.
4. Canonical dependency de-duplication is logged as a `PlanRepair`; warnings do not silently change semantics. Immutable `ValidatedWorkPlan` binds complete normalized items, repairs, warnings and TaskContract fingerprint.
5. `PlanCoverageEntry` records `RUNTIME_ENFORCED` gate obligations versus `PLANNER_DECLARED` positive business/semantic coverage. A plan claim is structural coverage only, **not proof of satisfaction**.
6. Semantic `regression_testing` means read-only *business authority*, even if Step 4 later grants the physical WRITE lock for bash. `code_modification` requires a positive mutation deliverable/authority and matched plan coverage claim.

## Frozen 22-PoC inventory (scope-specific, no false end-to-end claims)

| PoC | Status | Evidence / scope |
|---|---|---|
| P3-01 | PARTIAL | `test_p3_01_writer_precedes_bash_tester_by_semantic_phase` — Explicit Writer→Verifier semantic edge accepted; Step 4 still owns phase-derived materialization and physical Workspace WRITE scheduling |
| P3-02 | PARTIAL | `test_p3_02_tester_semantically_precedes_readonly_reviewer` — Explicit Verifier→Reviewer edge accepted; physical READ/WRITE relation is Step 4 |
| P3-03 | PARTIAL | `test_p3_03_discovery_before_implementation` — Explicit discovery→implementation edge accepted; Step 4 automatic phase edges pending |
| P3-04 | PARTIAL | `test_p3_04_unordered_same_phase_mutating_items_keep_ordinals_without_fake_provider_edges` — Planner ordinals stable and semantic edges untouched; Step 4 must compile deterministic WRITE serialization |
| P3-05 | PASS | `test_p3_05_explicit_review_to_implementation_is_hard_phase_contradiction` — REVIEW→IMPLEMENTATION rejected as PHASE_ORDER_CONTRADICTION |
| P3-06 | PASS | `test_p3_06_independent_discovery_remains_parallel_without_forced_edges` — Independent DISCOVERY READ work items retain no artificial semantic dependencies |
| P3-07 | PASS | `test_p3_07_c08_missing_required_gates_are_runtime_owned_monotonic_injected` — Mandatory missing verification/review injected as reserved runtime-owned gate items with correct dependencies |
| P3-08 | PASS | `test_p3_08_planner_may_not_impersonate_reserved_gate` — Planner-origin __aswe_ ID rejected |
| P3-09 | PASS | `test_p3_09_c07_report_only_cannot_request_business_mutation_capability` — Report-only TaskExecutionAuthority refuses code_modification |
| P3-10 | PASS | `test_p3_10_authorized_bug_fix_implementation_is_accepted` — Authorized mutation deliverable + coverage allows implementation capability |
| P3-11 | PARTIAL | `test_p3_11_semantic_verification_not_equivalent_to_business_mutation` — Semantic verification cannot carry code_modification; physical bash WRITE and Git post-node invariant remain Step 4/Runtime integration |
| P3-12 | PASS | `test_p3_12_mutating_workitem_requires_matching_deliverable_coverage` — Mutation work item without contract grant coverage rejected as PLAN_INVALID |
| C01 | PASS | `test_c01_repository_guidance_cannot_self_promote_to_hard` — Repository guidance source proof remains SOFT, never self-promotes |
| C02 | PASS | `test_c02_runtime_locked_deny_clashes_with_user_mutation_hard` — LOCKED deny and HARD mutation conflict produce CONTRACT_POLICY_CONFLICT |
| C03 | PASS | `test_c03_incompatible_user_exact_hard_constraints_are_unsatisfiable` — Mutually exclusive HARD choices produce CONTRACT_UNSATISFIABLE |
| C04 | PASS | `test_c04_unknown_exact_user_requirement_retained_as_semantic_hard` — Unknown explicit user requirement remains semantic HARD |
| C05 | PASS | `test_c05_runtime_allow_and_user_allow_intersect_subtrees_not_literal_strings` — Effective allowed scopes intersect without widening authority |
| C06 | PASS | `test_c06_forbidden_actions_and_paths_use_union_regardless_source` — Forbidden scopes and actions union across three sources |
| C07 | PASS | `test_p3_09_c07_report_only_cannot_request_business_mutation_capability` — Step 3B projected report-only authority and Step 3C rejects illegal code_modification work item |
| C08 | PASS | `test_p3_07_c08_missing_required_gates_are_runtime_owned_monotonic_injected` — Runtime gate injection is monotonic and logged with PlanRepair |
| C09 | GAP | — — Step 3D must prove HARD/LOCKED UNVERIFIED final leaf blocks success |
| C10 | GAP | — — Step 3D must bind final ContractVerdict to exact execution contract fingerprint |

## Explicit gaps and implementation order

- **P3-01/02/03:** direct semantic phase dependency cases now pass, but Step 4 still needs automatic phase-ordered dependency compilation when Planner omits explicit edges. These remain PARTIAL end-to-end.
- **P3-04:** two unordered same-phase business WRITEs preserve planner ordinals at Step 3C; deterministic WRITE serialization must be implemented and tested in Step 4 DAG Materializer.
- **P3-11:** Step 3C forbids business mutation capability on a Tester; real bash tool physical WRITE scheduling and Git source-mutation rejection need Step 4/Runtime checks.
- **C09/C10:** now directly tested in Step 3D (see `audits/step3d-conformance.md`); the five P3 physical/DAG obligations remain PARTIAL until Step 4.
- Semantic success does **not** imply current Provider availability, permissible shell, Sandbox admission, executable command identity or current repository Git binding; these remain later compilation/adapter gates.
- C07/C08 are complete *at semantic PlanValidator scope* with executable fake contracts.

## Next checkpoint

Proceed with independent Step 3 compiler audit, and preserve separate Step 4 physical DAG integration PoCs. Do not mark all P3 items PASS simply because a semantic plan can be constructed.
