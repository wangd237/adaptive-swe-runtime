# Step 7D-A — Efficiency / Terminal-Behavior Optimization

Base: `main` `e4573042cb3876d3dfbf0ecf9b9b887006e0a569`.
Frozen vendor remains unchanged:
`c0895d295bba34f6e95188fca380f555dabed891`.

## Observed problems and causal hypotheses

1. Genuine natural Boltons #524 completed and passed, but used 400,654
   provider-reported tokens (379,787 input + 20,867 output) over 22
   native model turns and 38 guarded tools; repeated command-output
   context may contribute to prompt growth. This is a hypothesis, not a
   confirmed root cause; a model's output and prompt caching can also vary.
2. Natural Boltons #565 hit `turn_capped` despite a post-run
   **diagnostic-only** test pass. Handoff correctly remained refused;
   do not conflate diagnostic tests with accepted execution.

## Bounded changes

- `ControlledSWEWorkspace.bash` now supplies **4,000 bytes** of command
  output to the model by default instead of up to **12,000 bytes**, while
  keeping file-reading output at 12,000 characters for source inspection.
- Docker stdout capture is still a secure unlinked temporary file and the
  SHA-256 digest still covers the *entire* original output. When truncated,
  show a small beginning and a larger end (where failed-test assertions are
  generally printed) with an explicit truncation marker and stable host
  observation status.
- The first `exit_code=...; timed_out=...\n` line stays **byte-compatible**
  with ToolGuard's parser for agent-observed tests and RepairFeedback.
  `output_truncated` is a second line, not a change to that receipt.
- Developer Coder system guidance emphasizes targeted reads, relevant
  checks, avoiding unnecessary repeated tool calls, and ending with a real
  final response after evidence is sufficient. **No artificial completed
  status, automatic acceptance, budget inflation, or safety relaxation.**
- The redacted `aswe.reliability.v1` view now includes numeric
  per-model-turn input/output usage tails, peak/first/last input tokens and
  whitelisted tool category counts. There is no raw prompt, path, output,
  model text, credential or invented monetary cost.

## Deterministic and physical acceptance gates

- Python 3.11 / 3.13 unit CI.
- Pinned DeerFlow native integration with actual Docker; ensure the
  multi-file failed tool test still records agent-test feedback after
  the exact first-line receipt remains unchanged.
- Physical Docker long-output test verifies bounded data, preserved
  beginning AND failure tail, full-output digest and lifecycle drain.
- Fail-closed Practical/Strict Scheduler and independent Tester behavior
  remain unchanged.

## Real-model A/B with Issue #524

Control: [original natural #524 run](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38129653670)
had 22 turns, 38 tools, 400,654 tokens, accepted Coder Handoff and
independent Tester passed.

Experimental run: same upstream SHA, model secret configuration, image pin
mechanism, adaptive planning and host-owned regression; Step 7D code changes
above. Even if its tokens fall, **one stochastic run does not prove a general
saving**. Record both tokens and correctness; any independent Tester failure
invalidates the optimization as a delivery improvement.

The temporary paid push-triggered workflow is deleted after the experiment.
Permanent evaluation remains manual typed `RUN` only.

## Actual genuine Issue #524 A/B observation

Experimental GitHub Actions:
[Step 7D #524 run #38194147927](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38194147927).
Reported artifact: `aswe-step7d-issue-524-evidence` (GitHub Actions ID
`11722827019`). Exact code under test was from this branch SHA
`5a22109ab94e3adf4cd4db25a1681c9f83832f0e`; the later output-limit
compatibility adjustment affects only non-default small-output profiles and
was separately tested.

| Measure | Earlier natural #524 | Optimized natural #524 |
| --- | ---: | ---: |
| Provider-reported total tokens | 400,654 | **163,623** |
| Input tokens | 379,787 | **150,918** |
| Output tokens | 20,867 | **12,705** |
| Model turns | 22 | **16** |
| Guarded tool calls | 38 | **26** |
| Accepted Practical Handoff | yes | yes |
| Independent Tester | passed | passed |
| Native stop cap | none | none |
| Repair | 0 | 0 |

**One observed reduction of 237,031 total tokens (~59.2%),** six fewer
model turns and twelve fewer tools, while preserving the accepted result.
This comparison is not causally isolated: model stochasticity, per-run
provider behavior and different Coder instructions are not controlled
separately. No claim of a stable 59% improvement should be made without
repeated matched trials. It is nevertheless a concrete regression check
that the output compaction has not prevented actual model success.

The optimized redacted trace also reports:

- 16 provider-reported model turns, input tokens per turn from **850** to
  **19,645** (max 19,645). The remaining context growth is significant.
- 26 tools = **22 Bash**, 3 `read_file`, 1 `str_replace`. Next iteration
  should investigate redundant shell commands, not blindly increase turns.
- Original independent host-owned suite failed at baseline, production code
  changed, host tests and original upstream unchanged, Coder Scheduler
  `succeeded`, DAG Tester `passed`, no fake native completion.

## Remaining Step 7D work (not yet proven)

- Re-execute the **natural** full-spec Issue #565 on this Runtime. The
  earlier failure was `turn_capped`; the improved prompt is intended to
  encourage normal completion, but no new natural #565 result is currently
  available. Never mark it fixed solely from this Issue #524 success.
- Analyze 22 Bash invocations in the #524 optimized run with privacy-safe
  categories (e.g. read-only searching versus test execution). Do not
  store raw shell commands or expose secrets just for analytics.
- Run multiple matched A/B trials before inferring a general improvement
  rate; report failures and repeated attempts alongside successes.

Temporary paid push workflows have been removed. Durable live survey
workflow in main continues to require manual `workflow_dispatch` and
explicit `RUN`.
