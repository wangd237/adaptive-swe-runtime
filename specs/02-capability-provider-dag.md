# Capability / Provider / Team Specification

> Authoritative implementation specification. 已经 P0 consistency sweep / Design Freeze 收口；Capability/Provider/WorkspaceAccess contracts 以本文为准。

## 5. Capability Registry：能力注册中心

### 5.1 核心设计原则

A-SWE Runtime 将 Capability 作为 Runtime 的**语义调度词汇**。

Capability 只回答：

> **一个 bounded work package 需要具备什么能力？**

例如：

```text
repo_exploration
code_search
bug_diagnosis
python_debugging
database_analysis
code_modification
test_generation
regression_testing
code_review
```

一期必须避免让 Capability Registry 同时承担 Provider Registry 的职责。

因此：

```text
CapabilitySpec
≠ eligible agent list
≠ concrete tool list
≠ skill allowlist
```

这些实现细节属于 Provider Contract。

### 5.2 P1 的 Provider 模型

一期只把：

> **AgentProvider**

作为可被 Scheduler / Team Builder 选择的 execution carrier。

Tool 与 Skill 不再和 Agent 并列为“可调度 Capability Provider”。

关系冻结为：

```text
WorkItem
   │
   ▼
Required Capabilities
   │
   ▼
AgentProvider
   │
   ├── CapabilityBinding
   │       ├── required tools
   │       ├── optional tools
   │       └── preferred skills
   │
   └── DeerFlow Subagent
```

其中：

- AgentProvider：真正承担一个 DAG Node 的执行主体；
- Tool：Provider 完成 Capability 所依赖的 execution resource；
- Skill：可选的 workflow / SOP / domain enhancement；
- MCP：Tool 的外部接入机制，不是 Capability，也不是 P1 的独立 schedulable provider。

未来如果需要 deterministic ToolNode，再单独增加：

```text
DirectToolProvider
```

但不进入 MVP。

### 5.3 CapabilitySpec

Capability Registry 只保存 provider-neutral semantic metadata：

```python
class WorkspaceAccess(str, Enum):
    READ = "read"
    WRITE = "write"

class CapabilityAuthorityClass(str, Enum):
    READ_ONLY = "read_only"
    REPOSITORY_MUTATION = "repository_mutation"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"

class CapabilitySpec(BaseModel):
    id: str
    description: str

    # physical shared-workspace lower bound
    workspace_effect_floor: WorkspaceAccess

    # semantic/business authority required to select this capability
    authority_class: CapabilityAuthorityClass

    default_acceptance_kind: str | None = None
```

例如：

```yaml
capability:
  id: code_modification
  description: modify repository source code
  workspace_effect_floor: write
  authority_class: repository_mutation
```

明确不保存：

```text
eligible_agents
required_tools
preferred_skills
```

原因：

> 同一 Capability 可以被不同 Provider 用不同 Tool / Skill 组合实现。

例如：

```text
code_search

Provider A
→ grep + glob + read_file

Provider B
→ repository-search MCP tool
```

如果 concrete tools 写进 CapabilitySpec，会把“语义能力”错误绑定到一种实现。

### 5.4 CapabilityBinding

Provider 对自己支持的每个 Capability 声明实现契约：

```python
class CapabilityBinding(BaseModel):
    capability_id: str

    # P1: hard dependencies must be eagerly model-callable
    required_tools: tuple[str, ...] = ()

    # optional resources may include deferred MCP tools
    optional_tools: tuple[str, ...] = ()

    preferred_skills: tuple[str, ...] = ()

    notes: str | None = None
```

例如 Tester：

```yaml
capability: regression_testing

required_tools:
  - bash

preferred_skills:
  - pytest
```

Repo Explorer：

```yaml
capability: repo_exploration

required_tools:
  - ls
  - glob
  - grep
  - read_file

preferred_skills:
  - repository-navigation
```

因此 authoritative resolution 变为：

```text
WorkItem Capability
      ↓
Candidate AgentProvider
      ↓
Provider CapabilityBinding
      ↓
Concrete Resource Requirements
```

#### Tool Contract ID 与 Exposed Name 分离

`CapabilityBinding.required_tools / optional_tools` 在 P1 仍保持轻量字符串，但其语义冻结为 **A-SWE Tool Contract ID**，不是未经验证的 DeerFlow exposed name。

为降低配置噪声，标准 SWE Tool 可以让 contract id 与 exposed name 同名，例如 `read_file`、`bash`、`str_replace`；但 DeerFlow Adapter 内部必须维护受信任映射：

```text
Tool Contract ID
      ↓
Expected Backend Implementation
      ↓
Resolved Tool Identity
      ↓
Exposed Name
```

Pinned DeerFlow 的 `get_available_tools()` 会按 exposed name 去重，且 config-defined tool 先于 built-in / MCP / ACP / plugin。因此 `name == read_file` 并不能证明实际 implementation 是 DeerFlow 标准 `read_file_tool`。

核心原则：

> **Tool name is a routing key; Tool identity is the capability/effect authority.**

同名 implementation 发生变化时，A-SWE 必须将其视为 inventory drift，而不是继续沿用旧 ToolEffect。

#### P1 Canonical Tool Identity

P1 不做通用 Python Tool 对象哈希。

对于 core SWE hard-required business tools，identity contract 收窄到 **config-defined eager tool**：

```text
Tool Contract ID
      ↓
expected ToolConfig.use
      ↓
resolve_variable(use)
      ↓
loaded BaseTool.name
```

例如：

```text
read_file
→ deerflow.sandbox.tools:read_file_tool
→ loaded tool.name == read_file
```

Pinned DeerFlow `ToolConfig` 原生包含：

```text
name
group
use
```

且 `get_available_tools()` 通过 `resolve_variable(cfg.use, BaseTool)` 加载。实际路由名以 loaded Tool 的 `.name` 为准；若 `cfg.name != loaded.name`，DeerFlow 只 warning，不改回 cfg.name。

因此 P1 的稳定 identity anchor 定义为：

