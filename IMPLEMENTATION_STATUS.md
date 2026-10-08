# Implementation Status

## Current phase

```text
Coding Step 0 — IN PROGRESS
```

## Completed in bootstrap

- [x] Python package skeleton (`src/aswe`)
- [x] `AGENTS.md` coding constraints
- [x] frozen design snapshot copied into repository
- [x] safe runtime ID helpers
- [x] canonical SHA-256 fingerprint helper
- [x] `RuntimeBudgetConfig`
- [x] shared Workspace/Evidence/Handoff contracts
- [x] `TaskNode / VerificationRepairBinding / TaskDAG`
- [x] `NodeExecutionPreparation / NodeExecutionInvocation`
- [x] deterministic `FakeExecutionBackend` harness
- [x] architecture conformance bootstrap tests
- [x] GitHub Actions CI

## Still required before Coding Step 0 exit

- [ ] implement/confirm remaining Step-0 shared contracts needed by Step 1
- [ ] convert POC-F01 ~ F06 into complete executable conformance coverage
- [ ] review first implementation against frozen Specs before starting Step 1

## Explicitly not started

- Workspace/Git substrate
- Scheduler
- Planning compiler
- DeerFlow integration
- LLM / prompts / Skills
