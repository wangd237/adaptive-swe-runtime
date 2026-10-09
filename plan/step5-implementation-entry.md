# Coding Step 5 — DeerFlow Execution Adapter Implementation Entry

**Status:** IN PROGRESS — 5A Inventory Identity and 5B Model-only Reasoning Adapter coded on `coding/step5-deerflow-adapter`. **Real shared mutable Workspace DeerFlow execution: NO-GO.** This entry preserves the pre-existing P0 Design Freeze; it grants no release waiver.

## Baseline and installation contract

- A-SWE Core accepted on `main` after PR #6, merge `e60491c4d34e69e387d6ac48d95b23e6afbe9134`.
- Frozen *DeerFlow implementation source* `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891` (2026-10-05); **do not silently follow main**. The working source MUST be the correct HEAD with a clean tracked `deerflow` harness package path; unpinned/wheel-only source cannot assert this contract.
- Its `backend/packages/harness/pyproject.toml` requires **Python >=3.12**, while A-SWE Core supports >=3.11. Keep base CI Python 3.11/3.13; actual import/DeerFlow integration lane MUST use Python 3.12/3.13 with the frozen checkout and its compatible dependencies, not assume Python 3.11 supports DeerFlow.
- `src/aswe/integrations/deerflow/` is the **only** DeerFlow-coupled Python namespace. No Scheduler/Planning imports of `deerflow`.
- No LLM/API key or network credentials are needed for 5A's deterministic contract tests. Real assembly/LLM smoke cannot pass until the pinned DeerFlow environment is installed and tested separately.

## Source entrypoints verified at the frozen commit

| Frozen source | Contract verified / use |
|---|---|
| `backend/packages/harness/deerflow/config/app_config.py` | `AppConfig.tools: list[ToolConfig]`, `models`, `sandbox` |
| `backend/packages/harness/deerflow/tools/tools.py` | `get_available_tools(..., app_config, include_mcp=False)` resolves `cfg.use` then deduplicates by *loaded Tool.name*; configurable name alone isn't identity |
| `backend/packages/harness/deerflow/reflection` | `resolve_variable(cfg.use, BaseTool)` is the implementation reference for config-loaded core tools |
| `backend/packages/harness/deerflow/subagents/registry.py` | `get_subagent_config(agent_type,app_config=...)` proves requested Agent type available |
| `backend/packages/harness/deerflow/subagents/config.py` | Resolved model / tools / disallowed / skills / timeout / max_turns, needed for 5B |
| `backend/packages/harness/deerflow/subagents/executor.py` | snapshot-scoped execution, tools, `_harvest_bash_executions`, cancellation/quiescence and result mapping in 5C+ |
| `backend/packages/harness/deerflow/sandbox/sandbox.py` | trusted Sandbox `persistent_shell_sessions` semantics; `None` cannot prove native tests_passed |

## 5A delivered (bounded inventory only)

1. Distinct `FakeBackend` identities (`config:read_file`) and **real DeerFlow** identities (`config:deerflow.sandbox.tools:read_file_tool`). Real effects are only trusted when config `ToolConfig.use`, routed exposed name, loaded tool object/callable, eager delivery and implementation effects align.
2. Candidate BackendInventory from **actual DeerFlow AppConfig + tool assembly output**, plus confirmed Subagent registry types. Same-name other config/plugin cannot prove READ. Missing/disallowed host bash does not appear as enabled.
3. Sandbox feature classification uses the passed **observed Sandbox** value `persistent_shell_sessions`: False enables `fresh_shell_per_command` and `deerflow_tests_passed_evidence`; True or None do not.
4. Identity fingerprints exclude observational `captured_at`; identical deployment sampled at two times does not falsely trigger `BACKEND_DRIFT_OBSERVED`.
5. On actual adapter import, fail closed for missing DeerFlow dependency, mismatched source Git HEAD, edited tracked harness source, or unknown requested Subagent type. **Git HEAD check occurs after module imports and is a compatibility tripwire, not a sandbox/security trust root.** Deployment still needs pinned dependencies and isolation.
6. Dedicated tests `tests/unit/test_deerflow_inventory_step5a.py` exercise 10+ deterministic positive/negative scenarios through exact API-shaped stubs. They are **not** live installed DeerFlow conformance tests.