```text
implementation_id
=
config:<ToolConfig.use>
```

同时记录：

```text
configured_name
resolved_exposed_name
group
schema_hash
```

其中：

- `ToolConfig.use` 是 implementation identity anchor；
- `resolved_exposed_name` 是实际 DeerFlow routing key；
- `schema_hash` 是 compatibility / drift evidence，不作为 implementation identity 本身；
- Python object id 不进入 fingerprint；
- runtime clone / description augmentation 不改变 implementation identity。

如果 required Tool Contract ID：

- 找不到对应 expected `ToolConfig.use`；
- 被同名其他 config implementation 取代；
- resolved Tool name 与 Contract mapping 不兼容；

则：

```text
PROVIDER_TOOL_IDENTITY_MISMATCH
```

而不是仅仅把它当作“同名 Tool 仍然可用”。

对于 P1 的 MCP / plugin / ACP optional tools：

> 可以进入 inventory，但若没有 Adapter 明确认可的 stable identity / effect contract，则 `ToolEffect.UNKNOWN`，不得成为 READ safety proof。

未来再扩展：

```text
MCP identity
→ server identity + tool identity + schema/version evidence

Plugin identity
→ namespace + declaration + installation/version
```

不在 MVP 为 optional enhancement 预先建设完整跨后端 identity protocol。

### 5.4.1 CapabilityBinding Merge

一个 WorkItem 可以要求多个 Capability，而一个 AgentProvider 可以同时覆盖它们。

对同一个 Provider：

```text
required_tools
→ stable ordered union

optional_tools
→ stable ordered union
→ 再减去已经 required 的 names

preferred_skills
→ stable ordered union
```

例如：

```text
bug_diagnosis
required: grep, read_file

code_modification
required: read_file, str_replace

合并后
required: grep, read_file, str_replace
```

required wins over optional：

```text
Capability A: bash optional
Capability B: bash required
→ bash required
```

禁止通过集合排序破坏声明稳定顺序；fingerprint 使用 canonical representation，execution config 保持 deterministic first-occurrence order。

### 5.4.2 Optional Tool Selection

`optional_tools` 表示 Provider 的可选增强资源，不代表默认全部开放。

P1 默认：

> **optional tool 不自动进入 Node allowed_tools。**

只有 ToolSelectionPolicy 显式选中后，才进入：

```text
selected_optional_tools
```

选择条件至少包括：

- backend candidate inventory 中存在；
- operator policy 未禁止；
- TaskContract 未禁止；
- 不会在没有明确收益时扩大 side-effect class；
- 不会无理由扩大 external side-effect surface。

例如：

```text
repo_exploration
required = read_file, grep
optional = bash

没有明确需求
→ bash 不开放
```

这保持 least privilege，也避免“optional bash”把本可并行 READ Node 无意义升级成 WRITE。

### 5.4.3 Required Tool Delivery Boundary

Pinned DeerFlow 的 deferred tool 机制具有明确边界：

```text
tool_search.enabled
AND candidate tool is MCP
→ deferred

ordinary built-in / configured non-MCP tool
→ eager
```

DeerFlow `build_deferred_tool_setup()` 只对：

```python
is_mcp_tool(tool)
```

返回 true 的 candidate 建 DeferredToolCatalog。

因此 P1 冻结：

> **CapabilityBinding.required_tools 只允许 EAGER hard dependency。**

一期 core SWE capability：

```text
repo_exploration
code_search
code_modification
test_generation
regression_testing
code_review
```

应尽量只依赖 DeerFlow eager built-ins。

MCP tools 在 P1 只能作为：

```text
optional_tools
```

被 ToolSelectionPolicy 选择后：

```text
selected optional MCP tool
      ↓
SubagentConfig static selection
      ↓
DeferredToolCatalog
      ↓
tool_search infrastructure helper
      ↓
runtime promotion
```

因此第一模型调用的 hard feasibility 不需要把“当前不可见但未来可能 promotion”误判为 required-tool missing。

未来如果业务确实需要：

> **某个 MCP tool 是完成 Node 的硬条件**

再引入：

```text
ToolRequirement.delivery = EAGER | DEFERRED_OK
```

并定义 catalog-level attestation；不在 MVP 预先建设。

### 5.4.4 Capability Authority Validation

Planner 的：

```text
capability_hints
```

仍然只是 candidate。

不能：

```text
Planner says code_modification
→ automatically grant write tools
```

否则模型仍然可以通过 capability hint 自我扩权。

SemanticPlanValidator / Capability Compiler 必须把 CapabilitySpec.authority_class 与 TaskExecutionAuthority 对齐。

P1 规则：

```text
READ_ONLY
→ 可进入普通 planning selection

REPOSITORY_MUTATION
→ TaskExecutionAuthority.repository_mutation_allowed 必须为 true

EXTERNAL_SIDE_EFFECT
→ 必须存在 explicit allowed external action
→ P1 默认 deny
```

此外，Planner-owned mutation WorkItem 必须至少有一个：

```text
coverage_claim
→ 指向 effect = REPOSITORY_MUTATION 的 positive deliverable constraint
```

否则：

```text
CAPABILITY_AUTHORITY_VIOLATION
→ PLAN_INVALID
```

这不是说 coverage claim 已证明任务完成，而只是要求：

> 每个业务 mutation Node 都必须说明它服务于哪个被 TaskContract 授权的 mutation obligation。

Runtime-owned gate 是例外：

- verification gate 的 regression_testing 属于 READ_ONLY semantic authority；
- review gate 的 code_review 属于 READ_ONLY semantic authority；
- 若未来 Runtime Policy 注入真正 mutation gate，必须由对应 Runtime-derived constraint 授权。

### 5.4.5 Authority Effect ≠ ToolEffect

两者必须严格分离：

```text
CapabilityAuthorityClass
→ 这个 WorkItem 在业务语义上被允许做什么

ToolEffect
→ 实际开放的工具在物理上可能产生什么副作用
```

例如：

