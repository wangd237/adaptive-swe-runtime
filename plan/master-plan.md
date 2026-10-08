# Adaptive Agent Runtime for Software Engineering 实施方案书

> 版本：MVP 面试项目收敛版（DeerFlow 源码审计后更新）  
> 项目简称：**A-SWE Runtime**  
> 核心目标：在较短实施周期内，完成一个可运行、可演示、可解释的自适应软件工程 Agent Runtime。

---

## 1. 项目概述

### 1.1 项目名称

**Adaptive Agent Runtime for Software Engineering（A-SWE Runtime）**

中文暂定名：

**面向软件工程的自适应智能体运行时系统**

### 1.2 项目定位

A-SWE Runtime 面向 Repository-Level Software Engineering Task，目标不是构建一个固定流程的 Coding Agent，也不是重复实现一套完整 Agent 基础设施，而是构建一个能够根据任务特征动态完成以下决策的软件工程智能体运行时：

- 当前任务需要哪些能力；
- 哪些 Agent / Skill / Tool 能够提供这些能力；
- 是否需要 Multi-Agent；
- 应构建怎样的 Agent Topology；
- 任务应如何拆解为可执行 DAG；
- 执行过程是否可观测、可追踪；
- 最终结果是否满足软件工程任务要求。

传统 SWE Agent 常采用固定执行结构，例如：

```text
Task
 ↓
Planner
 ↓
Coder
 ↓
Tester
 ↓
Reviewer
```

该模式的问题在于：

- 简单任务仍需经过完整 Multi-Agent 链路；
- 不同任务使用同一执行拓扑；
- Agent、Skill、Tool 之间缺少统一能力抽象；
- Runtime 很难解释“为什么选择这个 Agent”；
- Multi-Agent 协作可能引入不必要的 Token、时间与协调成本。

A-SWE Runtime 改为：

```text
Software Engineering Task
            │
            ▼
      Task Understanding
            │
            ▼
     Capability Analysis
            │
            ▼
    Capability Resolution
            │
            ▼
      Team Construction
            │
            ▼
        Task DAG
            │
            ▼
    Adaptive Execution
            │
      ┌─────┴─────┐
      ▼           ▼
   Trace      Evaluation
      │           │
      └─────┬─────┘
            ▼
          Result
```

项目当前默认通过 Adapter 对接 DeerFlow Harness，复用其 Subagent Execution、Skills、MCP、Sandbox、Context Management、Tool Receipt 等基础能力；A-SWE Runtime 自身保持独立，核心新增能力集中在任务理解、Capability Resolution、Workspace Runtime、动态团队构建、任务调度、Execution Trace 和 Evaluation。

### 1.3 核心项目命题

本项目一期需要证明的不是“Agent 能否写代码”，而是：

> **同一个 Runtime 面对不同软件工程任务，能够根据任务所需能力、复杂度和风险，生成不同的 Agent 执行结构。**

一句话定位：

> **A task-adaptive SWE agent runtime that dynamically composes capabilities, agents and execution topology.**

---

## 2. 项目建设目标

### 2.1 总体目标

建设一个面向软件工程任务的自适应 Agent Runtime，使系统能够自动完成：

1. 理解用户提交的软件工程任务；
2. 将自然语言任务转换为结构化 `TaskSpec`；
3. 创建并维护任务级 `WorkspaceSession`，保证同一任务内各执行节点共享稳定的软件工程工作区；
4. 识别任务所需 Capability；
5. 从 Agent、Skill、Tool、MCP Tool 中解析 Capability Provider；
6. 根据任务复杂度、风险和能力覆盖情况构建最小可行 Agent Team；
7. 生成 Task DAG，并显式标注节点对共享 Workspace 的 READ / WRITE 行为；
8. 调度 Agent、Skill 与 Tool 执行；
9. 记录 Runtime Decision、节点执行证据与底层 Harness Trace；
10. 对 Patch、测试结果和执行结果进行自动 Evaluation；
11. 输出结构化任务结果与运行指标。

### 2.2 一期建设重点

一期聚焦七个核心能力：

```text
1. Task Analyzer
2. Workspace Runtime
3. Capability Registry / Resolver
4. Dynamic Team Builder
5. Task Scheduler
6. Execution Trace / Observability
7. Evaluation
```

其中 `Workspace Runtime` 不是额外的 Agent，而是负责维护 Repository-Level Task 的共享执行身份与工作区生命周期。

### 2.3 一期明确不做

为了控制交付周期，一期不将以下能力作为必要目标：

- SWE-bench 等正式 Benchmark；
- 大规模 Experience Memory；
- Self-Improving / RL / Bandit；
- 复杂 `P(success | task, team)` 预测模型；
- Knowledge Graph；
- Agent Swarm；
- 大量 MCP Server；
- 多模型 Agent Ranking；
- 自动 Skill 生成；
- 大规模 Web UI 平台化建设；
- 分布式 Workspace / 多租户远程 Sandbox 平台；
- 复杂文件级冲突预测与自动 Merge。

一期重点是：

> **Runtime 核心链路能够真实运行，并能够通过 3～5 个 Demo Case 清晰展示不同任务产生不同执行拓扑，同时保证多个 DAG 节点在同一任务工作区内安全协作。**

---

## 3–14. Implementation Specifications

详细架构与实现规范已按职责拆分为唯一 authoritative source：

- [Task Understanding & Planning](../specs/01-task-planning.md)
- [Capability / Provider / Team](../specs/02-capability-provider-dag.md)
- [Execution Runtime](../specs/03-execution-runtime.md)
- [Evidence / Trace / Evaluation](../specs/04-evidence-evaluation.md)

Phase 0 DeerFlow 源码审计与架构冻结依据见：

- [DeerFlow Source Audit](../audits/deerflow-source-audit.md)
- [Architecture Conformance PoC Matrix](../tests/poc-matrix.md)

