# Coding Step 4 — Independent Design Freeze / Runtime Admission Audit

**Audit date:** 2026-10-09. **Decision: scoped GO for Step-4 Core/FakeBackend contract/compiler baseline, NO-GO for claiming full production DeerFlow integration.** This is an independent source-vs-frozen-spec review; tests and fingerprints alone are not authorization.

## Source of truth and reviewed scope

- Immutable authoritative `AGENTS.md`; `specs/01-task-planning.md` (verification / acceptance contracts), `specs/02-capability-provider-dag.md` (§5–8/10), `specs/03-execution-runtime.md`, `specs/04-evidence-evaluation.md`.
- Frozen `tests/poc-matrix.md` P0-5 including POC-27..53, R52, R73, F03; 22 previously frozen Stage-3 C/P3 tests.
- Reviewed `src/aswe/capabilities/{registry,effects}.py`, `src/aswe/providers/{contracts,inventory,resolver,policy,preflight,invariants}.py`, `src/aswe/planning/{validator,dag,descriptor,acceptance}.py`, `src/aswe/core/contracts/{task,backend}.py`, `src/aswe/runtime/scheduler.py`, the FakeBackend test harness and dedicated Step-4 tests.
- **No frozen spec or acceptance matrix criteria changed.** No actual DeerFlow/LLM/API execution, no deployment auth proofs.

## Independent findings and resolution

| Finding | Severity / status | Independent check / fix |
|---|---|---|
| S4-01 — Tool exposed name confused with implementation identity | P0 CLOSED for Fake backend | `trusted_effect` checks canonical `config:<contract-id>`, eager delivery, exposed name and effect; same-name extension/plugin cannot earn READ. Real `ToolConfig.use` adapter mapping is Step 5 |
| S4-02 — Provider ID could remain stable while CapabilityBindings changed | P0 CLOSED | `NodeResources.provider_contract_fingerprint` stamped by resolver, recomputed at policy compilation and Descriptor checks |
| S4-03 — Re-signed NodeResources could erase Provider hard-required bash | P0 CLOSED | `compile_policies` independently rebuilds stable ordered required tool closure from selected Provider bindings and compares required/optional identities; adversarial self-consistent false READ digest rejected |
| S4-04 — Descriptor allowed caller to omit verification RepairBinding | P0 CLOSED | `compile_plan_descriptor` derives check IDs from the same compiled Acceptance commands; independent check rejects caller-substituted IDs |
| S4-05 — Reviewer output & per-node constraints must not get lost | P0 CLOSED on compilation | `NodeExecutionPolicy` binds exact tests_passed command strings and CanonicalPolicy fingerprints, required infra `submit_review_verdict`, allowed/forbidden paths, prohibited actions, file budget and sandbox features. Static operator denies cause admission rejection; downstream DeerFlow enforcement remains Step 5 |
| S4-06 — Live inventory fingerprint comparison could overreject unrelated drift | P0 CLOSED | Revalidate required tool implementation/exposed/schema/delivery and model, sandbox evidence, operator authorization; changed unrelated inventory returns `BACKEND_DRIFT_OBSERVED` and still prepares |
| S4-07 — Runtime could accidentally widen/rename selected optional tools | P0 CLOSED for Fake backend | Explicit operator-selected optional, stable required union, optional drop under live narrowing, no default bash; lock class remains compile-time upper bound |
| S4-08 — Prepared execution could re-resolve config silently | P0 CLOSED in Fake-only seam | `LivePreflightBackend` checks signed Descriptor→Policy, constructs attempt-free precommit preparation, holds pinned underlying preparation; runtime execute uses same entry once only. Actual DeerFlow AppConfig/Tool snapshot still Step 5 |
| S4-09 — ProviderAssignment lacked frozen resource closure; nested inventory mutable | P0 CLOSED | `NodeResourceRequirements` + signed ProviderAssignment, single-source Capability Registry, deep-frozen Provider/Inventory mappings; Descriptor checks against DAG, team roster and policy |
| S4-10 — Provider auth changes after assembly, middleware visibility and tool-call guards | **Step 5 explicit ownership** | Cannot be verified without DeerFlow extension/AuthorizationProvider; do not mark POC-29/30/33–38/42–44/49 PASS |
| S4-11 — Semantic read-only Tester uses bash (physical WRITE) | P0 CLOSED in Stage-4 local real Git scenario | `PostNodeGitInvariantBackend` derives semantic intent from immutable TaskDAG, compares real Git state under existing Scheduler workspace RW lock; dirty Tester fails with Task root `DIRTY_WRITE_FAILURE`, Attempt `POST_NODE_INVARIANT_GIT_MUTATION`. Production adapter MUST install equivalent mandatory guard |
| S4-12 — Signature trust root | **Explicit limitation** | A self-consistent content digest is an integrity check, **not** authentication of the issuing Runtime. Step-5 host-owned pinned descriptor/binding store must prevent arbitrary caller-signed CompiledPlanDescriptor becoming execution authority |

