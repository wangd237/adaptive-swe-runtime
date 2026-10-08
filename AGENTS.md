# AGENTS.md — A-SWE Runtime Coding Constitution

> This file defines mandatory coding rules for AI-assisted implementation of **Adaptive Agent Runtime for Software Engineering (A-SWE Runtime)**.
>
> Its purpose is to prevent implementation drift after the P0 Design Freeze.
>
> **Treat this file as an implementation contract, not optional advice.**

---

## 1. Mission

A-SWE Runtime is **not** a DeerFlow fork with several extra agents.

```text
A-SWE Runtime
  ├── Task / Contract / Planning
  ├── Capability / Provider / DAG Compilation
  ├── Scheduler / Workspace / Evidence / Repair
  ├── Evaluation / Finalization
  └── ExecutionBackend abstraction
            │
            ├── FakeExecutionBackend
            └── DeerFlowExecutionBackend
                        │
                        ▼
                     DeerFlow
```

Core identity:

> **A-SWE is the control plane. DeerFlow is an execution plane.**

Implementation choices must preserve this boundary.

---

## 2. Source of Truth

Use this authority order:

1. **Authoritative Specs**
   - `specs/01-task-planning.md`
   - `specs/02-capability-provider-dag.md`
   - `specs/03-execution-runtime.md`
   - `specs/04-evidence-evaluation.md`
2. **Master implementation order**
   - `plan/master-plan.md`
3. **Architecture audit / rationale**
   - `audits/deerflow-source-audit.md`
4. **PoC / conformance expectations**
   - `tests/poc-matrix.md`
5. **README ownership map**
   - `README.md`

`archive/` is historical only.

**Never use archived definitions as implementation authority.**

If two active authoritative specs appear inconsistent:

- do not silently choose one;
- do not invent a compromise in code;
- stop implementation of the conflicting behavior;
- report the exact conflict;
- continue only with unrelated work;
- require an explicit Design Freeze reopen before changing the contract.

---

## 3. Design Freeze Rule

P0 is currently:

```text
DESIGN FROZEN
PoC Execution Pending
```

Coding convenience is not sufficient reason to change a frozen contract.

Frozen core contracts include:

- TaskContract / CompiledTaskContract
- ValidatedWorkPlan
- WorkspaceAccess / WorkspaceRevision
- EvidenceRef / TaskEvidenceRef / ReceiptRef
- NodeHandoff
- TaskNode / TaskDAG
- NodeExecutionPreparation / NodeExecutionInvocation
- NodeRuntimeState / NodeAttemptRecord
- DispatchTicket / acceptance_epoch / TaskDispatchGate
- Retry / Repair / Reverify semantics
- RepositoryStateDigest / Workspace lifecycle
- TaskResult / ContractVerdict
- backend quiescence / cancellation semantics

If implementation proves a frozen contract genuinely impossible or inconsistent:

1. do **not** patch around it;
2. mark the blocker explicitly;
3. identify affected Spec + PoC;
4. reopen Design Freeze explicitly;
5. update Spec, audit conclusion, PoC matrix, and tests together;
6. only then implement the revised contract.

---

## 4. Schema Ownership Rule

A schema class has exactly one authoritative owner.

Use the README Schema Ownership Map.

Rules:

- do not duplicate Pydantic models for convenience;
- do not create “almost equivalent” local copies;
- import the authoritative type;
- fix module boundaries instead of duplicating types to escape import cycles;
- `archive/` definitions are never imported or copied;
- mutable runtime state must not be added to immutable planning artifacts.

Example:

```text
TaskNode
→ immutable compile artifact

NodeRuntimeState
→ mutable logical runtime lifecycle

NodeAttemptRecord
→ attempt lifecycle/history
```

Never add mutable `status` back to `TaskNode`.

---

## 5. Core Architecture Invariants

### 5.1 DeerFlow must not leak into Core

Dependency direction:

```text
A-SWE Core
    ↑
ExecutionBackend Protocol
    ↑
integrations/deerflow
    ↑
DeerFlow
```

Forbidden:

```python
# src/aswe/runtime/scheduler.py
from deerflow... import ...
```

Only the DeerFlow integration layer may depend on DeerFlow implementation details.

Architecture tests must reject DeerFlow imports from:

- `core/`
- `runtime/`
- `workspace/`
- `repository/`
- `evidence/`
- `planning/`
- `evaluation/`

### 5.2 Do not fork DeerFlow by default

Preferred order:

```text
A-SWE
→ pinned DeerFlow dependency
→ DeerFlowExecutionBackend adapter
```

Fork only if a required P1 contract cannot be satisfied through available extension seams.

If a fork is necessary:

