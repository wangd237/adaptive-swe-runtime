# Step 5F-C-B — End-to-End SWE Task / MVP Result Integration

Date: 2026-10-10
Branch: `coding/step5-deerflow-adapter` / PR #7 (Draft, do not merge automatically)
Frozen native source: `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891`

## Scope and acceptance criterion

MVP must prove one real committed Scheduler WRITE execution; real installed
DeerFlow `SubagentExecutor` + LangGraph tool calling; an isolated Docker
command runner; iterative code correction after a failed model-side test;
Runtime's **separately executed**, HMAC-signed regression test on the actual
post-write Git state; and a machine-readable report with actual patch,
modified-file paths, test status and run identity.

User explicitly deferred full Sandbox Provider release/process group quiescence
hardening and detailed all-leaf Acceptance for MVP. These are **not**
satisfied by changing `quiescent` to True.

## Implementation

- `src/aswe/integrations/deerflow/mvp_task.py` implements
  `MVPTaskRunner`, `_VerificationProbe`, and `MVPTaskReport`.
- The Runner passes a wrapper into **real** `SchedulerCore.run_claim()`.
  Its probe calls the native backend and then (while the Scheduler still
  holds WorkspaceAccess) captures Git state, materializes the Git
  changeset, and runs the exact Runtime-owned `CanonicalCommandPolicy`
  using `CanonicalVerifier.run()`; the receipt is subsequently read and
  verified by `CanonicalVerifier.validate()`.
- Both missing/corrupt verification proof and command failure produce an
  explicit non-success verdict. The Agent's own Bash output never replaces
  this independent canonical test.
- `MVPTaskReport` includes task/node/execution/attempt identities,
  native execution outcome, canonical check ID and EvidenceRef, verified
  exit code, changed file paths, bounded Git diff with truncation flag,
  host-observed workspace fingerprint, Scheduler status, quarantine and
  failure flags, and noncertified Agent Bash/file-tool diagnostics.
  `to_json()` exposes an ordinary machine-readable response.
- **Original Core authority is untouched:** with missing full quiescence
  evidence the Scheduler's strict state still fails/closes/quarantines,
  even when the independent test succeeds.
  `delivery_status=tests_passed_scheduler_quarantined` is a supported
  *MVP diagnostic* and is NEVER an accepted NodeHandoff or TaskResult.

## Tested execution levels

**Core deterministic (Python 3.11 + 3.13):**
`tests/unit/test_deerflow_mvp_task_step5fcb.py` runs real Git fixture and
actual Scheduler commit, creates a code patch under the active execution,
uses actual Python unittest as the independent canonical command, validates
signed Runtime EvidenceRef and JSON output. Negatives include failing tests,
native execution failure, unavailable verification executable, foreign
task verifier and runner replay.

**Installed frozen native + real Docker (Python 3.12):**
`tests/integration/test_deerflow_mvp_e2e_step5fcb.py` uses actual
`NativeDeerFlowExecutionBackend`, source-pinned
`NativeSubagentAssembler.from_deerflow()`, real
`NodeExecutionBindingStore.bind()` after a genuine Scheduler Commit,
actual LangChain/LangGraph tool execution, and a genuine no-network Docker
container (locally resolved image digest). Scripted offline
`BaseChatModel` directs:
read broken `calc.py` → wrong edit → real container grep returns failure →
re-read → fix → real container grep succeeds → Native COMPLETED.
The probe independently runs Python unittest against the actual modified
worktree, obtains `holds` in a signed CanonicalVerifier receipt, and
returns a bounded diff and explicit strict Scheduler quarantine.
Actual Docker, native and canonical test happen in **one run**.

The native E2E test uses a **test-fixed source preparation adapter**, not
the full real 5C freeze/inventory/compiler path. This adapter provides
frozen-shaped `NodeExecutionPreparation`, fixed source-tool `ToolConfig.use`
mappings and scoped resource attributes; the *real* 5D
`NodeExecutionBindingStore` handles the postcommit tool view, policy
checks, object seals and ToolCallGuard. This is not sufficient evidence for
production 5C physical chain.

CI:
`.github/workflows/deerflow-pinned-native.yml` now also runs this
end-to-end installed-native + Docker + canonical regression test.
Do not claim newest CI GO until exact HEAD completes green.

## Deferred / known limitations

1. No real remote LLM API calls or production external AuthorizationProvider
   credentials; the physical E2E model is scripted but the tools, repository,
   Docker, LangGraph graph and canonical tests all run physically.
2. Full 5C installed-provider, source-sealed inventory and compiled-policy
   integration into this one production composition remains a separate gate.
3. No formal Sandbox Quiescence proof; the original Scheduler reports
   `quiescent=False`, fails closed, quarantines; MVP reports tests passed
   and actual status separately, and does not permit downstream accepted
   DAG dependencies.
4. No general repair retry after a *Runtime canonical* test fails across
   Scheduler attempts; native Agent's own iterative test-fail/retry is
   physically demonstrated. Scheduler's strict repair/failure budgets remain.
5. No production user-facing app/API orchestration, deployment environment,
   full review, locked image supply-chain, or benchmark. Report is a
   typed Python service result / JSON, not a live hosted endpoint.
6. `CanonicalVerifier.run()` uses trusted local process invocation for
   verification; it is not the general Agent Bash tool and its full process
   quiescence hardening has been deferred per user decision.

## Decision

**5F-C-B Scoped GO when latest CI passes**: MVP physical end-to-end
offline tool execution and independent verification demonstrated.
**Full Step 5 and PR merge remain NO-GO** until explicit production
credentials/provider preflight and declared release gates.