## Four-layer feasibility boundary

```text
DECLARED: AgentProvider/CapabilityBinding
  -> PREFLIGHT_FEASIBLE: resolved source-checked NodeResources + signed NodeExecutionPolicy
  -> PREPARED: revalidated live inventory and monotonic operator narrowing,
               signed descriptor matched, no execution identity yet
  -> COMMITTED/EXECUTED: existing SchedulerCore allocates attempt only under
                         workspace lock; FakeBackend executes pinned preparation
```

**Negative evidence:** missing/deferred tool, same-name override, provider binding substitution, disguised required-tool loss, model unavailable/unauthorized, denied required business/infra tool, missing sandbox feature, stale required tool, stale live schema/model/provider, fake READ downgrade, forged scope-limit removal, wrong descriptor policy, and old acceptance binding all fail closed. No automatic Provider switch is allowed.

**Positive evidence:** unrelated drift records its reason without failure; preferred incompatible skill withheld, optional bash unselected maintains READ, selected bash forces WRITE, tightened ceilings remain monotonic, prepared fake snapshot not refreshed on hot-reload, stable deterministic TaskDAG/TeamSpec, single Provider roster does not merge WorkItems.

## Frozen coverage, carefully scoped

- Stage-3 deferred physical P3-01/02/03/04/11: **PASS on PR #6's real Git + Scheduler/FakeBackend branch**; the complete Stage-3 22-case inventory currently **22 PASS / 0 PARTIAL / 0 GAP on this branch**, not automatically on merged main.
- P0-5 + R/F matrix in `audits/step4-poc-coverage.json`: **13 PASS (Core/static), 5 PARTIAL, 12 STEP5-OWNED**. Full production P0-5 is emphatically **not all green**.
- Concretely Step-4-scoped checks include POC-27/28/39/40/41/45/46/47/50/53, R52, R73 and F03; actual DeerFlow assembly/middleware, authorization refresh, persistent Bash evidence and cleanup need Step 5.

## Release boundary / recommendation

1. **Step 4 compiler/preflight substage can be accepted for merge** if latest-head Python 3.11 + 3.13 CI succeed, no merge conflict remains and no new source mismatch is found.
2. **Stage 4 Core semantic/physical contract implementation is not proof of running production DeerFlow.** Step 5 must add BackendInventory Adapter, ModelInvoker, NodeExecutionBindingStore, exact actual tool assembly attestation, A-SWE tool-surface middleware/tool-call denial, auth integration, live skill narrowing, missing-policy fail close, proper terminal/cleanup evidence, and real Git guard enforcement.
3. Do not label the Step-5-owned POC cases PASS based on the FakeBackend wrapper. If the release gate requires *all POC-27..53* fully PASS, remain NO-GO for that stronger gate until Step 5.
4. Keep authoritative owner types unique: `WorkspaceAccess` only in `core.contracts.workspace`; `CanonicalCommandPolicy` only in `runtime.canonical_verifier`; `ExecutionContractBinding` only in `planning.acceptance`; `ContractVerdict` only in `evaluation.contracts`.
5. Latest test evidence is recorded in PR #6 CI; audit-only commits require the same latest-head CI before changing merge state.

**Conclusion:** requested Stage-4 *Core* Live Preflight, Inventory Drift, NodeExecutionPolicy, CompiledPlanDescriptor and independent audit deliverables exist; Stage-5 live-adapter obligations remain explicitly fenced, with no false PASS or spec relaxation.
