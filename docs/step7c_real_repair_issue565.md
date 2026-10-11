# Step 7C genuine multi-round Repair acceptance: boltons #565

Real upstream issue: https://github.com/mahmoud/boltons/issues/565
Pinned source commit: 4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d
Runtime baseline: Step 7C-C main commit 2361185e4675ba2a451a3598f8e36bd47a865cec

Purpose: attempt a *natural* real-LLM Repair chain on an issue with multiple
regex-flag edge cases. Host-owned regression tests are added to the pinned
original repository before Agent execution and required to fail at baseline.
Planner, Explorer, Coder, Tester, and Repair use normal Runtime operation;
the test harness does not pre-apply patches or synthesize feedback.

**Hard acceptance:** at least one independent Docker Tester failure, an
actually scheduled Repair, at least two actual LLM Coder rounds with accepted
Practical Scheduler Handoffs, and a passing final independent Docker Tester.
If the model solves everything on the first round, classify the run as a
successful issue fix but *Repair unverified*, and do not claim Step 7C Repair
closure. If repeated Repair attempts fail, preserve the error evidence.

The paid workflow uses an exact-branch exact-commit-marker trigger and must
be deleted after the run. Never merge that trigger to main.

## Natural first attempt — no Repair witness

Run: https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38128598465

The first fully specified genuine Issue #565 attempt reached the 24-turn
native budget and returned `turn_capped`. The source code was changed and a
post-Coder diagnostic test passed, but that diagnostic is NOT a Scheduler
handoff or a DAG Tester verdict. The Coder Scheduler status was `failed`,
no Handoff was emitted, no DAG Tester ran, and `repair_scheduled=0`.
Thus no real Repair cycle was demonstrated. This remains a genuine observed
failure, not a result to be overridden by post-run test success.

## Controlled staged-spec test — separate classification

The second run preserves the same actual upstream issue and all ten
host-owned regression tests, with no injected patches or mocked tool calls.
It deliberately **narrows only the first Coder instruction** to precompiled
IGNORECASE, and authorizes later full generalization only upon receipt of
genuine independent Tester failure feedback. The model independently chooses
all code/tools. Label outcomes `staged_specification=true`; do not count
this as a natural first-pass Issue success rate.

Hard acceptance still requires: first Coder normal Handoff, independent
Tester failed, actual Repair scheduled, second genuine model Coder patch
and new accepted Handoff, and independent Tester passed.
