# Coding Step 2 — Scheduler Foundation Review (incremental)

## Scope

PR #3 introduces Scheduler dispatch concurrency primitives, **not** a complete Step 2 scheduler.

### Invariants exercised

1. READY evaluation, direct-dependency stamps and single ticket ownership are captured under SchedulerStateMutex.
2. Pre-commit ticket stages are revocable and do not allocate NodeAttemptRecord/execution/run identity.
3. After acquiring WorkspaceAccess, dependency evidence validation happens outside SchedulerStateMutex and final stamp+gate validation happens inside the mutex at dispatch commit.
4. A committed Node attempt records its immutable invocation identity and cannot be silently rolled back.
5. NodeHandoff must come from a trusted Runtime-owned acceptance callback; backend completion alone does not create success.
6. Clean retries require both PROVEN_NONE and a Scheduler-recognized transient failure kind; policy/acceptance failures do not auto retry.
7. Dirty failure closes task dispatch epoch and blocks unrelated READY/PENDING branches in the same state transaction.
8. Backend exceptions and external cancellation terminalize the committed attempt; lack of independent backend quiescence proof quarantines the workspace.
9. Runtime control does not import DeerFlow/LLM; tests use deterministic FakeExecutionBackend.

## Test gate

- Python 3.11: 101 passed / 0 skipped on PR head 9bf402052978a9b13a5af672e13ed8df9e4e7420.
- Python 3.13: 101 passed / 0 skipped on same head.
- Tests include ticket exclusivity, retry budget, unaccepted completion, stale revocation, task fail-closed, clean/policy retry denial, backend exceptions, READ mutation violation, and external cancellation.

## Not yet proven — explicit blocker

- VerificationRepairBinding → persisted evidence → deterministic RepairAttributionResult, including semantic authority checks.
- Writer reopen linearization against active downstream READY/ticket/COMMITTED dispatch (POC-R109–R126).
- REPAIR, REVERIFY, RepairFeedback freshness, and validated post-attempt WorkspaceRevision reconciliation.
- Backend cancellation join and terminal FROZEN/QUARANTINED across all committed active executions.
- Full task terminal state, ContractVerdict/TaskResult, and all Step-2 PoC exit criteria.

**Do not mark Step 2 complete, present this core as production-safe or merge this PR as a substitute for remaining P0 requirements.**

No frozen Spec has been changed.
