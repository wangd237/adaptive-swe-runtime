# Step 2 — Runtime Canonical Verifier / RepairFeedback / TaskResult Review

**Decision:** Step 2 implementation increment may be reviewed and CI tested, but the Stage 2 exit gate is **NOT MET** (31 PASS / 18 PARTIAL / 16 GAP among 65 frozen PoCs).

## Canonical verification

- Exact Runtime-owned command policy argv; `subprocess.run(shell=False)` with bounded timeout.
- Pre-execution WorkspaceRevision must match real Git baseline/current digest; after execution the repository is re-observed.
- Zero exit code / unchanged Git → HOLDS; nonzero / unchanged Git → FAILED; mutation or timeout → UNVERIFIED.
- Canonical attempt TOOL_RECEIPT_LEDGER proof lives in LocalEvidenceStore, full SHA-256 payload binding, HMAC issued with task-scoped key outside workspace.
- Strict RepairAttribution resolver independently checks tool receipt authenticity and matching execution/check/revision; unauthenticated fixture proof rejected unless explicit **test-only** Scheduler override.
- Local subprocess foreground success/timeout does not establish native DeerFlow admission/receipt-policy or distributed tool quiescence; defer to Step 5.

## Typed RepairFeedback

- Implements frozen source/target attempt and trigger fields, observed revision, failed check IDs, verification_result, repair_attribution, typed ReceiptRefs and diagnostic projection.
- Feedback's content fingerprint and receipt provenance are checked on construction; no model prose controls owner selection.
- Scheduler publishes feedback atomically with Writer reopen, and checks revision under workspace lock before REPAIR attempt commit.
- Remaining: feedback refresh if Workspace advances and no spurious Repair when refresh says holds (R23–R26).

## Terminal semantics

- ContractVerdict is BLOCKING if any LOCKED/HARD leaf is violated or unverified; successful TaskResult requires explicit **expected compiled contract fingerprint** and passing verdict.
- TaskResult status, WorkspaceDisposition, RepositoryDisposition, PatchDisposition are independent. Failed/cancelled with patch: RESIDUAL_UNACCEPTED, never ACCEPTED.
- Stable-FROZEN Runtime-only finalization emits `TaskEvidenceRef` for final Git state/changeset/contract verdict; final TaskResult itself is persisted separately, not fabricated as Node-attempt evidence.
- On QUARANTINED there is **zero current Git inspection**; only existing integrity-validated historical attempt refs survive.
- LocalTaskResultStore creates one immutable terminal result with atomic publication and restart integrity validation.
- A stable but scanner-excluded/unknown physical attribution stays STABLE_WITH_UNCERTAINTY unless the caller supplies complete proof.

## Risks and remaining conformance deficits

- TaskResult is not an evaluator: CompiledTaskContract and full leaf-to-evidence evaluation belong to Step 3/7. Never self-create a passing contract verdict from LLM text.
- Raw LocalVerifier command policies need higher-level compiled authority and sandbox policy; hash alone is not tool authorization.
- Current execution state is in-process Scheduler; persistent state replay/distributed scheduling are outside P1.
- 65-row exact PoC audit: audits/step2-poc-audit.md and machine-readable audits/step2-poc-coverage.json.
- **Do not close Step 2 or claim end-to-end autonomous SWE execution** until all 34 PARTIAL/GAP rows are resolved.

## Commit and CI

- Source of truth: PR #4; inspect the latest head and its Python 3.11/3.13 Actions jobs before any merge.
