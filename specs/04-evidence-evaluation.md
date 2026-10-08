# Evidence / Trace / Evaluation Specification

> Authoritative implementation specification. 已经 P0 consistency sweep / Design Freeze 收口；Trace/Evaluation/ContractVerdict 语义以本文为准。

## 13. Execution Trace / Observability

### 13.1 模块定位

Execution Trace 是一期核心模块，但 A-SWE 不重复实现 DeerFlow 已有的低层 LLM / Tool tracing。

一期采用三层 Trace：

```text
┌────────────────────────────────────────────┐
│          Layer 1: A-SWE Decision Trace     │
│                                            │
│ TaskAnalyzed                               │
│ CapabilityResolved                        │
│ TeamSelected                              │
│ DAGCreated                                 │
│ NodeDispatchTicketIssued / Revoked         │
│ NodeDispatchCommitted                      │
│ WorkspaceAccessGranted / Blocked           │
│ NodeRetried / RemediationPending           │
│ EvaluationCompleted                       │
└────────────────────────────────────────────┘
                      │
                    node_id
                      ▼
┌────────────────────────────────────────────┐
│       Layer 2: Node Execution Evidence     │
│                                            │
│ status / stop_reason                       │
│ duration                                   │
│ token usage                                │
│ tool receipts                              │
│ bash execution evidence                    │
│ acceptance verdict                         │
└────────────────────────────────────────────┘
                      │
                 backend_trace_id
                      ▼
┌────────────────────────────────────────────┐
│       Layer 3: DeerFlow / LLM Trace        │
│                                            │
│ model spans                                │
│ detailed tool execution                    │
│ middleware                                 │
│ Langfuse / LangSmith                       │
└────────────────────────────────────────────┘
```

### 13.2 A-SWE Runtime Event

A-SWE 自己记录 Runtime Decision 与 Scheduler 事件：

```python
class RuntimeEvent(BaseModel):
    event_id: str
    task_id: str
    event_type: str
    timestamp: datetime

    node_id: str | None = None
    source: str
    payload: dict
```

### 13.2.1 Execution Evidence Store Ownership

`RuntimeEvent` 与 immutable evidence object 分离：

```text
RuntimeEvent
→ timeline / decision / state transition

ExecutionEvidenceStore
→ changeset / report-receipt verdict / acceptance / verification / invariant payload
```

事件可以保存 EvidenceRef，但不把大 Patch、完整验证输出重复塞进 event payload。

P1 Trace 页面：

```text
event
  ↓ evidence_ref
ExecutionEvidenceStore
  ↓
typed evidence payload
```

NodeHandoff 本身不是 EvidenceRef。P1 将 bounded NodeHandoff 保存在 NodeAttemptRecord / current NodeRuntimeState；其中的大型、权威 execution payload 统一通过 EvidenceRef 指向 ExecutionEvidenceStore，因此不建设第二套 handoff-only artifact store。

现有 `EvidenceRef` 保持严格的 **Node-attempt-scoped provenance**。Terminal Task finalization 不允许伪造 synthetic Node / execution id 来复用它。

P1 的 task-scoped `TaskEvidenceRef` 与 attempt-scoped `EvidenceRef` 的**唯一 authoritative schema** 均定义在 `specs/01-task-planning.md §4.17.1`；本节只定义其 storage/evaluation 使用语义。

规则：

```text
EvidenceRef
→ Node / execution / attempt provenance
→ 可进入 NodeHandoff / ReceiptRef 等 execution chain

TaskEvidenceRef
→ Runtime terminal-finalization provenance
→ 不得进入 NodeHandoff
→ 不得伪装成某次 Agent execution evidence
```

两者由同一个 immutable `ExecutionEvidenceStore` 持久化：attempt artifact 使用 `put_attempt()`，terminal task artifact 使用 `put_task()`，并使用不同 provenance schema / namespace。

当 Workspace 已 `QUARANTINED`：

- 不创建声称“观察了 final workspace”的 `TaskEvidenceRef`；
- 只能在 `TaskResult.last_trusted_evidence_refs` 中引用 quarantine 前已经存在的 attempt-scoped `EvidenceRef`；
- 这些旧 evidence 必须明确理解为 last trusted observation，不是 current final-state proof。

Model-facing Handoff 不直接 dump EvidenceStore payload，而由 deterministic HandoffRenderer 生成 bounded `HandoffEvidenceProjection`。

---

### 13.3 一期事件类型

至少记录：

```text
TaskReceived
TaskAnalyzed

WorkspaceCreated
WorkspaceReady

CapabilityRequired
CapabilityResolved

TeamPlanningStarted
AgentSelected
SkillSelected
ToolSelected
TeamCreated

DAGCreated
NodeReady
NodeDispatchTicketIssued
NodeDispatchTicketRevoked

WorkspaceAccessGranted
WorkspaceAccessBlocked

NodeDispatchCommitted
NodeStarted
NodeCompleted
NodeFailed
NodeRetried
NodeRemediationPending
NodeCancelled

WorkspaceAccessReleased

RepairAttributionResolved
WriterReopened
TaskDispatchGateClosed

AcceptanceChecked
EvidenceCreated

WorkspaceFrozen
WorkspaceQuarantined

TaskFinalizationStarted
EvaluationStarted
EvaluationCompleted
TaskFinalizationCompleted

TaskCompleted
TaskFailed
TaskCancelled
WorkspaceClosed
```

