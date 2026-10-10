# Step 6G: Unified Developer Scheduling and Real Repair Acceptance

The Adaptive physical TaskDAG now has a single top-level developer controller
for dependency readiness, node attempts, canonical verification, and repair
budget. The native DeerFlow Coder still uses its internal strict
`SchedulerCore` and does **not** claim global strict multi-node acceptance.
This is a Developer MVP, not a production quiescence proof.

Repair diagnostics are now delivered from the **independently dispatched
Docker Tester** directly into the next real Coder model prompt, bounded and
redacted. The raw failure output does not enter the public Trace/report;
only its SHA-256 and byte length do.

## Real model repair acceptance

An explicitly paid Actions run uses existing `SWE_LLM_*` Secrets and calls
real LLM Planner, Explorer and native DeerFlow Coder. A controlled two-milestone
cross-module issue first asks for the inventory fix, then a legitimate full
regression suite tests order idempotence, with one authorized Repair attempt.
Unlike previous offline scripted tests, neither Coder pass is scripted; only
the source fixture and trusted canonical test requirements are defined by
the harness.

This is a **controlled staged task**, not proof that an arbitrary real-world
issue will fail on the first attempt and self-repair. The acceptance requires
a genuine first Docker FAIL, a real feedback fingerprint, a second genuine
native LLM edit, a second Docker PASS, and unchanged test sources. If the first
Coder solves everything, that is an ordinary pass but not a Repair acceptance.

The GitHub workflow is restricted to an explicit one-shot staging-branch
push marker for initial acceptance and manual `RUN` thereafter. Temporary
push activation will be removed before merging to `main`.


## First real repair attempt

[Run 38050394522](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38050394522)
observed two genuine native model rounds, a failed then passing
independent Docker check, and two modified implementation modules.
The Actions job still failed because the harness mixed the native tool
guard's `repair.feedback.available` events with the top-level canonical
tester's feedback event, and incorrectly required Explorer even when
the real adaptive planner validly chose a single Coder.

The assertions are now fixed to identify the exact canonical feedback
source and accept a legitimate minimum-sized team. A fresh paid run
will confirm a clean acceptance verdict. The first attempt is reported
as *observed repair behavior*, not a passing acceptance run.
