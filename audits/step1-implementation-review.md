# Coding Step 1 — Implementation Review

## Review verdict

ACCEPTABLE FOR CODING STEP 1, subject to PR CI and merge.

## Frozen-contract traceability

- specs/01-task-planning.md §4.17.2–4.17.4.1: WorkspaceRevision and immutable attempt/task EvidenceRef storage.
- specs/03-execution-runtime.md §3.2–3.2.3: Task Workspace, RepositoryBinding, Git digest, per-attempt delta, status semantics.
- specs/04-evidence-evaluation.md §13: RuntimeEvent/EvidenceStore ownership separation.
- plan/master-plan.md: Coding Step 1 implementation order and exit criteria.

## Evidence persistence

- Attempt-scoped and task-scoped references resolve after LocalEvidenceStore restart.
- Evidence objects have full SHA-256 payload digest and strict stored-ref provenance equality.
- JSON payloads are canonicalized; malformed/tampered data fails with typed EvidenceIntegrityError.
- Publication writes same-directory temporary file, fsyncs and atomically renames; single-process writer only.
- Data resides outside Agent Workspace and Trace references evidence rather than copying payload.

## Git / repository state

- Bootstrap resolves exact commit and detached HEAD, checks clean worktree, captures baseline after checkout.
- Temporary GIT_INDEX_FILE starts from resolved baseline; real index content is not changed.
- Git OID covers tracked updates/deletions and nonignored additions, regardless of real index stage.
- Per-attempt delta compares pre/post materialized tree OIDs (not cumulative baseline diffs).
- New paths relative to baseline are computed from staged temp-index diff-filter=A, NOT ls-files --others after temp staging.
- Baseline and newly introduced submodules, and configured sparse-checkout, are rejected in P1.
- HEAD drift/unauthorized commit is observable through RepositoryStateDigest/RepositoryInvariant.

## Workspace / quiescence

- Reader/writer access is task-local, exclusive for writers, writer-preferring, cancellable while waiting.
- Task dispatch closure denies new grants; FROZEN cannot be reached via ordinary lifecycle.transition().
- Only WorkspaceAccessManager.terminalize() may publish FROZEN/QUARANTINED; FROZEN requires caller-owned backend quiescence proof and no active workspace holders.
- QUARANTINED blocks workspace-touching finalization.
- Filesystem snapshot completeness refers to bounded scanner scope, NOT complete sandbox effects.
- Mutating-tool admission with no observed Git/filesystem delta is UNKNOWN, never PROVEN_NONE.

## CI / deterministic tests

- Reviewed PR head 4f346a2dd4db5d6fc4f9f6d8bce68df0ff533fa3:
- Python 3.11: 84 passed / 0 skipped.
- Python 3.13: 84 passed / 0 skipped.

## Explicitly deferred

- SchedulerStateMutex, revocable ticket/dispatch commit, retry/repair/reverify: Step 2.
- Backend quiescence collection/admission proof: ExecutionBackend / DeerFlow Adapter.
- Terminal ContractVerdict and final TaskResult assembly: later evaluation phase.
- Real network-hosted repository clone is not exercised by deterministic offline tests; network/credential/sandbox policy is an integration responsibility.
- Single-process EvidenceStore does not claim distributed multiwriter transactional guarantees.

No frozen P0 Spec was changed to make the code pass. Do not claim real DeerFlow execution is validated.