事件线性化语义：

- `NodeDispatchTicketIssued`：READY claim + dependency stamp capture 已在 SchedulerStateMutex 下完成；
- `NodeDispatchCommitted`：A-SWE attempt identity 已分配，Node logical status 已进入 RUNNING；
- `NodeStarted`：backend execution phase 真正进入 STARTED；它可以晚于 dispatch commit；
- pre-commit revoke 只产生 `NodeDispatchTicketRevoked`，不产生 NodeStarted / NodeFailed；
- `WorkspaceFrozen` 只在所有 committed execution quiescent 后发布；
- `WorkspaceQuarantined` 表示 quiescence 无法证明，不能与 Frozen 同义；
- `EvidenceCreated` payload 使用 attempt/task scope-aware provenance。

旧的单一“scheduled”模糊事件不再作为 P1 minimum event；claim 与 commit 必须分别记录。

低层 `ToolCalled / ToolReturned / LLMStarted` 不强制重新转写成 A-SWE Event；需要时通过 `backend_trace_id` 下钻到底层 Trace。

### 13.4 决策可解释性

例如：

```json
{
  "event_type": "AgentSelected",
  "task_id": "task_001",
  "payload": {
    "agent": "repo_explorer",
    "required_capability": "repo_exploration",
    "reason": "repository_level_task",
    "alternatives": ["coder"],
    "rejected_reason": {
      "coder": "exploration_scope_too_large"
    }
  }
}
```

Workspace 并发决策也必须可解释：

```json
{
  "event_type": "WorkspaceAccessBlocked",
  "node_id": "implement_fix_2",
  "payload": {
    "requested": "write",
    "reason": "another_write_node_is_running"
  }
}
```

### 13.5 Tool Receipt 作为 Execution Evidence

DeerFlow `SubagentResult.tool_receipts` 可直接作为节点级执行证据。

Receipt 至少包含：

```text
tool_call_id
tool_name
status
args_sha256
output_sha256
output_bytes
created_at
```

A-SWE 不必为了“看起来可观测”再给每一个 Tool 包一层重复 callback。

Tool Receipt 用于回答：

> 这个 Node 实际调用过哪些 Tool，以及这些调用是否成功。

若需要查看完整 Tool 输入、输出和 LLM span，则通过底层 Trace 查看。

### 13.6 Trace Metrics

一期至少记录：

```text
Task Duration
Node Count
Agent Count
LLM / Token Usage（底层可获取时）
Tool Receipt Count
Retry Count
Node Failure Count
Workspace Block Count
Workspace Lock Wait Duration
Workspace Lock Hold Duration
Backend Capacity Wait After Workspace Lock
Backend Capacity Busy Before Lock
Backend Lifecycle Deadline Overrun Count
Selected Skills
Selected Tools
Final Status
```

### 13.7 Trace UI

一期 UI 不需要复杂平台化，可以实现一个简单任务详情页：

```text
Task: Fix database connection leak
Status: Running

Task Analysis
────────────────────────
Type           bug_fix
Complexity     medium
Risk           high

Workspace
────────────────────────
Thread         aswe-task-001
Status         ready

Capabilities
────────────────────────
✓ repo_exploration
✓ database_analysis
✓ code_modification
✓ regression_testing

Selected Team
────────────────────────
Explorer
   ↓
Coder
   ↓
Tester
   ↓
Reviewer

Execution Timeline
────────────────────────
✓ inspect repository       READ
✓ locate DB layer          READ
✓ analyze lifecycle        READ
→ implement patch          WRITE
○ regression test          READ
○ review                   READ

Metrics
────────────────────────
Agents             4
Retries            1
Workspace Blocks   0
```

对于面试 Demo，Trace UI 的核心不是展示日志数量，而是展示：

> **Runtime 为什么生成当前 Team / DAG，以及 Scheduler 如何在共享 Workspace 上安全执行。**

---

## 14. Evaluation 与 Review 体系

### 14.1 模块定位

Evaluation 用于判断：

> Agent 是否真正完成了软件工程任务。

Evaluation 不等同于正式 Benchmark。

一期不做大规模 Benchmark，但每一次任务执行必须有内部 Evaluation。

### 14.2 两级验证

一期将验证拆成：

```text
Node Acceptance
      │
      ▼
Task Evaluation
```

#### Node Acceptance

回答：

> 当前 DAG Node 声称完成的结果，是否有确定性执行证据支持？

#### Task Evaluation

回答：

