# Step 6F Real LLM Adaptive Workflow Acceptance

Purpose: exercise the end-to-end task-adaptive developer implementation
using the connected GitHub Actions secrets, with **no scripted model**.

## Fixture

A self-contained disposable Python Git repository contains two real defects:

- stock release decreases available units instead of restoring them;
- repeat cancellation issues a duplicate refund rather than returning false.

Baseline tests must fail. The model receives a natural-language cross-module
issue, not file edits. The test command is fixed by the host.

## Required observed path

1. Real LLM minimum-team Planner selects Explorer, Coder and Tester.
2. A separate read-only real LLM Explorer reads tracked source excerpts.
3. Native frozen DeerFlow Coder uses tools to edit implementation files.
4. The developer DAG scheduler launches an independent Docker Tester.
5. A real failure can trigger one bounded Repair round; if tests pass on the
   first attempt, this is correctly recorded as repair not needed.
6. End state must be passing Docker tests, both defective modules changed,
   tests unchanged, and a redacted status-only evidence artifact.

This is a **paid, single-run E2E** and is never part of generic push/PR CI.
Its temporary restricted push gate is used only for the first explicit
acceptance run. The permanent workflow must be manual-only after this run.

Historical strict Scheduler quiescence acceptance remains a separate issue;
a passing developer workflow is not an ACCEPTED strict TaskResult.

## Real-model compatibility retest

Provider-side schema rejection is now retried using an ordinary JSON-text
chat response plus Pydantic validation. This does not mock or bypass the LLM.

## Explorer schema-recovery acceptance

The first live Planner selected the full multi-agent topology; the next
model response was incomplete. One bounded JSON fallback now handles
invalid structured responses while preserving strict validation.
