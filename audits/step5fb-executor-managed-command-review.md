# Step 5F-B — Trusted Command Admission / Executor Completion / Evidence Attribution Audit

Date: 2026-10-09  
Target: PR #7 branch `coding/step5-deerflow-adapter`  
Authority: `AGENTS.md`, `specs/03-execution-runtime.md` §§3.2.2, 3.4.1–3.4.4, 3.5, `plan/step5-implementation-entry.md`, Step 3D CompiledAcceptancePlan / VerificationCommand and Step 2 CanonicalVerifier.

**Disposition: 5F-B1 deterministic bounded foreground + historical evidence binding Scoped GO, contingent on latest HEAD CI. Full 5F-B and Step 5 remain NO-GO.**

## Source-level implementations

- `src/aswe/integrations/deerflow/managed_foreground.py`: `ManagedForegroundVerifier` admits exactly one `VerificationCommand` whose canonical string, ID, argv fingerprint, compiled acceptance fingerprint and CanonicalCommandPolicy fingerprint are exactly bound to the selected `NodeExecutionPolicy`. Runtime Task ID, Node ID and Scheduler-owned liveness check are mandatory. No model-composed command, prefix or shell substitution is trusted.
- Foreground process is launched through `asyncio.create_subprocess_exec(*argv, shell=False)` with a separate Unix process group. Timeout/cancel triggers TERM/KILL and bounded process-group drain. A separate `asyncio.Event` is only set after cleanup and final host Git state capture; it is not set by a cancellation request. Results have exact attempt and command fingerprints and do not contain model-supplied output or secrets. Missing executable, detached entrypoint, inline interpreter outside test mode, timeout, pre-state drift, duplicate claim and non-quiescent group all fail closed.
- This is a **Runtime-managed local verification command** path, **not** an enablement of native DeerFlow `bash` or free-form shell. The command receipt is a host observation **not** yet the HMAC `CanonicalCommandReceipt` / canonical tests_passed acceptance verdict; stdout/stderr are deliberately discarded. Therefore it must not be promoted into user-facing Acceptance success.
- `NativeDeerFlowExecutionBackend` now maintains independent per-execution outer-coroutine completion events set in `run_native finally`, after `_aexecute` unwind. The resource-evidence collector checks both child task terminal state and this signal. `cancel_node` snapshots the signal before concurrent cleanup and refuses absent/unset signal. An outer coroutine exit cannot by itself prove a Sandbox lease or descendant process drained.
- `SchedulerCore.run_claim` optionally receives a trusted Runtime-supplied `execution_evidence_store`. It validates tool receipt and workspace evidence refs *outside* SchedulerStateMutex (kind, task namespace, node/execution/attempt, durable reference bytes). `_finish` atomically attaches these verified refs to the historical attempt. No model-proposed ref, cross-attempt ref or missing store can attach, and evidence attachment **never** substitutes for acceptance / Handoff.
- Existing 5F-A unknown quiescence quarantine remains mandatory; no supervisor is fabricated.

## Adversarial CI proofs

- `tests/unit/test_deerflow_managed_foreground_step5fb.py` runs real local subprocesses: exact approved argv, no prefix/suffix match, fake uncommitted invocation deny, inline-shell/interpreter deny, genuine timeout process group drain and cancel-time independent completion, pre-execution Git revision drift, detached entrypoints, missing executable sanitization.
- `tests/unit/test_deerflow_native_execution_step5e.py` cancellation race checks the native completion event stays false while the stream is blocked and becomes true after cancellation unwind.
- `tests/unit/test_deerflow_execution_evidence_step5f.py` covers actual Scheduler commit, 5C/5D binding, mocked-native execution, 5F evidence write and historical attempt attachment; forged foreign execution evidence is rejected and triggers fail-close.
- Frozen Python 3.12 installed DeerFlow offline integration tests still exercise model/tool runtime + evidence separately, not native Bash or production Sandbox.
- Report specific latest HEAD Core Python 3.11 / 3.13 and vendor Python 3.12 CI results only after checks finish.

## Outstanding critical gates

1. **No actual released trusted sandbox lease/process supervisor** is wired to `ExecutionEvidenceCollector`. Event and local PGID tests cannot attest native AIO/LocalSandboxProvider process/lease/worker drain, remote command sessions, or detached children escaped via setsid. Full executor-owned quiescence NO-GO.
2. **No native managed Bash tool authorization.** Native `bash`, WRITE/replace, plugins/MCP/deferred tools remain disabled by 5D. The new foreground verifier cannot be called a tested DeerFlow Sandbox handler or a canonical Bash receipt.
3. `ManagedForegroundVerifier` output is *not* an HMAC-attested `CanonicalCommandReceipt` accepted by existing `CanonicalVerifier.validate`; command exit observations do not bind a TRUSTED tests_passed acceptance without the existing canonical verification path or an explicitly designed signing bridge with real stdout/stderr provenance and resource fences.
4. Exact compiler-bound argv is the primary authority, with known daemon entrypoint denylist as only defense in depth. It cannot prove arbitrary allowed programs never fork-and-detach. Unsafe/multi-command plans are unsupported in this bounded path.
5. Full `NodeExecutionResult`/Acceptance Compiler, real mutable Workspace/Bash reconciliation, Handoff, genuine external model and AuthorizationProvider credentials and final P0 matrix still pending.
6. A-SWE Core test lanes are Python 3.11/3.13; installed source-pinned DeerFlow Python 3.12 lane remains a separate offline physical test. Dependency lock/provenance remains a 5G release gate.

**Decision:** scoped deterministic implementation progress only. Keep PR #7 Draft/Open and unmerged; do not advertise full 5F-B quiescence, canonical Bash evidence, external auth or Step 5 completion.