## Coding sequence / next unimplemented checkpoints

| Sequence | What remains | Stop/go evidence |
|---|---|---|
| 5B | **CORE CODED / DETERMINISTIC TESTS PASS** — `DeerFlowReasoningBackend` / `ModelInvoker`, source-pinned model factory + live model-use auth | Exact role/name, no fallback/tool binding, JSON Schema strict output, timeout/cancel. **Real installed DeerFlow/LLM smoke pending**; not a production Go grant |
| 5C | `NodeExecutionPreparation` / immutable AppConfig + SubagentConfig + Tool + Extension snapshot, `ExecutionContractBinding` | precommit no execution ID; exact pinned resources reused at `execute_prepared`; no post-prepare config rescan |
| 5D | `NodeExecutionBindingStore`, Node tool-policy middleware and ToolCallGuard | required/effective/infra tools survive every model call, forbidden cannot leak; policy store miss fails closed in managed run; ordinary run pass-through |
| 5E | SubagentExecutor typed result mapping, quiescence, cancellation join / cleanup | no retry without independent quiescence; managed cancellation storage cleanup; proper dirty fail-close and Workspace read/write boundary |
| 5F | Canonical command receipt/evidence, review direct-return, AssemblyAttestation, fresh shell | test Bash receipts with `shell_persistent=False` and exact command policy; no model self-report promoted as authoritative |
| 5G | Actual DeerFlow integration Go/No-Go | Frozen POC-02/03/05/09, R34/35/36/38/50/51/69/70/73 and relevant P0-5 cases proven on exact pinned deployment |

No fork until a frozen requirement is proven impossible via the pinned public extension seam. No shared mutable Workspace/Writer execution is enabled for DeerFlow merely because its catalog was observed.

## POC disposition

`audits/step5-gate-audit.md` tracks exactly what 5A proves and what remains pending. **All real DeerFlow integration Go/No-Go tests still remain unpassed at this point.**

Reference: `plan/master-plan.md` Step 5, `audits/deerflow-source-audit.md` and immutable `tests/poc-matrix.md`.


## Step 5B model-only reasoning checkpoint (2026-10-09)

- `src/aswe/integrations/deerflow/model_invoker.py` implements Core's authoritative `ReasoningBackend.generate_structured` protocol without duplicating TaskSpec/WorkPlanProposal schemas.
- `ModelInvoker.from_deerflow()` lazily resolves *pinned source* `deerflow.models.create_chat_model(name, app_config, thinking_enabled=False, attach_tracing=False)`, LangChain System/HumanMessages, current config and current AuthorizationProvider. No default-model fallback.
- Runtime/operator-owned `role_models` selects an explicit configured model, not the LLM response or raw TaskRequest. Config ModelConfig digest rechecked after model-use AuthorizationProvider preflight; changed model/use/settings/auth config refuses call.
- Auth enabled: require trusted principal; provider `filter_resources(principal,"model",[name])` and fresh `AuthzRequest(resource="model", action="use", target=name)` both allow. Denial/provider failure fails closed, without logging credentials. Disabled auth follows trusted AppConfig setting.
- Only one JSON object per result, strictly validated with `Draft202012Validator`; reject duplicate keys, NaN/Infinity/overflows, wrong root type, unwanted schema fields, tool-call outputs. JSON Schema may reference only local `#/` definitions; external `$ref` and `$id` forbidden, size bounded.
- Invocation has fixed duration budget, cancellation propagates, model errors become typed `ModelInvocationError` with sanitized codes. Metrics are informational only; no model prose or emitted candidate earns execution authority.
- `tests/unit/test_deerflow_reasoning_step5b.py` exercises model API-shaped mocks, live model-use auth denial, reasoner/analyzer/validator crossover and no silent fallback. This does **not** prove actual remote model API availability/authorization or end-to-end DeerFlow Subagent operation.
- Independent review: `audits/step5b-model-invocation-review.md`. The next required implementation checkpoint is **5C immutable preparation + AppConfig/Tool/Model/Extensions pinning**.
