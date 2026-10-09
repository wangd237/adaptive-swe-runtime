# Coding Step 3B — ConstraintCompiler Conformance Review

**Stage:** Step 3B implementation under [draft PR #5](https://github.com/wangd237/adaptive-swe-runtime/pull/5). Step 3 itself remains **IN PROGRESS**.

## Frozen source authority

- `specs/01-task-planning.md` §4.8.2–§4.8.12, especially §4.8.7 Repository SOFT no-promotion, §4.8.8 typed registry, §4.8.9 family merge algebra, §4.8.10 conflict rules, §4.8.11 monotonic repairs.
- `tests/poc-matrix.md` POC-C01–C10 and POC-P3-01–P3-12.
- `AGENTS.md` source-of-truth, schema-single-owner, planner-is-not-execution-authority.

## Implementation and traceability

| PoC / Boundary | Source | Executable evidence | Assessment |
|---|---|---|---|
| C02 | `planning/compiler.py` | `test_c02_runtime_locked_deny_clashes_with_user_mutation_hard`, `test_c02_no_soft_demotion_of_explicit_hard_requirement`, external-side-effect and wildcard-deny negatives | Runtime LOCKED deny + User HARD request => `CONTRACT_POLICY_CONFLICT`, not silent demotion |
| C03 | `planning/compiler.py` | `test_c03_incompatible_user_exact_hard_constraints_are_unsatisfiable` | Conflicting exact target paths => `CONTRACT_UNSATISFIABLE` |
| C05 | `planning/registry.py`, `planning/compiler.py` | `test_c05_runtime_allow_and_user_allow_intersect_subtrees_not_literal_strings`, `test_c05_unrelated_allow_scopes_do_not_widen_permissions`, `test_c05_global_wildcard_is_safe_and_exact_scope_wins` | Conservatively computed anchored subtree / exact-path intersections; unsupported glob patterns fail closed |
| C06 | `planning/compiler.py` | `test_c06_forbidden_actions_and_paths_use_union_regardless_source` | Runtime + explicit User + Repository Guidance deny union |
| C07 — **contract half only** | `planning/compiler.py` | `test_c07_analysis_task_capability_hint_cannot_grant_mutation`, `test_c07_repo_guidance_mutation_directive_cannot_grant_authority` | TaskExecutionAuthority remains read-only for report-only; actual code_modification WorkItem must be rejected by Step 3C PlanValidator before C07 can be full PASS |
| Additional | `planning/contracts.py`, `planning/compiler.py` | `test_compilation_is_order_independent_and_has_stable_fingerprint`, tamper, source quote, derived-risk, soft preference, budget & monotonic merge tests | Digest-sealed immutable model validation, user > repo > runtime SOFT preference, source authenticity, risk-review policy rule |

## Invariants and narrow supported subset

- Runtime policy is an **operator-supplied trusted input**; `ConstraintCandidate` has no provenance/enforcement fields that can self-authorize.
- User source quotes must match the immutable `TaskRequestEnvelope`. Structured constraints require an **unquoted complete literal line** of a recognized `key: value` form, outside Markdown code fences. Otherwise preserve as semantic HARD; quoted examples cannot grant mutation.
- Repository file content is **data, not instructions**. It can contribute SOFT restrictions/preferences but never a positive Repository Mutation grant. RepositoryProfile Git-base authenticity is an upstream loading/Step 3C integration obligation; this pure compiler does not inspect the physical repository.
- Runtime-LOCKED scopes/denies cannot be expanded by lower authority. Scopes are limited to exact repo-relative POSIX paths and anchored `subtree/**` patterns; unsafe, traversal, arbitrary glob or shell expressions are rejected.
- Required obligations merge monotonically, budget ceilings take MIN, positive exact choices conflict if incompatible, and SOFT precedence is User > Repository > Runtime default.
- `CompiledTaskContract` has a canonical digest, `CompiledConstraint` a deterministic identity and `TaskExecutionAuthority` separate fingerprint with no external side effect permissions. Fingerprints detect accidental/tampered artifact mutation on validation; they are **not cryptographic operator signatures**.
- `TaskExecutionAuthority.repository_mutation_allowed` needs a trusted explicit repository-mutation deliverable and absence of effective locked denies. The Planner's `capability_hints` never grants this right.
- Compiler-owned RISK-REVIEW-001 promotion from high TaskSpec risk is enabled only by a trusted operator policy flag.

## Remaining gates

1. **Step 3C:** WorkPlanProposal, PlanValidator, authoritative PlanCoverageMap, mandatory Verification/Review gate injection; finish C07 (report-only plus illegal code_modification WorkItem) and C08 plus P3-01–12.
2. **Step 3D:** AcceptanceCompiler / VerificationCommand and C09/C10 contract-to-final-verdict linkage.
3. **Stage 3 exit:** complete all frozen C/P3 cases, independent source review and two-version CI. Keep PR #5 DRAFT, never label Step 3 CLOSED from this report.

## CI

Implementation head must pass Python 3.11 and Python 3.13 GitHub Actions before this report can be used as a checkpoint. No modified Step 2/DeerFlow runtime adapter is in this branch.
