# Coding Step 5E-B — Frozen DeerFlow Physical Integration Audit

Date: 2026-10-09  
PR: #7 (`coding/step5-deerflow-adapter`, Draft/Open)  
Upstream source: `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891`  
**Verdict: Scoped GO — installed, source-pinned, offline native execution PoC. NOT full Step 5/production GO.**

## Physical execution proof

New GitHub Actions workflow: `.github/workflows/deerflow-pinned-native.yml`.

- Checks out the exact upstream commit as a separate nested Git checkout, explicitly verifies `git rev-parse HEAD` and clean tracked source.
- Installs real `deerflow-harness` from that checkout in editable mode with Python **3.12**, including its declared dependencies, plus the local A-SWE package.
- Does **not** run native integration under unsupported Core-only Python 3.11 or 3.13 CI. Those lanes now intentionally exclude `tests/integration` while preserving their existing Core coverage.
- Imports the actual upstream `SubagentExecutor`, `AppConfig`, `SubagentConfig`, `LoadedExtensions`, `AuthorizationProvider` data contract, `RbacAuthorizationProvider`, LangChain `create_agent`, and compiled LangGraph `ToolNode`.
- Native assembly uses `NativeSubagentAssembler.from_deerflow()`; its `create_chat_model` seam is overridden by a local `BaseChatModel` that returns synthetic tool-calls. **No real model API credentials, external model requests or credentialed resources were accessed.**
- Uses actual `_build_initial_state` and `_create_agent` on a restrictive subclass; verifies the compiled `ToolNode.tools_by_name` contains the **same tool object** as the bound `BoundToolView`.
- Actually streams a LangGraph model -> `read_file` (strictly a harmless synthetic fixture, no file I/O) -> model completion. The 5D LangChain Middleware/ToolCallGuard checks run/execution identity and authorizes the native `ToolCallRequest`.
- Puts a foreign same-name tool into the real graph constructor and proves compiled-ToolNode identity guard rejects it before streaming.
- Builds real native `Principal` / `AuthzRequest` / `RbacAuthorizationProvider`: permit and deny paths exercised; denied tools never enter the synthetic handler. No claim that a real external AuthorizationProvider has been tested.
- Verifies revocation denies subsequent native graph execution.
- **Runs the frozen native `SubagentExecutor._aexecute()` path itself**, including capacity admission, compiled graph streaming and terminal `SubagentStatus.COMPLETED` without a network model.
- **Known compatibility correction:** native `_aexecute` passes its captured `LoadedExtensions` instance into `_create_agent`; test fixture now pins the actual generation rather than bypassing the identity check with `None`.

Physical test evidence: `tests/integration/test_deerflow_pinned_native_step5eb.py`, **6 PASS** in installed vendor CI for commit `fea71289b6c3974e0323f96b9a909ddcd8e2e8ac`, GitHub Actions run `37913740074`. Latest HEAD CI must also be green before changing checkpoint status.

## Distinguish the three proof levels

1. **Core deterministic** (5A–5D + 5E-A): verified independently under Python 3.11 and 3.13, fake native interfaces.
2. **Actual frozen package** (5E-B): vendor commit checked out and installed, actual LangChain/LangGraph graph, native execution and RBAC protocol with an offline, in-memory model and synthetic read tool.
3. **Real external credentials / production-like task execution**: **NOT PROVEN** — no API credentials supplied, no provider HTTP call, no actual repo sandbox mutation, no real Sandbox process/lease quiescence proof and no complete Core Scheduler → native permissioned task running a real model.

## Remaining P0/5F–5G entry blockers

- Real remote model API and external AuthorizationProvider with host-derived identity and *single-instance binding* need a separately authorized live preflight/PoC. The physical RBAC test constructs a concrete built-in provider in its test boundary, rather than exercising a deployed external provider.
- Native `NativeDeerFlowExecutionBackend` has a separate deterministic Scheduler-driven harness; the installed-vendor tests do not yet cover its **full** Scheduler/Workspace/real tool execution in one trusted run.
- A native `COMPLETED` result is **not** a quiescence proof: background tool children, sandbox leases/processes and cancellation-safe teardown require independent 5F attestation. All native backend records intentionally set `quiescent=False` and `mutation_evidence="unknown"`.
- No WRITE/Bash/str_replace, configured path constraints, Skill activation, MCP promotion, tool-search, plugin/extension declarations or unverified tool side effects may be enabled. Additional native middleware/safety behavior removed by restricted subclass requires future controlled reintroduction.
- Real dependency versions are resolved at CI install time from the pinned harness manifest; the checkout **source commit** is frozen, but the environment is not fully locked to the vendor's `uv.lock`. The eventual released image should use a lockfile/immutable provenance and supply-chain audit.
- The real graph physical tests use host-constructed synthetic `NodeExecutionBinding` resources rather than a deployed physical 5C/5D/Runtime-assembled binding. Do not elevate this scoped integration success into the complete runtime proof.
- PR #7 remains Draft/Open; Step 5 **not closed**, merge forbidden pending downstream gates.

## Recommendation

Declare **5E-B installed/offline physical integration Scoped GO**, then implement Step 5F trusted execution result/evidence, Workspace diff and sandbox process/lease quiescence. Keep genuine model/AuthorizationProvider credentialed preflight as a final explicit go/no-go test, never a hidden fixture or an assertion from mock results.
