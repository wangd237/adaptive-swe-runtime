# Step 5 Release Closure — P0-01 Source Gate (not closed)

Date: 2026-10-10
Branch: coding/step5-deerflow-adapter
Status: OFFLINE PHYSICAL GO at f56d0268; deployment authorization still gated.

## Observed pinned source

In bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891,
get_available_tools() excludes a config tool when it has group=bash or
use=deerflow.sandbox.tools:bash_tool and is_host_bash_allowed(config) is
false. In the current local sandbox configuration allow_host_bash=False.
That exclusion precedes resolve_variable, so the tool cannot truthfully be
reported as assembled/configured by 5C.

The previous installed-native MVP E2E uses PhysicalPreparedToolSource:
it creates a bash source object outside this filtered upstream inventory.
This validates 5D/native/Docker but is not a production 5C proof.

## Changes in this gate

* Added tests/integration/test_deerflow_host_bash_filter_step5_release.py,
  a physical installed-frozen-upstream negative assertion.
* Wired this negative assertion to the pinned-native CI workflow.
* No unsafe change to allow_host_bash or fabricated positive 5C inventory.

## Required positive contract to close P0-01

1. **New trusted logical Docker command capability.** Its origin must be
   Runtime-operated (not deerflow.sandbox.tools:bash_tool). Specify an explicit
   stable implementation ID, effect=WORKSPACE_MUTATING, isolated-container
   requirements, and a deterministic schema/identity witness. Review and
   deliberately re-open frozen tool identity mapping if necessary.
2. **Immutable inventory and descriptor.** Capture this capability only
   when the Runtime Docker executor has been independently provisioned, never
   by altering the output of get_available_tools or by setting
   allow_host_bash=True. Compile the identity into OperatorSurface,
   NodeExecutionPolicy and CompiledPlanDescriptor and verify live preflight.
3. **5C source seal.** Pin the actual runtime-owned logical tool identity,
   distinct from frozen DeerFlow host bash. Reject impersonated config Bash,
   different tool schema, different runner and missing Docker capability.
4. **5D postcommit binding.** Construct execution-specific Docker tool after
   Scheduler Commit; validate original trust origin, object/identity seals,
   binding store, ToolCallGuard and live AuthorizationProvider.
5. **Physical positive E2E.** Actual installed source -> inventory -> compiled
   descriptor -> 5C -> 5D -> native LangGraph -> no-network Docker ->
   independent canonical check -> actual Git Diff. Include denials when
   host Bash is filtered/unintended exposure; no test-fabricated source.

## Non-goals

Do not declare strict TaskResult ACCEPTED without real quiescence. No live
paid-model rerun is required; scripted offline native model is adequate for
this particular authority-composition gate.


## 2026-10-10 implementation update — offline physical chain PASS

Reviewed implementation head: `f56d0268973a3eed34dd08f4d631f9f7a0c5e216`.

- Compiler trusted-effect contract recognizes a separate
  `aswe.runtime.docker:bash.v1`, not the native
  `config:deerflow.sandbox.tools:bash_tool`.
- `compose_docker_bash_inventory` merges only a checked Runtime
  `DockerCommandBackend` / immutable Docker grant into a native observation,
  and rejects a native `bash` collision. The original native assembled
  tool objects are not replaced with a fabricated host tool.
- `DeerFlowPreparationBackend` reassembles real frozen DeerFlow tools
  during 5C, builds a fresh live inventory, combines the independently
  issued grant, checks the original compiled descriptor and live
  preflight, and pins an inert runtime source token for Bash.
- `NodeExecutionBindingStore` checks that token/grant/backend match
  only after a Scheduler-committed execution, and converts the source
  to execution-scoped Runtime tools. Frozen LangGraph/native tooling
  invokes the Runtime Docker implementation; host Bash remains denied.
- Test `tests/integration/test_deerflow_docker_production_chain_step5_release.py`
  uses real DeerFlow `get_available_tools` and resolved native tool objects,
  actual compiler `resolve_workplan`, `compile_policies`,
  `compile_plan_descriptor`, original Scheduler claim and 5C/5D,
  real pinned `NativeSubagentAssembler`, Docker Bash, independent
  Python canonical verification and Git Diff. Only model replies are
  scripted. It does **not** use `PhysicalPreparedToolSource`.
- Latest matching SHA GitHub Actions passed:
  - Python CI: https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38031513812
  - Installed native + Docker: https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38031513813
- Real native tool schemas can include callable fields not representable
  as Pydantic JSON Schema. Such schemas have a `None` schema hash,
  NOT a fabricated hash; pinned source + implementation identity remain
  mandatory.

**P0-01 limited conclusion: OFFLINE PHYSICAL GO for Runtime-owned Docker Bash,
compiled inventory/descriptor and real 5C/5D SWE execution chain.**
This test uses an explicitly supplied offline AppConfig and actual
SubagentConfig instance, plus disabled external authorization. It does not
establish deployed config loading/production `AuthorizationProvider`
credentials, full production task entrypoint, native Sandbox Quiescence, or
strict Scheduler ACCEPTED / TaskResult. Those remain separately gated.
