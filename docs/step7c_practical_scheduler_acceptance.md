# Step 7C-C — Practical Scheduler Acceptance and Multi-Agent Handoff

## Scope and goal

This is an intentionally **bounded**, single-owner SWE development profile.
It is not a replacement for high-assurance process-tree verification, it
does not certify arbitrary third-party tools, and it does not claim a strict
formal quiescence proof. The strict collector path remains available.

We separate three distinct questions:

1. **Execution terminated safely:** native task joined, tool admissions
   closed, no pending guarded calls, no incomplete Docker command, no
   uncertain container cleanup.
2. **Workspace snapshot is stable:** the Coder's exclusive Scheduler WRITE
   access is still held, Runtime captures full pre/post filesystem and Git
   evidence and checks the exact post-revision before Handoff. Incomplete
   scanner output and baseline drift are never accepted.
3. **Code is correct:** a separate independent Tester owns this verdict.
   A Coder may be accepted with a failed focused canonical precheck, because
   this merely means Tester/Repair have work to do.

## Modules changed

- `controlled_swe.py`: bounded Docker subprocess accounting. A definitely
  failed command **before subprocess spawn** need not poison the whole run;
  an unknown exit, cancellation or unverified cleanup does. The failure is
  sticky for the run, even if later commands succeed.
- `execution_evidence.py`: new `acceptance_profile="practical"` is
  explicitly opted in. It accepts only the genuine, host-owned
  `ToolCallGuard` and `ControlledSWEWorkspace`, backed by the exact
  `DockerCommandBackend`. The native execution must have joined, the guard
  must be closed and drained, no unknown tool surface may be present, and
  no external supervisor may be silently bypassed.
- `practical_acceptance.py`: Runtime-owned Handoff builder. Binds
  node/execution/attempt/provider identity, version, host-observed complete
  change evidence and independent canonical receipt. It requires a real
  observed mutation, stable snapshot, valid persisted evidence and uncapped
  native completion. It does **not** adopt Agent prose as acceptance evidence.
- `mvp_task.py`: opt-in practical `accept` callback passes the existing
  `SchedulerCore.run_claim` contract, rather than directly writing
  `SUCCEEDED` or manufacturing an accepted attempt.
- `developer_entry.py`: constructs practical evidence collector and
  canonical snapshot resolver only when opted in. Strict mode remains
  default for lower-level APIs. `aswe run` defaults to practical and
  exposes `--acceptance-mode strict` for the earlier conservative behavior.
- `dev_workflow.py`: physical Developer Task DAG selects practical mode
  and requires the Coder's **accepted Scheduler Handoff**, not just native
  COMPLETED, before it may dispatch the independent DAG Tester or Repair.
- `reliability.py`: exports `practical_scheduler_handoff` independently
  from `strict_scheduler_acceptance` and from code-verification success.

## Security boundaries deliberately retained

- Fresh `read_file` before modifying existing files; tool and path policy
  remain fail-closed.
- Exact isolated pinned Docker image and network-disabled commands; no
  Docker socket or arbitrary host Bash.
- Workspace write lock is held across native execution, post-snapshot,
  canonical check and Handoff creation.
- Missing or forged guard identity, unsupported tool, pending call,
  uncertain Docker cleanup, stale repo revision or an incomplete snapshot
  must reject Handoff.
- Mutable tool profiles cannot conclude **PROVEN_NONE** merely from a clean
  final Git diff; practical write nodes require an observed complete
  mutation to become accepted.
- Canonical test failure remains a FAILED test, even if Coder handoff was
  accepted; independent DAG Tester, not Coder self-report, owns final
  verification and repair scheduling.
- Strict mode retains the original `EVIDENCE_MUTABLE_SWE_PROFILE_UNATTESTED`
  and independent supervisor semantics.

## Validation

Offline unit tests:
- Real SchedulerCore attempt moves to `SUCCEEDED` and creates persisted,
  evidence-bound `NodeHandoff` after host proof.
- A legitimate Coder change may be handed off even when focused test fails.
- Unclosed guard, active/uncertain Docker resources and no evidence remain
  fail-closed; strict mode still quarantines the old unsupported profile.
- Outer DAG Tester cannot proceed on native completion without Handoff.

Physical frozen-vendor CI:
- An actual installed DeerFlow Graph/ToolNode runs the offline model's
  read-edit cycle and host-owned pinned-Docker canonical regression, then
  Scheduler accepts the practical Handoff. No model API key or upstream
  hosted inference is involved.

Remaining acceptance before declaring the full Step 7C-C closed:
- Run at least one **genuine** non-mocked upstream Issue under practical
  mode, confirm Coder Handoff -> independent Tester -> final verdict, and
  preserve exact trace/evidence.
- Then exercise a failed independent test that schedules an autonomous
  Repair, with a new accepted Handoff on the follow-up round.
- Keep the physical native and Python 3.11/3.13 tests green; do not infer
  general reliability from two distinct upstream Issues.

## Controlled live issue regression

A one-time, branch-only paid E2E validates that the *unmodified genuine*
Boltons #553 regression can complete through actual Scheduler-accepted Coder
Handoff and independent DAG Tester. The result is never substituted with
synthetic test output. Remove the temporary paid push workflow before PR merge.

## Initial genuine Issue #553 failure

The first controlled live run
https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38124840713
finished with a specific PracticalAcceptanceDenied that the old acceptance
harness flattened into its exception class. Unit CI and physical pinned native
tests passed; no claims of end-to-end practical acceptance are made.

The second run preserves the stable trusted rejection code and an additional
redacted child execution summary so that follow-up work can address the
observed predicate rather than blindly loosening the gate.

## Git-visible attribution correction and third real task acceptance

Real LLM boltons #553 on run #38125118901 executed 23 model turns,
24 successful guarded tool calls and passed the child canonical test,
but the new handoff rejected PRACTICAL_MUTATION_UNATTESTED. The filesystem
scanner marks ignored generated caches as incomplete, correctly preventing
a claim of *total* historical side-effect coverage, but this also masked
the independent Git-observed source patch.

Practical now attests only actual non-empty Git-visible source changes using
the complete repository delta and host-persisted post-repository fingerprint.
The handoff includes the changed repository paths and explicitly flags
filesystem-history incompleteness where relevant. A reverted/no-delta write
cannot be passed as a source patch. Strict mode remains unchanged.

Next genuine model run MUST demonstrate acceptance in the Scheduler and
the downstream independent Tester, or it remains a failed end-to-end case.
