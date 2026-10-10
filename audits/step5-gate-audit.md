# Step 5A — Pinned DeerFlow Inventory Source Audit

**Date:** 2026-10-09. **Decision: GO for isolated 5A inventory-source adapter development; NO-GO for any real DeerFlow shared mutable Workspace execution.**

## Source audit

Pinned upstream `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891` was read at commit, not main. Actual `AppConfig.tools`, `ToolConfig.use`, `get_available_tools` eager config tool resolution and first name dedup, `get_subagent_config(app_config=...)`, `Sandbox.persistent_shell_sessions` semantics verified. Frozen config.example.yaml lists:

```text
ls          -> deerflow.sandbox.tools:ls_tool
read_file   -> deerflow.sandbox.tools:read_file_tool
glob        -> deerflow.sandbox.tools:glob_tool
grep        -> deerflow.sandbox.tools:grep_tool
write_file  -> deerflow.sandbox.tools:write_file_tool
str_replace -> deerflow.sandbox.tools:str_replace_tool
bash        -> deerflow.sandbox.tools:bash_tool
```

**Correctness fix from Step 4:** P1 FakeInventory identities (`config:read_file`) were never real `ToolConfig.use` identifiers. Core now has source-discriminated fake vs actual DeerFlow effect matching. A `fake-config` tool renamed to `deerflow-config` cannot pass as READ, nor can a same-name function/tool object from a different implementation be promoted. Description-only `write_file` clones are permitted only if the actual function identity is preserved.

**Drift correction:** `captured_at` is observation metadata, not semantic inventory content. The fingerprint excludes only this field; tool identities/config/model/sandbox evidence still participate. This prevents synthetic drift caused by sampling time alone.

**Source verification:** actual import entry rejects unavailable dependency, unpinned Git HEAD and modified tracked harness code. This is a compatibility assertion *after* import; it is NOT cryptographically authenticating arbitrary Python imports and MUST NOT be presented as a complete security sandbox.

**Fresh-shell evidence:** observed `persistent_shell_sessions=False` is necessary for load-bearing native `tests_passed`; AIO true / unknown None are rejected. This does NOT prove actual per-attempt `bash_executions` receipt semantics or the correct sandbox instance until 5C/5F.

## CI evidence and honest limitations

The new tests cover actual source-shaped method contracts via deterministic stubs, not an installed/pinned DeerFlow runtime. Core unit suite is dual 3.11/3.13; pinned DeerFlow itself requires Python >=3.12 and will need a dedicated 3.12/3.13 live assembly lane.

Go/No-Go **all still pending** for actual DeerFlow: POC-02/03/05/09, POC-R34/R35/R36/R38/R50/R51/R69/R70/R73. Do NOT count the Stage-4 FakeBackend P0-5 PASS results as actual provider evidence.

### Required next actual integration negative checks

- actual `get_available_tools()` returns filtered tools from pinned `AppConfig` after host Bash deny; `config bash` declaration alone grants nothing;
- same-exposed-name config/extension collision, wrong `ToolConfig.use`, changed schema, dynamic extensions, tool search and skill authorization;
- precommit live Deployment drift triggers no Attempt and no Sandbox effect; irrelevant drift records reason but continues;
- two-stage `prepare_node`→`execute_prepared` uses the same AppConfig/tools/SubagentConfig/LoadedExtensions snapshot;
- tool-call policy, review direct-return, causal receipts, cancel/quiescence and fresh-shell proof.

### Freeze boundary

No frozen spec or `tests/poc-matrix.md` changed. No model or external service called. No DeerFlow fork. No PR merge or Step 5 closure authorized by 5A.


## Step 5B source-bound reasoning substage

The added `model_invoker.py` is independently reviewed in [Step 5B model invocation audit](step5b-model-invocation-review.md). Its structured TaskAnalyzer / SemanticPlanner boundary and model authorization API-shaped tests are deterministic; actual installed DeerFlow/model/identity integration and all Step-5 production Go/No-Go scenarios remain pending. A model-only request never allocates Scheduler execution attempts or tool permissions.