## 15. 核心运行流程

A-SWE Runtime 一期完整链路：

```text
TaskRequest
     │
     ▼
Runtime Policy Snapshot
     │
     ▼
Workspace Bootstrap
     │
     ▼
Basic RepositoryProfile
     │
     ▼
Task Analyzer
     │
     ├──────────────→ TaskSpec
     │
     └──────────────→ TaskContractDraft
                         │
                         ▼
                  Constraint Compiler
                         │
                         ▼
                  Compiled TaskContract
                         │
                         ▼
Targeted Repository Profiling
     │
     ▼
Planning Context Gate
   /       \
enough     gap
  │         │
  │         ▼
  │     Recon Probe
  │      READ ONLY
  │         │
  └────┬────┘
       ▼
PlanningContext
       │
       ▼
SemanticPlanner
       │
       ▼
WorkPlanProposal
       │
       ▼
PlanValidator / Normalizer
       │
       ▼
ValidatedWorkPlan
       │
       ▼
Node Capability Resolver
       │
       ▼
Provider Assignment
       │
       ▼
Minimal Team Builder
       │
       ▼
TeamSpec（roster only）
       │
       ▼
DAG Materializer
       │
       ▼
Executable TaskDAG
       │
       ▼
Workspace-Aware Scheduler
       │
       ▼
DeerFlowExecutionBackend
       │
       ▼
SubagentExecutor
       │
       ▼
Node Acceptance / Invariant / Handoff
       │
       ▼
Evaluation
       │
       ▼
Result
```

职责边界：

```text
SemanticPlanner
→ proposes bounded work packages

A-SWE Plan Compiler
→ validates and compiles execution semantics

A-SWE Scheduler
→ executes the already compiled DAG

DeerFlow
→ executes concrete bounded Agent nodes
```

Planning Phase 与 Execution Phase 在 Trace 中分开显示。

---

## 16. 工程目录与模块边界

### 16.1 推荐目录

```text
a-swe-runtime/
│
├── runtime/
│   ├── engine.py
│   ├── context.py
│   └── state.py
│
├── task/
│   ├── analyzer.py
│   ├── schema.py
│   ├── contract.py
│   ├── constraints.py
│   ├── provenance.py
│   ├── constraint_registry.py
│   ├── constraint_compiler.py
│   └── validator.py
│
├── reasoning/
│   ├── backend.py
│   ├── schema.py
│   └── errors.py
│
├── workspace/
│   ├── session.py
│   ├── manager.py
│   ├── access.py
│   ├── bootstrap.py
│   ├── repository.py
│   ├── profile.py
│   ├── invariants.py
│   └── changes.py
│
├── planning/
│   ├── schema.py
│   ├── context_gate.py
│   ├── recon.py
│   ├── planner.py
│   ├── validator.py
│   ├── normalizer.py
│   ├── node_boundary.py
│   ├── handoff.py
│   ├── handoff_renderer.py
│   ├── workspace_revision.py
│   ├── acceptance_compiler.py
│   └── materializer.py
│
├── capability/
│   ├── registry.py
│   ├── resolver.py
│   ├── bindings.py
│   ├── tool_effects.py
│   └── schema.py
│
├── team/
│   ├── builder.py
│   └── policy.py
│
├── scheduler/
│   ├── dag.py
│   ├── scheduler.py
│   ├── executor.py
│   ├── workspace_policy.py
│   └── retry.py
│
├── agents/
│   ├── registry.py
│   ├── provider.py
│   └── contract.py
│
├── skills/
│   ├── repository-navigation/
│   ├── python-debugging/
│   ├── pytest/
│   └── code-review/
│
├── evaluation/
│   ├── evaluator.py
│   ├── contract_evaluator.py
│   ├── acceptance.py
│   ├── checks.py
│   └── reviewer.py
│
├── observability/
│   ├── events.py
│   ├── event_bus.py
│   ├── evidence_store.py
│   ├── trace_store.py
│   └── metrics.py
│
├── integrations/
│   └── deerflow/
│       ├── backend.py
│       ├── reasoning.py
│       ├── inventory.py
│       ├── preflight.py
│       ├── preparation.py
│       ├── snapshot_store.py
│       ├── model_auth.py
│       ├── node_policy_store.py
│       ├── node_policy_outcome.py
│       ├── node_tool_policy.py
│       ├── handoff_context.py
│       ├── config_mapper.py
│       ├── assembly_attestation.py
│       ├── attestation_extension.py
│       ├── result_mapper.py
│       ├── report_verification.py
│       ├── acceptance_adapter.py
│       ├── contract_guardrail.py
│       └── trace_adapter.py
│
├── api/
│   └── routes.py
│
├── ui/
│   └── trace-viewer/
│
├── examples/
│   ├── simple_edit/
│   ├── bug_fix/
│   └── repo_refactor/
│
└── README.md
```

### 16.2 核心依赖方向

```text
TaskRequest
   ↓
Workspace / Repository Profile
   ↓
Task Understanding
   ↓
Planning
   ↓
Capability
   ↓
Team / Provider Set
   ↓
DAG Materialization
   ↓
Scheduler
   ↓
Execution Backend
   ↓
Evaluation
```

### 16.3 依赖约束

- `workspace/` 不依赖 Team Builder；
- Repository lifecycle 属于 `workspace/` Runtime infrastructure；
- `task/` 不依赖具体 Agent；
- `reasoning/` 只定义 provider-neutral structured reasoning contract；
- Task Analyzer / SemanticPlanner 只能通过 `ReasoningBackend` 调用模型；
- `planning/` 不依赖 DeerFlow；
- SemanticPlanner 不直接读取 Agent roster；
- `capability/` 不依赖 DeerFlow；
- `team/` 只形成 roster，不拥有 topology；
- topology 只由 `planning/materializer.py` 形成；
- `scheduler/` 禁止重新 decomposition；
- `scheduler/` 只执行已编译 TaskDAG；
- `observability/` 不参与业务决策；
- 所有 DeerFlow-specific 逻辑集中在 `integrations/deerflow/`。