```text
regression_testing

CapabilityAuthorityClass = READ_ONLY
workspace_effect_floor = READ

Provider requires bash
ToolEffect(bash) = WORKSPACE_MUTATING

最终：
semantic authority = no business source mutation
WorkspaceAccess = WRITE / exclusive
```

因此 Tester 可以获得 WRITE lock，却仍然没有业务源码修改 authority。

其执行后：

```text
Git ChangeSet
+
TaskContract
+
post-node invariant
```

必须确认没有超出 verification 允许的 mutation 范围。

同理：

```text
code_modification
CapabilityAuthorityClass = REPOSITORY_MUTATION
workspace_effect_floor = WRITE
```

只有 TaskContract 授权 repository mutation 才能进入 ValidatedWorkPlan。

### 5.5 Capability / Tool Side-Effect Authority

最终 `workspace_access` 不由 LLM 决定，也不能只从 Capability 名称推断。

必须同时考虑：

```text
Capability Workspace Effect Floor
+
Selected Provider's CapabilityBinding
+
Required Tool Effects
+
Backend / Sandbox Contract
        ↓
Effective WorkspaceAccess
```

Capability `workspace_effect_floor` 只是物理 Workspace access 的 lower bound：

```text
repo_exploration   → READ
code_search        → READ
bug_diagnosis      → READ
code_modification  → WRITE
test_generation    → WRITE
regression_testing → READ semantic intent
code_review        → READ
```

其中：

```text
regression_testing + bash
→ WRITE / exclusive
```

因为 DeerFlow `bash` 是通用 shell execution；pinned 源码明确说明 local bash path validation 不实施 bash-command write prevention。

ToolEffect：

```python
class ToolEffect(str, Enum):
    READ_ONLY = "read_only"
    WORKSPACE_MUTATING = "workspace_mutating"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"
    UNKNOWN = "unknown"
```

P1 保守分类必须基于**已解析 implementation**：

| Resolved implementation | ToolEffect |
|---|---|
| DeerFlow standard `ls/glob/grep/read_file` | READ_ONLY |
| DeerFlow standard `write_file/str_replace` | WORKSPACE_MUTATING |
| DeerFlow standard `bash` | WORKSPACE_MUTATING |
| 未识别 config / MCP / ACP / extension implementation | UNKNOWN |

禁止通过 `tool.name == "read_file"` 直接赋予 `READ_ONLY`。同名 Tool 若无法确认 implementation identity，则 hard dependency 直接 preflight mismatch；仅作为 optional resource 时按 `UNKNOWN` 处理。

最终：

```text
workspace_effect_floor == READ
AND every tool in the final effective Node allowlist
    is provably READ_ONLY
→ WorkspaceAccess.READ

otherwise
→ WorkspaceAccess.WRITE
```

即：

> **MVP 只有“可证明只读”的 Node 才能并发读取 Workspace。**

`WorkspaceAccess` 的唯一 authoritative enum 就是 §5.3 的 `READ | WRITE`。未知/外部副作用不增加第三个 lock class；它们一律保守编译为 `WRITE`，副作用不确定性由 `ToolEffect.UNKNOWN / EXTERNAL_SIDE_EFFECT` 与 MutationEvidence 单独表达。

这里必须使用最终：

```text
required_tools
+
selected_optional_tools
+
Node-visible non-infrastructure execution tools
```

而不是只检查 `required_tools`。

因为：

> **Tool 只要被开放给模型，就必须按“可能被调用”计算 side effect。

因此最终 WorkspaceAccess 在 NodePolicy materialization **最后一步**确定；NodeToolPolicy 允许的业务 Tool 集发生变化时，必须重新计算 fingerprint 与 WorkspaceAccess。**

LLM 的 `effect_hint` 仍然只是 hint，可以更保守，但不能降低 Runtime 编译结果。

### 5.6 与 Plugin / Extension System 的边界

Capability-Centric Runtime 与“Everything is a Plugin”不是同一层概念。

```text
Plugin / Extension System
→ 系统组件如何注册、加载、替换

Capability System
→ 当前 WorkItem 需要什么语义能力

Provider Contract
→ 某个执行主体如何实现这些能力
```

A-SWE 不重新实现 DeerFlow Plugin / Extension Framework。

### 5.7 一期 Capability 范围

一期建议：

```text
repo_exploration
code_search
bug_diagnosis
code_modification
test_generation
regression_testing
code_review
```

必要时增加：

```text
python_debugging
database_analysis
architecture_analysis
```

Repository clone / checkout / base SHA / final patch 属于 Workspace Runtime，不属于普通 Agent Capability。

---

## 6. Capability Resolver：能力解析器

### 6.1 模块职责

Capability Resolver 的 authoritative input：

```text
ValidatedWorkPlan
+
Capability Registry
+
AgentProvider Registry
+
BackendInventorySnapshot
+
CompiledTaskContract
```

对每一个 WorkItem 形成：

```text
ProviderAssignment
+
NodeResourceRequirements
```

建议：

```python
class NodeResourceRequirements(BaseModel):
    required_capabilities: tuple[str, ...]
    required_tools: tuple[str, ...]
    optional_tools: tuple[str, ...]
    preferred_skills: tuple[str, ...]
    required_sandbox_features: tuple[str, ...]

class ProviderAssignment(BaseModel):
    work_item_id: str
    provider_id: str

    provider_contract_fingerprint: str
    planning_inventory_fingerprint: str

    resources: NodeResourceRequirements

    preflight_status: Literal["preflight_feasible"]
    preflight_diagnostics: tuple[str, ...]

    fingerprint: str
```

`ProviderAssignment` 是 planning artifact。

其中 `required_sandbox_features` 不只来自 Capability / Tool execution needs，也必须合并 Acceptance Compiler 的 evidence requirements，例如：

```text
tests_passed:<command>
→ deerflow_tests_passed_evidence
```

因此“Tester provider 有 bash”不足以通过 regression verification preflight。

它记录：