- patch the smallest compatibility seam possible;
- keep A-SWE Scheduler / DAG / Evidence / Repair logic outside DeerFlow;
- document the exact limitation requiring the fork;
- retain adapter isolation.

### 5.3 Runtime correctness must be deterministic

These decisions must be deterministic Runtime/Python logic, not LLM judgment:

- Ready calculation
- WorkspaceAccess
- dependency authority
- dispatch commit
- retry eligibility
- repair eligibility
- repair target attribution
- cancellation state
- failure propagation
- repository mutation authority
- evidence integrity
- Task success/failure
- ContractVerdict blocking logic

Forbidden:

```python
llm.invoke("Should this node retry?")
```

LLMs may produce proposals and semantic interpretations only where the Specs explicitly allow them.

### 5.4 Planner output is never execution authority

```text
LLM WorkPlanProposal
        ↓
deterministic validation / normalization
        ↓
ValidatedWorkPlan
        ↓
Capability / Provider / DAG compiler
```

Never feed raw `WorkPlanProposal` directly into Scheduler execution.

### 5.5 FakeBackend before DeerFlow

Scheduler correctness must first be proven with deterministic fakes.

Fake backend must be able to simulate at least:

- success
- transient failure
- timeout
- cancellation
- pre-start vs started execution
- proven-no-mutation
- observed mutation
- unknown mutation
- verification failure
- repair success/failure
- quiescence success/failure
- controlled race/barrier points

Do not use LLM randomness or DeerFlow behavior to prove the Scheduler state machine.

---

## 6. Dispatch / Handoff Invariants

### 6.1 Pre-commit execution is revocable

Before final dispatch commit:

```text
READY
→ PREPARING
→ WAITING_WORKSPACE
→ LOCKED_PRECOMMIT
```

These phases use a revocable `NodeDispatchTicket` and do **not** create a real attempt.

A pre-commit revoke:

- creates no NodeAttemptRecord;
- consumes no retry/repair budget;
- creates no execution evidence;
- must not require backend execution cancellation;
- discards preparation safely.

### 6.2 Attempt identity begins at dispatch commit

`prepare_node()` may create only:

```text
preparation_id
```

Do not allocate:

- attempt
- execution_id
- run_id

until final Scheduler dispatch commit.

### 6.3 Writer reopen and consumer commit must linearize

Both operations use the same Scheduler state linearization boundary.

Before commit, downstream consumers are revocable.

After commit, P1 does not retract the consumer attempt and continue Writer repair.

If an affected downstream consumer is already COMMITTED/RUNNING:

```text
REPAIR_SCOPE_INVALIDATED
reason = ACTIVE_DOWNSTREAM_DISPATCH
```

Then use task-wide fail-close/drain semantics.

### 6.4 WorkspaceRevision is not dependency authority

Two independent fences exist:

```text
WorkspaceRevision
→ physical workspace state

acceptance_epoch + accepted_attempt + handoff fingerprint
→ logical dependency authority
```

Never replace one with the other.

### 6.5 NodeHandoff is not EvidenceRef

`NodeHandoff` is a bounded runtime contract.

Heavy/authoritative payloads are referenced through `EvidenceRef`.

Historical Handoffs remain attached to attempts.

Current dependency authority is represented by:

- accepted_attempt
- accepted_handoff
- acceptance_epoch

Writer reopen clears current authority but does not erase historical attempt artifacts.

---

## 7. Evidence / Repository Invariants

### 7.1 Attempt and Task evidence are different

```text
EvidenceRef
→ node / execution / attempt scoped

TaskEvidenceRef
→ task / finalization scoped
```

Never invent synthetic node IDs to store task finalization evidence.

Use:

- `put_attempt(...)`
- `put_task(...)`
- `get(...)`

### 7.2 Evidence is immutable

EvidenceStore artifacts:

- use canonical serialization;
- use full SHA-256 integrity hashes;
- are atomically published;
- are never silently overwritten;
- preserve old Retry/Repair attempts.

Trace events may reference evidence metadata but must not become the canonical evidence store.

### 7.3 Git-visible business state is authoritative

Use the frozen temporary-index `RepositoryStateDigest` approach.

Do not replace deterministic Git state with:

- model self-report;
- file-list guesses;
- last-writer heuristics;
- stack-trace path overlap.

### 7.4 Residual patch is not success

If Task is FAILED or CANCELLED and a Git-visible patch remains:

```text
PatchDisposition = RESIDUAL_UNACCEPTED
```

It may be inspected or used for diagnostics/manual recovery.

It must not:

- satisfy TaskContract;
- unlock downstream work;
- become Reviewer-approved success;
- be described as completed work.

---

## 8. Retry / Repair / Reverify Rules

Retry and Repair are attempts of the **same immutable TaskNode**.

