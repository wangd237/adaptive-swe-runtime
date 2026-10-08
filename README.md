# Adaptive SWE Runtime

Implementation repository for **Adaptive Agent Runtime for Software Engineering (A-SWE Runtime)**.

> **A-SWE is the control plane. DeerFlow is an execution plane.**

## Current phase

P0 Design: FROZEN (DeerFlow integration PoCs pending)
Coding Step 0: CLOSED / ACCEPTED
Coding Step 1: CLOSED / ACCEPTED
Next: Step 2 — Scheduler State Machine on FakeBackend
DeerFlow / LLM integration: NOT STARTED

## Accepted implementation

- Provider-neutral frozen contracts and two-stage deterministic TaskDAG identity (Step 0).
- Local immutable attempt/task EvidenceStore and minimal trace events.
- Git bootstrap to pinned SHA; isolated temporary-index working tree digest and per-attempt patch attribution.
- Workspace snapshots/revision evidence, reader/writer access, quiescence-gated FROZEN vs QUARANTINED lifecycle.

Step 1 reviewed in [PR #2](https://github.com/wangd237/adaptive-swe-runtime/pull/2).
Python 3.11 / 3.13: **84 passed, 0 skipped** on reviewed PR head.

## Architecture and design authority

- [AGENTS.md](AGENTS.md): coding constitution / no silent design drift.
- [Master Plan](plan/master-plan.md): mandatory Coding Step 0–8 order.
- [Frozen Specs](specs/): implementation contracts.
- [Step 0 Review](audits/step0-implementation-review.md) / [Step 1 Review](audits/step1-implementation-review.md).
- [Implementation Status](IMPLEMENTATION_STATUS.md): current progress and next gate.
- Frozen design pin: [PLAN_SOURCE](design/PLAN_SOURCE.md).

## Tests

Install dev requirements and run:

    python -m pip install -e ".[dev]"
    python -m pytest

No DeerFlow dependency or LLM integration has been added.