> **为什么在当时的 Backend snapshot 下选择了这个 Provider。**

它不承诺未来执行时 deployment 永远不变。

### 6.2 Node-Level Resolution

例如：

```text
WorkItem: diagnose
→ repo_exploration
→ code_search
→ bug_diagnosis

WorkItem: implement
→ code_modification

WorkItem: verify
→ regression_testing
```

Resolver 不再输出“Agent / Skill / Tool 三类 provider 组合”。

它执行：

```text
Required Capabilities
      ↓
AgentProvider semantic coverage
      ↓
CapabilityBinding expansion
      ↓
Required / Optional Tools
Preferred Skills
      ↓
Backend Preflight
      ↓
Provider Assignment
```

### 6.3 Backend Inventory Snapshot

Compile-time 不能把 A-SWE Registry 中声明的 Tool 当成真实运行时事实。

DeerFlow 的实际 Tool catalog 来自：

- config-defined tools；
- built-ins；
- model-dependent tools；
- MCP cache / personal MCP；
- ACP；
- plugin tools；
- tool groups；
- sandbox / host-bash availability。

因此 DeerFlow Adapter 需要给 Core 提供 provider-neutral inventory snapshot：

```python
class BackendToolInfo(BaseModel):
    contract_id: str

    configured_name: str | None
    resolved_exposed_name: str

    source: str
    delivery: Literal["eager", "deferred"]

    # P1 core required tools: "config:<ToolConfig.use>"
    implementation_id: str

    group: str | None = None
    schema_hash: str | None = None

    # Display/source metadata is informative; never sufficient as identity authority.
    provenance: str | None = None

    effect: ToolEffect

class BackendInventorySnapshot(BaseModel):
    backend_id: str
    captured_at: datetime

    candidate_agent_types: frozenset[str]
    candidate_tools: dict[str, BackendToolInfo]
    candidate_skill_names: frozenset[str]
    configured_model_names: frozenset[str]

    sandbox_features: frozenset[str]
    max_parallel_executions: int

    fingerprint: str
```

#### P1 Sandbox Feature Vocabulary

Adapter 不只报告：

```text
"bash available"
```

还必须报告 shell / evidence semantics。

P1 至少使用：

```text
fresh_shell_per_command
deerflow_tests_passed_evidence
persistent_shell_sessions
shell_session_semantics_unknown
```

Pinned DeerFlow 映射：

```text
Sandbox.persistent_shell_sessions == False
→ fresh_shell_per_command
→ deerflow_tests_passed_evidence

Sandbox.persistent_shell_sessions == True
→ persistent_shell_sessions
→ NO deerflow_tests_passed_evidence

Sandbox.persistent_shell_sessions == None
→ shell_session_semantics_unknown
→ NO deerflow_tests_passed_evidence
```

当前 pinned provider declarations：

```text
LocalSandbox      → False
E2B               → False
OpenSandbox       → False
Tenki             → False
BoxLite           → False

AioSandbox        → True
```

> **Sandbox 能执行 bash ≠ Sandbox 能为 DeerFlow native tests_passed checker 提供 load-bearing deterministic evidence。**

AIO 的 ordinary subagent bash path使用 execution-scoped persistent shell；当前 `_harvest_bash_executions` 的 provenance stamp 又来自 Sandbox-level `persistent_shell_sessions=True`，因此 P1 不把 AIO 宣称为 native `tests_passed` evidence-capable backend。

注意命名：

> **candidate_tools，而不是 actual_bound_tools。**

`candidate_tools` 建议按 `Tool Contract ID` 索引。`name/source/provenance` 便于解释，但 hard feasibility 与 ToolEffect 不能只依赖这些 display fields，必须匹配 `implementation_id`。

Inventory 中的 `delivery` 用于区分当前 deployment 下的：

```text
eager tool
deferred MCP tool
```

但它仍然只是 planning-time snapshot，不是 runtime assembly proof。

Inventory 只能回答：

> 当前 deployment 看起来有没有这些资源？

不能证明：

> 当前用户、当前 Node 最终 assembly 后一定拿得到这些资源。

因为后续还有：

- operator SubagentConfig；
- runtime authorization；
- skill authorization；
- dynamic MCP/config drift；
- deferred-tool assembly；
- middleware-declared tools。

DeerFlow inventory 构建属于 Adapter；Core 不直接 import `deerflow.tools.get_available_tools`。

### 6.4 Feasibility 分层

A-SWE 不把“Provider 声明自己会做”直接等价为可执行。

冻结四层状态：

```text
DECLARED
→ ProviderContract 声明 semantic capability

PREFLIGHT_FEASIBLE
→ 当前 Backend inventory / static policy 看起来可执行

ASSEMBLED_MATCH
→ DeerFlow 实际 assembly 与 NodeExecutionPolicy 一致

EXECUTED
→ Node 真正执行并产生 evidence
```

因此：

```text
Declared Capability
≠ Executable Capability
≠ Successful Execution
```

### 6.5 Provider Preflight

每个 Candidate AgentProvider 至少检查：

1. required capability 是否都有 CapabilityBinding；
2. binding.required_tools 的 Tool Contract ID 是否都能唯一解析到预期 `implementation_id`；
3. required tool 是否存在于 backend inventory 且 `delivery == eager`；
4. resolved implementation 的 exposed name 是否仍满足 operator SubagentConfig 静态 allow / deny；
5. `required_sandbox_features ⊆ BackendInventorySnapshot.sandbox_features`，包括 acceptance-derived evidence semantics；
6. TaskContract 是否禁止该 Tool / effect；
7. resolved model 是否存在；
8. authorization-enabled deployment 下，required tools 做 identity-aware authorization preflight；
9. authorization-enabled deployment 下，resolved model 做 `model:use` preflight；
10. selected optional tools 是否满足 least-privilege / effect policy；
11. preferred skills 是否与 Node required-tool closure 兼容；
12. 由**最终 resolved tool identity set**编译出的 WorkspaceAccess 是否满足 Node policy。

通过后才进入：

