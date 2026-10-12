# Step 7D-E3 — Paired genuine real-LLM validation (#524 / #565)

Date: 2026-10-12 (UTC). Source run: https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38216766755

## Frozen comparison
- OLD: `2a64d8a20ce54cc605c17b6d5153ab3a1aef6ee6` (before E1/E2)
- NEW: `40f6c8afd95fa8d2261e330b7e7315a1706137bc` (E1/E2 merged)
- Frozen upstream Boltons: `4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d`
- Frozen DeerFlow: `c0895d295bba34f6e95188fca380f555dabed891`
- Both same configured model SHA256: `7d963f65d1ede1bd9416a5f55575efe0d202e0a00519ef04e47dae20c3180445`.
- Same Docker digest: `python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1`
- Host test SHA256 #524 `674b16eecc87a5bdc13cd4c35d892c4a3d16f009105de1425025be4ab68491b9`; #565 `801b00af9506ced0fcad06aed25107d4228c9a6e150ad6dd2f726ab393ae7c93`.
- Each job: original full natural issue task, no staged specification or prepared patch, real LLM, failing host-owned baseline, fixed native logical turns (24), normal physical cap/timeout, `max_repairs=1`, unchanged canonical independent Tester/Handoff gates.
- `scripts/step7de3_post_test_probe.py` is evaluation-only and applies the SAME tool observer in both versions without modifying messages, statuses, prompts, scheduling or independent Tester. It never reuses or skips tools.

## Corrected-run evidence

| Metric | #524 OLD | #524 NEW | #565 OLD | #565 NEW |
|---|---:|---:|---:|---:|
| Valid overall verdict | **PASS** | **PASS** | **FAIL** | **FAIL** |
| Model turns | 19 | 19 | 24 | 15 |
| Tool calls | 28 | 29 | 25 | 24 |
| Bash calls | 25 | 26 | 15 | 20 |
| Provider-reported total tokens | 222,271 | 260,162 | 352,373 | 183,853 |
| Peak provider input tokens/turn | 19,994 | 25,280 | 22,035 | 22,386 |
| Native final state | completed | completed | failed | timed_out |
| Native cap reason | none | none | turn_capped | none (timeout) |
| Practical Scheduler Handoff | accepted | accepted | absent | absent |
| Independent DAG Tester | passed | passed | not run | not run |
| Repair rounds | 0 | 0 | 0 | 0 |
| Recorded simple test-like commands (shared proxy) | 0 | 0 | 0 | 0 |
| Post-recognized-pass non-test Bash (proxy) | 0* | 0* | 0* | 0* |

\* **No recognized passing-test denominator in any of these runs:** zero proxy post-test counts MUST NOT be interpreted as zero wasted exploration. The model chose mostly compound shell commands, deliberately classified as `other` in the conservative old/new shared proxy. No raw Bash content is retained in evidence. To resolve this question rigorously, record a bounded, audited post-test event timeline with command-level safe semantics beyond only *simple* Bash, or make the model use focused standalone test calls, without changing acceptance authority.

Artifacts: `step7de3-old-524-evidence`, `step7de3-new-524-evidence`, `step7de3-old-565-evidence`, `step7de3-new-565-evidence` on source run. These capture all failures and successes.

## Answers

1. **Did E1/E2 genuinely reduce pointless post-test exploration?** **NOT PROVEN.** Observed whole-run #524 did not improve: same 19 turns, +1 Bash, +37,891 total tokens (+17.0%). #565 +5 Bash with fewer turns and total tokens but failed delivery. Proxy did not observe recognized passing tests in any case. Do not claim that zero proxy post-pass activity means improvement.
2. **Does natural #565 finish within original budget with accepted Handoff and independent Tester pass?** **NO.** New failed native `timed_out` after 15 turns, 24 tools, 183,853 total tokens. No Handoff or Tester dispatch. Old failed at `turn_capped` after 24 turns. Neither counts as accepted delivery.

## Important methodological limits
- One non-deterministic real-model run per cell, not randomized repeated estimation. Same configured model fingerprint and Docker digest do not establish identical server-side model version or stochastic trajectory.
- Provider-reported tokens are not equivalent to billing or guaranteed dollar savings; especially do not claim that fewer tokens on a **failed** issue is better SWE efficiency.
- Agent-local test observations do not replace the independent Tester.
- The first attempt at https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38216492002 is excluded: its observer wrapper accidentally changed `read_file`'s keyword-only argument schema, causing `TypeError`. The corrected wrapper preserves that signature; ONLY the corrected-run evidence is used above.
- The once-only paid push workflow is deleted as part of this evaluation branch before any merge. Retain the permanent user-authorized, typed-`RUN` workflow.

## Gate decision
**Step 7D-E3 execution completed; requested validation did NOT pass.** #524 functional correctness preserved, no demonstrated post-test efficiency benefit; #565 unresolved. Do not raise token/turn budgets, force native success, synthesize Handoff or weaken independent Tester. Next diagnostic step should focus on compound Bash patterns and #565's post-edit verification and completion trajectory with trustworthy low-noise event instrumentation.