### 16.4 Anti-Corruption Layer

`integrations/deerflow/` 负责：

```text
TaskNode
AgentProvider
WorkspaceSession
Node Handoff Context
      ↓
DeerFlow SubagentConfig / SubagentExecutor
      ↓
SubagentResult
      ↓
NodeExecutionResult / NodeAcceptanceResult
```

A-SWE 核心 Planning / Scheduler 代码禁止散落 `deerflow.*` import。

DeerFlow integration 分为两条 Anti-Corruption seam：

```text
ReasoningBackend
→ DeerFlow ModelInvoker

ExecutionBackend
→ DeerFlow SubagentExecutor
```

P1 暂不使用 `AgentRuns` 作为细粒度 DAG Worker，因为 AgentRuns 的 Custom Agent 与 thread 绑定，而 A-SWE 需要多个不同 Provider 共享同一 WorkspaceSession / thread filesystem。

---

## 17. 项目核心技术亮点

### 17.1 Capability-Centric Runtime

以 Capability 而非 Agent 作为 Runtime 的语义调度中心。

```text
Task Requirement
      ↓
Capability
      ↓
Provider
      ↓
Agent / Skill / Tool
```

核心价值：降低任务需求与具体执行主体之间的耦合。

### 17.2 Adaptive Team Formation

根据任务：

```text
Complexity
Risk
Scope
Capability Requirement
```

动态选择不同 Agent Topology。

核心思想：

> **什么时候不使用 Multi-Agent，同样是 Runtime 的核心能力。**

### 17.3 Minimal Feasible Team Policy

一期不虚构复杂成功率预测，而使用：

```text
Capability Coverage
+
Risk Constraint
+
Minimal Team
```

形成可解释、可实现的团队选择逻辑。

### 17.3.1 Provider Feasibility Ladder

A-SWE 不把 Registry 声明当成 execution truth。

```text
DECLARED
   ↓
PREFLIGHT_FEASIBLE
   ↓
ASSEMBLED_MATCH
   ↓
EXECUTED
   ↓
ACCEPTED / EVALUATED
```

这一分层让系统可以解释：

> 一个 Agent“理论上会做”、当前部署“看起来能做”、运行时“实际拿到了什么”、以及最终“有没有做成”，是四个不同问题。

### 17.4 Workspace-Aware Task DAG Scheduling

A-SWE 不仅调度依赖关系，还显式调度共享 Repository 状态：

```text
Task DAG
   +
READ / WRITE Side Effect
   +
WorkspaceSession
```

一期以“READ / READ 可并行，存在 WRITE 即串行”的保守规则保证 correctness。

这使 Scheduler 的价值不仅是并发执行，而是：

> **在共享代码工作区上安全组织多个执行主体。**

### 17.5 Control Plane / Execution Plane Separation

```text
A-SWE Control Plane
→ what / who / when

DeerFlow Execution Plane
→ how to execute safely
```

A-SWE 不重复实现 Agent Harness，而是将核心工程价值集中在 Runtime Decision 与 Scheduling。

### 17.6 Layered Observability

可观测性分为：

```text
Runtime Decision Trace
Node Execution Evidence
Backend LLM / Tool Trace
```

既能解释“为什么这样调度”，又不重复底层 Harness 的 tracing。

### 17.7 Evaluation First

任务执行结束不等于任务完成。

必须经过：

```text
Node Acceptance
Tests
Build / Import
Regression Check
Review
```

再决定最终状态。

---

## 18. 一期实施范围

### 18.1 Runtime Core

必须完成：

```text
Task Analyzer
Workspace Runtime
Capability Registry
Capability Resolver
Dynamic Team Builder
Task Scheduler
Execution Trace
Evaluation
```

### 18.2 Agent

只实现：

```text
Repo Explorer
Coder
Tester
Reviewer
```

其中：

```text
Explorer → READ
Coder    → WRITE
Tester   → READ（生成测试文件时可升级为 WRITE）
Reviewer → READ
```

具体 Workspace Access 最终以 TaskNode 行为为准，而不是仅按角色硬编码。

### 18.3 Skills

只实现：

```text
repository-navigation
python-debugging
pytest
code-review
```

可选：

```text
git
```

### 18.4 Tool / MCP

基础：

```text
filesystem
shell
code search
git read-only exploration
```

其中必须区分：

```text
Runtime-owned Git operations
→ clone / checkout / base SHA freeze / invariant / final patch

Agent-available Git operations
→ status / log / show / diff 等任务探索
```

一期不将 Repository lifecycle operation 作为普通 `git_operation` Capability 下放给 Agent。

可选：

```text
GitHub MCP
```

GitHub MCP 不应阻塞 MVP 主链路。

### 18.5 Memory

一期只保留必要的运行态 Task Context 与 WorkspaceSession。

暂不单独建设复杂：

```text
Repository Memory
Experience Memory
Long-term Vector Memory
```

Execution Trace 为后续 Experience Memory 提供数据基础。

### 18.6 Sandbox / Deployment Boundary

一期区分两类执行模式：

```text
Development / Trusted Fixture:
LocalSandboxProvider + allow_host_bash=true

Default SWE Execution:
AioSandboxProvider + Local Container Backend
```

DeerFlow 的 LocalSandbox 会直接在 Gateway / Host 文件系统上执行命令，没有容器隔离。因此：

> **LocalSandbox 只用于受信任的 Demo Fixture、本地开发和调试，不作为任意外部 Repository 的默认执行环境。**

真实 Repository-Level SWE Task 需要执行 `pytest`、`npm test`、`make`、安装依赖等潜在不可信代码，一期默认推荐使用本地 AIO Container Sandbox。

核心要求：

