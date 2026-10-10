# Coding Step 5F-B2 — Native Lease / Canonical Foreground Attestation Consistency Audit

**Date:** 2026-10-09
**PR:** #7, `coding/step5-deerflow-adapter`, Draft / Open, unmerged
**Authority:** `AGENTS.md`, `specs/03-execution-runtime.md` §§3.2.2, 3.4.1–3.4.4, 3.5, Step 3D `CompiledAcceptancePlan`, Step 2 `CanonicalVerifier`, and frozen `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891`.
**Result:** 5F-B2-A **Scoped deterministic / installed-offline protocol GO conditional on latest HEAD CI**. Full native Sandbox quiescence, arbitrary Bash/WRITE admission and production Acceptance remain **NO-GO**.

## Frozen-vendor factual findings

- Upstream `SubagentExecutor._aexecute` creates a `SubagentResult` with a random `task_id`; `_aexecute_admitted` sets `sandbox_lease_owner_id = "subagent:" + result.task_id` and releases it in `finally` using `get_sandbox_lease_manager(provider).release_async(owner_id)`.
- Upstream `SandboxLeaseManager.binding_for(owner_id)` observes whether an owner is still associated with a sandbox. **Its `release()` removes that binding before executing `sandbox.release_command_scope(owner_id)` and `provider.release(sandbox_id)`. If these release steps raise, the owner may already be absent.** Therefore absent owner binding is NOT independent proof of provider release or external-process quiescence.
- `LocalSandboxProvider` exposes the actual manager under Python 3.12 installed Harness. The physical test exercises its `acquire_async/release_async` and the real `binding_for` transition, while deliberately refusing to promote this alone into a positive `QuiescenceObservation`.

## Implementation

1. `src/aswe/integrations/deerflow/native_lease_supervisor.py` defines the Scheduler-derived native task ID and actual owner ID `subagent:<sha256-prefix>`. `NativeSubagentAssembler` creates a real vendor `SubagentResult` with that exact ID before calling the frozen `_aexecute`; the vendor still owns admission, `_aexecute_admitted`, streaming, and cleanup. No arbitrary model-supplied owner is accepted.
2. `NativeSandboxQuiescenceSupervisor` registers the task/execution/owner scope before native spawn, checks the live frozen Lease Manager and native completion, then requires **both** independently attested `provider.release` completion and executor-owned process-tree drain before returning `complete=True`. Wrong task, no known scope, changed/uninitialized provider, busy owner, incomplete native exit, failed probe or missing probes yield negative.
3. There is **no production source of `release_completion_probe` or `process_tree_probe` yet**. These are Runtime trust dependencies, not boolean flags a model or Sandbox may set. The installed vendor physical test proves lease binding transitions, not actual daemon/process/cgroup teardown or complete release attestation.
4. `src/aswe/integrations/deerflow/managed_foreground.py` now uses Runtime-owned temporary files outside the worktree to hash actual stdout/stderr, not user/tool-supplied hashes; command identity, compiler policy, task/node/attempt, revision, process drain and pre/post Git are captured.
5. The host process-group finalizer is an **independently owned task** that does not set the completion fence until it has reconciled the pending spawn and process drain and captured Git state. Cancellation (including repeated cancellation) returns promptly without waiting on intentionally blocked cleanup; the separate completion wait remains false until the finalizer exits. A test caught and fixed a deadlock where cancelling the caller did not unblock until the finalizer returned.
6. New privileged `CanonicalVerifier.attest_foreground_observation` checks exactly matched frozen `CanonicalCommandPolicy` + invocation provenance, revocation-independent completion, process-group-drained flag, return code, timeout and repository identity before issuing a Runtime HMAC `CanonicalCommandReceipt` through trusted `LocalEvidenceStore`. Read-after-write validation and `CanonicalVerifier.validate` are required; nonzero is FAILED, timeouts/cancel/incomplete cleanup are UNVERIFIED, not HOLDS.
7. `ManagedForegroundVerifier.canonical_check_binding` produces Step 3D `CanonicalCheckBinding` with a real validated EvidenceRef for the existing `verified_canonical_check_finding` path. **This does not itself run the compiled Acceptance verifier or set an accepted Node/Task state.**
8. Original 5D tool gate still **disables native DeerFlow Bash/WRITE/Skill/MCP/Extensions**. The signed path is an independently managed Runtime foreground verifier, not an implicit promotion of native `bash_tool`.

## Test matrix

- Python 3.11 / 3.13 Core deterministic and actual host foreground subprocess: exact compiled argv, forged command denial, output hash capture, HMAC signer/validator, matching CanonicalCheckBinding, timeout/nonzero/cancel negative receipt, two-phase completion fence and replay rejection.
- Real frozen Python 3.12 Harness: native `SubagentExecutor._aexecute` returns the Scheduler-derived task ID, real Lease Manager acquires/releases a scoped lease; no fake source or simulated `ToolNode` used in these physical tests. The test explicitly asserts absence of release/process completion attestation keeps quiescence **unproven**.
- Additional fault injection: owner still bound, native not complete, manager failure, release completion probe false, process probe false/missing, mistaken task/execution ID, and registration replay.
- Pre-existing P0-C tests with fixed 300 event-loop-yield loops were changed to bounded actual-time waiting in two spots to avoid load-sensitive false CI failures, without weakening the state assertions or behavior.

## Residual P0 / release blockers

- **Lease manager's owner absence is not proof of a successful provider release.** Production requires a trustworthy release-success receipt from the actual provider, with matching owner and relevant sandbox identity, not an injected test lambda. It must also track runtime-owned subprocess groups, native Task workers, detached children and provider-specific shell-session state through a concrete independent process probe. **Full native Quiescence is not closed.**
- Runtime-managed local foreground subprocess verifier does not justify enabling native DeerFlow `bash_tool` or arbitrary `str_replace/write_file`. Process groups cannot contain descendants that deliberately escape via `setsid`; known daemon entrypoints are denied, but exact compiler argv alone is not a cgroup/sandbox isolation proof.
- The new attestation API is a privileged Runtime-to-Runtime seam. Do not expose the `CanonicalVerifier` signer/key or foreground observation object to the untrusted model/sandbox; a forged Python object in the same fully compromised Runtime process cannot be cryptographically distinguished from an authorized caller by class type alone.
- The original synchronous `CanonicalVerifier.run` remains a separate local subprocess implementation; this stage does not retrofit its timeout/process-tree management. The managed runner HMAC bridge must be selected explicitly by trusted assembly, and end-to-end immutable Scheduler Attempt/TaskResult Acceptance still needs physical integration.
- No real model API credential or deployed external AuthorizationProvider invocation has been proven. Dependency runtime comes from pinned upstream source but not an immutable `uv.lock` deployment image.
- PR #7 remains Draft/Open; **no production enablement, Writer/Bash authorization widening, merge, or whole Step 5 declaration**.

## Gate

**Scoped GO** for deterministically tested HMAC-sealed managed foreground and source-pinned lease-owner tracing once newest HEAD CI passes. **NO-GO** for end-to-end Native Sandbox Quiescence, canonical native Bash tool receipts, unrestricted mutation, production Acceptance and PR #7 merge.
