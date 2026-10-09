# Coding Step 3 — Task / Contract / Planning Compiler Kickoff

**Stage: IN PROGRESS (Step 3A). Step 2 is CLOSED on main and must not be reopened merely to accommodate Planner output.**

## Authority

- `AGENTS.md` §4/§5/§11; `specs/01-task-planning.md` §§4.2–4.15; `plan/master-plan.md` Coding Step 3.
- `tests/poc-matrix.md`: POC-C01–C10 and POC-P3-01–P3-12.
- Step 4 Capability/Provider/DAG compiler is separate. No Planner proposal may be dispatched directly.

## Workstream order

1. **Step 3A source/provenance boundary:** immutable `TaskRequestEnvelope`, `RepositoryProfile`, `TaskSpec`, provider-neutral `ReasoningBackend`, `TaskContractDraft` and compiler-issued evidence stamps. Tests C01/C04 + tamper and reproducibility negatives.
2. **Step 3B full ConstraintCompiler:** recognized typed registry and strict provenance, enforced policy versus user versus guidance, set intersection for allow scopes, union for denies/required checks, min for ceilings, exact-value conflict, `CompiledTaskContract` hash, `TaskExecutionAuthority`. Tests C02/C03/C05/C06/C07.
3. **Step 3C semantic planning:** `WorkPlanProposal` is untrusted, `PlanValidator/Normalizer` checks phase direction and coverage, injects reserved verify/review gates monotonically, yields frozen `ValidatedWorkPlan` and deterministic fingerprints. Tests P3-01..12 and C08.
4. **Step 3D AcceptanceCompiler:** compiler-owned immutable `VerificationCommand`, policy fingerprint and sandbox evidence requirements; P0-C09/C10 contract terminal compatibility. Scheduler receives only validated upstream authority.

## Explicit exclusions

- Do not promote `ConstraintCandidate.origin_hint` or `modality_hint` to evidence or enforcement. User quotes must match the immutable raw request. Repository natural language never self-promotes above SOFT.
- The Step 3A early compiler only handles verified user **semantic fallback** and repository guidance SOFT. It is NOT yet a full contract compiler and must not issue an executable TaskExecutionAuthority or a `ValidatedWorkPlan`.
- No DeerFlow, no model-derived scheduling authority, no dynamic DAG mutation, no unsafe shortcut from `TaskSpec.capability_hints` into execution tools.

## Step 3 exit gate

Full POC-C01..C10 + POC-P3-01..P3-12, immutable schemas, normalized plan fingerprints, negative authority tests and 3.11/3.13 CI. **Do not call Step 3 CLOSED on the basis of Step 3A tests alone.**
