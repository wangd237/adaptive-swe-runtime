# Coding Step 2 — Repair Attribution & Writer Reopen (incremental review)

**Status:** Implemented as an incremental change on PR #3; NOT full Step-2 closeout.

## Tested behavior

1. VerificationResult and RepairAttributionEvidence include validated content fingerprints. An attempt-scoped VerificationResult must be attached to the exact completed failed verification attempt, and restored using LocalEvidenceStore.get().
2. Each FAILED check requires deterministic=true and same-attempt tool-receipt evidence whose provenance and WorkspaceRevision match. Missing, wrong-execution, malformed, and cross-state proof never authorize remediation.
3. Resolver uses the frozen compiler-owned VerificationRepairBinding for **every** failed check. Every candidate set must be the identical singleton. MULTI_WRITER, NO_OWNER and SOURCE_INELIGIBLE never fall back to model prose, nearest or last Writer.
4. Target is the current accepted logical WRITE Implementation node. Source pre/post Git fingerprint and revision evidence must be coherent. Intervening distinct Writer mutation or missing chronology invalidates scope.
5. Attribution has to be persisted as attempt EvidenceRef and attached to the failed source attempt. On reopen the Runtime re-derives the deterministic decision outside SchedulerStateMutex, then rechecks authorizations inside it.
6. Reopen serializes with downstream final dispatch commit under the same SchedulerStateMutex. READY without ticket goes PENDING; PREPARING, WAITING_WORKSPACE and LOCKED_PRECOMMIT tickets become REVOKED without allocating an attempt.
7. A COMMITTED/RUNNING consumer, including a FakeBackend reporting PRE_START, or an already SUCCEEDED ordinary non-verification descendant prevents Writer reopen and triggers task fail-close.
8. A successful reopen preserves historic accepted attempts and revokes only current Writer authority: acceptance_epoch goes 1→2. A successful repair publishes H2 and increments to 3; old H1 tickets cannot revive even if physical WorkspaceRevision is unchanged.
9. The same immutable TaskNode receives the REPAIR attempt; the same Verification Node receives REVERIFY with fresh attempt evidence. Repair dispatch checks observed WorkspaceRevision after gaining the Workspace lock.

## Deterministic gate

- Python 3.11: **122 passed, 0 skipped**.
- Python 3.13: **122 passed, 0 skipped**.
- Reviewed code baseline: PR #3 after the source-proof and PRE_START race tests.

## Still unproven (do not misrepresent)

- A trusted Runtime-owned canonical checker must validate actual test command completion and verdict; fake tool receipt/deterministic=True alone is **not** accepted production proof.
- Full typed RepairFeedback and externally verified tool/admission receipt semantics remain to be integrated.
- Automatic cancellation/join of COMMITTED affected consumer(s) is not yet implemented by reopen. Current fail-close stops dispatch but does not establish backend quiescence.
- FROZEN must wait for independently proven completion of every committed execution. Unknown quiescence requires QUARANTINED.
- PatchDisposition, root TaskResult, and cancellation evidence are deferred pending remaining Step-2 implementation.
- All mandatory PoC-R16–R26 and R75–R128 still require an exhaustive exit matrix; do not extrapolate from this subset.

## Frozen architecture

No P0 schema or authoritative Spec was modified. No DeerFlow or LLM was introduced.
PR #3 remains **open**, and Coding Step 2 remains **IN PROGRESS**.