- 同一 `user_id + thread_id` 可以稳定映射到同一任务 Workspace；
- Sandbox release / warm reuse 不破坏 Workspace 中的 Repository 文件状态；
- 多个 Node 可以在同一 WorkspaceSession 上连续执行。

一期不承诺：

```text
Remote AIO / K8s provisioner
cross-region shared workspace
multi-worker remote filesystem persistence
```

远程 Sandbox 可能依赖显式文件同步或共享存储，必须独立验证后再进入支持范围。

Private Repository Auth 一期作为 optional integration。DeerFlow GitHub Webhook Channel 可以注入 GitHub App installation token，但 A-SWE Direct Runtime 不应默认假设自动获得该 token。MVP 必须稳定支持 public HTTPS repo 与 local fixture repo；private clone / push 需要单独设计 RepositoryCredential / GitHub integration boundary。

### 18.7 Demo Case

一期准备 3～5 个可稳定复现的 Demo。

#### Demo 1：简单修改

```text
README / config small edit
→ Coder
```

证明：

> Runtime 不会无意义创建 Multi-Agent Team。

#### Demo 2：普通 Python Bug

```text
Explorer
 ↓
Coder
 ↓
Tester
```

同时证明：

> Explorer、Coder、Tester 共享同一 WorkspaceSession，Tester 能看到 Coder 的修改。

#### Demo 3：高风险 Bug

```text
Explorer
 ↓
Coder
 ↓
Tester
 ↓
Reviewer
```

#### Demo 4：跨模块探索

```text
Explorer A ─┐
            ├─ READ / READ parallel
Explorer B ─┘
      ↓
    Coder        WRITE exclusive
      ↓
    Tester
      ↓
   Reviewer
```

Demo 重点展示：

```text
Same Runtime
Different Task
Different Agent Topology
Shared Workspace
Explainable Scheduling
```

---

## 19. 实施原则

### 19.1 核心 Runtime 自主、Infrastructure 复用

项目主要工程价值集中在：

```text
Task → Capability
Capability → Provider
Capability → Team
Team → DAG
DAG → Execution
Execution → Trace
Execution → Evaluation
```

基础 Agent Harness、Sandbox、Skill Loader 等成熟能力尽量复用。

### 19.2 Adapter 隔离

不得让 A-SWE 的核心模块大量直接引用 DeerFlow 内部类。

优先通过：

```text
Adapter
Interface
Schema
Event
```

形成明确边界。

### 19.3 可解释优先

Dynamic Team 每次选择必须可解释。

系统不能只输出：

```text
selected = tester
```

还需要输出：

```text
selected tester because regression_testing is required
```

### 19.4 Evaluation First

新增 Agent、Skill 或 Tool 时，应明确：

- 它解决什么 Capability；
- 什么时候被选择；
- 如何判断任务执行成功。

### 19.5 Progressive Complexity

项目演进：

```text
Rule-based Runtime
       ↓
LLM-assisted Runtime
       ↓
Trace-aware Runtime
       ↓
Experience-aware Runtime
       ↓
Performance-driven Runtime
```

一期停留在前三层即可。

### 19.6 Demo First

每完成一个 Runtime 能力，都优先保证：

```text
可运行
可观察
可解释
可 Demo
```

而不是继续增加抽象层级。

---

## 20. 阶段性实施计划

### Phase 0：Integration Validation / Architecture Freeze

状态：

```text
Design Frozen
PoC Execution Pending
```

Phase 0 的详细源码审计、冻结结论、Go/No-Go 与 PoC 位于：

- [audits/deerflow-source-audit.md](../audits/deerflow-source-audit.md)
- [tests/poc-matrix.md](../tests/poc-matrix.md)

`Design Frozen` 表示 schema ownership 与 P1 execution semantics 已收口，可以开始 Core/FakeBackend 实现；它不表示真实 DeerFlow integration PoC 已通过。

冻结后若要修改下列核心 contract：

```text
TaskContract / ValidatedWorkPlan
TaskNode / TaskDAG
WorkspaceAccess / WorkspaceRevision
EvidenceRef / TaskEvidenceRef / NodeHandoff
NodeRuntimeState / dispatch commit
Retry / Repair / Reverify
TaskResult / ContractVerdict
Backend quiescence contract
```

必须显式 reopen Design Freeze，并同步：

1. authoritative Spec；
2. audit conclusion；
3. PoC matrix；
4. affected implementation tests。

### Phase 1：Adaptive SWE Runtime MVP

这是当前唯一必须完成的产品阶段。

#### Phase 1 Authoritative Coding Order

下面的 **P1-1～P1-7 是功能 workstream，不是 Git commit / 编码先后顺序**。

实际实现必须按以下顺序推进：

##### Coding Step 0：Core Contracts + Deterministic Test Harness

先实现纯 Python、无 DeerFlow execution、无 LLM 的 contracts：

```text
core/contracts/
core/config/
core/ids/
tests/fakes/
```

至少落地：

- Task / Planning contracts 的基础 shared types；
- `WorkspaceAccess`；
- `EvidenceRef / TaskEvidenceRef / ReceiptRef / NodeHandoff`；
- `TaskNode / TaskDAG`；
- Runtime failure/status enums；
- Runtime budget config；
- canonical serialization / fingerprint helpers；
- `FakeExecutionBackend`；
- deterministic Workspace/Fake execution fixtures。

Exit Criteria：

- active schema 可直接 import；
- fingerprint deterministic；
- `POC-F01 ~ F06` 对应 static/unit checks 通过；
- **不调用 LLM，不依赖 DeerFlow SubagentExecutor。**

##### Coding Step 1：Evidence + Workspace / Git Substrate

实现：

```text
evidence/
workspace/
repository/
trace/minimal_events.py
```

顺序：

