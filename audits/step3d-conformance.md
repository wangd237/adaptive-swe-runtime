# Coding Step 3D — Acceptance Compiler Conformance

**Checkpoint: Step 3D implementation and direct C09/C10 scenarios PASS.** Stage 3 stays **IN PROGRESS** until the remaining Step-4-owned P3 physical/DAG PoCs and an independent final compiler review are resolved.

## Frozen authority and reused owners

- `specs/01-task-planning.md` §4.15 VerificationCommand, command-policy identity and sandbox evidence.
- `specs/04-evidence-evaluation.md` §14.4 ContractLeafVerdict and TaskResult acceptance requirements.
- **Single source**: `src/aswe/runtime/canonical_verifier.py` owns `CanonicalCommandPolicy` and attested receipts; `src/aswe/evaluation/contracts.py` owns `ContractVerdict`. Step 3D reuses them.
- Implemented in `src/aswe/planning/acceptance.py` and tested in `tests/unit/test_acceptance_compiler_step3d.py`.

## Compiler products

1. Immutable `VerificationCommand` with stable command ID, kind, exact argv, source/provenance fingerprint, and canonical command text. Runtime operator rules or explicitly enabled compiler-owned safe pytest profile mapping can supply an executable command. Planner free-text cannot authorize command execution.
2. `CompiledAcceptancePlan` binds each command to a `tests_passed:<exact-command>` criterion, exact Bash allowlist entry, and the existing `CanonicalCommandPolicy` fingerprint. Mismatches fail with `ACCEPTANCE_COMMAND_POLICY_MISMATCH` instead of silently accepting one string.
3. Any load-bearing shell acceptance adds `required_sandbox_features=(deerflow_tests_passed_evidence,)` **before** executor admission; actual DeerFlow `shell_persistent=False` evidence support still requires Step 5 adapter validation.
4. Unknown/missing verification commands are listed in `unresolved_check_keys`; they cannot silently become SATISFIED.
5. `ExecutionContractBinding` fingerprints TaskContract, ValidatedWorkPlan, AcceptancePlan, exact execution policy and repository base. Final binding assertion checks compiled policy identity and exact terminal verdict coverage; `finalize_bound_task` validates before invoking the preexisting Step-2 TaskResult finalizer.

## C09 direct evidence

- `test_c09_hard_locked_unverified_and_missing_proof_must_block_success`: missing HARD/LOCKED evaluation evidence is UNVERIFIED and blocking; a claimed SATISFIED with no evidence is not proof.
- `test_c09_not_applicable_without_verified_proof_remains_unverified`: NOT_APPLICABLE is not a bypass without applicability proof.
- `test_c09_unresolved_required_check_never_passes_even_with_other_attested_receipt`: a successful Unit receipt cannot satisfy an unresolved Regression requirement.
- `test_c09_invalid_or_cross_attempt_receipt_never_authenticates`: attempt identity mismatch rejected by the existing CanonicalVerifier.
- `test_c09_nonzero_real_canonical_check_is_contract_violation`: an actual checker nonzero exit is VIOLATED, not success.
- Authenticated results are mapped using `verified_canonical_check_finding` and `CanonicalCheckBinding`, which calls HMAC-backed `CanonicalVerifier.validate`. `evaluate_compiled_contract` does **not** permit caller-asserted verification success without executing this resolver.

## C10 direct evidence

- `test_d07_execution_binding_covers_contract_plan_and_acceptance_policy`: the bound execution snapshot fingerprints immutable contract/plan/policy.
- `test_c10_substituted_execution_or_verdict_contract_is_rejected`: replacing compiled contract or runtime-observed binding stamp yields `TASK_CONTRACT_FINGERPRINT_MISMATCH`.
- `test_c09_c10_real_canonical_attested_proof_and_finalization_binding`: real Git temporary workspace + canonical command receipt → evaluator → bound terminal TaskResult; correct contract yields SUCCEEDED, wrong expected fingerprint yields FAILED.

## Boundaries not claimed

- Runtime operator configuration is the trust root of verification commands; `user_hard_requirement` exists in the schema but no user-supplied arbitrary shell command is activated by this compiler.
- Fixed command argv may not contain shell metacharacters/interpreters; the check is intentionally conservative and **not** a general shell safety proof. Only `VerificationCommandKind.TEST` compiles to `tests_passed`; BUILD/IMPORT_CHECK/STATIC_CHECK fail closed as `ACCEPTANCE_KIND_UNSUPPORTED` until their independent checker semantics are implemented (`test_d08_non_test_command_cannot_impersonate_tests_passed_acceptance`).
- Local `CanonicalVerifier` HMAC and Git provenance are Step-2 runtime mechanisms, not distributed trust, DeerFlow's native tests_passed checker, or its persistent-shell evidence.
- `finalize_bound_task` requires an **observed Runtime-owned execution binding fingerprint** provided by the Step-4 admission snapshot. Step 3D provides the checker but does **not** yet install the snapshot in a real Provider/DeerFlow scheduler run.
- Semantic/Review SATISFIED evidence resolution remains scoped to the trusted Runtime evaluator and receipt resolver; model prose cannot be passed as successful deterministic test evidence.
- Five P3 physical DAG cases still PARTIAL (P3-01/02/03/04/11). Stage 3 is not CLOSED; no merge of draft PR #5.

## CI

Acceptance kind hardening HEAD `2a4b952c2e17e66ced003336b5cb07aef795e2b7`: Python 3.11 **273 passed**, Python 3.13 **273 passed**, GitHub Actions run 37880285730. Audit-only sync head requires the same CI gate before any Step 3 closure.