```text
PREFLIGHT_FEASIBLE
```

但 runtime authorization 仍可能在真正 assembly 时进一步收窄。

### 6.5.1 Execution-Time Live Revalidation

`PREFLIGHT_FEASIBLE` 是 planning-time 判断，会过期。

因此 Scheduler 在 NodeReady 后、不获取 Workspace WRITE lock 之前调用：

```text
ExecutionBackend.prepare_node()
```

DeerFlow Adapter 在这一阶段重新解析当前 deployment，并形成：

```python
class NodeExecutionPreparation(BaseModel):
    # Pre-commit preparation identity; NOT a Node attempt/execution id.
    preparation_id: str

    node_id: str
    provider_id: str

    compiled_policy_fingerprint: str

    planning_inventory_fingerprint: str
    live_inventory_fingerprint: str

    effective_policy_fingerprint: str

    backend_snapshot_id: str

    drift_observed: bool
    drift_diagnostics: tuple[str, ...]

    status: Literal["prepared"]
```

P1 identity boundary：

```text
prepare_node()
→ preparation_id only
→ no attempt / execution_id / run_id yet

final Scheduler dispatch commit
→ allocate attempt
→ allocate execution_id
→ allocate run_id
→ freeze NodeExecutionInvocation
```

因此 `NodeExecutionPreparation` 被 pre-commit ticket revoke 时可以安全 discard，不会留下一个“已经存在但从未运行”的 execution identity。

`backend_snapshot_id` 是 provider-neutral opaque id。Core 不通过它读取 DeerFlow object；它只让 Adapter 在 `execute_prepared()` 时取回本次准备阶段冻结的 concrete resources。

### 6.5.2 Fingerprint Drift Semantics

不能：

```text
planning fingerprint != live fingerprint
→ automatically fail
```

因为无关资源变化也会改变 fingerprint。

正确规则：

```text
fingerprint changed
      ↓
re-run hard feasibility against live snapshot
      │
      ├─ all constraints still hold
      │     → PREPARED
      │     → record BACKEND_DRIFT_OBSERVED
      │
      └─ required condition no longer holds
            → BACKEND_PREFLIGHT_STALE
            → fail before workspace mutation
```

Fingerprint 变化本身不是 failure；重新验证后 required condition 不再成立才是 failure。

### 6.5.3 Monotonic Runtime Narrowing

Execution preparation 只允许继续收窄 compiled Node policy。

允许：

- optional tool disappeared → drop optional tool；
- preferred skill disappeared → warning / drop；
- operator timeout 变小 → lower effective timeout；
- operator max_turns 变小 → lower effective turns；
- authorization 移除 optional tool → drop；
- new unrelated tools appear → ignore。

禁止：

- 自动添加新 Tool；
- 用新 Tool 替代 required Tool；
- 扩大 path / action authority；
- 提高 operator ceiling；
- 自动换 Provider；
- 改 WorkItem objective。

准备后形成：

```text
Compiled NodeExecutionPolicy
      ↓ monotonic narrowing
Effective NodeExecutionPolicy
```

`WorkspaceAccess` 一期保持 compiled upper-bound lock class，不因 runtime narrowing 从 WRITE 动态降回 READ。

### 6.5.4 DeerFlow Execution Snapshot Pinning

Pinned DeerFlow `SubagentExecutor` 自身已经明确采用：

> **one AppConfig snapshot per execution**

A-SWE Adapter 应强化而不是破坏这个性质。

`prepare_node()` 一次性解析并冻结：

```text
AppConfig snapshot
effective SubagentConfig
concrete base tool objects
resolved model
LoadedExtensions generation
user / auth identity
inventory fingerprint
```

随后 `execute_prepared()` 必须把同一份 AppConfig、tools、SubagentConfig、extensions snapshot 传给 `SubagentExecutor`。

禁止：

```text
prepare with config A
execute later with get_app_config() → config B
```

### 6.5.5 Authorization 是 Live Gate，不伪装成 Snapshot

AuthorizationProvider 不能被 A-SWE 宣称为冻结 policy snapshot。

DeerFlow 当前执行链会在 assembly、middleware-declared tools、tool call 与 Skill activation 等位置继续重新授权。

因此 planning/preparation preflight 只是早失败优化；真正 authority 仍来自运行时 DeerFlow authorization / guardrail。

### 6.5.6 Provider Rebinding Boundary

如果 live revalidation 失败，P1 不自动 switch 到另一个 Provider。

原因：ProviderAssignment、Tool policy、WorkspaceAccess、prompt/skills、fingerprint 都属于已编译 execution plan。

结果：

```text
BACKEND_PREFLIGHT_STALE
→ explicit node admission failure
```

发生在首次 business WRITE 前时，上层可使用已有 bounded replan policy 重新编译；Workspace 已有 mutation 时，MVP fail closed。

未来若做 Provider Rebinding，也必须是带 Trace 与新 fingerprint 的显式 Plan Repair，而不是 Scheduler 私下替换。

### 6.6 Provider Selection

一期：

```text
Required Capability
        │
        ▼
Semantic Coverage
        │
        ▼
CapabilityBinding Expansion
        │
        ▼
Backend Inventory Preflight
        │
        ▼
Static Operator Policy Check
        │
        ▼
Contract / ToolEffect Compatibility
        │
        ▼
Minimal / Priority Rule
        │
        ▼
Provider Assignment
```

不需要一期实现学习型 success probability。

### 6.7 Single Source of Truth

Capability Registry 不维护：

```text
eligible_agents
```

AgentProvider Registry 才声明：

```text
provider → capability bindings
```

若需要 capability → providers 的反向查询：

```text
Runtime derives reverse index
```

而不是维护双向配置。

否则容易出现：

```text
Capability says Coder eligible
AgentRegistry says Coder does not support capability
```

这种 drift。

### 6.8 核心价值

最终解耦成：

```text
SemanticPlanner
→ bounded work semantics

Capability Registry
→ semantic vocabulary

AgentProvider Contract
→ implementation choice

Backend Inventory
→ current deployment preflight

DeerFlow Assembly Attestation
→ actual runtime evidence
```