1. `LocalEvidenceStore.put_attempt / put_task / get`；
2. 最小 RuntimeEvent sink（先服务调试，不做 UI）；
3. `WorkspaceSession / RepositoryBinding`；
4. Repository bootstrap / exact base SHA；
5. `RepositoryStateDigest` temporary-index implementation；
6. `WorkspaceRevision`；
7. `NodeWorkspaceDelta`；
8. READ/WRITE workspace lock manager；
9. FROZEN / QUARANTINED lifecycle substrate。

Exit Criteria：

- Git state/delta 可确定性测试；
- attempt/task evidence provenance 不混用；
- workspace lock/revision tests 在无 Agent 环境通过。

##### Coding Step 2：Scheduler State Machine on FakeBackend

这是 **第一阶段真正的项目核心**。

实现：

```text
runtime/state.py
runtime/scheduler.py
runtime/dispatch.py
runtime/remediation.py
runtime/finalization.py
```

先只接 `FakeExecutionBackend`，完成：

- `NodeRuntimeState / NodeAttemptRecord`；
- Ready predicate；
- `SchedulerStateMutex`；
- `NodeDispatchTicket`；
- `DependencyAcceptanceStamp / acceptance_epoch`；
- `TaskDispatchGate`；
- Workspace arbitration；
- dispatch commit；
- cancellation；
- Retry / Repair / Reverify transitions；
- task-wide dirty fail-close；
- FROZEN / QUARANTINED drain；
- `RootFailureRecord / TaskResult` state assembly。

Exit Criteria：

- `POC-R16 ~ R26`；
- `POC-R75 ~ R108`；
- **尤其 `POC-R109 ~ R126`**；
- 全部先在 deterministic FakeBackend 下通过。

原则：

> **如果 FakeBackend 状态机都不能证明正确，不允许用 DeerFlow/LLM 的复杂行为掩盖问题。**

##### Coding Step 3：Task / Contract / Planning Compiler

实现：

```text
planning/profile.py
planning/analyzer.py
planning/contracts.py
planning/constraints.py
planning/planner.py
planning/validator.py
planning/acceptance.py
```

完成：

- RepositoryProfile / AnchorMatch；
- TaskSpec；
- ReasoningBackend interface + fake reasoning backend；
- TaskContractDraft；
- provenance validation；
- ConstraintCompiler / merge algebra；
- CompiledTaskContract；
- TaskExecutionAuthority；
- WorkPlanProposal；
- PlanValidator / Normalizer；
- `ValidatedWorkPlan`；
- VerificationCommand / Acceptance Compiler。

Exit Criteria：

- P0-3 semantic-plan tests；
- `POC-C01 ~ C10`；
- planner 输出永远不能直接进入 Scheduler。

##### Coding Step 4：Capability / Provider / DAG Compiler

实现：

```text
capabilities/
providers/
planning/dag.py
```

完成：

- Capability Registry；
- CapabilityBinding；
- AgentProvider Registry；
- provider-neutral BackendInventory interface；
- ProviderAssignment；
- TeamSpec；
- ToolEffect / WorkspaceAccess compiler；
- TaskDAG Materializer；
- phase/workspace conflict normalization；
- VerificationRepairBinding；
- CompiledPlanDescriptor。

Exit Criteria：

- P0-3 DAG tests；
- P0-5 中不依赖真实 DeerFlow 的 contract/preflight tests；
- 同一个 ValidatedWorkPlan deterministically 生成相同 TaskDAG fingerprint。

##### Coding Step 5：DeerFlow Integration Adapter

只有 Core/Scheduler/compiler 已可独立测试后，才接真实 DeerFlow：

```text
integrations/deerflow/
```

实现顺序：

1. inventory adapter；
2. `DeerFlowReasoningBackend / ModelInvoker`；
3. `NodeExecutionPreparation(preparation_id)`；
4. AppConfig/tool/model snapshot pinning；
5. `NodeExecutionInvocation` mapping；
6. `NodeExecutionBindingStore`；
7. trusted ToolPolicy / Handoff middleware；
8. SubagentExecutor result mapper；
9. independent completion/quiescence compatibility seam；
10. cancellation join；
11. Acceptance / receipt-citation adapters；
12. AssemblyAttestation；
13. fresh-shell deterministic verification profile。

Go / No-Go：

真实 shared mutable Workspace execution 在关键 DeerFlow integration PoC 通过前仍关闭。至少覆盖：

```text
POC-02 / 03 / 05 / 09
POC-R34 / 35 / 36 / 38
POC-R50 / 51
POC-R69 / 70 / 73
```

##### Coding Step 6：Cross-Node SWE Semantics

在真实 Adapter 合同成立后接完整 Node 语义：

- Repo Explorer / Coder / Tester / Reviewer Provider definitions；
- bounded prompts；
- Skills 作为 optional enhancement；
- Handoff renderer / projector；
- evidence finalization；
- NodeAcceptanceResult；
- RepairAttributionResolver；
- RepairFeedback；
- REVERIFY；
- structured Review direct-return tool；
- ReviewEvidenceResolver。

这里才开始认真调 Agent prompt / Skill；**不要把 prompt engineering 放在 Runtime state machine 之前。**

Exit Criteria：

- H-series PoC；
- unique-writer / repair loop；
- structured review gate；
- one complete single-writer repair scenario。

##### Coding Step 7：Task Finalization + Evaluation

实现：

```text
evaluation/
runtime/finalization.py
```

完成：

- TaskContractEvaluator；
- ContractVerdict；
- final RepositoryState / RepositoryChangeSet TaskEvidence；
- residual unaccepted patch；
- TaskResult；
- root failure aggregation；
- stable / quarantine terminal paths。

Exit Criteria：

- Task SUCCEEDED 必须有 final ContractVerdict；
- dirty failure / residual patch / quarantine cases deterministic；
- no “LLM says done → task success” shortcut。

##### Coding Step 8：Observability + Demo Packaging

最后补齐：

