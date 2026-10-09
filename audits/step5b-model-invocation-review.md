# Step 5B — DeerFlowReasoningBackend / ModelInvoker Review

**Status: scoped GO for Core adapter implementation; real provider deployment GO/NO-GO remains OPEN.** Review date: 2026-10-09. PR #7 stays Draft until Step-5 real execution gates pass.

## Source-checked frozen interface

Upstream exact source `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891`:

- `backend/packages/harness/deerflow/models/factory.py`: `create_chat_model(name, thinking_enabled=False, *, app_config=None, attach_tracing=True, model_overrides=None,...)`. 5B requires explicit name/AppConfig, `thinking_enabled=False` and `attach_tracing=False`; never pass unapproved model-overrides.
- `backend/packages/harness/deerflow/config/model_config.py`: real `ModelConfig` fields include `name`, `use`, `model`; pin full JSON-exportable profile fingerprint.
- `backend/packages/harness/deerflow/authz/provider.py`: `AuthzRequest(principal, resource="model", action="use", target=name)`, `AuthorizationProvider.filter_resources` and `aauthorize` used as separate visibility and use permission checks.
- `backend/packages/harness/deerflow/authz/runtime.py`: `resolve_authorization_provider(config.authorization)` called fresh when authorization is enabled. A-SWE still relies on trusted host principal supplier.
- `backend/packages/harness/deerflow/subagents/config.py`: separate Subagent model inheritance and skill policy. 5B intentionally does NOT create subagents or bind tools; Step 5C–5D must integrate these independently.

## Execution and authority flow

```text
Core TaskAnalyzer/SemanticPlanner
        ↓ generate_structured() (non-authoritative proposal)
DeerFlowReasoningBackend  [only implementation of Core ReasoningBackend protocol]
        ↓
ModelInvoker
  -> trusted operator role_model mapping (no implicit first-model fallback)
  -> pinned-source check + copied AppConfig/model profile
  -> current model:use Authz visibility + per-call decision (when enabled)
  -> model profile/auth config drift check
  -> DeerFlow create_chat_model(name, app_config, thinking_enabled=False)
  -> LangChain SystemMessage + HumanMessage, no tools
  -> async ainvoke with timeout/cancel propagation
  -> strict JSON root object + local-only Draft202012 JSON Schema validation
  -> StructuredReasoningResult (deep-frozen model data; usage informational)
        ↓
Core deterministic TaskAnalyzer rule validation / SemanticPlanValidator
        ↓ only validated CompiledTaskContract/ValidatedWorkPlan can authorize
```

## Validated negative cases

- Unknown or model-chosen roles and absent configured profile => `MODEL_ROLE_NOT_CONFIGURED` or `MODEL_CONFIG_UNAVAILABLE` before factory call; no default fallback.
- Invalid/too-large JSON schemas, external/recursive dynamic refs, remote `$id` => pre-model rejection (no schema-driven outbound fetch).
- Model output: Markdown fences, trailing text, duplicate JSON keys, NaN/nonfinite numeric overflow, non-object root, wrong field types, unapproved keys and tool-call responses => typed failure, not acceptance.
- Enabled authorization with untrusted/missing principal, denied `filter_resources`, denied `aauthorize`, provider error => pre-model fail close; configured-model and authorization policy drift => denied.
- Model network/transport failures are sanitized into stable codes; timeout fails, asyncio cancellation propagates. **Cancellation of an external provider request does not prove remote request quiescence**; no Workspace mutation permitted at this layer.
- End-to-end TaskAnalyzer models may only emit candidate hints. A model asking for `code_modification` does not automatically grant mutation when TaskContract is analysis-only; `SemanticPlanValidator` still fails `CAPABILITY_AUTHORITY_VIOLATION`.
- True upstream `from_deerflow()` factory module import/call signature checked with API-shaped module stubs. These stubs are not an installed pinned DeerFlow runtime.

## Source audit decision and remaining evidence

| Requirement | Status |
|---|---|
| Core ReasoningBackend signature, no duplicate domain schema | PASS (deterministic) |
| Pinned DeerFlow model factory signature & explicit model name | PASS (source-audited + mock seam) |
| Selected model-use authorization fail-closed | PASS (API-shaped mock) |
| Schema, tool-call, role, error, config drift denial | PASS (deterministic) |
| TaskAnalyzer / SemanticPlanner → Validator authority separation | PASS (deterministic) |
| Installed pinned DeerFlow package actual import + model construct | PENDING |
| Real AuthorizationProvider + active user identity integration | PENDING |
| Actual remote model call and structured output on configured provider | PENDING |
| NodeExecutionPreparation / AppConfig+tool+model+extensions pinning | STEP 5C |
| Managed execution ToolPolicy middleware, cancellation/quiescence | STEP 5D–5F |

**CI:** Code/negative tests run in Python 3.11/3.13 Core lanes. Actual DeerFlow harness has `requires-python >=3.12`; tests cannot infer native deployment compatibility from Python 3.11 mock success. No credentials invoked, no real model/provider network calls and no real shared Workspace execution. Frozen design/PoC matrix unmodified.

**Release judgement:** Step 5B model-only deterministic API and safety contract may move to 5C in same Draft PR. **Do NOT merge Step-5 production Adapter or claim integrated DeerFlow GO** based on this checkpoint alone.
