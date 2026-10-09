# Step 3 — Independent Design Freeze P0 Closure Review

**Disposition (2026-10-09): GO for scoped Step-3 semantic/compiler baseline merge, subject to this PR's latest-head two-version CI. NOT 22/22 full-stage closure.**

This is a *second audit*, comparing the implementation at `4e76a9c9acc1010026336733777468e84620cc4e` with the four failures in `audits/step3-global-freeze-review.md`. The initial NO-GO was appropriate; these are the specific closures, not a retroactive claim that the initial review passed.

| Original blocker | Implementation / evidence | Closure |
|---|---|---|
| DF3-01 real bounded Git profiling | `planning/profiler.py::collect_repository_profile` reads exact committed Git HEAD tree (not mutable worktree/index), manifests/CI/guidance, bounded anchor matches. `test_p0a_git_head_profile_deterministic_and_anchor_resolved`, `test_p0a_budget_and_noncommitted_paths_are_ignored` | **RESOLVED** within P1 bounded-scan scope; no embeddings / exhaustive project indexing claimed |
| DF3-02 Analyzer / Context / Recon | `planning/analyzer_runtime.py` consumes structured ReasoningBackend, validates bug_fix/test/high-risk/targets; `planning/context.py` gates uncertain plans and uses read-only Git HEAD deterministic reconnaissance; `PlanningContext` now has frozen `recon_report/context_complete/unresolved_questions/fingerprint`. `test_p0b_analyzer_rules_and_candidate_nonpromotion`, `test_p0b_planning_context_gate_no_llm_or_write_tools` | **RESOLVED** for deterministic P1, unresolved context fails closed. No DeerFlow Recon tools |
| DF3-03 plain-language SWE mutation effects | `ConstraintCompiler._direct_user_mutation` issues HARD mutation only for a very narrow, source-verified direct imperative in the *original* TaskRequest. Refusal/negation, quotes, examples and analysis stay read-only. `test_p0c_direct_user_mutation_granted`, `test_p0c_analysis_negation_examples_do_not_grant_write`, `test_design_freeze_natural_language_effect_flows_into_validated_workplan` | **RESOLVED for the frozen P1 example**, not open-domain natural-language semantic authority |
| DF3-07 mutable nested authority values | `planning/immutable.py::deep_freeze` recursively converts dicts to mutation-denying mappings and lists to tuples at compilation boundaries: `CompiledConstraint.value`, `CompiledTaskContract.compiler_repairs/warnings`, `PlanRepair.details`, `PlanWarning.details`, RepositoryProfile languages and structured backend results. `test_p0d_deep_immutable_authority_and_repair_payload`, `test_design_freeze_compiled_repair_records_and_warning_are_deeply_immutable` | **RESOLVED for public mutation APIs**; this is not hostile same-process memory or cryptographic trust |

## Additional negative evidence carried forward

- Fake non-test HARD/LOCKED `SATISFIED + EvidenceRef` remains `UNVERIFIED` unless an authenticated evaluator exists.
- Canonical verification receipts must match the terminal WorkspaceRevision; old receipt or wrong execution-contract binding fails closed.
- Compiler ruleset/version and every loaded repository guidance digest remain bound into CompiledTaskContract fingerprint.

## CI and independent assessment

At implementation SHA `4e76a9c9acc1010026336733777468e84620cc4e`, GitHub Actions run 37893896230: **297 tests passed on Python 3.11 and 297 tests passed on Python 3.13**. All existing Step-2 Runtime tests are in the same run. Audit/document-only commits still require latest-head checks before merging.

An independent source-boundary review confirms no Step-3 path accepts raw `WorkPlanProposal` as `TaskDAG`, no Planner or TaskSpec hint can self-authorize tools, no DeerFlow imports are introduced, and authoritative CanonicalCommandPolicy/ContractVerdict remain owned by their original modules. The exact new natural-language grammar intentionally refuses ambiguous instructions and requires follow-up rather than guessing mutation rights.

## Scope and residual gates

Frozen 22-case PoC matrix remains **17 PASS / 5 PARTIAL / 0 GAP**. In particular P3-01/P3-02/P3-03/P3-04/P3-11 still require Step-4 materialized phase edges, physical WRITE serialization, and Tester bash/Git post-node checking. These have not been reclassified.

**Merge recommendation:** accept PR #5 as a **scoped Stage-3 semantic compiler baseline**, not full 22/22 CLOSED. Official full-stage closure awaits the deferred Step-4 physical PoC results; Step 5 DeerFlow remains explicitly excluded. Step 4 may start from a PR #5-merged main only.

No frozen Design Freeze spec or P3/C PoC criterion was changed to reach this recommendation.