- full RuntimeEvent vocabulary；
- Trace Store；
- Decision Timeline；
- metrics；
- simple Trace Viewer；
- README architecture/demo；
- 3～5 个 stable scenarios。

一期 benchmark 仍不作为主线 blocker。

#### Coding Order Rule

```text
Contracts
→ Evidence/Workspace
→ Scheduler(FakeBackend)
→ Planning Compiler
→ Capability/DAG Compiler
→ DeerFlow Adapter
→ SWE Agent Semantics
→ Evaluation/Finalization
→ Trace UI/Demos
```

任何后续实现 PR 若跨越该依赖顺序，必须说明为什么不会让未冻结/未测试的下层 contract 被上层代码反向定义。


#### P1-1：Runtime Skeleton + Workspace Runtime

完成：

- 独立 A-SWE 工程目录；
- `ExecutionBackend` Interface；
- `DeerFlowExecutionBackend`；
- `SubagentExecutor` Adapter；
- Runtime State / Context；
- `WorkspaceSession`；
- `RepositoryBinding`；
- Repository Bootstrap；
- `resolved_base_sha` freeze；
- Repository clean baseline check；
- baseline workspace snapshot；
- Repository invariant；
- Repository ChangeSet；
- temporary-index RepositoryStateDigest / working_tree_oid；
- Git submodule / sparse-checkout P1 bootstrap rejection；
- Workspace identity：`task_id → user_id + thread_id`；
- shared execution capacity；
- DeerFlow compatibility integration tests；
- fresh-shell deterministic-verification reference Sandbox profile；
- AIO persistent-shell evidence limitation documented。

目标：

```text
Task Node
+
WorkspaceSession
→
DeerFlow Subagent Execution
```

#### P1-2：Task Understanding + Planning Pipeline

完成：

- RepositoryProfile；
- Basic / Targeted Profiling；
- ReasoningBackend；
- DeerFlowReasoningBackend / ModelInvoker adapter；
- TaskSpec；
- TaskContractDraft；
- Constraint Provenance Validation；
- Constraint Registry / Merge Algebra；
- ConstraintCompiler；
- CompiledTaskContract / fingerprint；
- Contract coverage validation；
- TaskExecutionAuthority projection；
- Capability authority validation；
- Task Analyzer；
- Planning Context Gate；
- Read-only Recon Probe；
- PlanningContext；
- SemanticPlanner；
- WorkPlanProposal；
- NodeBoundaryPolicy；
- PlanValidator；
- PlanNormalizer；
- ValidatedWorkItem / ValidatedWorkPlan；
- PlanRepair / PlanWarning；
- Acceptance Compiler；
- VerificationCommand / command identity；
- acceptance-derived sandbox evidence requirements。

目标：

```text
Task + Repository Evidence
→
ValidatedWorkPlan
```

#### P1-3：WorkPlan → Capability → Team → DAG

完成：

- provider-neutral CapabilitySpec；
- CapabilityAuthorityClass / workspace_effect_floor；
- CapabilityBinding；
- Node-Level Capability Resolver；
- Agent Registry；
- AgentProvider / ProviderContract；
- BackendInventorySnapshot；
- Sandbox evidence feature inventory / preflight；
- Provider preflight feasibility；
- ProviderContract fingerprint；
- Minimal Feasible Team Policy；
- TeamSpec（roster only）；
- WorkspaceRevision；
- NodeHandoff dual-channel schema；
- Handoff evidence authority；
- deterministic multi-parent handoff merge；
- revision-aware HandoffEvidenceProjection / renderer；
- WorkspaceAccess；
- DAG Materializer；
- TaskNode / TaskDAG / WorkKind；
- VerificationRepairBinding compilation；
- ToolEffect Registry；
- Capability + Tool Effect workspace access compiler；
- deterministic workspace-conflict serialization。

目标：

```text
ValidatedWorkPlan
→
Executable TaskDAG
```

#### P1-4：Workspace-Aware Execution

完成：

- Scheduler / SchedulerStateMutex linearization；
- Ready Node calculation；
- revocable NodeDispatchTicket / dispatch commit；
- dependency acceptance_epoch / DependencyAcceptanceStamp；
- TaskDispatchGate epoch；
- NodeExecutionPreparation / preparation_id；
- NodeExecutionInvocation / post-commit execution identity；
- live Backend revalidation；
- Backend snapshot pinning；
- `BACKEND_PREFLIGHT_STALE` classification；
- Dependency Handoff Routing；
- ASWEHandoffContextMiddleware；
- request-scoped dependency context projection；
- Handoff staleness / revision check；
- RepairAttributionResolver / RepairAttributionEvidence；
- atomic Writer reopen + accepted_handoff revocation；
- RepairFeedback routing；
- READ / WRITE Workspace Access；
- provably READ-only Basic Parallel Execution；
- WRITE / UNKNOWN-MUTATING Exclusive Execution；
- ContractGuardrailProvider integration；
- BashCommandPolicy DENY / EXACT_ALLOWLIST；
- managed foreground-shell contract；
- Pre-tool constraint guard；
- monotonic SubagentConfig narrowing；
- identity-aware Tool / Model authorization preflight；
- NodeExecutionBindingStore / NodeExecutionInvocation；
- trusted ASWENodeToolPolicyMiddleware；
- first-model / every-model required-tool admission gate；
- synthetic policy-failure ModelResponse short-circuit；
- A-SWE failure marker → structured failure mapping；
- final model-visible tool filtering；
- required runtime output tool contract；
- tool-call name-level deny backstop；
- A-SWE AgentAssemblyObserver extension；
- DeerFlow AssemblyAttestation；
- PROVIDER_ASSEMBLY_MISMATCH classification；
- Post-node Git-aware contract invariant；
- RepositoryStateDigest / semantic mutation authority invariant；
- NodeAttemptRecord / NodeRuntimeState；
- Retry / Repair / Reverify attempt state machine；
- Cancellation；
- DeerFlow independent background-completion/quiescence compatibility seam；
- WorkspaceSession QUARANTINED fail-safe；
- fixed Workspace→Backend-capacity resource ordering；
- capacity backpressure hint + lock-hoarding metrics；
- BackendExecutionPhase / pre-start vs started failure semantics；
- ExecutionCompleteness / capped-partial logical acceptance gate；
- NodeAcceptanceResult / acceptance EvidenceRef；
- Failure Propagation；
- task-wide dirty fail-closed / Workspace FROZEN semantics；
- TaskResult + Workspace/Repository/Patch disposition；
- residual unaccepted patch finalization；
- Result Aggregation；
- Node Acceptance Gate；
- WRITE Node 后 Repository Invariant Check；
- NodeHandoff generation；
- mandatory WRITE / UNKNOWN-mutating before/after workspace snapshot；
- NodeWorkspaceDelta + truncation fail-safe。

