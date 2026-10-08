# Adaptive SWE Runtime

Implementation repository for **Adaptive Agent Runtime for Software Engineering (A-SWE Runtime)**.

> **A-SWE is the control plane. DeerFlow is an execution plane.**

## Current phase

```text
P0 Design: FROZEN (integration PoCs remain gated)
Coding Step 0: CLOSED — validated / merged
Next: Step 1 — EvidenceStore + Workspace / Git substrate
DeerFlow integration: NOT STARTED
```

Coding Step 0 was reviewed in [PR #1](https://github.com/wangd237/adaptive-swe-runtime/pull/1).
Python 3.11 and 3.13 CI: **53 passed / 0 skipped** on the reviewed PR head.

## Architecture

```text
Frozen Specs + AGENTS.md
        ↓
Provider-neutral contracts
        ↓
Evidence / Workspace / Git           ← Coding Step 1 (next)
        ↓
Deterministic Scheduler + FakeBackend ← Step 2
        ↓
Planning / Capability / DAG
        ↓
DeerFlow ExecutionBackend adapter     ← later Go/No-Go gated
```

No DeerFlow dependency or LLM has been added.

## Design authority

The frozen design snapshot is copied from `wangd237/adaptive_swe_plan`.
The exact bootstrap pin is recorded in `design/PLAN_SOURCE.md`.
Implementation rules live in `AGENTS.md`; see `audits/step0-implementation-review.md` for Step 0 evidence.

## Tests

```bash
python -m pip install -e ".[dev]"
python -m pytest
```
