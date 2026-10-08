# Adaptive SWE Runtime

Implementation repository for **Adaptive Agent Runtime for Software Engineering (A-SWE Runtime)**.

> **A-SWE is the control plane. DeerFlow is an execution plane.**

## Current phase

```text
P0 Design: FROZEN
Coding: Step 0 — Core Contracts + Deterministic Test Harness
DeerFlow integration: NOT STARTED / GO-NO-GO GATED
```

This bootstrap intentionally contains **no DeerFlow dependency and no LLM integration**.

## First implementation target

```text
Contracts
→ deterministic IDs / fingerprints
→ Runtime budget config
→ deterministic FakeExecutionBackend
→ architecture conformance tests
```

Then follow the mandatory order in `AGENTS.md`.

## Design authority

Frozen design is copied from `wangd237/adaptive_swe_plan`.
The exact bootstrap pin is recorded in `design/PLAN_SOURCE.md`.

## Tests

```bash
python -m pytest
```