#### P1-5：Execution Trace

完成：

- RuntimeEvent；
- Event Bus；
- Trace Store；
- Decision Timeline；
- Node Execution Evidence；
- ExecutionEvidenceStore；
- ToolReceiptLedgerEvidence / ledger-backed ReceiptRef；
- attempt-scoped EvidenceRef；
- task-scoped TaskEvidenceRef for terminal finalization；
- backend trace correlation；
- Metrics；
- 简单 Trace Viewer。

#### P1-6：Evaluation

完成：

- DeerFlow Receipt Citation Verification Adapter；
- DeerFlow Acceptance Adapter；
- Build / Import Check；
- Test Execution；
- Regression Test；
- Reviewer + structured `submit_review_verdict` direct-return gate；
- citing-turn ReviewEvidenceResolver；
- Git-aware task-level Repository ChangeSet；
- per-attempt NodeWorkspaceDelta；
- DeerFlow Workspace ChangeSet；
- TaskContractEvaluator / ContractVerdict / final_contract_verdict TaskEvidenceRef；
- Evaluation Report。

#### P1-7：Demo Packaging

完成 3～5 个稳定 Demo：

```text
Simple Task
Normal Bug
High-Risk Bug
Repository-Level Exploration
```

并在 README 展示：

```text
Task
→ Workspace / Repo Profile
→ Semantic Work Plan
→ Plan Validation
→ Capability / Provider Resolution
→ Selected Team
→ Compiled DAG
→ Workspace-Aware Scheduling
→ Trace
→ Evaluation
→ Result
```

### Phase 2：Memory & Experience（非一期目标）

后续可增加：

- Repository Memory；
- Experience Memory；
- Historical Task Retrieval；
- Similar Task Matching；
- Team Execution Statistics；
- Skill Effectiveness Statistics；
- Workspace conflict statistics。

核心目标：

> 让过去的任务执行数据开始影响未来决策。

### Phase 3：Cost / Performance-Aware Selection（非一期目标）

在具有足够 Trace 数据以后再增加：

- historical success rate；
- token cost；
- execution time；
- retry cost；
- coordination cost；
- workspace contention cost；
- Team Ranking。

此时才引入真正有数据支撑的 Cost-Aware Team Selection。

### Phase 4：Experience-Driven Adaptation（远期）

可进一步研究：

```text
Execution Trace
      ↓
Experience Extraction
      ↓
Team / Skill / Scheduling Statistics
      ↓
Selection Policy Update
      ↓
Future Runtime Decision
```

在具备实际自动策略更新机制前，不将项目核心宣传为 Self-Improving Runtime。

---

## 21. 面试展示与项目包装重点

### 21.1 不将项目包装为普通 Coding Agent

项目不是：

> 一个可以自动写代码的 Multi-Agent 系统。

而是：

> **一个能够根据 Software Engineering Task 动态构建执行能力、Agent Topology 与 Workspace-aware Task DAG 的 Runtime。**

### 21.2 README 首页首先展示 Adaptive Topology

建议 README 首屏展示：

```text
Task A
"Fix README typo"

A-SWE Runtime
→ Coder
```

```text
Task B
"Fix Python API regression"

A-SWE Runtime
→ Explorer → Coder → Tester
```

```text
Task C
"Fix high-risk database lifecycle bug"

A-SWE Runtime
→ Explorer → Coder → Tester → Reviewer
```

然后展示一个并行探索案例：

```text
Explorer A ─┐
            ├─ parallel READ
Explorer B ─┘
      ↓
Coder            exclusive WRITE
```

强调：

> **Same runtime. Different task. Different agent topology. One controlled workspace.**

### 21.3 面试必须能够讲清楚的问题

至少准备以下问题：

