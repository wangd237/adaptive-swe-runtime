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
