# Coding Step 3 — Task / Contract / Planning Compiler Kickoff

**Stage: IN PROGRESS (Step 3A–3D code checkpoints implemented; 5 frozen P3 physical DAG PoCs remain PARTIAL in Step 4). Step 2 remains CLOSED on main.**

## Authority

- `AGENTS.md` §4/§5/§11; `specs/01-task-planning.md` §§4.2–4.15; `plan/master-plan.md` Coding Step 3.
- `tests/poc-matrix.md`: POC-C01–C10 and POC-P3-01–P3-12.
- Step 4 Capability/Provider/DAG compiler is separate. No Planner proposal may be dispatched directly.

## Workstream order

1. **Step 3A source/provenance boundary:** immutable `TaskRequestEnvelope`, `RepositoryProfile`, `TaskSpec`, provider-neutral `ReasoningBackend`, `TaskContractDraft` and compiler-issued evidence stamps. Tests C01/C04 + tamper and reproducibility negatives.
2. **Step 3B ConstraintCompiler — implementation submitted:** typed registry, operator Policy/HARD user/soft guidance, allowed scope intersection, forbidden/required union, budgets min, exact conflicts, signed-by-digest contract/authority; deterministic source-line parsing and runtime-derived high-risk review. C02/C03/C05/C06 have direct tests. C07's TaskExecutionAuthority half is tested; its PLAN_INVALID work-item half remains Step 3C.
3. **Step 3C semantic planning — implemented:** Untrusted `WorkPlanProposal` is converted via deterministic `SemanticPlanValidator` to `ValidatedWorkPlan`, with phase/authority/coverage validation and reserved verify/review gate injection. C07/C08 and semantic P3 cases tested. **P3-01/02/03/04/11 remain PARTIAL for physical/phase DAG materialization in Step 4**; see `audits/step3c-conformance.md`.
4. **Step 3D AcceptanceCompiler — implemented:** immutable `VerificationCommand`, re-used CanonicalCommandPolicy, exact acceptance criterion/allowlist identity, required sandbox evidence, ExecutionContractBinding and `finalize_bound_task` seam. C09/C10 direct FakeBackend + real Git CanonicalVerifier scenarios PASS; see `audits/step3d-conformance.md`.

## Explicit exclusions

- Do not promote `ConstraintCandidate.origin_hint` or `modality_hint` to evidence or enforcement. User quotes must match the immutable raw request. Repository natural language never self-promotes above SOFT.
- The Step 3B compiler can now issue a coarse-grained TaskExecutionAuthority only after deterministic source/merge checks. It must **not** issue a ValidatedWorkPlan, execute tools, or convert an analyzer's capability_hints into authority. Natural-language intent extraction is intentionally conservative; only unquoted full-line recognized directives are canonicalized to typed executable constraints.
- No DeerFlow, no model-derived scheduling authority, no dynamic DAG mutation, no unsafe shortcut from `TaskSpec.capability_hints` into execution tools.

## Step 3 exit gate

Full POC-C01..C10 + POC-P3-01..P3-12, immutable schemas, normalized plan fingerprints, negative authority tests and 3.11/3.13 CI. **Do not call Step 3 CLOSED on the basis of Step 3A tests alone.**
