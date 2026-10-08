# Implementation Status

## Current phase

```text
Coding Step 0 — CLOSED / ACCEPTED
Coding Step 1 — NOT STARTED
```

## Step 0 accepted deliverables

- [x] Python package skeleton, `AGENTS.md`, pinned design snapshot
- [x] Provider-neutral shared contracts, safe runtime IDs, canonical SHA-256, RuntimeBudgetConfig
- [x] Immutable TaskNode/TaskDAG and canonical two-stage fingerprint/topology invariants
- [x] NodeAttemptRecord/NodeRuntimeState validated atomic authority snapshots
- [x] FakeBackend deterministic scenarios, cancellation cleanup, preparation/execution identity guards
- [x] P0-F01–F06 architecture conformance checks and negative regression tests
- [x] Core/DeerFlow/LLM import boundaries
- [x] Focused implementation review in `audits/step0-implementation-review.md`
- [x] Python 3.11 CI: 53 passed, 0 skipped
- [x] Python 3.13 CI: 53 passed, 0 skipped
- [x] PR #1 merged (squash commit `89e0b3c89acf3c95dd0116362c535317d6946675`)

## Step 1 — next, not yet implemented

1. LocalEvidenceStore `put_attempt / put_task / get`
2. RuntimeEvent minimal sink
3. WorkspaceSession / RepositoryBinding
4. exact baseline SHA and Git temporary-index RepositoryStateDigest
5. WorkspaceRevision / NodeWorkspaceDelta
6. READ/WRITE workspace lock manager
7. FROZEN / QUARANTINED lifecycle substrate

## Still deferred

- Step 2 Scheduler state transitions / dispatch commit / Repair
- Step 3–4 Planning / Capability / DAG compilers
- Step 5 DeerFlow integration (Go/No-Go gated)
- Agent/LLM, full evaluation and UI

The Step 0 closeout does **not** certify real DeerFlow execution; the P0 integration PoCs are pending.