---

## 7. Dynamic Team Builder：动态团队构建模块

### 7.1 建设目标

Dynamic Team Builder 输入：

```text
ValidatedWorkPlan
+
Provider Assignments
+
Task Risk / Constraints
```

输出：

```text
TeamSpec
```

Team Builder 只回答：

> **哪些执行 Provider 参与本任务？**

不负责：

```text
Task decomposition
dependency topology
execution order
parallelism
```

这些属于 Planning / DAG Materializer。

### 7.2 核心原则

Multi-Agent 不是默认选择。

> **若一个 Provider 对多个既有 WorkItem 都是可行 execution carrier，Team roster 可以只包含这一个 Provider；但这不合并 WorkItem，也不表示共享 Agent session。**

### 7.3 TeamSpec 只保存 Roster

建议：

```python
class TeamMember(BaseModel):
    provider_id: str
    capabilities: list[str]

    selected_for_nodes: list[str]
    selection_reason: str

class TeamSpec(BaseModel):
    members: list[TeamMember]
```

例如：

```yaml
team:
  members:
    - provider_id: repo_explorer
      selected_for_nodes:
        - diagnose
      selection_reason: diagnosis_requires_repository_exploration

    - provider_id: coder
      selected_for_nodes:
        - implement
      selection_reason: code_modification

    - provider_id: tester
      selected_for_nodes:
        - verify
      selection_reason: regression_testing
```

TeamSpec 不包含：

```text
Explorer → Coder → Tester
strategy: explore_code_test_review
```

Topology 只存在于最终 TaskDAG。

### 7.4 Planning Recon 不计入 Execution Team

Planning Phase 中的只读 Recon Probe 属于 Runtime planning infrastructure。

例如：

```text
Planning:
  Repo Profile
  Recon Probe

Execution Team:
  Coder
  Tester
  Reviewer
```

Recon Probe 不因为运行过一次就自动成为 TeamSpec 成员。

### 7.5 Explainability

Team Builder 仍需记录：

```text
为什么选
为什么不选
哪些 WorkItem 被谁覆盖
```

这些进入 Decision Trace。

---

## 8. MVP Team Selection Policy：最小可行团队策略

### 8.1 一期选择目标

Provider 只有进入：

```text
PREFLIGHT_FEASIBLE
```

集合以后，才参与 Team Selection。

然后在：

```text
WorkItem Capability Coverage
Task / Contract Constraints
Provider Static Compatibility
Backend Preflight
```

全部满足的前提下：

> **选择最小可行 AgentProvider Set。**

形式化：

```text
Minimize:
    Provider Count
    + Estimated Coordination Cost

Subject to:
    WorkItemCapabilityCoverage == 100%
    EveryAssignment == PREFLIGHT_FEASIBLE
    ContractConstraints == satisfied
```

### 8.2 Feasibility 先于 Ranking

一期禁止这种逻辑：

```text
Provider A score higher
但 required tool 缺失
→ 仍然选 A
```

必须先做 hard feasibility filter，再做 ranking。

```text
All Providers
      ↓
Hard Feasibility
      ↓
Feasible Providers
      ↓
Priority / Cost
      ↓
Selection
```

### 8.3 一期不构造虚假 Success Probability

一期没有足够历史数据可靠估计：

```text
P(success | task, provider, repo)
```

因此不使用形式复杂但无数据基础的模型。

### 8.4 规则示例

```text
低风险单文件修改
且 Coder capability bindings 覆盖全部 required capabilities
且 required tools preflight 可用
→ Team = {Coder}

Diagnosis 需要 repo_exploration + bug_diagnosis
且 Coder 没有完整 binding
→ Explorer 进入候选

CompiledTaskContract.verification.required exists
→ Runtime / validated plan 必须有 VERIFICATION WorkItem
→ 必须有 Provider 能覆盖 regression_testing
→ 若其实现依赖 bash，则 Node workspace_access = WRITE

CompiledTaskContract.review.required exists
→ Runtime / validated plan 必须有 REVIEW WorkItem
→ 必须有 code_review-compatible Provider
```

注意：

> Team Selection Rule 不负责决定 Provider 先后关系。

### 8.5 Provider Reuse

如果同一个 Provider 可以覆盖多个不同 WorkItem：

```text
Provider Count
```

在 Team roster 中只计算一次。

但每个 WorkItem / Node 仍是独立 execution assignment，并独立生成：

```text
NodeExecutionPolicy
```

因此：

```text
same Provider
≠ same Node
≠ same tool allowlist
≠ same workspace access
≠ same Agent session
≠ implicit context continuity
```

Pinned DeerFlow native subagent 是 one-shot execution：

- child graph 使用 `checkpointer=False`；
- 不继承 parent conversation history；
- 每次 invocation 构建 fresh child state；
- subagent 自身不会替下一个 Node 保留隐藏 reasoning / conversation context。

跨 Node 连续性只能来自：

```text
explicit NodeHandoff
+
shared Workspace artifacts
+
deterministic execution evidence
```

因此 Provider reuse 只表示：

> **复用同一个 execution implementation / role contract。**

它不表示：

> **复用一个持续存在的 Agent 实例。**

Team Selection 中的 `Provider Count` 是 roster complexity 指标，不是 LLM invocation count，也不是 handoff count。

例如同一个 Coder：

```text
Diagnosis Node
→ read_file / grep only
→ READ

Implementation Node
→ read_file / write_file / str_replace
→ WRITE
```

---

## 10. Agent Registry：智能体注册中心

### 10.1 设计定位

Capability Registry 定义：

> 系统使用什么语义能力词汇。

Agent Registry 定义：

> 哪些 execution carrier 可以实现这些 Capability，以及每种实现需要哪些 execution resources。

Agent Registry 不直接保存 DeerFlow runtime object。

### 10.2 一期 AgentProvider

一期只保留：