Do not dynamically create:

```text
implement
implement_repair_1
implement_repair_2
```

### Retry

Allowed only under Scheduler-owned retry rules and safe mutation conditions.

Retry does not change:

- objective
- ProviderAssignment
- authority ceiling
- dependencies

### Repair

P1 automatic Repair is intentionally narrow.

Do not infer repair ownership from:

- last Coder
- test failure filename
- stack trace path
- changed-path overlap
- model prose
- Provider identity

Downstream verification attribution is **repair ownership**, not causal blame.

Ambiguous multi-writer repair fails closed.

### Reverify

After successful Writer Repair, use a fresh attempt of the same Verification node.

Never reuse an old Verification verdict as current proof.

---

## 9. Failure / Workspace Rules

Do not collapse:

```text
FROZEN
!=
QUARANTINED
```

### FROZEN

- backend quiescence proven;
- terminal workspace snapshot stable;
- ordinary DAG dispatch closed;
- deterministic Runtime finalization allowed.

### QUARANTINED

- quiescence not proven;
- late mutation may still occur;
- no new Agent execution;
- no workspace-touching final inspection;
- only previously persisted trusted evidence may be reported.

A workspace-compromising terminal failure causes **task-wide fail-close**, not only descendant blocking.

Do not run Reviewer/Explorer/Tester “just to diagnose” after task-wide fail-close.

Only Runtime-owned deterministic finalizers are allowed in FROZEN state.

---

## 10. Task Success Rule

Never equate:

```text
LLM says done
```

with:

```text
Task SUCCEEDED
```

Task success requires frozen TaskResult invariants, including:

- no root failure;
- final ContractVerdict exists;
- required contract leaves are satisfied;
- repository/patch disposition is valid;
- workspace is not quarantined;
- required Verification/Review gates are satisfied.

`UNVERIFIED != PASSED`.

---

## 11. Coding Order — Mandatory

The functional P1 sections are **not** the implementation order.

### Step 0 — Core Contracts + Deterministic Test Harness

Implement shared contracts, IDs/fingerprints, Runtime config, and FakeExecutionBackend.

No LLM.
No DeerFlow SubagentExecutor.

### Step 1 — Evidence + Workspace / Git Substrate

Implement EvidenceStore, WorkspaceSession, RepositoryBinding, RepositoryStateDigest, WorkspaceRevision, locks, and FROZEN/QUARANTINED substrate.

### Step 2 — Scheduler State Machine on FakeBackend

Implement:

- NodeRuntimeState
- NodeAttemptRecord
- Ready calculation
- SchedulerStateMutex
- NodeDispatchTicket
- DependencyAcceptanceStamp
- TaskDispatchGate
- dispatch commit
- cancellation
- Retry/Repair/Reverify
- dirty fail-close
- terminal drain/state assembly

This is the first major correctness milestone.

### Step 3 — Task / Contract / Planning Compiler

Implement RepositoryProfile, TaskSpec, contracts, ConstraintCompiler, PlanningContext, WorkPlanProposal, PlanValidator/Normalizer, ValidatedWorkPlan, Acceptance Compiler.

### Step 4 — Capability / Provider / DAG Compiler

Implement capability/provider contracts, WorkspaceAccess compiler, ProviderAssignment, TeamSpec, TaskDAG, VerificationRepairBinding, CompiledPlanDescriptor.

### Step 5 — DeerFlow Integration Adapter

Only now integrate DeerFlow.

Keep DeerFlow-specific behavior under:

```text
integrations/deerflow/
```

Real shared mutable workspace execution remains Go/No-Go gated by integration PoCs.

### Step 6 — Cross-Node SWE Agent Semantics

Only after Runtime and Adapter contracts are sound:

- Repo Explorer / Coder / Tester / Reviewer
- prompts
- Skills
- Handoff renderer
- RepairAttributionResolver
- structured Review gate

Do not prioritize prompt engineering before Runtime correctness.

### Step 7 — Task Finalization + Evaluation

Implement ContractVerdict, final repository task evidence, residual patch semantics, TaskResult, and root failure aggregation.

### Step 8 — Observability + Demo Packaging

Implement full trace UI/metrics and stable demos after correctness.

---

## 12. Required Spec → Code → Test Traceability

Every non-trivial implementation change must be traceable:

```text
Spec
 ↓
Code
 ↓
Test / PoC
```

Before coding a core feature, identify:

- authoritative Spec section;
- target source files;
- PoC/test IDs validating it.

Recommended change summary:

```text
Implements:
- specs/03-execution-runtime.md
  - NodeDispatchTicket
  - dispatch commit

Covers:
- POC-R109
- POC-R112
- POC-R113
- POC-R124

Architecture deviations:
- none
```

