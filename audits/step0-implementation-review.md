# Coding Step 0 — Implementation Review

Review scope: PR #1 (`coding/step0-contract-conformance`).

## TaskDAG fingerprints — corrected

- `structure_fingerprint` is computed from canonical nodes/edges (node and dependency order normalized).
- `TaskDAG` construction validates the supplied structure hash and final DAG hash.
- VerificationRepairBinding references the structure hash, not the final hash; no recursive hash.
- Duplicate/unknown repair binding references and noncanonical topological order are rejected.
- `model_copy(update=...)` for frozen contract models is revalidated rather than bypassing invariants.

## NodeRuntimeState authority — corrected

- NodeAttemptRecord and NodeRuntimeState are immutable *published snapshots*; their logical state is changed through Scheduler-owned atomic replacement in Step 2.
- Accepted authority must map to an ACCEPTED historical attempt with the exact same Handoff content and matching source execution/attempt identity.
- Reopened Writer may preserve historical Handoff while clearing current accepted authority.
- Duplicate attempt identities, reused `next_attempt`, and SUCCEEDED-without-current-authority states are rejected.
- Direct field assignments and invalid `model_copy(update=...)` are rejected.

## FakeBackend cancellation — corrected

- Cooperative `cancel_node` unblocks barrier waits and returns a CANCELLED fake record.
- External `asyncio.Task.cancel()` always cleans registered waiters and does **not** forge a terminal/quiescence record.
- Duplicate execution identity / preparation replay is rejected; cancel state does not poison subsequent executions.
- `quiescent=False` in a fake scenario is a test signal, **not** evidence of quiescence.

## Explicit scope boundary

These changes implement Step-0 data contracts, pure validation, and FakeBackend test instrumentation **only**.
The Scheduler's real dispatch/reopen transitions, Workspace/Git substrate, and full ExecutionBackend adapter remain later Coding Steps.
No frozen P0 semantic contract was changed.

## Final acceptance

- Required: Python 3.11 and 3.13 CI green, no skipped test for POC-F01.
- Required: PR merged without changing frozen Specs to accommodate code.
- Upon acceptance: Step 0 CLOSED; next activity is Step 1 Evidence/Workspace/Git.

## Accepted closeout

- PR: https://github.com/wangd237/adaptive-swe-runtime/pull/1
- Reviewed head: `689de98cbbbbf947b31a0c97a01aac908b1d5d8e`
- CI: Python 3.11 **53 passed / 0 skipped**; Python 3.13 **53 passed / 0 skipped**
- Merge: squash commit `89e0b3c89acf3c95dd0116362c535317d6946675`
- Verdict: **Coding Step 0 CLOSED / ACCEPTED**
- Next work: Coding Step 1; no DeerFlow/LLM integration was introduced.