```text
Repo Explorer
Coder
Tester
Reviewer
```

`SWE Lead` 作为 A-SWE Runtime Coordinator 的逻辑角色存在，不实现为负责自主 delegation 的长期 DeerFlow Lead Agent。

### 10.3 Provider Contract

建议：

```python
class AgentProvider(BaseModel):
    id: str
    role: str

    backend: Literal["deerflow"] = "deerflow"
    backend_agent_type: str

    capability_bindings: dict[str, CapabilityBinding]

    model_policy: Literal["operator_config_or_inherit"] = "operator_config_or_inherit"

    cost_class: Literal["low", "medium", "high"] = "medium"

    fingerprint: str
```

明确不保存：

```text
workspace_access
actual_tools
actual_skills
```

原因：

- workspace access 是 Node + selected binding + ToolEffect 的编译结果；
- actual tools 只有 DeerFlow assembly 后才能知道；
- Skill allowlist 只表示 discoverability，不表示实际 activation/use。

### 10.4 Provider 示例

Repo Explorer：

```yaml
provider:
  id: repo_explorer
  role: explorer
  backend_agent_type: repo-explorer

capability_bindings:
  repo_exploration:
    required_tools:
      - ls
      - glob
      - grep
      - read_file
    preferred_skills:
      - repository-navigation

  code_search:
    required_tools:
      - grep
      - read_file
```

Tester：

```yaml
provider:
  id: tester
  role: tester
  backend_agent_type: tester

capability_bindings:
  regression_testing:
    required_tools:
      - bash
    preferred_skills:
      - pytest

  test_generation:
    required_tools:
      - read_file
      - write_file
      - str_replace
```

注意：

> Tester 不再静态声明 `workspace_access=read`。

`regression_testing + bash` 会在 Node 编译阶段得到 `WorkspaceAccess.WRITE`。

### 10.5 Operator Config 与 A-SWE Policy 的关系

DeerFlow 的 `SubagentConfig.tools` 是 operator / deployment 侧的静态 allowlist。

A-SWE Node policy 只能继续收窄它，不能扩权。

正确关系：

```text
Operator SubagentConfig
        ∩
A-SWE Node Allowlist
        ∩
Runtime Authorization
        ↓
Actual Bound Tools
```

Adapter 的 monotonic narrowing：

```python
base = get_subagent_config(provider.backend_agent_type)

if base.tools is None:
    narrowed_allow = node_policy.allowed_business_tools
else:
    narrowed_allow = intersection(base.tools, node_policy.allowed_business_tools)

narrowed_deny = union(
    base.disallowed_tools,
    node_policy.denied_tools,
)

if not required_tools <= (narrowed_allow - narrowed_deny):
    raise ProviderStaticContractMismatch
```

实际实现必须保留稳定顺序，不要求用无序 set 直接输出。

核心原则：

> **A-SWE may narrow operator authority; it must never widen it.**

同样：

```text
effective max_turns
→ min(operator limit, node budget)

effective timeout
→ min(operator limit, node budget)
```

A-SWE 不应通过 Node policy 抬高 operator 已配置的 execution ceiling。

### 10.6 Skill Contract

Provider binding 中的：

```text
preferred_skills
```

一期表示：

> 希望该 Skill 对此 Capability 可发现 / 可激活。

不是：

> 该 Skill 必须被实际加载后任务才算完成。

因此 Skill 缺失默认：

```text
warning / lower preference
```

而不是 hard feasibility failure。

如果未来确实需要：

```text
MUST_ACTIVATE skill X
```

必须单独定义 SkillRequirement，并验证 runtime skill-usage evidence；不能用 `enabled_skills` 冒充 activation 证据。

#### Preferred Skill Compatibility

Pinned DeerFlow 中，Skill 只有在 slash / in-context 激活后才施加 `allowed-tools` policy；但一旦生效，它会动态收窄 model-visible tools 与实际 tool calls。

因此 preferred skill 也不能只检查“存在”。例如：

```text
Node required tool = bash
preferred skill allowed-tools = [read_file]
```

该 Skill 一旦单独激活，就可能让 Node 失去完成 Capability 所需的 `bash`。

P1 采用保守规则：

- `allowed_tools is None`：兼容，表示 legacy allow-all；
- explicit `allowed_tools` 覆盖 Node 全部 required business tool exposed names：兼容；
- explicit `allowed_tools` 缺任一 required business tool：不向该 Node 暴露该 preferred skill，并记录 warning。

DeerFlow framework-always-available names（如 `read_file` / `describe_skill` / `tool_search`）仍由 DeerFlow 自身 Skill policy 处理。

注意：这只是 discoverability compatibility，不证明 Skill 实际被激活。

### 10.7 Model Policy

P1 的 AgentProvider 不自行指定高低模型，也不做 provider-level model routing。

使用：

```text
operator-configured Subagent model
or
inherit runtime/default model
```

这样避免：

```text
Capability Resolver
→ 顺便变成 Model Router
```

当前 pinned DeerFlow 有一个必须记录的 direct-executor compatibility boundary：

- Lead Agent / DeerFlowClient 会显式执行 `model:use` authorization；
- `SubagentExecutor` 自身直接 `create_chat_model(...)`；
- `create_chat_model()` 不负责 model authorization。

因此 A-SWE DeerFlow Adapter 在 authorization-enabled deployment 下必须进行：

```text
Resolved Model
      ↓
Model Authorization Preflight
      ↓
SubagentExecutor
```

P1 不复制 Lead Agent 的“deny → fallback to another model”私有逻辑，也不依赖 private `_authorize_model_name` 作为核心接口。

A-SWE 采用更严格、可解释的策略：

```text
model:use ALLOW
→ execute

model:use DENY
→ PROVIDER_MODEL_UNAUTHORIZED
→ provider infeasible / node admission failure
```

provider error：

```text
authorization.fail_closed = true
→ fail closed

authorization.fail_closed = false
→ preserve DeerFlow fail-open policy
```

实现只复用 DeerFlow 已有 lower-level authorization primitives：