If there is a deviation, do not hide it.

---

## 13. Architecture Conformance Tests

Create and keep tests equivalent to the P0-Final checks.

At minimum:

```text
tests/architecture/
  test_import_boundaries.py
  test_schema_single_source.py
  test_no_deerflow_in_core.py
  test_no_llm_in_runtime_control.py
  test_frozen_contracts.py
  test_identity_allocation_boundary.py
```

Protect invariants such as:

- no DeerFlow imports outside integration layer;
- TaskNode has no mutable lifecycle status;
- Handoff is not an EvidenceRef;
- preparation has no execution_id;
- attempt/execution identity starts at dispatch commit;
- planner proposal cannot directly enter Scheduler;
- task final evidence does not fake Node provenance;
- authoritative schemas remain single-sourced.

Do not delete or weaken a conformance test merely to make implementation pass.

---

## 14. AI Coding Workflow

For each coding task:

### Before implementation

1. Read this `AGENTS.md`.
2. Read the relevant authoritative Spec.
3. Read matching PoC rows.
4. Reuse existing authoritative types instead of recreating them.
5. Identify target files, invariant, and expected tests.

### During implementation

- make the smallest coherent change;
- keep deterministic control logic separate from model behavior;
- do not broaden authority for convenience;
- do not silently fall back when evidence is missing;
- fail closed where required;
- preserve typed failure distinctions;
- preserve historical attempts/evidence.

### After implementation

1. Run targeted unit tests.
2. Run architecture/conformance tests.
3. Run related PoC-derived tests.
4. Run broader tests when feasible.
5. Check import boundaries.
6. Report any unimplemented frozen behavior.
7. Do not claim a Coding Step complete until Exit Criteria pass.

---

## 15. What Not To Do

Do not:

- start by modifying DeerFlow internals;
- build A-SWE inside the DeerFlow source tree;
- let Scheduler import DeerFlow;
- use LLM decisions for Runtime correctness;
- let raw Planner output control execution;
- dynamically spawn arbitrary Repair DAG nodes in P1;
- implement multi-writer auto repair in P1;
- implement dirty transactional rollback in P1;
- add distributed scheduling in P1;
- weaken quiescence requirements to make tests pass;
- treat backend terminal status as logical Node success;
- treat model self-report as mutation/evidence authority;
- treat test failure as proof of causal blame;
- treat UNVERIFIED as success;
- reuse stale Verification/Acceptance evidence after repair;
- run diagnostic Agents after task-wide fail-close;
- copy large patch/test payloads into Trace events;
- optimize prompts/UI before Scheduler correctness;
- expand P1 scope with benchmark/RL/memory unless explicitly requested.

---

## 16. P1 Explicit Non-Goals

Unless Design Freeze is explicitly reopened, P1 does not include:

- arbitrary runtime DAG spawning;
- arbitrary descendant rollback;
- dirty WRITE transactional rollback;
- multi-writer automatic repair;
- parallel write merge;
- distributed Scheduler;
- cross-machine Workspace locks;
- RL-based scheduling;
- automatic Provider rebinding after mutation;
- benchmark as a mainline blocker;
- self-improving policy claims without real update mechanics.

Do not “helpfully” implement these early.

---

## 17. Go / No-Go for Real DeerFlow Execution

Real DeerFlow shared mutable Workspace execution remains disabled until required integration PoCs pass.

At minimum preserve these gates:

```text
POC-02 / 03 / 05 / 09

POC-R34 / R35 / R36 / R38
POC-R50 / R51
POC-R69 / R70 / R73
```

Writer-reopen / dispatch-race semantics must first pass deterministic FakeBackend tests, especially the R109+ series.

If pinned DeerFlow cannot satisfy a frozen contract:

> do not weaken A-SWE semantics silently.

Use a compatibility seam, minimal fork, or explicit Design Freeze reopen.

---

## 18. Definition of Done

A feature is not done because it “works in a demo”.

It is done when:

```text
authoritative contract implemented
+
architecture boundary preserved
+
deterministic tests pass
+
relevant PoC expectations pass
+
failure paths tested
+
no silent contract deviation
```

A Coding Step is not done until its Master Plan Exit Criteria pass.

---

## 19. Final Principle

When implementation pressure conflicts with architecture correctness, prefer:

```text
explicit blocker
> silent semantic drift
```

When uncertain:

```text
preserve frozen authority boundaries
preserve evidence provenance
preserve deterministic state semantics
fail closed
do not invent hidden behavior
```

The goal is not to make A-SWE “look autonomous” as quickly as possible.

The goal is to build a Runtime whose behavior remains explainable, testable, and correct under retries, repairs, cancellation, shared workspace mutation, and backend failure.
