# Natural #565 terminal regression (Step 7D-B)

- Frozen Runtime baseline: `6886d81bb35bc01ab680add8e34232d2f617546d`.
- Frozen upstream boltons SHA: `4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d`.
- True public Issue: https://github.com/mahmoud/boltons/issues/565
- Reference natural **failure**: https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38128598465
- Identical independent regression suite as staged #565 case, but unlike the
  staged task, this first Coder is given the entire genuine Issue scope.
- No scripted patch, fake model, model reply injection, changed acceptance
  tests or Runtime terminal bypass. Repair budget unchanged.
- Stop successfully only if native `completed` with no cap, child Practical
  Handoff accepted, independent DAG Tester passed and source/test provenance
  retained. Else report natural failure honestly.
- This is a **repeat of the same Issue ID**, so it is NOT another distinct
  Issue for the Step 7D 4/5 initial smoke survey.
- Delete the one-shot paid push trigger after the run.

## Actual live result: failure, native timeout

[GitHub Actions run #38194620421](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38194620421)
used an actual LLM, frozen upstream source and the complete host-owned
regression suite (no staging instruction).

- Original independent regression baseline: **failed** (valid reproduction).
- Native execution: **timed_out**, `native_stop_reason=null`. This is a
  different observed failure from the earlier natural #565 `turn_capped`;
  **neither is successful completion**.
- 20 real model turns, 25 guarded tools, of which 17 `bash`, 5
  `read_file`, 3 `str_replace`; one actual
  `SWE_READ_BEFORE_WRITE_REQUIRED` denied call.
- Provider reported 307,164 input + 16,614 output = **323,778 tokens**.
  First-to-last input tokens grew from **1,080** to **25,131**.
- Source was modified and host-owned tests/original upstream were untouched,
  but there was **NO** accepted Coder Handoff, `scheduler_node_status=failed`,
  `dag_tester_results=[]`, `repair_rounds=0`, and final workflow
  verdict `unverified`. No post-hoc patch success is inferred.
- The report's redacted error code is
  `EVAL_CODER_HANDOFF_NOT_ACCEPTED`; the causal failure is the host-observed
  Native `timed_out`, not an independent Tester verdict.
- Temporary paid workflow push trigger was deleted after this experiment.

**Conclusion:** Step 7D-A improved observed #524 efficiency and maintained
valid independent acceptance, but natural #565 reliability has NOT been
resolved. Do not merge a blanket max-turn / timeout inflation or accept
uncapped claims here. The next issue-specific efficiency investigation
should examine repeated model-selected Bash calls and long-context growth.
This rerun is the **same distinct Issue ID** and does not raise the sample
size of the original five-Issue survey.
