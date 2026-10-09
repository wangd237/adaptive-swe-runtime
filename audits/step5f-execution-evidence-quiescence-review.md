# Step 5F — Execution Evidence / Workspace Mutation / Quiescence audit
Date: 2026-10-09 | PR #7 Draft/Open | Scope: frozen specs/03-execution-runtime.md §3.2.2, §3.4, §3.5

**Verdict: 5F-A readonly host-scoped evidence implementation — conditional scoped GO. Full 5F physical sandbox quiescence / Bash receipts / production WRITE: NO-GO.**

## Source-to-contract trace

- ExecutionEvidenceCollector.begin captures live RepositoryStateDigest and FilesystemSnapshot after Scheduler dispatch commit, inside the existing WorkspaceAccess window. Refuses revision fingerprint, HEAD and baseline drift before native model dispatch. A preparation is not execution proof.
- ExecutionEvidenceCollector.finish collects workspace state *after* closing ToolCallGuard and joining the native task. Existing derive_node_workspace_delta compares attempt-local snapshots, not a cumulative baseline diff. Partial observations are retained. Scanner exclusions, limits and truncation force mutation UNKNOWN in authoritative result; changed paths are still persisted for diagnostics.
- ToolCallGuard now records thread-safe per-call authorization/handler outcomes, reserves tool IDs before dispatch, and persists only argument/output hashes, tool IDs/names, stable error codes and execution ID. These are host-bound ToolCallGuard receipts, **not** canonical Bash/sandbox receipts. A missing/unfinished ledger never certifies clean execution.
- Outside-workspace LocalEvidenceStore persists TOOL_RECEIPT_LEDGER and WORKSPACE_CHANGESET with attempt ID, execution ID and revision identity; persisted artifacts are read back to verify integrity.
- NativeDeerFlowExecutionBackend optionally wires this collector into the actual Scheduler-owned execution path. No collector leaves previous quiescent=False/mutation_evidence=unknown. Non-readonly/mutating tools are still strictly rejected.
- Runtime-provided external ResourceSupervisor.inspect must corroborate matching task/execution, complete tool-worker drain, process scope drain and sandbox lease release, with native task joined and no ToolCallGuard in-flight calls. Missing, wrong, failing, or incomplete supervisor produces quiescent=False, mutation UNKNOWN and existing Scheduler QUARANTINED on termination.
- The QuiescenceObservation dataclass alone is **NOT an independent proof**; unit positives deliberately use a synthetic supervisor. No verified production supervisor exists yet.

## Tests and evidence

- Core 3.11/3.13 unit tests in tests/unit/test_deerflow_execution_evidence_step5f.py: baseline mismatch, replay, partial/excluded snapshot, native-shaped actual Scheduler Workspace lock+5C+5D+5E+5F, runtime evidence provenance and receipt replay/serialization, supervisor mismatch/timeout/error and guarded cancellation effects.
- Installed frozen DeerFlow Python 3.12 integration in tests/integration/test_deerflow_pinned_native_step5eb.py: genuine SubagentExecutor._aexecute with offline BaseChatModel/real LangGraph ToolNode/guarded tool, evidence persisted to Git-independent LocalEvidenceStore, and explicit negative quiescence with no external witness.
- Test results on latest HEAD are required before saying the code checkpoint passed.

## Residual P0 and release gates

1. **No production resource supervisor / independent sandbox process or lease attestor.** The scope of quiescence is executor-owned work, not every warm container/process in the universe; completion of a coroutine alone does not certify either. Do not treat an injected true-valued fake as physical proof.
2. WRITE, arbitrary shell, canonical compiled foreground VerificationCommand, tool-start side-effect admission ledger, native Bash command receipts, sandbox path policy, review direct-return and Acceptance Compiler receipts still require dedicated physical 5F-B tests and policy binding. No weakening 5D restrictions.
3. Snapshot scope is bounded. Excluded directories force incomplete evidence; Git HEAD/tree does not attest every git-control-file or external state mutation. Do not equate hash-only receipt with guaranteed absence of side effects.
4. Result data are intermediate NativeExecutionRecord values, not full frozen NodeExecutionResult; Workspace and tool EvidenceRefs are durably persisted but not yet automatically attached to historical Scheduler attempt records via attach_attempt_evidence.
5. Credentialed model API, real external AuthorizationProvider, real native Sandbox cancellation/process drain, fully locked vendor dependencies and end-to-end final TaskResult remain open for 5G.
6. PR #7 remains Draft/Open/unmerged. No Step 5 closure or production execution approval.

**Decision:** Scoped GO for tested host readonly evidence/negative quiescence if newest CI is green. Explicit NO-GO for production quiescence, managed WRITE, PR merge and whole Step 5.
