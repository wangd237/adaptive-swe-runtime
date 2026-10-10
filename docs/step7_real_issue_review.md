# Step 7 — Real-World SWE Capability Review

## Goal

Stop expanding Runtime infrastructure. Verify whether the current adaptive
SWE developer workflow can solve an **existing public issue in an unfamiliar
upstream repository**, not a manufactured project or mock-model test.

## Trial 7A-1: boltons Issue #500

- Public repository: https://github.com/mahmoud/boltons
- Actual open issue: https://github.com/mahmoud/boltons/issues/500
- Immutable base SHA: `4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d`
- Real defect: a monthly `daterange` from the 29th–31st can raise
  `ValueError: day is out of range for month`.
- Behavior decision for THIS acceptance only: use reporter-suggested Option
  1 (clamp to last valid day and allow subsequent month-day drift), including
  negative monthly increments. The upstream maintainer has not approved
  this as the official semantics. This is an evaluation choice, not a PR.

The Actions runner clones upstream at the exact SHA, commits **only an
independent host-owned five-case unittest** based on Issue #500, and proves
baseline Docker tests fail before starting the agent. No defective
implementation code is generated, rewritten or seeded. This distinguishes
the test from our earlier purpose-built integration fixtures.

The agent is given the natural-language issue, expected behavior and
repository, **not an edited target file, exact code replacement, reference
patch or fabricated tool response**. Real LLM Planner/Explorer and native
DeerFlow Coder choose exploration, tools and modifications. A separate
Docker Tester executes the independent regression. The original upstream
clone and host-owned test must remain unchanged; production Python code
must change. Both original failure and final verdict are recorded.

This initial smoke is **one real issue**, not 3–5 tasks, a benchmark, a
generality claim or proof of global strict SchedulerCore acceptance. A
failed run is useful Step 7B error analysis; it must not be reported as
a solved issue. Later trials can be selected only after examining this
trace.

## Safe reproducibility

The paid workflow `SWE Step 7 Real Issue E2E` reads existing GitHub
Actions `SWE_LLM_*` Secrets, mapped to the project's user-facing
`LLM_*` environment variables. The initial one-shot branch push gate has been removed. Future runs are
manual-only and require authorization `RUN`.

The workflow retains a redacted JSON artifact describing only:
baseline failure, roles, DAG topology and dispatch, model/tool event
counts, code/test integrity and independently verified result.
No raw provider errors, prompts, credentials, source patches or test
output enter Actions summaries/artifacts.

## Authorized upstream issue acceptance run

An explicit one-time real-model execution is authorized for the fixed
boltons #500 commit and the host-owned reproduction tests above.

## First live trial: advisory Explorer failure

[Run 38052082735](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38052082735)
reproduced the actual upstream bug, compiled the physical DAG, and
started Explorer. The provider's structured Explorer reply was invalid
(`ValidationError`), so the job did not reach Coder.

Step 7B improvement: an invalid *advisory* Explorer payload now has a
clearly marked read-only Git-index fallback, while provider/network
errors are still fatal. This avoids treating malformed LLM advice as a
task execution authority while letting Coder work independently. The
fallback is explicitly reflected in the Trace, not claimed as a
successful LLM diagnosis.

## Second live trial: native Coder terminal failure

[Run 38052351881](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38052351881)
reproduced the upstream bug, selected Explorer/Coder/Tester, compiled and
dispatched the real physical DAG, then reached the DeerFlow Coder. It made
13 real tool-call events and eight native model-turn events, and changed
production source code. However, the native Coder terminal status was
`failed`, with canonical child checks `not_run` and no independent DAG
Tester dispatch. Therefore the Issue remains **unverified and unsolved**
in the acceptance report, even though a patch was attempted.

Step 7B instrumentation now captures stable native delivery and Scheduler
state categories, plus a separate **diagnostic-only** Docker test of the
failed Coder workspace. These checks can distinguish a correct but
unaccepted patch from an actually incorrect patch without changing
the acceptance gate. No raw patch or model output is published.

## Third live trial: confirmed incomplete patch (2026-10-10)

[Run #38052690155](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38052690155)
reproduced the actual public bug, used a real LLM, planned
`Explorer → Coder → Tester`, and dispatched Explorer then Coder.
Coder made changes to the real upstream implementation, but did not
reach native `completed` status, so the DAG Tester was **not**
dispatched. The separate **diagnostic-only** Docker run of the Coder
workspace also **failed**; this is not a falsely rejected correct patch.

| Evidence | Actual result |
|---|---|
| Original upstream bug reproduced | Yes |
| Model / tool mocks | None |
| TaskDAG | Physical DAG compiled |
| Team chosen | Explorer, Coder, Tester |
| Dispatched | Explorer, Coder |
| Coder native status | **failed** |
| Native model turns | 6 |
| Tool events | 9 (8 completed; 1 failed) |
| Dynamic command invocations | 4 |
| Production implementation changed | Yes |
| Agent-level test observation | Observed only |
| Native canonical verifier | Not run |
| Separate diagnostic Docker test | **failed** |
| DAG Tester | **not dispatched** |
| Final verdict | **FAIL / unverified** |

The first and second paid runs are also documented above. This
negative result proves the test is capable of finding actual
execution-level limitations. It does **not** prove successful
completion of real-world Issue #500.

### Prioritized Step 7B engineering follow-up

1. **P0 — Identify the real native failed tool-call category**:
   capture a bounded allowlist of tool name, stable failure code, and
   terminal failure category, never raw model messages or secrets.
2. **P0 — Recoverable native tool errors**: distinguish ordinary
   transient tool-input mistakes from fatal policy/admission errors
   and let the model correct permitted mistakes within its budget.
3. **P0 — Retry the *same pinned Issue* after an actual recovery fix**:
   require passing independent tests; do not simply keep issuing paid
   runs to hope nondeterminism solves it.
4. **P1 — Expand to 2–4 additional diverse public Issues** once the
   first failure mode is understood.

### Security / scope

The paid workflow is now **manual RUN-only**, never push/PR CI.
The original upstream clone was unchanged and the independent test
file was never edited by the agent. No source patches, prompts, API
keys, raw test output or provider credentials are uploaded.
The supported top-level Scheduler remains the developer orchestrator,
not strict globally ACCEPTED multi-node SchedulerCore.