1. 为什么选择 Runtime，而不是再做一个 Coding Agent？
2. 为什么 Capability 比 Agent 更适合作为调度中心？
3. Capability 与 Plugin 有什么区别？
4. Agent、Skill、Tool、MCP 分别是什么角色？
5. 为什么不是所有任务都使用 Multi-Agent？
6. Dynamic Team 如何选择？
7. 为什么一期使用 Minimal Feasible Team，而不是成功率预测模型？
8. Task Scheduler 如何构建和执行 DAG？
9. 为什么 SWE Agent 需要独立的 WorkspaceSession？
10. 多个 Agent 共享同一 Repository 时如何避免并发写冲突？
11. 为什么 READ / READ 可以并行，而 MVP 中 WRITE 默认独占？
12. Retry、Cancellation 与 Failure Propagation 如何处理？
13. A-SWE 为什么直接使用 DeerFlow `SubagentExecutor` 而不是让 Lead Agent 自主 delegation？
14. A-SWE Control Plane 与 DeerFlow Execution Plane 的边界是什么？
15. `SubagentResult` 如何映射为 NodeExecutionResult？
16. Tool Receipt 与完整 Trace 有什么区别？
17. 为什么 Acceptance Checker 要从 DeerFlow 回接，而不是自己重写？
18. Execution Trace 为什么不仅仅是日志？
19. Evaluation 为什么优先使用确定性检查？
20. Direct Subagent 的 Skill projection 有什么已知边界？
21. 为什么一期要区分 Sandbox execution capability 与 deterministic-evidence capability？
22. 为什么 CapabilitySpec 不直接保存 required_tools / eligible_agents？
23. CapabilityBinding 为什么属于 Provider，而不是 Capability？
24. Backend Inventory 与 DeerFlow Assembly Attestation 有什么区别？
25. 为什么 SubagentConfig.tools 不能当作实际 Tool 可用性证明？
26. A-SWE 如何保证 Node policy 不扩大 operator SubagentConfig 权限？
27. enabled skill 与 skill activation / usage 有什么区别？
28. 为什么 AssemblyObserver 不能作为 execution safety gate？
29. direct SubagentExecutor 的 model authorization 边界是什么？
30. 为什么 SubagentConfig.tools 不是最终 schema allowlist？
31. packaged Extension middleware 与 trusted extensions.middlewares 有什么权限差异？
32. 为什么 NodeToolPolicy 与 ContractGuardrail 要分开？
33. 为什么 WorkspaceAccess 要按最终 allowed tools，而不是 required tools 计算？
34. NodeExecutionBindingStore 为什么一期只承诺 single-process？
35. 为什么 planning-time preflight 之后还需要 prepare_node？
36. Backend inventory fingerprint 变化为什么不应该自动判失败？
37. 为什么 authorization 不能被当成 frozen snapshot？
38. 为什么 P1 不在 runtime 自动切换另一个 Provider？
39. DeerFlow 的 one-AppConfig-snapshot 设计如何减少 TOCTOU？
40. 为什么 Tester 可以获得 WRITE lock，却仍然不能修改 Git-visible Repository patch？
41. 为什么 DeerFlow `completed + stop_reason` 不能直接映射为 A-SWE Node success？
42. 为什么 mandatory Review 不能只解析 Reviewer 自由文本，而要用 structured direct-return verdict？
43. 为什么 Review direct-return verdict 不能复用普通 self-report receipt verifier？
44. 为什么 executor quiescence 不等于 AIO container/process quiescence？
45. 为什么 P1 的 bash 使用 exact Runtime allowlist，而不是允许 Agent 自由拼 shell？
46. 为什么“Sandbox 能执行 pytest”不等于 DeerFlow tests_passed 能产生确定性通过证据？
47. 为什么 AIO 在 pinned baseline 下不是 P1 deterministic regression reference backend？
48. 为什么 VerificationCommand 必须同时生成 acceptance criterion 和 bash authority？

### 21.4 代码掌握边界

需要重点掌握并能够现场解释的代码：

```text
Task Analyzer
WorkspaceSession / Workspace Manager
Capability Registry / Resolver
Dynamic Team Builder
Selection Policy
Task DAG
Workspace Access Policy
Scheduler
Execution Trace
Evaluation
DeerFlowExecutionBackend
BackendInventory / ProviderPreflight
SubagentConfig Narrowing
AssemblyAttestation
ContractGuardrailProvider
Acceptance Adapter
Result Mapper
```

对于底层成熟基础设施，应能够解释：

```text
SubagentExecutor 如何调用
thread_id / user_id 如何绑定 workspace
Sandbox Lease 为什么复用
Tool Receipt 如何进入节点证据
为什么不重复实现 Skill / MCP / Sandbox
```

而不是将主要时间投入重复实现 Sandbox、MCP Client 或 LangGraph Engine。

### 21.5 面试中的核心架构表述

推荐表述：

> **A-SWE is the control plane. DeerFlow is the execution plane.**

进一步展开：

```text
A-SWE:
Task → Contract → Capability → Provider Preflight → Team → DAG → Scheduling → Evaluation

DeerFlow:
Subagent → Skill / Tool / MCP → Sandbox → Execution Evidence
```

这比“我在 DeerFlow 上又套了一层 Multi-Agent”更准确，也更能体现 Runtime 设计价值。

---

## 22. 项目最终定位

A-SWE Runtime 最终不定义为：

> 一个拥有很多 Agent 的软件开发系统。

更准确的定义是：

> **A task-adaptive control plane for resolving software engineering capabilities, managing a shared repository workspace, composing the minimum feasible agent team, scheduling workspace-aware task DAGs, and tracing/evaluating execution on top of a reusable agent execution plane.**

其核心执行链路为：

```text
Task
 ↓
WorkspaceSession
 ↓
Capability
 ↓
Team
 ↓
Task DAG
 ↓
Workspace-Aware Scheduling
 ↓
DeerFlow Execution Plane
 ↓
Execution Evidence
 ↓
Evaluation
```

项目核心思想可以概括为：

> **Don't build one SWE agent. Build the runtime that assembles the right execution structure for each software engineering task.**

进一步补充：

> **A-SWE owns runtime decisions and shared-workspace scheduling; DeerFlow owns safe agent execution.**

对应中文：

> **不是构建一个固定的软件工程 Agent，而是构建一个能够针对不同软件工程任务动态组装能力、执行主体和协作拓扑，并在同一 Repository Workspace 上安全调度这些执行主体的运行时控制面。**

一期项目的成功标准不是功能数量，而是：

1. 核心链路真实运行；
2. 不同任务能够产生不同 Team / DAG；
3. 同一任务内多个 Node 能共享稳定 Workspace；
4. READ / WRITE 调度规则能够避免基础并发冲突；
5. A-SWE 能通过 Adapter 直接驱动 DeerFlow SubagentExecutor；
6. Runtime Decision 能够通过 Trace 解释；
7. Node 执行具有 Tool Receipt / Acceptance 等证据；
8. 最终结果能够通过 Evaluation 验证；
9. 3～5 个 Demo Case 能稳定展示整个流程。
