# Coding Step 2 — Final Source and Design Freeze Consistency Review

## Review scope

Inspected the PR #4 implementation against `AGENTS.md`, `specs/03-execution-runtime.md`, `specs/04-evidence-evaluation.md`, the immutable 65-row frozen PoC inventory, and full Python 3.11/3.13 GitHub Actions. This review is separate from the incremental status labels but **is not a third-party security audit or live DeerFlow adapter test**.

## Findings addressed prior to merge

1. **Audit-record integrity.** The original Markdown audit had incorrectly concatenated and duplicated PoC table entries and an obsolete header. Rebuilt it deterministically from the 65 unique machine-readable entries and added a regression to prevent recurrence.
2. **Obsolete stage evidence.** Old review/status material still referenced early 31/18/16 counts and 158-test CI despite the later 65/0/0 matrix. Replaced with current acceptance state and explicit limitations.
3. **Cancel-versus-COMPLETED race.** A backend can settle COMPLETED after the task's or a node's cancellation. Previously the invalidated handoff could manufacture a new business failure. Runtime now treats these late results as cancellation consequences, with tests for task fail-close and local cancellation. Quiescence and mutation evidence still govern Workspace safety.
4. **Physical Workspace holder quiescence.** The P0-D suite verified cancellation drains both committed backend executions and outstanding physical LOCKED_PRECOMMIT holders; waiting timeout conservatively yields QUARANTINED, not FROZEN.
5. **Synchronous evidence resolver scheduling.** Potentially blocking EvidenceChecker work was moved off the event loop; final ticket/epoch/dependency stamps are still checked at dispatch commit under SchedulerStateMutex.

## Source authority and boundaries

- No DeerFlow/LLM imports are permitted in core Runtime control; FakeExecutionBackend is the Step-2 execution test seam.
- Immutable TaskNode/TaskDAG and EvidenceRef/TaskEvidenceRef identity remain separate from runtime NodeAttemptRecord and TaskResult.
- Retry and Repair never spawn new DAG business nodes; automatic multi-writer repair remains prohibited.
- Typed feedback must bind source and target attempt, WorkspaceRevision, immutable checker/attribution refs, and authority epochs; stale evidence cannot authorize a silent repair.
- Scheduler dispatch ticket and accepted Handoff publication are fenced by the same mutex; success is not inferred from backend COMPLETED alone.
- Dirty failed tasks may retain a Git-visible residual Patch without acceptance. QUARANTINED forbids current Workspace/Git reads.

## Step 2 conformance result

The 65 frozen Step-2 PoCs are individually marked **PASS** in the machine-readable inventory. The associated suite is scenario-specific, including adversarial fake backend and temporary real Git repository tests. Verify latest PR SHA's two CI lanes before merge and record the exact final commit in `IMPLEMENTATION_STATUS.md`.

## Deferred, not claimed

- Real DeerFlow/LLM tool admission, command-policy reconciliation, and shared sandbox lifecycle: Step 5.
- Compiler-owned task constraint provenance, mutation authority, and execution command policy: Steps 3/4.
- Distributed/restart-safe Scheduler replay and cross-machine locks: explicit P1 non-goals.

**Recommendation:** merge only when the latest PR head is green and the audit integrity test passes; then mark Step 2 CLOSED on main, without treating deferred integration PoCs as complete.