> 整个 Patch 是否解决原始问题，并满足 Repository-Level 软件工程要求？

### 14.3 DeerFlow Acceptance Checker 复用

`SubagentExecutor` 会采集 acceptance 所需的 execution evidence，例如：

- tool receipts；
- bash executions；
- thread / workspace context。

但标准 DeerFlow 中最终 deterministic acceptance check 位于 `task_tool` 的父调用路径。

A-SWE 绕开 Lead Agent / `task_tool`，因此 DeerFlow Adapter 必须显式回接：

```text
SubagentExecutor
      │
      ▼
SubagentResult
      │
      ▼
deerflow.subagents.acceptance_checks
      │
      ▼
NodeAcceptanceResult
```

原则：

> **复用 DeerFlow acceptance checker，不重新实现一套平行的 acceptance 语义。**

同样，Direct `SubagentExecutor` 也绕过标准 `task_tool` 的：

```python
verify_receipt_citations()
```

因此 Adapter 在 completed result mapping 阶段还必须显式回接 DeerFlow receipt citation verifier。

两者职责不同：

```text
Receipt Citation Verdict
→ self-report action claims 是否引用了真实 execution record
→ advisory only

Acceptance Verdict
→ canonical acceptance leaves 是否被 deterministic evidence 支持
→ Node acceptance input
```

不能把两个 verdict 合并成一个 `verified=true`。

一期优先支持 DeerFlow 已能确定性判断的 criterion，例如：

```text
file:<path> exists
file:<path> non-empty
file_written:<path>
tests_passed:<command>
```

无法确定性判断的 criterion 标记为：

```text
UNVERIFIED
```

而不是由 LLM 强行判为成功。

### 14.4 Task Evaluation Pipeline

```text
Code Patch
    │
    ▼
Evaluator
    │
    ├── Build / Import Check
    ├── Existing Tests
    ├── Generated Tests
    ├── Regression Tests
    ├── Optional Static Check
    └── Reviewer
    │
    ▼
TaskContractEvaluator
    │
    ▼
ContractVerdict
    │
    ▼
Evaluation Report / TaskResult
```

#### ContractVerdict

`CompiledTaskContract` 在 Planning 阶段定义 obligation；terminal evaluator 必须把最终 deterministic / semantic evidence 映射回同一 constraint identity。

```python
class ContractLeafStatus(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNVERIFIED = "unverified"
    NOT_APPLICABLE = "not_applicable"

class ContractLeafVerdict(BaseModel):
    constraint_id: str
    enforcement: ConstraintEnforcement
    status: ContractLeafStatus

    supporting_refs: tuple[EvidenceRef | TaskEvidenceRef, ...] = ()
    diagnostics: tuple[str, ...] = ()

class ContractVerdict(BaseModel):
    task_contract_fingerprint: str

    leaves: tuple[ContractLeafVerdict, ...]

    blocking_constraint_ids: tuple[str, ...]
    all_required_satisfied: bool

    fingerprint: str
```

冻结规则：

- `LOCKED / HARD` leaf 的 `VIOLATED` 或 `UNVERIFIED` 都是 blocking；
- `NOT_APPLICABLE` 只有 evaluator 能确定该 constraint 对当前 task state 不适用时才允许；
- SOFT leaf 不直接阻止成功，但进入 diagnostics / warnings；
- deterministic constraint 优先消费 final RepositoryChangeSet、VerificationResult、Acceptance evidence；
- semantic constraint 可以消费 structured ReviewVerdict；无法确认仍为 `UNVERIFIED`；
- `undecidable != passed`；
- stable terminal finalization 将 `ContractVerdict` 写入 ExecutionEvidenceStore，并返回 `TaskEvidenceRef(kind="final_contract_verdict")`；
- `TaskLogicalStatus.SUCCEEDED` 要求 `ContractVerdict.all_required_satisfied == true`。

### 14.5 EvaluationResult

```yaml
evaluation:
  execution_status: completed

  acceptance:
    all_required_nodes_hold: true
    unverified: []

  build:
    status: pass

  tests:
    existing:
      passed: 241
      failed: 0

    added:
      passed: 4
      failed: 0

  reviewer:
    status: pass
    concerns: []

  contract:
    all_required_satisfied: true
    blocking_constraint_ids: []

  final_status: accepted
```

### 14.6 Reviewer 关注点

Reviewer 主要检查：

- Patch 是否解决原始问题；
- 是否存在无关修改；
- 是否违反 Repository Coding Convention；
- 是否可能引入 Regression；
- 是否缺少测试；
- 是否存在明显安全 / 性能问题；
- 是否可以进一步简化。

### 14.7 Evaluation 原则

优先级：

```text
Deterministic Check
        >
Execution Evidence
        >
Reviewer Judgment
        >
LLM Self-Claim
```

例如：

```text
pytest
build
import
lint
file existence
recorded execution evidence
```

能够确定的结果，不应只依赖 Reviewer Agent 判断。

---
