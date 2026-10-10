# Step 6F — Real LLM Adaptive Workflow Acceptance

Date: 2026-10-10. This is a **real external-model** GitHub Actions
acceptance, not a scripted-model E2E. Secrets were provided by the
repository's existing `SWE_LLM_*` Actions secrets and mapped to `LLM_*`.
No provider key, model transcript, raw code diff or API endpoint is included.

## Final verdict: PASS

Successful run:
https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38042334500

| Observed contract | Result |
|---|---|
| Source fixture | Self-contained disposable Git repository, two actual bugs |
| Initial regression check | Failed as expected |
| Planning role selection | `explorer, coder, tester` |
| Physical TaskDAG | Successfully compiled |
| DAG topological order | `explorer -> coder -> __aswe_verify` |
| Scheduler dispatch order | `explorer -> coder -> __aswe_verify` |
| Explorer | Separate, real read-only LLM call |
| Coder | Frozen pinned DeerFlow, real LLM and tools |
| Native model turns | 8 |
| Native tool calls | 17 |
| Implementation modules changed | `shop/orders.py`, `shop/inventory.py` |
| Independent Docker Tester | Passed |
| Test source files | Unchanged |
| Developer rounds | 1 |
| Repair scheduled | 0, because the first coding round passed |

`adaptive-live-e2e-summary` in the successful Actions run is the
redacted machine-readable evidence. The test originally also recorded
untracked Python `__pycache__` files in `changed_files`, so the
fixture now ignores bytecode in its own `.gitignore`. This cleanup does not
alter or retroactively rerun the successful live acceptance.

## Provider interoperability improvements from actual failures

First run
[38041913650](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38041913650)
failed early with `OpenAIInvalidRequestError` when requesting structured
LLM output from the provider.

Second run
[38042123062](https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38042123062)
compiled the physical DAG and dispatched Explorer but failed on an incomplete
LLM structured response (`ValidationError`).

The final passing run uses a bounded compatibility path:
request native structured output first, then for specifically recognized
schema-rejection / malformed-structure failures try **one** ordinary
JSON-text model response and validate with Pydantic. It never fabricates
missing required fields or silently marks an invalid plan successful.

## Explicit remaining limitations

- This test **does not prove a live Repair attempt**: the Coder passed
  on its first real run. The Repair path has already been verified in
  scripted-native/Docker integration tests.
- The top-level `DeveloperDagScheduler` orchestrates the physical DAG;
  each Coder attempt runs its own strict `SchedulerCore`. This is not a
  globally strictly accepted multi-node `NodeHandoff` task.
- One successful acceptance fixture does not establish general performance
  across real-world GitHub Issues or serve as a benchmark.
- Repeated live runs require manual Actions authorization `RUN`.
