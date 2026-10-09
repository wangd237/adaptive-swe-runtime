# Step 4 — Physical Integration Closure of Frozen P3 PoCs

**Stage-4 scoped result:** P3-01 / 02 / 03 / 04 / 11 direct deterministic FakeBackend/real-Git integration scenarios all PASS on Step-4 coding branch. Step 3's existing frozen 22-case inventory now records **22 PASS / 0 PARTIAL / 0 GAP** in THIS branch. Full Step-4 **Core** follow-up is now independently audited in `audits/step4-independent-freeze-review.md`; actual DeerFlow adapter remains Step 5.

| Frozen PoC | Direct test | Physical invariant |
|---|---|---|
| P3-01 | `tests/unit/test_step4_physical_p3.py::test_p3_01_02_03_real_scheduler_stage_barriers` | Coder has exclusive physical WRITE; Tester using bash is physical WRITE; materialized phase edge and real Scheduler gate confirmed. |
| P3-02 | `tests/unit/test_step4_physical_p3.py::test_p3_01_02_03_real_scheduler_stage_barriers` | Materialized Tester WRITE -> Reviewer READ dependency, verified in real Scheduler READY progression. |
| P3-03 | `tests/unit/test_step4_physical_p3.py::test_p3_01_02_03_real_scheduler_stage_barriers` | Discovery READ -> Implementation WRITE materialized edge validated through real Scheduler. |
| P3-04 | `tests/unit/test_step4_physical_p3.py::test_p3_04_ordinal_physical_writes_are_deterministically_serialized` | Same-phase unordered business WRITEs get stable ordinal-dependent edge and actual successor claim gate; deterministic TaskDAG fingerprint. |
| P3-11 | `tests/unit/test_step4_physical_p3.py::test_p3_11_tester_bash_physical_write_business_read_git_invariant` | Tester bash requires physical WRITE, remains business READ_ONLY: actual tracked Git mutation rejected and fail-closed by Stage4 Git guarded FakeBackend; clean bash passes. |

## Actual execution authority chain

```text
Accepted Stage-3 CompiledTaskContract + TaskExecutionAuthority
     + ValidatedWorkPlan (fingerprint checked)
     + trusted AgentProvider and FakeBackendInventory
     ↓ Provider resolver (tool-implementation identity, not exposed name)
ResolvedPlan (typed bound resources, immutable inventory)
     ↓ TaskDAG Materializer (re-validates physical ToolEffect)
TaskDAG (phase barriers, same-phase WRITE ordering)
     ↓ Existing SchedulerCore (workspace RW lock and accepted handoffs)
FakeBackend execution / real Git PostNodeGitInvariantBackend
```

**Negative tests:** optional bash never escalates Explorer READ; required bash escalates Tester to exclusive WRITE, despite semantic READ_ONLY. Unknown implementation identity cannot masquerade as read_file. A caller re-signing NodeResources with `workspace_access=READ` cannot pass the materializer's independent tool-effect check. BackendInventory and AgentProvider are deeply frozen.

**Business vs physical authority:** WorkKind.VERIFICATION with bash is *semantically READ_ONLY* but *physically WRITE*. The Tester's real tracked Git mutation is detected by comparing Git repository state **before and after the task-local exclusive lock**. The existing Step-2 TaskResult fail-close root is `DIRTY_WRITE_FAILURE`; the precise attempt reason is `POST_NODE_INVARIANT_GIT_MUTATION`. A clean bash run is accepted.

## Scope limits; not Stage 4 CLOSED

- These are actual temporary Git + FakeBackend + Scheduler scenarios, **not** live DeerFlow tools. `PostNodeGitInvariantBackend` is a Step-4 FakeBackend adapter requiring a compiled TaskDAG; production provider admission must always install the equivalent guard before Step 5.
- The remaining overall Step-4 Provider preflight, live inventory drift, MCP/skills and detailed `NodeExecutionPolicy` / `CompiledPlanDescriptor` contracts require dedicated Step-4 development and their OWN frozen P0-5 PoCs. Do not claim Step 4 completed from this physical slice.
- Stage-3 scoped semantic baseline was merged in PR #5 as `584c1eaee442aa7b3a81b507b24a54a3b4d799f2`. Step-3's P3 physical deferred conditions now pass on this Step-4 branch, not yet on `main` until PR #6 merge.
- No alteration to `specs/01-task-planning.md`, `specs/02-capability-provider-dag.md`, or `tests/poc-matrix.md`.

## CI

Last physical hardening implementation HEAD `29cc2aef14d2d189c5992a8692b2d0b1c552c421`: Python 3.11 and Python 3.13 each **305 passed** (GitHub Actions 37895498872). Latest audit-only head must run both Python lanes.