- `AuthorizationProvider`；
- `AuthzRequest(resource="model", action="use")`；
- `build_principal_from_context`；
- async provider resolution pattern。

这样不复制 RBAC policy engine，也不会在 A-SWE 背后静默替用户换模型。

### 10.8 Provider Contract Fingerprint

A-SWE 自己维护：

```text
ProviderContractFingerprint
```

绑定：

- provider id / role；
- backend agent type；
- capability bindings；
- required / optional tools；
- preferred skills；
- model policy；
- runtime ceilings。

最终 Trace 关联：

```text
ProviderContractFingerprint
        ↓
NodeExecutionPolicyFingerprint
        ↓
DeerFlowAssemblyFingerprint
```

从而区分：

> 我声明了什么、我编译了什么、Backend 实际装配了什么。

### 10.9 DeerFlow 映射

执行时：

```text
AgentProvider
     │
     ▼
CapabilityBinding
     │
     ▼
NodeExecutionPolicy
     │
     ▼
DeerFlowExecutionBackend
     │
     ├─ load operator SubagentConfig
     ├─ monotonic narrowing
     ├─ model authorization preflight
     └─ backend inventory / identity context
             │
             ▼
      Effective SubagentConfig
             │
             ▼
       SubagentExecutor
```

A-SWE Agent Registry 不实例化 LangGraph Agent，也不管理 Sandbox。

### 10.10 Agent Registry 不负责

Agent Registry 不负责：

- DAG Scheduling；
- Workspace Lock；
- Backend resource discovery；
- Runtime authorization；
- Sandbox 生命周期；
- Tool 实际执行；
- Skill 文件加载；
- MCP Session；
- Evaluation。

这些职责分别归 Resolver / Backend Adapter / Scheduler / Workspace Runtime / Evaluation。

---

## 11. Skills 系统设计

### 11.1 Skill 定位

Skill 表示：

> 执行某类任务所需要的知识、规范、SOP、操作经验和上下文模板。

Agent 表示执行主体，Skill 表示动态装配的能力增强。

因此不建议设计：

```text
PythonAgent
ReactAgent
DockerAgent
```

而更适合设计：

```text
Coder
+
Python Debugging Skill
```

或者：

```text
Coder
+
Pytest Skill
```

### 11.2 一期 Skills

一期只建设：

```text
repository-navigation
python-debugging
pytest
code-review
git
```

### 11.3 动态装配

Skill 在 P1 是 Provider 的 optional execution enhancement。

例如：

```text
Capability: python_debugging

Coder CapabilityBinding
+
preferred skill: python-debugging
```

或者：

```text
Capability: regression_testing

Tester CapabilityBinding
+
preferred skill: pytest
```

Adapter 可以将 Node 相关 Skill 收窄成 DeerFlow `SubagentConfig.skills` discoverability allowlist。

但：

> **allowlisted ≠ loaded ≠ used。**

### 11.4 Progressive Loading

继续复用 DeerFlow Harness 已有 Progressive Loading：

```text
Skill Metadata
      ↓
Discovery
      ↓
Model chooses to load / activate
      ↓
SKILL.md
      ↓
Reference / Script on Demand
```

A-SWE 不自行实现 Skill Loader。

### 11.5 DeerFlow Direct Subagent 的 Skill Boundary

DeerFlow 标准设计中，Subagent 的 `skills` 配置主要限制：

- Skill discovery；
- Skill activation；
- active skill 的 allowed-tools policy。

它不是：

```text
eager skill loading list
```

也不是：

```text
per-subagent filesystem isolation declaration
```

A-SWE 一期直接使用 `SubagentExecutor`，因此必须明确：

> **Phase 1 的 Skill allowlist 是 discoverability / activation policy，不宣称为每个 Subagent 独立的 filesystem security boundary。**

### 11.6 Skill Availability 与 Skill Usage

DeerFlow `AgentAssemblyDescriptor.enabled_skills` 只能证明：

> 该 Skill 在 assembly 时处于可发现的 enabled set。

不能证明：

> Agent 真正加载 / 激活 / 采用了该 Skill。

DeerFlow 对显式 skill activation 存在 server-owned usage metadata：

```text
skill_usage
skill_usages
```

并包含 skill path / content hash / activation mode 等 evidence。

但 P1 不把 Skill activation 设为普通 Node 的 hard feasibility requirement。

因此：

```text
preferred skill missing
→ warning

preferred skill enabled but unused
→ normal

hard MUST_ACTIVATE skill
→ P1 默认不支持
```

后续若增加 hard skill usage contract：

```text
SkillRequirement(MUST_ACTIVATE)
      ↓
Runtime skill-usage evidence
      ↓
content hash / activation provenance
```

而不是：

```text
enabled_skills contains X
→ claim X was used
```

### 11.7 一期 Skills

一期只建设或复用少量真正能提升执行质量的 Skill：

```text
repository-navigation
python-debugging
pytest
code-review
git
```

不以 Skill 数量作为项目复杂度指标。

---

## 12. MCP 集成设计

### 12.1 MCP 的正确定位

MCP 在 A-SWE 中不定义为 Capability 本身，而定义为：

> **External Tool / Context Provider Mechanism。**

关系为：

```text
Capability
    │
    ▼
Tool Requirement
    │
    ├── Built-in Tool
    │
    └── MCP Tool
            │
            ▼
       MCP Server
```

### 12.2 一期范围

一期只考虑 GitHub MCP，且不是强制依赖。

用途包括：

```text
repository_context
issue_context
pull_request_context
commit_history
```

如果本地 Repository 已具备足够上下文，一期可以优先使用本地 filesystem / git tool 完成核心 Demo。

### 12.3 Capability Mapping

例如：

```yaml
capability: issue_context

providers:
  tools:
    - source: mcp
      server: github
      tool: get_issue
```

A-SWE Runtime 关心的是：

```text
issue_context
```

而不是让上层 Team Builder 直接依赖：

```text
github.get_issue
```

---
