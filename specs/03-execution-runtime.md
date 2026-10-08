# Execution Runtime Specification

> Authoritative implementation specification. 已经 P0 consistency sweep / Design Freeze 收口；Workspace、TaskDAG、Scheduler、Retry/Repair/Reverify 与 TaskResult 以本文为准。

## 3. 总体系统架构

A-SWE Runtime 采用“控制面 + Workspace Runtime + 执行适配层 + DeerFlow Execution Plane”的设计。

```text
┌──────────────────────────────────────────────────────────────┐
│                       A-SWE Runtime                           │
│                                                              │
│  Task Analyzer                                               │
│  Capability Registry / Resolver                              │
│  Dynamic Team Builder                                        │
│  Task DAG / Scheduler                                        │
│  Execution Trace / Observability                             │
│  Evaluation                                                  │
│                                                              │
├───────────────────────────┬──────────────────────────────────┤
│      Workspace Runtime    │       Runtime Decision Plane     │
│                           │                                  │
│  WorkspaceSession         │  what / who / when               │
│  thread_id / user_id      │                                  │
│  repo / base_ref          │                                  │
│  shared workspace         │                                  │
├───────────────────────────┴──────────────────────────────────┤
│                DeerFlow Execution Adapter                    │
│                                                              │
│     TaskNode + AgentProvider + WorkspaceSession               │
│                         │                                    │
│                         ▼                                    │
│               DeerFlowExecutionBackend                       │
├──────────────────────────────────────────────────────────────┤
│                   DeerFlow Execution Plane                   │
│                                                              │
│  SubagentConfig → SubagentExecutor → SubagentResult          │
│  Skills / Tools / MCP / Middleware / Sandbox / Receipts      │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

核心职责边界：

> **A-SWE 决定 what / who / when；DeerFlow 负责 how to execute safely。**

### 3.1 A-SWE Runtime 层

A-SWE Runtime 是项目主体，负责：

- Task Understanding；
- Capability Modeling；
- Capability Provider Resolution；
- Dynamic Team Formation；
- DAG Planning；
- Agent Assignment；
- Workspace-aware Scheduling；
- Retry / Failure Propagation；
- Runtime Decision Trace；
- Evaluation；
- 运行指标采集。

A-SWE 不让 DeerFlow Lead Agent 自主决定任务拓扑。Team 与 DAG 由 A-SWE 控制面显式生成，底层 Harness 只负责执行已确定的节点。

### 3.2 Workspace Runtime

Repository-Level SWE Task 不是若干互相独立的 Agent 调用，而是在同一份代码状态上持续推进的执行过程，因此一期显式引入 `WorkspaceSession`。

建议数据结构：

```python
class WorkspaceSessionStatus(str, Enum):
    BOOTSTRAPPING = "bootstrapping"
    READY = "ready"
    ACTIVE = "active"

    # The workspace is stable/quiescent, but ordinary DAG dispatch has been
    # permanently closed for this task. Runtime-owned finalization only.
    FROZEN = "frozen"

    # Backend execution may still be live / late-mutating and quiescence
    # cannot be proven. No further DAG node or workspace-touching finalizer
    # may enter this workspace.
    QUARANTINED = "quarantined"

    CLOSED = "closed"

class WorkspaceSession(BaseModel):
    task_id: str

    # DeerFlow execution identity
    thread_id: str
    user_id: str

    # runtime workspace
    workspace_root: str

    # optional Git repository bound to this workspace
    repository: RepositoryBinding | None = None

    status: WorkspaceSessionStatus
```

#### Runtime Identity Safety

任何进入 Runtime filesystem / backend registry key 的 identity 都必须由 Runtime/server ownership 保证安全。

P1 safe-id 子集：

```regex
^[A-Za-z0-9_-]+$
```

规则：

- `task_id`：server-generated opaque id，推荐 `aswe-task-${uuid4().hex}`；
- `thread_id`：server-generated / trusted-mapped opaque safe id；
- `run_id`：execution-scoped `aswe-${uuid4().hex}`；
- `evidence_id` / `finalization_id` / `preparation_id`：Store/Runtime generated safe ids；
- `node_id` 可以保留 planner semantic id，但不得直接拼入 filesystem path；
- raw external user/account id 不直接作为 DeerFlow filesystem `user_id`；必须经过 trusted identity mapping / opaque safe-id projection。

因此 LocalEvidenceStore 的：

```text
tasks/<task_id>/...
```

只接受已经通过 Runtime identity contract 的 `task_id`，不在 storage layer 对任意用户字符串做 path join。

关键约束：

`FROZEN` 与 `QUARANTINED` 必须严格区分：

```text
FROZEN
→ backend quiescence 已证明
→ Workspace state 可视为稳定 terminal snapshot
→ ordinary Agent / DAG dispatch 永久关闭
→ 只允许 Runtime-owned deterministic finalization

QUARANTINED
→ backend quiescence 无法证明
→ Workspace 可能仍被 late mutation
→ 禁止任何新的 Agent dispatch
→ 禁止依赖“当前 workspace 稳定”的 finalization probe
→ 只能使用 quarantine 前已持久化的 trusted evidence
```

因此：

> **dirty task failure does not automatically mean QUARANTINED.**

典型 dirty WRITE failure 若 `execute_prepared()/cancel_node()` 已证明 executor-owned quiescence，应进入 terminal `FROZEN`；只有 completion/quiescence proof 丢失时才进入 `QUARANTINED`。

正常成功、失败或取消在形成 terminal task state 后，也可以短暂：

```text
ACTIVE → FROZEN → CLOSED
```

以完成 final result materialization。这里的 `FROZEN` 是 dispatch/lifecycle state，不是业务 success/failure verdict。

关键约束：

```text
one A-SWE task
      │
      ▼
one WorkspaceSession
      │
      ├── stable user_id
      └── stable thread_id
              │
              ▼
shared DeerFlow thread workspace / sandbox identity
```

Explorer、Coder、Tester、Reviewer 只要在同一 `WorkspaceSession` 中执行，就必须使用相同的 `user_id + thread_id`。

这使：

```text
Explorer discovers code
        ↓
Coder modifies code
        ↓
Tester observes the modification
        ↓
Reviewer reviews the same working tree
```

成为 Runtime 的显式契约，而不是依赖 Agent 输出在 Prompt 中传递代码状态。

Repository / Workspace Bootstrap 的职责边界经 P0-2 审计后固定为：

> **Repository Bootstrap 属于 A-SWE Control Plane，不属于 Agent Task。**

A-SWE 不让 Coder / Explorer 自行决定 Repository 的 clone、checkout 和 baseline。Runtime 必须在第一个 Agent Node 执行前确定性完成 Repository Bootstrap，并冻结 Repository 基线。

建议增加：

```python
class RepositoryBinding(BaseModel):
    source_type: str

    remote_url: str | None = None
    requested_ref: str | None = None

    # immutable runtime authority
    resolved_base_sha: str

    repository_root: str
    default_branch: str | None = None

    clean_at_bootstrap: bool
```

其中 `requested_ref` 可以是：

```text
main
develop
feature/foo
v1.2.0
<commit sha>
```

但 Runtime 真正使用的基线必须是：

```text
resolved_base_sha
```

而不是可漂移的 branch / tag 名称。

一期推荐一个 Task 对应一个独立 Thread Workspace，并直接将 Repository Root 放在：

```text
/mnt/user-data/workspace
```

而不是：

```text
/mnt/user-data/workspace/<repo-name>
```

因为 DeerFlow 的 bash 工具本身会将默认工作目录定位到 thread workspace，这样 Explorer、Coder、Tester、Reviewer 均天然在 Repository Root 执行。

Repository Bootstrap 标准流程：

```text
WorkspaceSession Allocate
        │
        ▼
Prepare Empty Workspace
        │
        ▼
Clone / Materialize Repository
        │
        ▼
Resolve requested_ref
        │
        ▼
Checkout exact resolved_base_sha
        │
        ▼
Verify Repository Clean
        │
        ▼
Capture Baseline Workspace Snapshot
        │
        ▼
WORKSPACE READY
```

一期推荐以 detached HEAD / immutable baseline 方式运行，使 Agent 只修改 Working Tree，不负责 commit / branch / merge / rebase 等 Repository lifecycle operation。

### 3.2.1 Repository Invariant

A-SWE 必须在关键 WRITE Node 后检查 Repository invariant：

```python
class RepositoryInvariant(BaseModel):
    git_repo_exists: bool
    head_sha: str
    head_matches_baseline: bool
```

最重要的不变量：

```text
.git exists
HEAD == resolved_base_sha
```

如果 Agent 擅自 commit、checkout、rebase 等导致 HEAD 偏离 baseline，一期直接将该 Node 判为失败，不做静默自动恢复。

### 3.2.2 Repository Change Evidence

DeerFlow 已提供 filesystem-level `workspace_changes`：

```text
before snapshot
      ↓
execution
      ↓
after snapshot
      ↓
filesystem change result
```

A-SWE 直接复用：

```text
capture_workspace_snapshot
compare_snapshots
```

但 DeerFlow 的 workspace scanner 明确忽略 `.git`，因此它不是 Git-aware Patch。

一期采用双证据模型：

```text
Repository Result
      │
      ├── Git ChangeSet
      │     └── authoritative repository patch
      │
      └── Workspace ChangeSet
            └── filesystem execution evidence
```

建议：

```python
class RepositoryChangeSet(BaseModel):
    base_sha: str

    head_sha: str
    head_matches_baseline: bool

    tracked_diff: str
    changed_files: list[str]
    untracked_files: list[str]

    dirty: bool
```

注意：`git diff HEAD` 不包含 untracked files，因此最终 Patch 提取不能仅依赖该命令。

正式输出完整 Patch 时，可使用 temporary Git index 生成不污染真实 index 的 patch：

```text
temporary GIT_INDEX_FILE
        ↓
git read-tree <base_sha>
        ↓
git add -A
        ↓
git diff --cached --binary <base_sha>
```

同一次 materialization 还应执行：

```text
git write-tree
```

生成 `working_tree_oid`，使 Final Patch 与 RepositoryStateDigest 来自同一 canonical Git view，而不是两套独立扫描逻辑。

Baseline Workspace Snapshot 必须在 clone / checkout 完成之后采集，否则整个 Repository 会被误判为 task-created files。

Task-level baseline / Git ChangeSet 用于最终 Repository patch。

**所有 WRITE / UNKNOWN-MUTATING Node attempt 必须采集 before / after workspace snapshot。**

它不是 UI 可选项，而是以下 Runtime 语义的输入：

```text
Node-level observed changed-path attribution
WorkspaceRevision evidence
post-node contract/invariant evidence
```

但 pinned DeerFlow scanner 明确排除：

```text
.git
.venv
node_modules
build
dist
__pycache__
.cache
...
```

因此：

> **WorkspaceChangeSet 是 bounded filesystem observation，不是整个 sandbox / process environment 的 complete mutation oracle。**

例如：

```text
bash("pip install ...")
bash("npm install ...")
bash("pytest")
```

可能改变被 scanner 排除的环境/cache/dependency state，而 WorkspaceChangeSet 仍显示“无 observed change”。

所以 `DIRTY_WRITE_FAILURE`、retry eligibility、WorkspaceRevision 不能只看 `WorkspaceChangeResult.has_changes()`。

纯 READ Node 不强制全量 snapshot，因为其可执行 Tool set 已被证明 read-only。

#### NodeWorkspaceDelta

Task-level Git ChangeSet 与 Node-level attribution 必须分离。

原因：

```text
baseline
  ↓ Node A modifies src/a.py
workspace dirty
  ↓ Node B modifies src/b.py
```

Node B 执行后的：

```text
git diff <base_sha>
```

包含 A+B，不能证明哪些路径属于 Node B。

P1 对每个 mutating attempt 生成：

```python
class MutationEvidence(str, Enum):
    PROVEN_NONE = "proven_none"
    OBSERVED = "observed"
    UNKNOWN = "unknown"

class NodeWorkspaceDelta(BaseModel):
    node_id: str
    execution_id: str
    attempt: int

    before_revision_generation: int
    after_revision_generation: int

    # DeerFlow scanner-visible filesystem attribution.
    changed_paths: tuple[str, ...]
    changed_paths_complete: bool

    # Git-visible per-attempt business patch attribution.
    repository_changed_paths: tuple[str, ...]
    repository_changed_paths_complete: bool

    has_observed_changes: bool
    attribution_truncated: bool

    mutating_tool_admitted: bool | None
    mutation_evidence: MutationEvidence

    summary: dict

    workspace_changeset: EvidenceRef | None

    fingerprint: str
```

其中：

- `changed_paths` 来自当前 attempt 的 before/after deterministic snapshot comparison；
- Task-level `RepositoryChangeSet` 仍负责 authoritative final Git patch；
- NodeHandoff.changed_paths 来自 `NodeWorkspaceDelta`，不从 cumulative baseline Git diff 推断。

`changed_paths_complete` 的语义必须严格限定为：

> **DeerFlow scanner-visible scope 内的 path attribution completeness。**

它不能解释成“整个 sandbox 没有其他变化”。

#### MutationEvidence 判定

P1 额外使用 execution evidence 判断 mutating tool 是否真正执行：

```text
PROVEN_NONE
→ 能证明本 attempt 没有任何 WORKSPACE_MUTATING / UNKNOWN tool call 真正执行
→ 且 scanner snapshot 未截断

OBSERVED
→ scanner 观察到 mutation path / state change

UNKNOWN
→ mutating / UNKNOWN tool 已执行但 scanner 未观察到变化
OR receipt / tool-call evidence 缺失
OR snapshot truncated / attribution incomplete
```

特别是：

```text
bash executed
+ workspace_changes says no changes
→ UNKNOWN
```

而不是 `PROVEN_NONE`。

Tool receipt 只证明调用发生；它不能证明 bash 命令无副作用。因此任何实际执行过的通用 `bash` 在没有更强 sandbox transaction evidence 时，至少使 mutation state 进入 `UNKNOWN`。

#### Tool-Start Evidence：PROVEN_NONE 的必要条件

Pinned DeerFlow 的两个现成 evidence layer 都不够早：

```text
ToolProgressMiddleware
→ handler(request) 返回后更新/记录状态

ToolReceiptMiddleware
→ handler(request) 返回后 stamp receipt
```

因此 cancellation / exception 可能发生在：

```text
mutating tool 已开始
        ↓
workspace/environment 已发生副作用
        ↓
尚未形成 ToolMessage / Receipt
        ↓
execution 被取消
```

这时：

```text
no receipt
+ no scanner-visible change
```

绝不能推出 `PROVEN_NONE`。

P1 复用已经存在的 trusted `ASWENodeToolPolicyMiddleware`，在它的 tool-call enforcement boundary 增加一个**pre-handler admission record**：

```text
tool call reaches A-SWE trusted middleware
        ↓
resolve exact NodeExecutionBinding
        ↓
verify name / identity / Node policy
        ↓
if allowed:
    record ToolCallAdmissionRecord
        ↓
call downstream handler
```

记录必须发生在 downstream handler 前。

它不是“工具成功执行”的证明，只表示：

> **该 tool call 已经越过 A-SWE 自己的最后 policy gate，并可能在后续 execution chain 产生副作用。**

对于：

```text
effect == WORKSPACE_MUTATING
OR effect == EXTERNAL_SIDE_EFFECT
OR effect == UNKNOWN
```

一旦存在 admission record，即使：

- 没有 receipt；
- tool handler 被 cancellation 打断；
- DeerFlow snapshot 无 changed path；

P1 也不能判 `PROVEN_NONE`。

若更外层 DeerFlow Guardrail / ReadBeforeWrite 在调用到 A-SWE middleware 前就 short-circuit：

- 不会产生 A-SWE admission record；
- actual business tool 也没有越过该 outer gate；
- 仍可结合其他 evidence 判断 clean。

若 A-SWE admission 后，后续更内层 middleware 又 short-circuit：

- A-SWE 会保守认为 mutation possibility 已打开；
- 最多把本可 clean 的 attempt 降为 UNKNOWN；
- 不会把危险 attempt 错判 clean。

这是 deliberate fail-safe asymmetry。

#### PROVEN_NONE Frozen Predicate

P1 的 `MutationEvidence.PROVEN_NONE` 有两条 mutually exclusive proof path：

```text
A. PRE_START proof
   execution_phase == PRE_START
   AND NodeExecutionBinding / audit integrity intact
   AND no ToolCallAdmissionRecord
   → PROVEN_NONE

B. STARTED proof
   before/after workspace snapshot available
AND snapshot attribution not truncated
AND no observed workspace change
AND NodeExecutionBinding / RuntimeOutcome intact
AND admitted_tool_calls_truncated == false
AND no admitted tool call whose effect is:
    WORKSPACE_MUTATING
    EXTERNAL_SIDE_EFFECT
    UNKNOWN
AND no independent runtime evidence of mutation
   → PROVEN_NONE
```

否则：

```text
observed mutation
→ OBSERVED

not observed but proof incomplete / mutating admission exists
→ UNKNOWN
```

注意：

> **Receipt absence is never a clean-execution proof.**

Receipt 仍用于“某个工具调用完成并返回了什么”的 execution evidence；pre-handler admission record 专门用于“是否可能已经进入副作用区间”的 retry-safety proof。

#### Snapshot Truncation Fail-Safe

Pinned DeerFlow `WorkspaceChangeLimits` 默认：

```text
max_files = 200
max_scanned_files = 2000
max_file_bytes_for_diff = 256 KiB
max_total_diff_bytes = 1 MiB
```

且：

```text
WorkspaceSnapshot.truncated
WorkspaceChangeSummary.truncated
```

都可能成立。

因此：

```text
truncated == true
≠ no more changes
```

P1 规则：

- `changed_paths_complete = false`；
- Handoff 只能把 observed paths 标成“observed changed paths”，不能声称完整；
- 添加 warning `WORKSPACE_DELTA_TRUNCATED`；
- snapshot truncated → `mutation_evidence = UNKNOWN`；
- failed WRITE / UNKNOWN-mutating attempt 只有 `mutation_evidence == PROVEN_NONE` 才允许进入自动 retry 候选；
- successful WRITE / UNKNOWN-mutating attempt 只要 `mutation_evidence != PROVEN_NONE`，就保守推进 WorkspaceRevision；
- Runtime 不因 diff content unavailable（binary / sensitive / large）丢弃 path-level mutation事实；
- snapshot truncation 不等同于 task failure，但必须降低 evidence completeness。

即：

> **Unknown mutation state is treated as dirty for retry safety and stale-context invalidation.**

### 3.2.3 RepositoryStateDigest 与 Semantic Mutation Invariant

`WorkspaceAccess.WRITE` 只表示：

> 该 Node 的物理工具可能修改共享 Workspace，因此需要 exclusive scheduling。

它不自动授予：

> 修改 Repository patch 的业务权限。

典型：

```text
VERIFICATION
CapabilityAuthorityClass = READ_ONLY
Tool = bash
WorkspaceAccess = WRITE
```

Tester 可以运行 pytest，但不能因为拥有 shell 就顺手修改源码让测试通过。

P1 增加 deterministic：

```python
class RepositoryStateDigest(BaseModel):
    base_sha: str
    head_sha: str

    base_tree_oid: str
    working_tree_oid: str

    head_matches_baseline: bool
    dirty_vs_base: bool

    fingerprint: str
```

Digest 表达当前 **Git-visible Repository working state**，不复制完整 patch。

P1 不自行发明目录哈希，直接复用 Git object model。

Runtime 在 Repository root 创建**真实 index 之外**的 temporary index：

```text
temp_index outside repository .git
        ↓
GIT_INDEX_FILE=<temp_index>
git read-tree <resolved_base_sha>
        ↓
GIT_INDEX_FILE=<temp_index>
git add -A -- .
        ↓
GIT_INDEX_FILE=<temp_index>
git write-tree
        ↓
working_tree_oid
```

同时：

```text
base_tree_oid = git rev-parse <resolved_base_sha>^{tree}
head_sha      = git rev-parse HEAD
```

因此：

```text
working_tree_oid == base_tree_oid
→ Git-visible working state clean relative to baseline

working_tree_oid != base_tree_oid
→ Git-visible business patch differs from baseline
```

这个 tree identity 原生覆盖：

- tracked file content changes；
- tracked deletion；
- non-ignored untracked file；
- file mode；
- symlink/tree structure；
- canonical Git path/tree ordering。

ignored cache/build artifact 不进入 tree，符合“business patch state”语义。

真实 Repository index 不参与 authority，也不被修改。

它与 WorkspaceRevision 不同：

```text
WorkspaceRevision
→ 共享 Workspace 的物理状态版本
→ cache/build artifact 变化也可能推进

RepositoryStateDigest
→ Git-visible business patch state
→ 用于 semantic repository-mutation authority
```

#### Per-Attempt Repository Attribution

pre/post attempt 都 capture `RepositoryStateDigest` 后，可直接：

```text
git diff --name-status <pre.working_tree_oid> <post.working_tree_oid>
```

得到**当前 attempt 的 Git-visible path delta**。

这优于：

```text
git diff <base_sha>
```

因为后者是 cumulative patch，会把更早 Node 的修改重复归给当前 Node。

建议 Node evidence 同时保留：

```python
repository_changed_paths: tuple[str, ...]
repository_changed_paths_complete: bool
```

默认 complete 仅在 Git tree materialization + tree-to-tree diff 全部成功时成立。

Handoff 对代码修改路径优先使用 repository per-attempt delta；DeerFlow WorkspaceChangeSet 继续补充 outputs/cache/filesystem observation。

#### READ_ONLY Semantic Authority Invariant

对：

```text
CapabilityAuthorityClass = READ_ONLY
```

但物理：

```text
WorkspaceAccess = WRITE
```

的 Node attempt，Scheduler/Runtime 必须在执行前后 capture：

```text
pre_repository_state_digest
post_repository_state_digest
```

要求：

```text
pre.fingerprint == post.fingerprint
```

否则：

```text
REPOSITORY_MUTATION_AUTHORITY_VIOLATION
```

即使：

- SubagentResult.status == completed；
- tests_passed criterion holds；
- Agent 自报“只是修了一个小问题”；

也不得接受该 Node。

典型允许：

```text
.pytest_cache/
coverage cache
ignored build output
/mnt/user-data/outputs/*
```

只要它们不改变 Git-visible Repository patch state。

典型禁止：

```text
Tester modifies src/auth.py
Tester rewrites expected snapshot tracked in Git
Reviewer edits README.md
Discovery agent creates non-ignored source file
```

除非对应 WorkItem 本身拥有 `REPOSITORY_MUTATION` authority。

#### Verification Contamination

若 Verification Node 改变 RepositoryStateDigest：

1. 先发布真实 post WorkspaceRevision / NodeWorkspaceDelta；
2. 产生 `REPOSITORY_MUTATION_AUTHORITY_VIOLATION`；
3. verification verdict 不得作为“writer patch failed”的 RepairFeedback；
4. P1 fail closed，因为 verifier 已污染共享 Repository；
5. 不自动尝试推断并撤销 verifier 的修改。

原则：

> **A verifier may physically write; it may not semantically rewrite the patch being verified.**

---

#### P1 Git Feature Boundary

Temporary-index tree identity has one重要边界：Git submodule dirty working state is **not** represented by the parent tree OID when the gitlink commit itself is unchanged.

例如：

```text
parent gitlink SHA unchanged
submodule working tree dirty
→ parent working_tree_oid may remain unchanged
```

因此 P1 bootstrap 必须显式 detect：

```text
tracked mode 160000 / .gitmodules
→ UNSUPPORTED_GIT_SUBMODULES_P1
```

而不是让 semantic mutation invariant 产生 false clean。

同理，P1 默认拒绝 active sparse checkout：

```text
core.sparseCheckout / sparse-index active
→ UNSUPPORTED_SPARSE_CHECKOUT_P1
```

因为“working tree materialization”不再等价于完整 Repository tree，`git add -A -- .` 的 authority 语义需要额外规则。

P1 支持范围冻结为：

- ordinary non-bare Git worktree；
- detached baseline HEAD；
- no submodule working-tree semantics；
- no sparse checkout；
- normal files / executable mode / symlink 由 Git tree object 处理。

未来若需要 submodule：

```text
parent tree oid
+
recursive submodule HEAD/dirty digest
```

单独扩展，不在 MVP 隐式支持。

---

### 3.3 DeerFlow Execution Adapter

Adapter 不再暴露：

```python
create_agent()
run_agent()
load_skill()
execute_tool()
run_in_sandbox()
```

这类过度贴近 Harness 内部组件的接口。

一期收敛为节点级执行接口：

```python
class ExecutionBackend(Protocol):
    async def prepare_node(
        self,
        node: TaskNode,
        policy: NodeExecutionPolicy,
        workspace: WorkspaceSession,
    ) -> NodeExecutionPreparation:
        ...

    async def execute_prepared(
        self,
        preparation: NodeExecutionPreparation,
        invocation: NodeExecutionInvocation,
        workspace: WorkspaceSession,
    ) -> NodeExecutionResult:
        """Return only after backend execution is quiescent."""
        ...

    async def cancel_node(
        self,
        execution_id: str,
    ) -> None:
        ...

    async def check_acceptance(
        self,
        result: NodeExecutionResult,
        acceptance_criteria: list[str],
        workspace: WorkspaceSession,
    ) -> NodeAcceptanceResult:
        ...
```

因此 A-SWE 核心模块只理解：

```text
TaskNode
NodeExecutionPolicy
NodeExecutionPreparation
NodeExecutionInvocation
WorkspaceSession
NodeExecutionResult
NodeAcceptanceResult
```

其中 `NodeExecutionPreparation` 冻结 backend resources；`NodeExecutionInvocation` 冻结**拿到 Workspace lock 以后才能确定的本 attempt execution context**。

为关闭 Writer reopen 与 downstream dispatch 的 TOCTOU，Invocation 还必须携带 Runtime-owned dependency authority snapshot：

```python
class DependencyAcceptanceStamp(BaseModel):
    upstream_node_id: str

    # Monotonic authority generation owned by Scheduler state.
    acceptance_epoch: int

    accepted_attempt: int
    handoff_fingerprint: str

class NodeExecutionInvocation(BaseModel):
    task_id: str
    node_id: str
    attempt: int
    attempt_kind: NodeAttemptKind

    execution_id: str
    run_id: str

    execution_workspace_revision: WorkspaceRevision

    # Scheduler-linearized dispatch authority.
    dispatch_ticket_id: str
    task_dispatch_epoch: int
    dependency_acceptance_stamps: tuple[DependencyAcceptanceStamp, ...]

    # Already deterministically rendered, bounded and neutralized.
    dependency_context_text: str
    dependency_handoff_fingerprints: tuple[str, ...]

    repair_feedback_text: str | None

    context_fingerprint: str
```

Core 不知道 DeerFlow middleware store；Adapter 再将 Invocation 投影到 DeerFlow-specific execution binding。

`prepare_node()` 在 P1 必须满足：

```text
no model/tool execution
no Workspace mutation
no backend execution registration that requires task-level cancellation
discardable when a dispatch ticket is revoked
```

因此 Writer reopen 发生在 preparation / Workspace wait 阶段时，Scheduler 可以直接丢弃 `NodeExecutionPreparation`；若 Backend future 版本需要 preparation resource cleanup，必须新增显式 `release_preparation()` seam，不能让“prepared object 丢弃”留下隐藏执行副作用。

而不知道 DeerFlow 内部如何加载 Skill、Tool、MCP、Middleware 或 Sandbox。

### 3.4 DeerFlowExecutionBackend

一期推荐将 DeerFlow 的 `SubagentExecutor` 作为 DAG Worker Primitive。

执行链路：

```text
A-SWE Scheduler
      │
      ▼
TaskNode
      │
      ▼
Capability / Agent Provider
      │
      ▼
DeerFlowExecutionBackend
      │
      ├── resolve SubagentConfig
      ├── resolve tools / skills / MCP
      ├── bind WorkspaceSession.thread_id
      ├── bind WorkspaceSession.user_id
      └── use shared execution capacity
      │
      ▼
SubagentExecutor
      │
      ▼
SubagentResult
      │
      ▼
NodeExecutionResult
```

`SubagentExecutor` 已能接收：

- `SubagentConfig`；
- tools；
- app config；
- thread data；
- sandbox state；
- `thread_id`；
- `user_id`；
- trace id；
- shared execution capacity；
- acceptance criteria。

Adapter 可以持有一个进程级 `SubagentRuntime` / shared execution capacity，并将同一容量控制器传入不同节点执行，避免 A-SWE 自己重新实现底层并发 admission control。

#### 3.4.1 Backend Terminal Status ≠ Execution Quiescence

Pinned DeerFlow 的 `SubagentResult.status.is_terminal` 只表示：

> **结果对象已经发生 terminal state transition。**

它不保证 executor 已经完成所有 unwind / cleanup。

正常 completed / failed 路径中，源码顺序是：

```text
result.try_set_terminal(...)
        ↓
result.status becomes terminal
        ↓
executor finally
        ├── publish final token snapshot
        ├── release sandbox execution lease
        └── notify extension task stop
        ↓
_aexecute returns
```

因此：

```text
poll result.status == terminal
```

不能作为 Scheduler 释放 WorkspaceAccess 的条件。

否则可能出现：

```text
Node A status = COMPLETED
        ↓
A-SWE releases WRITE lock
        ↓
Node B starts
        │
        └──── overlaps Node A stream / sandbox cleanup tail
```

这违反 A-SWE 的 Workspace serialization contract。

同样不能假设 public `SubagentExecutor.execute()` 在所有路径都代表 quiescence：

- 正常路径：`Future.result()` 返回时 child coroutine 已完成；
- timeout 路径：`Future.result(timeout=...)` 超时后会 request cancellation 并抛出，外层 `execute()` 可以先形成 FAILED result，而 isolated-loop cancellation cleanup 仍在继续。

因此 P1 冻结：

> **NodeExecutionResult 只能在 backend execution quiescent 后返回给 Scheduler。**

Quiescent 的最低定义：

```text
agent stream closed
AND child execution coroutine returned
AND sandbox execution lease release path completed
AND capacity slot unwind completed
AND no executor-owned tool body may continue after terminalization
```

Extension notification failure可以记录 warning；它不能让已完成的 sandbox/tool cleanup重新变成 running。

#### 3.4.2 DeerFlow Quiescence Compatibility Seam

Pinned DeerFlow 当前公开 execution APIs：

```text
SubagentExecutor.execute()
SubagentExecutor.execute_async()
get_background_task_result()
request_cancel_background_task()
cleanup_background_task()
force_cleanup_background_task()
```

**没有公开的 quiescence/join API。**

更重要的是，不能简单把内部 `_background_futures` 暴露出来然后：

```text
await Future done
→ assume quiescent
```

因为 pinned `request_cancel_background_task()` 会：

```python
result.cancel_event.set()
future.cancel()
```

对 `run_coroutine_threadsafe()` 返回的 `concurrent.futures.Future` 调用 `cancel()` 时：

> Future 的 cancelled/done 状态不能作为 isolated-loop coroutine 已经完成 cancellation cleanup 的证明。

因此 A-SWE 需要的不是“Future getter”，而是：

> **一个不会被 Future.cancel() 提前完成、只在 background execution coroutine 真正退出后置位的独立 completion signal。**

##### Minimal DeerFlow Compatibility Patch

P1 允许对 pinned DeerFlow fork 做一个极薄 compatibility patch；不复制 SubagentExecutor，也不从 A-SWE Core 读取 private registry。

建议 DeerFlow 内部增加：

```text
_background_completion_signals:
    execution_id → completion signal
```

signal 必须：

- 在 `execute_async()` 成功提交 execution 之前/同时注册；
- 与 result / Future 使用同一个 server-generated `execution_id`；
- **不随 `Future.cancel()` 被置位或删除**；
- 只在 outer `run_with_timeout()` 的 `finally` 中 set；
- 一直保留到显式 background cleanup；
- done-callback 可以继续删除 `_background_futures`，但不能删除未消费的 completion signal。

语义：

```python
async def await_background_task_quiescence(
    execution_id: str,
) -> SubagentResult:
    """
    Return only after the background execution coroutine has fully exited.
    Terminal SubagentResult.status alone is insufficient.
    """
```

为了处理 first-terminal-wins 与 outer timeout race，实际 public seam 不应只返回裸 `SubagentResult`。建议 compatibility layer 返回：

```python
class BackgroundQuiescenceOutcome(BaseModel):
    execution_id: str

    result: SubagentResult

    quiescent: bool
    quiescent_at: datetime

    outer_timeout_fired: bool
    cancellation_requested: bool

    lifecycle_warnings: tuple[str, ...] = ()
```

其中：

- `result` 仍保持 DeerFlow first-terminal-wins contract；
- `outer_timeout_fired` 由 `run_with_timeout` wrapper 记录，而不是从 result.status 倒推；
- completion signal 与 lifecycle outcome 同时在 wrapper `finally` 完成；
- A-SWE Core 不直接依赖该 DeerFlow-specific schema，Adapter 映射为 provider-neutral lifecycle metadata。

内部可以基于 thread-safe completion event / equivalent primitive；实现细节由 DeerFlow fork 持有，A-SWE Adapter 只依赖 public seam。

##### 为什么 signal 要在 run_with_timeout finally 才 set

Pinned execution nesting：

```text
run_with_timeout()
    ↓
await _aexecute()
    ↓
async with capacity.slot()
    ↓
_aexecute_admitted()
    ↓
stream close / tool unwind
    ↓
sandbox lease release_async()
    ↓
extension task-stop notification
    ↓
_aexecute_admitted returns
    ↓
capacity.slot exits / slot released
    ↓
_aexecute returns
    ↓
run_with_timeout finally
    ↓
COMPLETION SIGNAL SET
```

因此该 signal 至少能作为：

```text
child execution coroutine exited
+
stream teardown completed
+
sandbox lease release path completed/attempted
+
capacity slot exited
```

的 fence。

Extension task-stop notification 是 bounded/fail-open；若其失败，只记录 warning，不重新打开 execution。

##### First-Terminal-Wins vs Lifecycle Deadline

Pinned `SubagentResult.try_set_terminal()` 是严格 first-terminal-wins：

```text
if result.status.is_terminal:
    late terminal write is ignored
```

因此存在合法竞态：

```text
Agent produced final result
      ↓
result → COMPLETED
      ↓
executor enters sandbox / stream cleanup tail
      ↓
outer wait_for deadline expires
      ↓
run_with_timeout tries TIMED_OUT
      ↓
try_set_terminal(TIMED_OUT) returns false
      ↓
final result remains COMPLETED
```

如果 Adapter 只看：

```text
result.status
```

就会完全看不见 deadline 已经触发。

P1 语义冻结：

```text
COMPLETED
+ outer_timeout_fired == false
→ ordinary completed candidate

COMPLETED
+ outer_timeout_fired == true
+ quiescence eventually proven
→ completed work may still be evaluated
→ add lifecycle warning BACKEND_LIFECYCLE_DEADLINE_OVERRUN
→ never report as clean within-budget completion

TIMED_OUT
→ timeout won the first-terminal race
→ normal timeout failure semantics
```

是否接受 `COMPLETED + DEADLINE_OVERRUN` 仍取决于：

- deterministic acceptance；
- repository invariants；
- execution completeness；
- no policy violation；
- quiescence proof。

P1 不因为 cleanup-tail budget overrun 自动丢弃已经确定产生的有效 Patch；但 metrics / Trace 必须真实反映 budget overrun。

原则：

> **Terminal outcome and lifecycle deadline outcome are related but not identical facts.**

---

##### Adapter Execution Flow

```text
A-SWE execution_id
      ↓
create NodeExecutionBinding
      ↓
backend_execution_id =
SubagentExecutor.execute_async(
    task,
    task_id=<A-SWE execution_id>,
)
      ↓
await await_background_task_quiescence(
    backend_execution_id
)
      ↓
read final SubagentResult
      ↓
map NodeExecutionResult
      ↓
cleanup_background_task(
    backend_execution_id
)
      ↓
remove NodeExecutionBinding
      ↓
Scheduler may release WorkspaceAccess
```

两类 id 必须分离：

```text
A-SWE execution_id
→ control-plane NodeAttempt identity

DeerFlow backend_execution_id
→ execution-plane registry / cancel / join identity
```

##### Cancellation

`ExecutionBackend.cancel_node(execution_id)`：

1. resolve `backend_execution_id`；
2. call `request_cancel_background_task()`；
3. **仍然等待 independent completion signal**；
4. 不以 Future.cancelled / SubagentResult.CANCELLED 提前返回；
5. 读取最终 evidence；
6. cleanup registry/binding；
7. 最后返回给 Scheduler。

因此：

> **Cancellation acknowledgement is not quiescence.**

##### Completion Signal Failure

如果出现：

```text
result terminal
BUT completion signal missing/corrupted/unresolvable
```

A-SWE 禁止：

```text
assume cleanup probably finished
→ release lock
→ continue DAG
```

P1：

```text
WorkspaceSession.status = QUARANTINED
Task = fail closed
cancel remaining runnable nodes
retain trace / workspace for diagnostics
do not produce a trusted final patch/evaluation
```

Scheduler 可以结束自身 bookkeeping，但**不得再向该 WorkspaceSession dispatch 新 execution**。

这是因为底层 execution 是否仍可能 late-mutate Workspace 已无法证明。

##### No-Private-API Rule

P0.5 可以用 private registry 验证 patch prototype，但 P1 production Adapter 禁止长期依赖：

```text
_background_futures
_background_tasks_lock
SubagentExecutor._aexecute()
_submit_to_isolated_loop_in_context()
```

这些都属于 DeerFlow internal implementation。

若不接受这一个极薄 fork patch，则：

> **Direct SubagentExecutor 不能满足 A-SWE P1 的 strict shared-WORKSPACE serialization contract，属于 No-Go。**

该 seam 是 P0.5 Go/No-Go 项，不是 optional optimization。

#### 3.4.3 ExecutionBackend Quiescence Contract

对 Core：

```python
await execute_prepared(...)
await cancel_node(...)
```

两者返回时都必须满足同一个 invariant：

```text
backend execution quiescent
OR
WorkspaceSession transitioned to QUARANTINED and task is fail-closed
```

正常路径：

```text
execute/cancel
→ independent completion signal
→ final result/evidence mapping
→ backend registry cleanup
→ binding cleanup
→ Workspace lock release
```

异常路径：

```text
cannot prove completion
→ QUARANTINED
→ no more node dispatch
```

Core 永远不理解 DeerFlow Future、registry 或 cancel-event 细节。

原则：

> **Quiescence is the workspace-lock release boundary; unprovable quiescence quarantines the workspace.**

#### 3.4.4 Quiescence Guarantee Scope

P1 必须精确定义“quiescent”，不能把不同层级混成一句“没有后台任务”。

##### Level 1：Executor-Owned Quiescence

Pinned DeerFlow 对 sandbox-backed core tool 的同步 worker 提供 cancellation drain：

```text
async sandbox wrapper
→ run_sync_lifecycle_operation(...)
→ asyncio.to_thread(...)
→ asyncio.shield(worker)
→ cancellation
→ drain worker until done
→ only then propagate cancellation
```

Sandbox lease release 同样 shield + drain。

配合 3.4.2 的 independent completion signal，A-SWE 可以证明：

```text
DeerFlow execution coroutine exited
AND executor-owned sandbox/tool worker drained
AND capacity slot exited
AND sandbox lease release path finished
```

这定义为：

> **executor-owned quiescence**

它是 Workspace lock 正常释放所需的最低 backend fence。

##### Level 2：不是 Container / Arbitrary Process Quiescence

不能进一步声称：

```text
executor-owned quiescence
→ every process in sandbox/container is gone
```

Pinned AIO 明确：

```text
AioSandboxProvider.release()
→ healthy sandbox enters warm pool
→ container keeps running
```

而 AIO execution-scoped shell：

```text
release_command_scope(scope_id)
→ _cleanup_session_best_effort(...)
```

其 cleanup exception 会被内部吞掉并只记录 warning。

因此现有 DeerFlow API 无法向 A-SWE 提供强证明：

```text
remote shell session cleanup definitely succeeded
```

也无法证明 Agent 若主动启动：

```text
detached process
daemon
nohup/background job
external asynchronous side effect
```

已经停止。

所以：

> **Executor-owned quiescence is not arbitrary process quiescence.**

##### P1 Managed Bash Contract

为了让 shared mutable Workspace 仍具有可证明的生命周期边界，P1 不允许 A-SWE managed Node 使用任意 LLM-generated free-form shell。

增加 provider-neutral：

```python
class BashCommandPolicyMode(str, Enum):
    DENY = "deny"
    EXACT_ALLOWLIST = "exact_allowlist"

class BashCommandPolicy(BaseModel):
    mode: BashCommandPolicyMode

    # Canonical Runtime-compiled foreground commands.
    allowed_commands: tuple[str, ...] = ()

    fingerprint: str
```

并进入 §9.13 唯一 authoritative `NodeExecutionPolicy` schema 的：

```text
bash_policy: BashCommandPolicy
```

本节不再重复声明 `NodeExecutionPolicy`。

P1 规则：

```text
Node 不需要 bash
→ DENY

Node 需要 deterministic test/build/import command
→ EXACT_ALLOWLIST
→ only Runtime-compiled commands
```

Runtime-compiled command 可以来自：

- canonical `tests_passed:<command>` acceptance；
- RepositoryProfile 已确认的 test/build command；
- Runtime-owned deterministic evaluation rule；
- explicit user HARD command requirement。

不能来自：

> “模型觉得这条命令可能有用，所以临时加进 allowlist”。

##### Command Matching

P1 不做通用 shell semantic equivalence。

Guard 对 `bash(command=...)` 使用 canonical string identity：

```text
normalize only Runtime-owned benign formatting
→ compare against exact allowed command set
```

禁止为了方便而：

- shell-eval 后比较；
- 忽略 control operator；
- 通过前缀匹配允许额外 suffix；
- `startsWith("pytest")` 这类宽松规则。

如果 Agent 想把：

```text
pytest -q
```

改成：

```text
pytest -q & ...
```

必须被拒绝。

##### Detached-Execution Defense in Depth

在 exact allowlist 之外，可以再对已允许命令做 defense-in-depth validation，拒绝已知 daemon/background/detach 形态，例如：

```text
nohup
disown
setsid
tmux / screen session launch
system/service manager start
docker/podman detached mode
known daemonization flags
background control operators when parsed as control syntax
```

但这只是 secondary guard。

不能宣传为：

> “我们写了几个正则，所以任意 shell 都不会 daemonize。”

真正的 P1 guarantee 来自：

> **只运行 Runtime 预先编译并审定的 foreground command identity。**

##### Bash Outside the Contract

如果任务确实要求：

- 启动长期 server；
- background daemon；
- detached watcher；
- arbitrary shell workflow；
- command 本身会 fork-and-detach；

则 P1：

```text
UNSUPPORTED_BACKGROUND_EXECUTION
```

或要求未来更强 Backend contract，例如：

```text
per-node disposable sandbox/container
+
explicit process-group kill/drain proof
```

不得在当前 shared AIO warm-pool contract 下假装安全执行。

##### AIO Best-Effort Cleanup 的解释

当 exact foreground command 已经由 tool handler 返回并且 executor worker 已 drain：

- shell-session cleanup failure 仍应进入 warning / backend diagnostics；
- 但 P1 不把“cleanup warning 未暴露”当作可以证明 session close 的依据；
- correctness 依赖“没有被允许启动 detached work”，而不是依赖 best-effort session close；
- 若未来 DeerFlow 暴露 strict cleanup outcome，Adapter 可进一步提升 quiescence attestation。

当前 completion signal 因此证明的是：

```text
executor-owned work quiescent
```

不是：

```text
container stopped
remote process universe empty
```

##### External Tool Boundary

对于：

```text
MCP
plugin
ACP
custom external-side-effect tool
```

若其实现不受 DeerFlow sandbox drained-worker contract 约束：

- backend execution quiescent 只表示 DeerFlow agent/tool-call coroutine 已结束；
- 不能证明远端服务没有继续处理已提交 side effect；
- 不能证明外部系统 rollback；
- `MutationEvidence.PROVEN_NONE` 不得仅依赖 Workspace snapshot。

所以 P1：

```text
EXTERNAL_SIDE_EFFECT
OR unverified custom UNKNOWN tool admitted
→ automatic clean retry disabled by default
```

除非 Tool Contract 明确提供：

```text
idempotency key
or transaction / rollback contract
or backend-specific quiescence/idempotency proof
```

一期 core SWE Runtime 不以这类 Tool 作为 hard dependency。

原则：

> **Workspace quiescence is bounded by the execution contract, not by wishful assumptions about every process or external service.**

### 3.5 NodeExecutionResult

A-SWE 不直接暴露 DeerFlow `SubagentResult`，而映射成自身稳定 Schema。

Pinned DeerFlow executor terminal status 只有：

```text
completed
failed
cancelled
timed_out
```

其中 `polling_timed_out` 只存在于上层 `task_tool` / wire-status contract，不是 direct `SubagentExecutor` 的 terminal status。A-SWE direct Adapter 禁止把两层 status vocabulary 混在一起。

P1 定义 provider-neutral typed contract：

```python
class BackendTerminalStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

class BackendStopReason(str, Enum):
    TOKEN_CAPPED = "token_capped"
    TURN_CAPPED = "turn_capped"
    LOOP_CAPPED = "loop_capped"

# ExecutionCompleteness is authoritative in specs/01-task-planning.md
# because NodeHandoff and NodeExecutionResult both depend on it.

class BackendExecutionPhase(str, Enum):
    PRE_START = "pre_start"
    STARTED = "started"

class BackendFailureClass(str, Enum):
    NONE = "none"

    # Capacity reject / queue timeout before the execution acquired a slot.
    ADMISSION = "admission"

    # A-SWE synthetic policy/assembly failure surfaced through terminal AI fallback.
    POLICY_OR_ASSEMBLY = "policy_or_assembly"

    # Ordinary DeerFlow / provider / tool / graph execution failure.
    EXECUTION = "execution"

    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

class NodeExecutionResult(BaseModel):
    execution_id: str
    node_id: str
    attempt: int

    # Backend terminal result, not logical Node status.
    terminal_status: BackendTerminalStatus

    result: str | None
    error: str | None

    stop_reason: BackendStopReason | None
    completeness: ExecutionCompleteness

    failure_class: BackendFailureClass
    admission_failure: bool

    execution_phase: BackendExecutionPhase

    started_at: datetime | None
    completed_at: datetime | None

    token_usage: list[dict]
    tool_receipts: list[dict] | None
    bash_executions: list[dict] | None

    # Raw assistant step metadata needed for precise A-SWE synthetic-failure mapping.
    ai_messages: list[dict]

    # Provider-neutral mapped advisory evidence; only produced when the
    # corresponding verifier has a valid terminal input.
    report_receipt_verdict: ReportReceiptVerdict | None

    backend_trace_id: str | None

    # Adapter-mapped execution lifecycle metadata.
    outer_timeout_fired: bool
    lifecycle_warnings: tuple[str, ...]
```

### 3.5.1 NodeAcceptanceResult

`ExecutionBackend.check_acceptance()` 返回 provider-neutral typed result，并作为 attempt-scoped `EvidenceRef(kind="acceptance_verdict")` 的 payload authority。

```python
class AcceptanceCriterionStatus(str, Enum):
    HOLDS = "holds"
    DOES_NOT_HOLD = "does_not_hold"
    UNVERIFIED = "unverified"

class AcceptanceCriterionResult(BaseModel):
    criterion: str
    status: AcceptanceCriterionStatus

    # Bounded deterministic diagnostics from the checker.
    diagnostics: tuple[str, ...] = ()

class NodeAcceptanceResult(BaseModel):
    node_id: str
    execution_id: str
    attempt: int

    observed_workspace_revision: WorkspaceRevision

    criteria: tuple[AcceptanceCriterionResult, ...]

    all_required_hold: bool
    has_unverified: bool

    checker: str = "deerflow_acceptance_checks"
    fingerprint: str
```

冻结规则：

```text
all_required_hold == true
↔ every load-bearing criterion status == HOLDS

any DOES_NOT_HOLD
→ AcceptanceFailure candidate

any UNVERIFIED
→ cannot promote to logical success when that criterion is load-bearing
```

`UNVERIFIED` 与 `DOES_NOT_HOLD` 不得合并：前者表示证据不足/检查器不能确定，后者表示确定性 obligation 未满足。

Adapter 顺序：

```text
NodeExecutionResult
→ check_acceptance()
→ NodeAcceptanceResult
→ ExecutionEvidenceStore.put_attempt(kind="acceptance_verdict")
→ EvidenceRef
→ logical acceptance/completeness gate
```

#### Terminal Status 与 Cap 必须正交

Pinned DeerFlow 明确允许：

```text
completed + token_capped
completed + turn_capped
completed + loop_capped
```

用于“有可用 partial result 的 capped run”。

同时也允许：

```text
failed + turn_capped
failed + token_capped / loop_capped
```

用于“cap fired but no usable partial result”。

所以 P1 不再使用：

```text
backend status != completed
→ completeness = None
```

而是：

```text
stop_reason is None
→ completeness = UNCAPPED

stop_reason in {
    token_capped,
    turn_capped,
    loop_capped
}
→ completeness = CAPPED
```

即：

> **Execution completeness is orthogonal to terminal success/failure.**

A-SWE 后续 logical-success gate 再解释：

```text
COMPLETED + UNCAPPED
→ backend clean completion candidate

COMPLETED + CAPPED
→ capped partial candidate
→ only deterministic-completeness proof may promote to logical success

FAILED + CAPPED
→ capped execution failure
→ never logical success
→ retry/repair only under mutation-safety rules

FAILED + UNCAPPED
→ ordinary backend failure

TIMED_OUT
→ timeout termination

CANCELLED
→ cancellation termination
```

#### PRE_START vs STARTED

Pinned DeerFlow background path 的顺序：

```text
execute_async()
      ↓
result = PENDING
      ↓
await capacity.slot()
      ↓
slot acquired
      ↓
result.status = RUNNING
result.started_at = utcnow()
      ↓
_aexecute_admitted()
      ↓
agent / model / tool / sandbox execution
```

因此在 pinned commit 中：

```text
started_at is None
→ native execution slot never acquired
→ _aexecute_admitted() never entered
→ no model/tool/sandbox business execution started
```

Adapter 映射：

```text
started_at is None
→ execution_phase = PRE_START

started_at is not None
→ execution_phase = STARTED
```

这个字段不能由 status 文本推断，而直接来自 `SubagentResult.started_at`。

特别重要的是 outer：

```python
asyncio.wait_for(
    self._aexecute(...),
    timeout=config.timeout_seconds,
)
```

**包含 capacity queue wait。**

所以可能出现：

```text
terminal_status = TIMED_OUT
admission_failure = false
started_at = None
```

这不是“Agent 已执行后超时”，而是：

> **整体 execution deadline 在 capacity admission 前耗尽。**

它与：

```text
TIMED_OUT
started_at != None
```

必须分开。

#### Mutation / Retry Consequence

`PRE_START` 是强 mutation-safety signal：

- no A-SWE admitted tool call should exist；
- no DeerFlow agent/model/tool body entered；
- no sandbox business action from this Node attempt occurred；
- no Repository mutation can originate from this backend execution。

因此：

```text
PRE_START
+ Binding/audit integrity intact
→ backend mutation evidence = PROVEN_NONE
```

不需要因为 DeerFlow workspace scanner truncated 就把**这个 backend execution**降为 UNKNOWN；它根本没有开始。

但：

- task-wide/user cancellation 仍不自动 retry；
- external out-of-band workspace mutation 不属于该 proof；
- 如果 `started_at=None` 却存在 A-SWE `ToolCallAdmissionRecord`，则属于 `BACKEND_CONTRACT_MISMATCH`，fail closed。

`STARTED` 后的 timeout/cancel/failure 才进入完整的：

```text
snapshot
+
ToolCallAdmissionRecord
+
receipt / workspace evidence
```

mutation classification。

原则：

> **No slot acquired is stronger than “no change observed”.**

---

#### Admission Failure 映射

Pinned DeerFlow `SubagentResult.admission_failure=True` 的语义是：

> capacity rejection / queue admission timeout occurred before the subagent execution acquired a running slot.

因此所有正常 `admission_failure=True` 都应同时满足：

```text
execution_phase == PRE_START
started_at is None
```

若不满足，Adapter 视为 `BACKEND_CONTRACT_MISMATCH`。

因此：

```text
terminal_status == FAILED
AND admission_failure == true
→ failure_class = ADMISSION
```

它不是：

- model authorization failure；
- A-SWE Provider preflight failure；
- NodeToolPolicy synthetic mismatch；
- general LLM provider failure。

这些必须保留不同 taxonomy。

#### Synthetic A-SWE Failure 映射

A-SWE synthetic policy response 仍通过：

```text
terminal_status = FAILED
```

返回，但 Adapter 必须读取 terminal AIMessage 的 server-owned：

```text
aswe_policy_failure
aswe_failure_code
aswe_node_execution_id
```

映射为：

```text
failure_class = POLICY_OR_ASSEMBLY
```

而不是靠 `error` 自由文本猜测。

其他：

```text
FAILED
+ admission_failure == false
+ no A-SWE failure marker
→ failure_class = EXECUTION

TIMED_OUT
→ failure_class = TIMEOUT
→ execution_phase 决定它是 pre-start deadline exhaustion 还是 started execution timeout

CANCELLED
→ failure_class = CANCELLED

COMPLETED
→ failure_class = NONE
→ outer_timeout_fired may still be true; preserve lifecycle warning separately
```

#### Adapter Mapping 必须穷举

DeerFlow Adapter 对 pinned `SubagentStatus` / `stop_reason` 使用 exhaustive mapping。

未知 status / stop_reason：

```text
→ BACKEND_CONTRACT_MISMATCH
→ fail closed
```

禁止：

```text
unknown string
→ treat as failed / clean by default
```

这样 DeerFlow 升级新增 terminal semantics 时，会由 compatibility test 暴露，而不是静默改变 Retry/Repair 行为。

> **Backend COMPLETED 仍然不等于 A-SWE Node SUCCEEDED。**

### 3.6 DeerFlow 集成基线与升级策略

本轮源码审计冻结基线：

```text
bytedance/deer-flow
commit: c0895d295bba34f6e95188fca380f555dabed891
```

重点验证路径：

```text
deerflow/subagents/config.py
deerflow/subagents/executor.py
deerflow/subagents/runtime.py
deerflow/subagents/capacity.py
deerflow/sandbox/middleware.py
deerflow/sandbox/lease.py
deerflow/subagents/acceptance_checks.py
```

由于 `SubagentExecutor` 属于较低层 Harness API，A-SWE 必须：

1. 将所有 DeerFlow-specific import 限制在 `integrations/deerflow/`；
2. 固定并记录兼容的 DeerFlow commit / version；
3. 为 Adapter 建立独立 integration tests；
4. 升级 DeerFlow 时优先重新执行 P0.5 PoC，而不是直接假设接口兼容。

### 3.7 DeerFlow Harness 复用范围

底层 Harness 主要复用：

- Subagent 执行；
- Tool Calling；
- Skill Discovery / Activation；
- MCP Tool Routing；
- Sandbox；
- Sandbox Lease；
- Context / Thread Data；
- Tool Receipt；
- Token / Turn / Loop Guard；
- Langfuse / LangSmith 等底层 Trace 能力。

实施原则：

> 能通过 Execution Adapter 使用的基础设施能力，不在 A-SWE 中重复实现。

---

## 9. DAG Materialization 与 Task Scheduler

### 9.1 DAG Materializer 的职责

DAG Materializer 输入：

```text
ValidatedWorkPlan
+
Provider Assignment
+
Capability Metadata
+
Workspace Policy
+
Acceptance Policy
```

输出：

```text
Executable TaskDAG
```

LLM 不直接生成最终 TaskNode。

### 9.2 TaskNode

```python
class TaskNode(BaseModel):
    id: str
    objective: str
    work_kind: WorkKind

    required_capabilities: tuple[str, ...]
    provider_id: str

    dependencies: tuple[str, ...]

    workspace_access: WorkspaceAccess

    planner_ordinal: int
    runtime_owned: bool = False

    affected_paths: tuple[str, ...] | None = None

    # Canonical compiled acceptance criteria only.
    acceptance_criteria: tuple[str, ...] = ()

    fingerprint: str
```

冻结规则：

- `TaskNode` / `TaskDAG` 是 immutable compile artifacts；
- mutable lifecycle 只存在于 `NodeRuntimeState / NodeAttemptRecord`；
- Retry / Repair eligibility 与预算属于 Scheduler-owned Runtime config，不写进 Planner/TaskNode；
- `provider_id` 来自 validated ProviderAssignment，不允许 execution-time 私下 rebinding；
- `planner_ordinal` 延续 `ValidatedWorkItem.planner_ordinal`，用于 deterministic same-phase serialization；
- `runtime_owned` 标识 compiler 注入的 `__aswe_*` gate。

#### Verification Repair Ownership Binding

P1 不允许在测试失败以后根据：

- “最后一个 Coder”；
- Tester / Coder 自由文本；
- failed test path 与 changed path 的表面重合；
- Provider identity；
- 执行时间上最近的 WRITE；

来猜测 Repair target。

原因是：

> **Verification failure does not prove causal blame.**

P1 只解决一个更窄、可确定性实现的问题：

> **当前 deterministic verification obligation 是否存在唯一的 logical repair owner。**

这里的 attribution 是 **repair ownership attribution**，不是 root-cause causality proof。

DAG Materializer / ExecutionPlanCompiler 为每个 downstream deterministic verification check 编译 immutable binding：

```python
class VerificationRepairBinding(BaseModel):
    verification_node_id: str
    verification_check_id: str

    # Logical IMPLEMENTATION nodes that may own remediation for this check.
    candidate_write_node_ids: tuple[str, ...]

    derivation: Literal[
        "dag_business_writer_ancestors",
        "runtime_owned_gate",
    ]

    # Canonical nodes + dependency structure only; avoids a hash cycle.
    dag_structure_fingerprint: str
    fingerprint: str

class TaskDAG(BaseModel):
    nodes: tuple[TaskNode, ...]
    topological_order: tuple[str, ...]

    # Canonical nodes + dependencies only.
    structure_fingerprint: str

    verification_repair_bindings: tuple[VerificationRepairBinding, ...] = ()

    # Final identity covers structure + compiled bindings.
    fingerprint: str
```

其中 `verification_check_id` 必须引用 Runtime 编译后的 deterministic check identity；shell-based check 通常直接引用 `VerificationCommand.id`。

`VerificationRepairBinding.dag_structure_fingerprint` 必须等于所属 `TaskDAG.structure_fingerprint`。最终 `TaskDAG.fingerprint` 再覆盖 structure + bindings，避免 binding 与最终 DAG hash 相互递归。

P1 candidate 集合只从 immutable DAG / semantic authority 推导：

```text
transitive ancestors of Verification Node
        ∩
WorkKind == IMPLEMENTATION
        ∩
semantic authority includes REPOSITORY_MUTATION
```

注意：

```text
WorkspaceAccess.WRITE
!=
business writer
```

所以：

- Tester 因 bash 获得 WRITE lock，不进入 candidate writers；
- Reviewer / Discovery 即使物理 ToolEffect 导致 WRITE scheduling，也不进入 candidate writers；
- same Provider 执行两个 IMPLEMENTATION Node，仍然是两个 logical writer candidates；
- 同一个 logical Writer 的多次 attempt 不扩大 candidate node 集合，attempt 在 runtime attribution 时再解析。

对于 Runtime 注入的：

```text
__aswe_verify
```

其 mandatory edges 已经是：

```text
all relevant IMPLEMENTATION nodes
        ↓
__aswe_verify
```

因此 global gate 的 candidate set 会自然覆盖所有业务 mutation owners。

P1 **不允许**用以下信息缩小 candidate set：

```text
failed test filename
stack trace path
repository_changed_paths overlap
affected_paths hint
verifier_report
Agent self-report
"last writer"
```

这些信息可以进入 diagnostics / Trace，但不是 attribution authority。

如果需要更精确的 multi-writer repair ownership，必须未来引入更强的 compiler-owned obligation-to-writer mapping，而不是在运行时做启发式 root-cause guessing。

### 9.3 Side-Effect Compilation

`workspace_access` 由 Runtime 根据：

```text
Capability Workspace Effect Floor
+
Node Required Tools
+
ToolEffect Registry
+
Backend Capability
```

联合编译。

```text
only provably read-only capabilities/tools
→ READ

any write-capable / unknown tool
→ WRITE
```

因此：

```text
regression_testing + bash
→ WRITE

code_review + read_file/grep
→ READ

repo_exploration + read_file/glob/grep
→ READ
```

这不是说“运行测试等价于修改业务代码”，而是表示：

> Scheduler 无法证明 shell execution 对共享 Workspace 无副作用，因此需要独占。

LLM `effect_hint` 不具有 authority。

### 9.4 Dependency / Workspace Conflict Normalization

Planner dependency 先做：

```text
existence validation
cycle detection
phase consistency
transitive sanity check
```

Workspace Mutex 只能回答：

> **两个 Node 能不能同时执行？**

它不能回答：

> **哪个 Node 应该先观察 Repository 状态？**

因此 DAG Materializer 先依据 `WorkKind` 冻结语义阶段，再用 `WorkspaceAccess` 解决同阶段或未显式排序的资源冲突。

#### 9.4.1 WorkKind Phase Order

P1 定义语义偏序：

```text
DISCOVERY
    ↓
IMPLEMENTATION
    ↓
VERIFICATION
    ↓
REVIEW
```

这不是要求所有任务都必须包含四阶段，而是：

> 当两个节点共享同一任务状态、存在潜在 workspace interaction 且没有用户/Planner 明确 dependency 时，Runtime 不得生成违背这一语义方向的顺序。

典型：

```text
Explorer READ
→ Coder WRITE

Coder WRITE
→ Tester WRITE/exclusive

Tester WRITE/exclusive
→ Reviewer READ
```

注意：

```text
WorkspaceAccess(Tester) = WRITE
WorkspaceAccess(Reviewer) = READ
```

并不会推出：

```text
Reviewer → Tester
```

因为语义顺序由 WorkKind 决定。

#### 9.4.2 Explicit Dependency Validation

Planner 显式 dependency 优先保留，但必须通过 phase consistency。

例如：

```text
REVIEW → IMPLEMENTATION
```

若 REVIEW 的语义是最终修改后审查，则属于：

```text
PHASE_ORDER_CONTRADICTION
```

进入 bounded replan，而不是 Runtime 静默反转 Edge。

同理：

```text
VERIFICATION → IMPLEMENTATION
```

对独立 post-change verification 是非法方向。

若 Planner 真正想表达：

> “先检查现有 tests，再决定怎么改”

则前一个 WorkItem 应标为：

```text
DISCOVERY
```

而不是 VERIFICATION。

#### 9.4.3 Cross-Phase Missing Edges

若两个相关 Node phase 有明确偏序但 Planner 漏边：

```text
DISCOVERY + IMPLEMENTATION
→ add DISCOVERY → IMPLEMENTATION

IMPLEMENTATION + VERIFICATION
→ add IMPLEMENTATION → VERIFICATION

VERIFICATION + REVIEW
→ add VERIFICATION → REVIEW
```

这种 Edge 注入是 monotonic ordering repair：

- 不改变 objective；
- 不删除 WorkItem；
- 不扩大权限；
- 只阻止语义阶段倒序或错误并行。

所有 injected edges 必须进入：

```text
PlanRepair log
```

#### 9.4.4 Same-Phase Workspace Conflict

当 WorkKind 相同、Planner 未显式排序，但 WorkspaceAccess 冲突：

##### WRITE / WRITE

```text
Node A
  ↓
Node B
```

按 validated planner ordinal 等稳定顺序串行。

##### READ / WRITE

不再采用全局：

```text
READ → WRITE
```

规则。

同一 phase 中使用稳定 planner ordinal：

```text
earlier ordinal
      ↓
later ordinal
```

因为一旦二者都属于同一语义阶段，Runtime 没有足够 authority 根据 READ/WRITE 猜测业务数据依赖。

若真实语义需要固定顺序，Planner 必须显式依赖，或由 phase/gate rule 推导。

#### 9.4.5 READ / READ

无 dependency 且均为：

```text
WorkspaceAccess.READ
```

时可以并行。

#### 9.4.6 WorkKind 与 Access Validation

典型 consistency：

| WorkKind | 允许的物理 Access | 说明 |
|---|---|---|
| DISCOVERY | READ 为主 | 若编译成 WRITE，需明确 ToolEffect 原因并产生 warning |
| IMPLEMENTATION | READ / WRITE | 通常 WRITE |
| VERIFICATION | READ / WRITE | bash testing 常被物理编译成 WRITE |
| REVIEW | READ 为主 | P1 不允许 Reviewer 拥有 business mutation capability |

因此：

> **WorkKind 是语义 phase；WorkspaceAccess 是并发资源 class。二者都进入 DAG Materialization，但职责不能混用。**

#### 9.4.7 Ordering Algorithm

P1 Materializer：

```text
1. preserve validated explicit edges
2. reject explicit phase inversion
3. inject mandatory gate edges
4. add missing cross-phase edges when nodes are workspace-related
5. recompute acyclic
6. for remaining unordered conflicting same-phase pairs:
      stable ordinal serialization
7. recompute transitive reduction / canonical edge ordering
8. emit PlanRepair log
```

其中“workspace-related”一期可保守定义为：

> 同一个 WorkspaceSession 中、至少一个节点不是 pure READ-independent branch。

不做复杂 file-level dependency inference。

原则：

> **Semantic phase determines direction; Workspace policy determines concurrency.**

### 9.5 READ Parallelism

只有 dependency-free 且语义 phase 允许并行的 READ / READ 才允许真实并行：

```text
Inspect API ─┐
             ├→ downstream
Inspect Test ─┘
```

并行仍受：

- NodeBoundaryPolicy；
- backend execution capacity；
- global Runtime budget；

限制。

### 9.6 Handoff Data Dependency

DAG Edge 同时表示：

```text
Control Dependency
+
Data Dependency
```

下游请求由 Runtime 组装：

```text
Original Task
+
Current Node Objective
+
Bounded Dependency Handoff Envelopes
+
Current Workspace Revision
+
Runtime Guidance
+
Acceptance Criteria
```

其中：

- Handoff `self_report` 永远是 untrusted data；
- Runtime evidence / revision 由 framework-owned envelope 标识其 provenance；
- evidence reference 的存在不代表下游已经重验证其语义；
- 上游 receipt 不成为下游 receipt；
- revision stale 的 handoff 要显式标注；
- 多 parent handoff 按 canonical dependency order 保持分离，不做 LLM pre-merge。

安全 authority 仍来自 NodeExecutionPolicy / Guardrail / Sandbox，而不是 prompt 中的 Runtime Guidance。

### 9.7 Scheduler 的职责

Scheduler 不负责 Task decomposition。

一期职责：

- Ready Node calculation；
- dependency enforcement；
- READ-only parallel dispatch；
- Workspace Access arbitration；
- WRITE exclusivity；
- Node status tracking；
- retry classification；
- NodeRuntimeState / attempt lifecycle；
- bounded repair / reverify；
- cancellation；
- failure propagation；
- acceptance gate；
- Repository invariant gate；
- handoff routing；
- post-lock handoff / dependency-authority revalidation；
- revocable dispatch ticket / final dispatch commit；
- Writer reopen vs consumer commit linearization；
- result aggregation。

### 9.8 Failure Taxonomy

不能把所有失败统一成 “retry once”。

至少区分：

```text
AdmissionFailure
BackendPreflightStale
ProviderAssemblyMismatch
ExecutionTransientFailure
ExecutionCappedPartial
DirtyWriteFailure
WorkspaceQuarantined
AcceptanceFailure
AcceptanceCommandPolicyMismatch
VerificationFailure
ReviewGateRejected
ReviewGateUnverified
PlanInvalidated
PolicyViolation
RepositoryInvariantFailure
RepositoryMutationAuthorityViolation
EvidenceFinalizationFailure
RepairFeedbackStale
RepairScopeInvalidated
Cancelled
```

处理原则：

| Failure | 行为 |
|---|---|
| admission failure before execution | wait / bounded retry |
| overall timeout before capacity slot (`PRE_START`) | bounded retry candidate；无需按 started WRITE 处理 mutation |
| backend preflight stale | fail before execution；pre-WRITE 时可 bounded replan |
| provider assembly mismatch | fail closed；P1 不自动换 Provider |
| READ transient failure | Scheduler-owned retry rules |
| capped partial + complete deterministic proof | accept with `EXECUTION_CAPPED_BUT_ACCEPTED` warning |
| capped partial + no complete proof + proven-clean READ | bounded retry / fail |
| capped partial + dirty/unknown WRITE | no blind retry；deterministic repair evidence exists 才 repair，否则 fail closed |
| WRITE failure 且 `mutation_evidence == PROVEN_NONE` | bounded retry candidate |
| WRITE failure 且 `mutation_evidence == OBSERVED / UNKNOWN` | publish dirty/advanced post revision，然后 fail closed |
| acceptance does-not-hold | repair unmet condition / fail |
| verification test failure | bounded upstream repair，再 verify |
| repair feedback revision stale | refresh deterministic checker / reverify；无法刷新则 REPAIR_FEEDBACK_STALE |
| repair scope invalidated | fail closed / restart-from-baseline；不隐式 rollback descendants |
| review decision = REQUEST_CHANGES | REVIEW_GATE_REJECTED；保留 findings；P1 不自动 semantic repair |
| review decision = UNVERIFIED | REVIEW_GATE_UNVERIFIED；gate unsatisfied |
| UNVERIFIED | additional deterministic check 或保留 uncertainty |
| PLAN_INVALIDATED before any WRITE | bounded replan |
| PLAN_INVALIDATED after WRITE | MVP fail / restart-from-baseline |
| policy / repository invariant violation | fail closed |
| read-only semantic Node changes Git-visible Repository state | REPOSITORY_MUTATION_AUTHORITY_VIOLATION；fail closed |
| cancelled | propagate cancellation |

### 9.8.1 Backend Completion vs Logical Node Success

Pinned DeerFlow 的 `completed` 只表示：

> execution ended with usable result text.

它不保证 objective 已完整完成，也不保证 guard budget 未提前终止。

尤其：

```text
completed + token_capped
completed + turn_capped
completed + loop_capped
```

统一映射为：

```text
ExecutionCompleteness.CAPPED
```

DeerFlow delegation ledger 自身也明确：

```text
Completed means execution ended, not task acceptance.
```

因此 A-SWE logical Node outcome 由：

```text
Backend terminal status
+
ExecutionCompleteness
+
Workspace / Repository invariants
+
Acceptance verdict
+
WorkKind semantic-gate policy
        ↓
Logical Node Outcome
```

共同决定。

#### Capped Completion Admission Matrix

P1 保守规则：

| 条件 | CAPPED 是否可被逻辑接受 |
|---|---:|
| deterministic acceptance coverage 完整，所有 load-bearing leaves checked + holds，所有 repository / contract invariants 通过 | 可以，但必须携带 capped warning |
| 没有 acceptance criteria / completeness proof | 不可以 |
| 任一 criterion does-not-hold | 不可以 |
| 任一 load-bearing criterion UNVERIFIED | 不可以 |
| mandatory REVIEW | 不可以 |
| DISCOVERY 且没有 deterministic completeness proof | 不可以 |
| WRITE 已修改 Workspace，但缺少完整 deterministic proof | 不可以，也不能 blind retry |

这里的：

```text
deterministic acceptance coverage complete
```

必须由 Acceptance Compiler / ExecutionPlanValidator 显式生成，不等于“恰好存在一个 acceptance criterion”。

只有满足完整 proof 的 capped run 才能：

```text
Logical Node Status = SUCCEEDED
warning = EXECUTION_CAPPED_BUT_ACCEPTED
```

其 Handoff 仍必须标记：

```text
backend_stop_reason
execution_completeness = capped
```

不能向下游伪装成 clean completion。

#### Unaccepted Capped Completion

否则：

```text
ExecutionCappedPartial
```

不是普通 `ExecutionTransientFailure`。

处理：

- READ / semantic READ_ONLY 且 Workspace proven unchanged：
  - 可按 bounded Scheduler retry rules 重试；
  - Runtime 可以缩小 attempt context / objective projection；
  - P1 不自动提高 DeerFlow operator `max_turns` / token budget。
- WRITE / UNKNOWN-mutating 且 Workspace proven unchanged：
  - 可 bounded retry。
- WRITE / UNKNOWN-mutating 已发生或无法排除 mutation：
  - 不自动 retry；
  - 若存在 deterministic unmet acceptance，可进入既有 Repair 规则；
  - 若只有“被 cap 截断”而没有 deterministic repair evidence，则 fail closed。

#### Mandatory Review

P1 mandatory Review 是 semantic gate：

```text
REVIEW + CAPPED
→ review gate unsatisfied
```

即使 reviewer 的部分文本看起来像“looks good”，也不算完整 review evidence。

#### Partial Result Preservation

未被接受的 capped run 的：

- result；
- receipts；
- workspace delta；
- report receipt verdict；

仍进入 Trace / EvidenceStore。

但：

- 不产生 normal success NodeHandoff；
- 不解锁普通 downstream dependency；
- retry / repair 可以显式消费 failure context。

原则：

> **Preserve partial work as evidence; do not silently promote partial execution to logical success.**

---

### 9.9 WRITE Retry Safety

DeerFlow `workspace_changes` snapshot 适合作为 evidence / diff，不是通用 transaction rollback：

- binary / large / sensitive content 可能不可恢复；
- snapshot 有 scan / file / diff limit；
- 它不是 Git transaction log；
- `.git` 本身被 scanner 排除。

因此 WRITE Node 前可以 capture pre-attempt snapshot。

失败后：

```text
mutation_evidence == PROVEN_NONE
→ retry may be allowed

mutation_evidence == OBSERVED
OR mutation_evidence == UNKNOWN
→ DIRTY_WRITE_FAILURE
→ no automatic retry in MVP
```

因此“无修改可安全重试”必须满足冻结的 `PROVEN_NONE` predicate，而不是“snapshot 没列出文件”。

后续若实现真正的 Git/worktree checkpoint，再开放 dirty-write rollback + retry。

### 9.10 Retry vs Repair

```text
Retry
→ 同一个逻辑 Node 因 transient execution fault 再执行
→ 前一 attempt 必须 proven-clean / 无 Workspace mutation

Repair
→ acceptance / downstream verification 提供新 deterministic evidence
→ 在当前 mutated Workspace 上对原 WRITE objective 做 bounded amendment
```

二者都不创建新的语义 WorkItem，也不改 TaskDAG topology。

#### Logical Node State 与 Dependency Satisfaction

P1 必须区分：

```text
Attempt Outcome
vs
Logical Node Status
```

一次 attempt 失败后，如果 Runtime 已合法选择：

```text
RETRY
REPAIR
REVERIFY
```

则 Node **尚未 terminal FAILED**，而进入：

```text
REMEDIATION_PENDING
```

只有：

- 没有合法 remediation transition；
- remediation budget 耗尽；
- policy / dirty-state / invariant 要求 fail closed；

才进入最终：

```text
FAILED
```

普通 DAG dependency edge 的 ready predicate 冻结为：

```text
for every upstream dependency U:

U.logical_status == SUCCEEDED
AND U.accepted_attempt is not None
AND U.accepted_handoff is not None
AND accepted_handoff.source_attempt == U.accepted_attempt
AND Handoff EvidenceRefs resolve successfully
AND Handoff / evidence satisfies current revision-staleness rules
```

因此：

| Upstream logical state | Ordinary downstream |
|---|---|
| PENDING / READY / RUNNING | 保持 PENDING |
| REMEDIATION_PENDING | 保持 PENDING；不能消费旧 success handoff |
| SUCCEEDED | 满足 handoff/revision gate 后才可 READY |
| FAILED | BLOCKED |
| BLOCKED | BLOCKED，记录 root blockers |
| CANCELLED | local cancel → BLOCKED；task-wide cancel → CANCELLED |

P1 不把失败处理建模成普通 failure-edge DAG：

```text
Writer FAILED → Repair Node
```

Repair / Retry / Reverify 是 Scheduler 对**原 immutable TaskNode**的 attempt transition，不创建新语义节点。

#### Revocable Dispatch Ticket 与 Dispatch Commit

`NodeLogicalStatus` 不应该承担“正在 prepare / 等 Workspace lock / 已拿锁但尚未真正开始 attempt”这些瞬时调度状态。

P1 增加 Scheduler-only、可撤销的 dispatch ticket：

```python
class NodeDispatchTicketState(str, Enum):
    PREPARING = "preparing"
    WAITING_WORKSPACE = "waiting_workspace"
    LOCKED_PRECOMMIT = "locked_precommit"

    # Linearization point crossed; an actual Node attempt now exists.
    COMMITTED = "committed"

    REVOKED = "revoked"
    FINISHED = "finished"

class NodeDispatchTicket(BaseModel):
    ticket_id: str
    node_id: str

    task_dispatch_epoch: int
    dependency_acceptance_stamps: tuple[DependencyAcceptanceStamp, ...]

    state: NodeDispatchTicketState
```

Ticket 不是 EvidenceRef，也不是 NodeAttemptRecord。它只是 Scheduler concurrency-control artifact。

规则：

READY predicate 计算与 ticket claim 必须在 `SchedulerStateMutex` 下完成，形成一个短事务：

```text
lock SchedulerStateMutex
→ verify Node still READY
→ verify task dispatch gate OPEN
→ capture each direct dependency:
     acceptance_epoch
     accepted_attempt
     handoff fingerprint
→ create exactly one active ticket
→ release SchedulerStateMutex
```

禁止：

```text
compute READY
→ release scheduler state authority
→ later capture dependency stamps
```

否则 ticket 可能从两代 dependency authority 拼出一个不存在的 snapshot。

随后：

```text
READY Node claimed
→ create one active ticket
→ Node logical_status remains READY

prepare_node()
→ PREPARING

wait WorkspaceAccess
→ WAITING_WORKSPACE

Workspace lock granted
→ LOCKED_PRECOMMIT

final dependency / dispatch validation succeeds
→ atomic DISPATCH COMMIT
→ allocate attempt/execution/run ids
→ Node READY → RUNNING
→ ticket COMMITTED
→ NodeAttemptRecord begins
```

因此：

> **RUNNING means dispatch committed, not merely selected by Scheduler.**

pre-commit ticket 被 revoke：

- 不创建 NodeAttemptRecord；
- 不消耗 retry / repair budget；
- 不生成 execution evidence；
- prepared backend object 丢弃；
- Workspace wait 可取消；
- 若 lock 已拿到，则在 pre-commit gate 失败后释放；
- Node 回到 / 保持 `PENDING`，等待依赖重新满足后再次 READY。

##### acceptance_epoch

每个 Node 的 `acceptance_epoch` 是 dependency authority generation。

以下 transition 必须递增：

```text
no accepted authority
→ publish accepted attempt/handoff

accepted H1
→ revoke H1 because Writer reopens

no current authority after repair
→ publish accepted H2
```

例如：

```text
Writer success H1      epoch = 1
Writer reopen          epoch = 2, accepted authority = none
Writer repair success  epoch = 3, H2
```

accepted authority publication 也必须在 `SchedulerStateMutex` 下原子完成：

```text
logical success confirmed
        ↓
lock SchedulerStateMutex
        ↓
publish accepted_attempt
publish accepted_handoff
acceptance_epoch += 1
recompute dependent READY predicates
        ↓
unlock
```

不能先让 downstream 看见新 Handoff，再晚一步更新 epoch。

consumer 的 `DependencyAcceptanceStamp` 同时记录：

- upstream node id；
- epoch；
- accepted attempt；
- handoff fingerprint。

这样即使旧 Handoff object 仍留在 Trace，旧 ticket 也不会重新获得 authority。

##### Task Dispatch Gate

Task Runtime 维护：

```python
class TaskDispatchGateState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"

class TaskDispatchGate(BaseModel):
    state: TaskDispatchGateState
    epoch: int
```

task-wide fail-close / cancellation 关闭 gate 时递增 epoch。

任何 ticket 的最终 dispatch commit 都必须验证：

```text
gate.state == OPEN
AND ticket.task_dispatch_epoch == gate.epoch
```

这使已经 READY / waiting 的旧 ticket 在 Task fail-close 后无法越过 commit boundary。

##### Dispatch Commit Linearization Point

仅有“post-lock handoff revalidation”仍存在 TOCTOU：

```text
consumer validates H1
        ↓
Writer reopens / revokes H1
        ↓
consumer enters backend
```

所以 P1 要求 **dispatch commit 与 Writer reopen 使用同一个 SchedulerStateMutex**。

consumer 在持有 WorkspaceAccess 后：

```text
freeze WorkspaceRevision
resolve/render handoffs
        ↓
acquire SchedulerStateMutex
        ↓
validate:
  ticket still active / not REVOKED
  task dispatch gate still OPEN + same epoch
  Node still READY and owns this ticket
  every direct dependency still:
      SUCCEEDED
      same acceptance_epoch
      same accepted_attempt
      same handoff fingerprint
        ↓
if valid:
  allocate attempt/execution ids
  freeze NodeExecutionInvocation
  READY → RUNNING
  ticket → COMMITTED
        ↓
release SchedulerStateMutex
        ↓
pre-attempt snapshot / execute_prepared()
```

禁止在持有 SchedulerStateMutex 时等待 Workspace lock、backend capacity 或执行 I/O。

资源关系保持：

```text
Workspace lock
→ short SchedulerStateMutex commit section
→ backend capacity
```

而 Writer reopen 只短暂持有 SchedulerStateMutex，不在其中等待 Workspace lock，因此不会引入反向：

```text
SchedulerStateMutex → wait Workspace
```

的 ABBA。

#### Accepted Handoff Single-Owner Rule

同一 Node 任意时刻最多只有一个：

```text
accepted_attempt
accepted_handoff
```

能够满足普通 downstream dependency。

当已 SUCCEEDED 的 Writer 因 downstream deterministic verification failure 被重新打开进入 REPAIR：

1. Writer 从 `SUCCEEDED` → `REMEDIATION_PENDING`；
2. 保存旧 accepted attempt/handoff identity 到 RepairFeedback / Trace 后，撤销 current dependency authority；
3. `accepted_attempt = None`、`accepted_handoff = None`，并递增 `acceptance_epoch`；
4. 新 Repair attempt 基于 current WorkspaceRevision 执行；
5. Repair 成功后产生新的 accepted attempt/handoff，并再次递增 acceptance_epoch；
6. Verification 使用 REVERIFY attempt 重新验证；
7. 只有最新 verification accepted attempt 才能继续解锁 Review / final downstream。

这防止：

```text
Writer attempt 1 succeeded
→ Reviewer/consumer keeps running on H1
while
Writer attempt 2 is repairing the same workspace
```

#### Repair Reopen Safety Gate

由于 P1 不实现 arbitrary DAG rollback / descendant invalidation，已成功 Writer 只能在满足以下条件时被 verification-triggered Repair 重新打开：

```text
single target WRITE Node uniquely identified
AND repair budget remains
AND target's mutation authority permits repair
AND no affected ordinary downstream dispatch is COMMITTED / RUNNING
AND no ordinary non-verification descendant has already committed
    a logical success that depends on the target's currently accepted Handoff
AND no later business WRITE has made target repair ownership ambiguous
```

否则：

```text
REPAIR_SCOPE_INVALIDATED
→ fail closed / restart-from-baseline
```

mandatory phase ordering通常使：

```text
IMPLEMENTATION → VERIFICATION → REVIEW
```

天然满足这个条件；但 Runtime 仍必须检查，不能仅靠 prompt/plan 假设。

##### Writer Reopen vs Downstream Dispatch Race

Repair reopen 与 downstream dispatch 必须在 SchedulerStateMutex 上线性化。

Writer W 准备 reopen 时，Runtime 先计算：

```text
affected descendants of W
```

并检查这些 Node 的 logical / dispatch state。

###### A. READY，尚无 ticket

```text
Writer reopen wins
→ revoke accepted authority
→ READY predicate no longer holds
→ consumer READY → PENDING
```

不产生 attempt。

###### B. PREPARING / WAITING_WORKSPACE

ticket 可撤销：

```text
ticket → REVOKED
Node remains / returns PENDING
```

- preparation result 丢弃；
- Workspace lock wait 被取消或唤醒后自行退出；
- 不调用 Backend cancel，因为 backend execution 尚未 commit；
- 不产生 NodeAttemptRecord。

###### C. LOCKED_PRECOMMIT

consumer 已拿 Workspace lock、完成或正在完成 context resolution，但还没有 dispatch commit。

Writer reopen 在 SchedulerStateMutex 中：

```text
ticket → REVOKED
Writer authority revoked
```

consumer 随后的 commit gate 必须看到：

```text
ticket REVOKED
OR acceptance_epoch mismatch
OR accepted handoff mismatch
```

因此：

```text
no commit
→ no attempt
→ discard Invocation candidate
→ release Workspace lock
→ PENDING
```

这正是 post-lock revalidation 之后仍需要 commit mutex 的原因。

###### D. COMMITTED / RUNNING

一旦 affected ordinary downstream ticket 已 `COMMITTED`：

> **P1 不再撤销该 execution 后继续 Writer Repair。**

即使 DeerFlow 还处于：

```text
execution_phase = PRE_START
```

只要 A-SWE dispatch commit 已经发生，Repair reopen gate 就视为 active consumer 已跨越 rollback-free boundary。

原因：

- NodeAttemptRecord 已存在；
- immutable Invocation / dependency authority 已冻结；
- binding/backend execution lifecycle 可能已建立；
- 再引入“cancel clean → pretend attempt never happened → reopen writer”需要新的 transaction semantics。

P1 返回：

```text
REPAIR_SCOPE_INVALIDATED
reason = ACTIVE_DOWNSTREAM_DISPATCH
```

然后：

```text
close Task dispatch gate
do NOT reopen Writer
request cancellation of affected committed/running consumers
await quiescence
classify their actual mutation/evidence normally
Task → FAILED
Workspace → FROZEN if all quiescent
          or QUARANTINED if quiescence cannot be proven
```

被 fail-close 取消的 consumer 不成为新的业务 root failure；root 仍是：

```text
verification failure
+
repair scope invalidation evidence
```

如果 consumer cancellation 自身造成 repository authority violation / dirty mutation，则该证据进入 secondary runtime failure diagnostics，并影响 Workspace/Repository disposition。

未来可以优化：

```text
COMMITTED + backend PRE_START + proven clean cancellation
→ retract attempt and permit repair
```

但 P1 明确不实现，以免把 backend execution phase 与 Scheduler transaction rollback 混为一谈。

###### E. 已 SUCCEEDED ordinary non-verification descendant

沿用现有规则：

```text
REPAIR_SCOPE_INVALIDATED
reason = COMMITTED_DOWNSTREAM_SUCCESS
```

P1 不做 descendant rollback / accepted-handoff cascade invalidation。

##### Reopen Transaction

若不存在 COMMITTED/RUNNING 或已成功的 unsafe consumer，则 reopen 在一次 SchedulerStateMutex transaction 内完成：

```text
1. persist/attach RepairAttribution reference
2. revoke all affected pre-commit tickets
3. Writer SUCCEEDED → REMEDIATION_PENDING
4. capture old target accepted attempt for RepairFeedback
5. clear Writer accepted_attempt / accepted_handoff
6. Writer acceptance_epoch += 1
7. source Verification → REMEDIATION_PENDING for future REVERIFY
8. recompute affected READY nodes → PENDING
9. release SchedulerStateMutex
```

注意：

- transaction 内不等待被 revoke ticket 释放 Workspace lock；
- Repair attempt 后续正常请求 WRITE lock；
- 已拿 READ lock 的 `LOCKED_PRECOMMIT` consumer 会在 commit gate 看到 revoked，释放后 Repair 才能获得 WRITE；
- 这避免 SchedulerStateMutex 与 Workspace lock 反向等待。

##### Dispatch Ticket 与 WorkspaceRevision 是两个不同 Fence

```text
WorkspaceRevision
→ 保护“context 对应哪一个物理 workspace state”

DependencyAcceptanceStamp / dispatch commit
→ 保护“上游 accepted authority 是否仍然有效”
```

只检查 revision 不够，因为 Writer 可以：

```text
accepted H1 @ revision R
→ reopen / revoke H1
```

而在真正 Repair mutation 发生前 WorkspaceRevision 仍然可能还是 R。

所以：

> **staleness is not only a workspace-version problem; it is also an accepted-authority problem.**

#### Failure Propagation Root Cause

BLOCKED Node 自身不是新的业务失败根因。

它必须记录：

```text
blocked_by = terminal upstream node ids
root_failures = structured root records with supporting evidence refs
```

最终 Task Result 聚合时：

- 首先报告 root terminal failures；
- blocked descendants 作为 propagation consequence；
- 不把 10 个 BLOCKED descendants 统计成 10 个独立 Agent failures。

原则：

> **A failed attempt may be remediable; a failed logical node blocks the DAG.**

#### Task-Level Fail-Closed Semantics

Node failure propagation 只能回答“哪些 DAG descendants 不能继续”，还不足以回答：

> **共享 Workspace 已被失败 attempt 修改后，整个 Task 是否还能继续调度其他 branch？**

P1 冻结为两种不同 scope：

```text
ordinary clean terminal node failure
→ block ordinary descendants
→ unrelated branch 可按 DAG 继续

workspace-compromising terminal failure
→ task-wide fail closed
→ no further ordinary DAG dispatch anywhere in this WorkspaceSession
```

其中 workspace-compromising terminal failure 至少包括：

- WRITE / UNKNOWN-mutating attempt terminal failure，且 `mutation_evidence == OBSERVED | UNKNOWN`，同时不存在合法 Retry / Repair transition；
- `REPOSITORY_MUTATION_AUTHORITY_VIOLATION`；
- Repository invariant broken，且 P1 不提供 deterministic rollback；
- dirty-state 下 `REPAIR_SCOPE_INVALIDATED` / post-WRITE `PLAN_INVALIDATED`；
- 任何要求 fail closed 且无法证明当前 shared Workspace 仍可作为后续 business execution 基线的状态。

注意：

```text
AcceptanceFailure + mutation
+ legal deterministic Repair
→ REMEDIATION_PENDING
→ 不是 task-wide terminal dirty failure
```

只有 remediation 不成立 / 已耗尽 / scope invalidated 后，才进入 terminal fail-closed。

特别地，`REPAIR_SCOPE_INVALIDATED(reason=ACTIVE_DOWNSTREAM_DISPATCH)` 即使尚未发生新的 dirty mutation，也必须先：

```text
close Task dispatch gate
→ cancel/join affected committed executions
→ wait for quiescence classification
→ then freeze/finalize Task
```

它复用 task-wide terminal drain path，但不能在仍有 active consumer 时提前把 Workspace 标成 `FROZEN`。

##### Task / Workspace / Repository / Patch 四轴状态

P1 禁止用单个枚举同时表达业务结果与 workspace condition。

定义：

```python
class TaskLogicalStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

class WorkspaceDisposition(str, Enum):
    # Backend quiescence is proven and the terminal workspace state is stable.
    # This says nothing about whether a legitimate/residual repository patch exists.
    STABLE = "stable"

    # Backend quiescence is proven, but bounded workspace observation cannot rule
    # out scanner-excluded/environment side effects.
    STABLE_WITH_UNCERTAINTY = "stable_with_uncertainty"

    # Backend may still be live / late-mutating.
    QUARANTINED = "quarantined"

class RepositoryDisposition(str, Enum):
    BASELINE_CLEAN = "baseline_clean"
    PATCH_PRESENT = "patch_present"
    INVARIANT_BROKEN = "invariant_broken"
    UNKNOWN = "unknown"

class PatchDisposition(str, Enum):
    NONE = "none"
    ACCEPTED = "accepted"
    RESIDUAL_UNACCEPTED = "residual_unaccepted"
    UNAVAILABLE = "unavailable"
```

这允许明确表示：

```text
FAILED
+ WorkspaceDisposition.STABLE
+ RepositoryDisposition.PATCH_PRESENT
+ PatchDisposition.RESIDUAL_UNACCEPTED
```

即：

> **任务失败，但 Workspace 中仍保留一份未被接受的 residual patch。**

也允许：

```text
FAILED
+ WorkspaceDisposition.STABLE_WITH_UNCERTAINTY
+ RepositoryDisposition.BASELINE_CLEAN
+ PatchDisposition.NONE
```

例如 bash 进入过 mutating/UNKNOWN execution path，Git-visible business patch 没有变化，但 scanner-excluded cache/environment side effect 无法完全排除。

以及：

```text
FAILED
+ WorkspaceDisposition.QUARANTINED
+ RepositoryDisposition.UNKNOWN
+ PatchDisposition.UNAVAILABLE
```

因此“dirty”不能被偷换成“Git patch 一定存在”。

Workspace disposition 的计算只描述 terminal stability：

```text
quiescence not proven
→ QUARANTINED

quiescence proven
AND final physical-mutation attribution complete enough for the relevant contract
→ STABLE

quiescence proven
BUT scanner-excluded / environment mutation cannot be ruled out
→ STABLE_WITH_UNCERTAINTY
```

Repository / Patch disposition 再独立回答：

> Git-visible business patch 是否存在、是否被接受。

因此一个正常成功的软件修改完全可以是：

```text
SUCCEEDED
+ WorkspaceDisposition.STABLE
+ RepositoryDisposition.PATCH_PRESENT
+ PatchDisposition.ACCEPTED
```

##### Atomic Task Fail-Closed Transition

当 workspace-compromising terminal failure 成立，且当前 execution quiescence 已证明：

```text
1. publish post-attempt WorkspaceRevision / NodeWorkspaceDelta / failure evidence
2. failing Node → FAILED
3. TaskLogicalStatus → FAILED
4. WorkspaceSessionStatus → FROZEN
5. close ordinary dispatch gate
6. every remaining PENDING / READY / REMEDIATION_PENDING ordinary Node
      → BLOCKED
      → block_reason = TASK_FAIL_CLOSED
      → blocked_by includes root terminal failure node
7. only then run Runtime-owned finalization
```

步骤 2–6 必须是一个 Scheduler logical state transaction。

不能：

```text
Writer dirty-fails
→ release lock
→ another unrelated READY Node dispatches
→ later Task marked FAILED
```

因为 shared Workspace 已不再是 validated execution baseline。

已 `SUCCEEDED` 的 Node 保留其历史 logical success / evidence；Task failure 不重写历史 attempt。它们的 accepted Handoff 也不得再用于新的 ordinary dispatch，因为 Task dispatch gate 已关闭。

如果 dirty-failure path 上 quiescence **无法证明**：

```text
TaskLogicalStatus → FAILED
WorkspaceSessionStatus → QUARANTINED
WorkspaceDisposition → QUARANTINED
final_repository_state / final_repository_changeset = None
ordinary dispatch = closed
```

这里仍保持四轴正交：若进入 QUARANTINED 的根因是 task-wide user cancellation，而不是 dirty business failure，则 TaskLogicalStatus 可以是 `CANCELLED`；WorkspaceDisposition 仍为 `QUARANTINED`。

并禁止 workspace-touching finalization。

##### Dirty Failure 后允许什么

P1 明确禁止在 task-wide fail closed 后继续执行：

- Reviewer Agent；
- Explorer / diagnostic Agent；
- Tester；
- 任意 Provider-backed Node；
- MCP / plugin / external tool；
- “只读 prompt 诊断”形式的新 LLM run。

即使某个 Agent 的业务 capability 是 READ_ONLY，也不重新打开 Agent execution surface。

允许的只有 **Runtime-owned deterministic finalization**，且仅当 Workspace 已 `FROZEN` 而非 `QUARANTINED`：

```text
final RepositoryStateDigest resolve/materialization
final RepositoryChangeSet / residual patch materialization
final ContractVerdict evaluation
final WorkspaceRevision reference
root failure aggregation
blocked-node aggregation
already-persisted evidence integrity resolution
TaskResult construction
```

这些 finalizer：

- 不经过 AgentProvider；
- 不调用 LLM；
- 不调用 MCP/plugin；
- 不扩大 business mutation authority；
- 不产生新的普通 NodeHandoff；
- 产物只进入 final TaskResult / EvidenceStore。

对 Git finalization，优先复用已经持久化的 canonical `working_tree_oid` / RepositoryStateDigest；不要为了“诊断”重新让 Agent 扫 Repository。

如果 finalizer 无法确定性 materialize residual patch：

```text
PatchDisposition.UNAVAILABLE
```

不能因为“看起来有改动”伪造 Patch。

##### Residual Patch 不是 Accepted Patch

Task 失败时，即使 final Git ChangeSet 可完整 materialize：

```text
PatchDisposition = RESIDUAL_UNACCEPTED
```

它只能用于：

- 用户检查；
- Debug / Trace；
- 后续显式 restart-from-baseline / manual recovery 的参考。

它不能：

- satisfy TaskContract；
- 作为 normal success artifact；
- 解锁 downstream；
- 被标记为 Reviewer approved；
- 被描述成“任务已完成”。

同样，Review `REQUEST_CHANGES`、post-WRITE plan invalidation、task-wide cancellation 等都可能产生：

```text
Task FAILED or CANCELLED
+ residual patch present
```

即使终态根因不是 `DIRTY_WRITE_FAILURE`。Final result 必须忠实表达当前 Repository 状态，而不是只看最后一个 failure class。

##### TaskResult

P1 增加 Runtime-owned terminal schema。Root failure 本身不是 `EvidenceRef`；它是 TaskResult 内的结构化归因记录，并可引用 supporting attempt evidence：

```python
class RootFailureRecord(BaseModel):
    failure_kind: str

    node_id: str | None = None
    execution_id: str | None = None
    attempt: int | None = None

    supporting_evidence_refs: tuple[EvidenceRef, ...] = ()
    diagnostics: tuple[str, ...] = ()

    fingerprint: str

class TaskResult(BaseModel):
    task_id: str

    status: TaskLogicalStatus

    workspace_disposition: WorkspaceDisposition
    repository_disposition: RepositoryDisposition
    patch_disposition: PatchDisposition

    final_workspace_revision: WorkspaceRevision | None

    # Canonical terminal-finalization artifacts. TaskEvidenceRef is defined
    # by specs/04-evidence-evaluation.md and never impersonates a Node attempt.
    final_repository_state: TaskEvidenceRef | None
    final_repository_changeset: TaskEvidenceRef | None
    final_contract_verdict: TaskEvidenceRef | None

    # When QUARANTINED prevents a final observation, retain only the last
    # already-persisted trusted attempt evidence, explicitly as historical.
    last_trusted_evidence_refs: tuple[EvidenceRef, ...] = ()

    # Root business/runtime failures only; BLOCKED consequences are separate.
    root_failures: tuple[RootFailureRecord, ...] = ()

    blocked_node_ids: tuple[str, ...] = ()
    cancelled_node_ids: tuple[str, ...] = ()

    warnings: tuple[str, ...] = ()

    fingerprint: str
```

约束：

```text
status == SUCCEEDED
→ root_failures empty
→ final_contract_verdict is not None
→ resolved ContractVerdict.all_required_satisfied == true
→ patch_disposition in {NONE, ACCEPTED}
→ workspace_disposition in {STABLE, STABLE_WITH_UNCERTAINTY}

status in {FAILED, CANCELLED}
AND repository_disposition == PATCH_PRESENT
→ patch_disposition == RESIDUAL_UNACCEPTED

patch_disposition == ACCEPTED
→ status == SUCCEEDED

workspace_disposition == QUARANTINED
AND no previously persisted trustworthy final repository artifact
→ repository_disposition == UNKNOWN
→ patch_disposition == UNAVAILABLE
```

`TaskResult` 不复制完整 patch bytes；`final_repository_changeset` 通过 task-scoped `TaskEvidenceRef` 指向 EvidenceStore artifact。

##### Terminal Finalization

稳定 terminal path：

```text
Task terminal decision
        ↓
close ordinary dispatch
        ↓
Workspace ACTIVE → FROZEN
        ↓
Runtime deterministic finalization
        ↓
TaskResult persisted
        ↓
Workspace CLOSED
```

quarantine path：

```text
quiescence proof lost
        ↓
Workspace QUARANTINED
        ↓
no workspace inspection
        ↓
aggregate only already-persisted trusted evidence
        ↓
TaskResult persisted
        ↓
backend-specific teardown / CLOSED when possible
```

核心原则：

> **Fail closed stops execution; it does not erase evidence. Residual state must be reported, not promoted to success.**

#### Immutable TaskNode + Mutable NodeRuntimeState

P1 冻结：

> **TaskNode / TaskDAG 是编译产物，执行期不原地改 objective / capability / provider / dependency。**

运行状态单独保存：

```python
class NodeAttemptKind(str, Enum):
    INITIAL = "initial"
    RETRY = "retry"
    REPAIR = "repair"
    REVERIFY = "reverify"

class NodeAttemptStatus(str, Enum):
    RUNNING = "running"
    ACCEPTED = "accepted"
    FAILED = "failed"
    CANCELLED = "cancelled"

class NodeAttemptRecord(BaseModel):
    node_id: str
    attempt: int
    kind: NodeAttemptKind

    execution_id: str

    pre_workspace_revision: WorkspaceRevision
    post_workspace_revision: WorkspaceRevision | None

    status: NodeAttemptStatus

    # Stable machine-readable code from §9.8 Failure Taxonomy / compiler failure
    # vocabulary. Kept extensible across backend compatibility versions.
    failure_kind: str | None

    evidence_refs: tuple[EvidenceRef, ...] = ()

    # Bounded terminal handoff for a logically accepted attempt.
    handoff: NodeHandoff | None = None

class NodeBlockReason(str, Enum):
    UPSTREAM_FAILURE = "upstream_failure"
    TASK_FAIL_CLOSED = "task_fail_closed"

class NodeLogicalStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"

    # Previous attempt did not establish terminal success/failure because
    # a bounded retry / repair / reverify transition is active.
    REMEDIATION_PENDING = "remediation_pending"

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

class NodeRuntimeState(BaseModel):
    node_id: str
    logical_status: NodeLogicalStatus

    next_attempt: int
    repair_count: int

    # Monotonic dependency-authority generation.
    # Increment whenever accepted downstream authority is published or revoked.
    acceptance_epoch: int = 0

    # Only the currently accepted logical-success attempt may own a normal
    # downstream handoff.
    accepted_attempt: int | None = None
    accepted_handoff: NodeHandoff | None = None

    # At most one pre-commit dispatch ticket may claim this Node.
    active_dispatch_ticket_id: str | None = None

    terminal_failure_kind: str | None = None

    block_reason: NodeBlockReason | None = None
    blocked_by: tuple[str, ...] = ()

    attempts: tuple[NodeAttemptRecord, ...]
```

Current-authority invariant：

```text
accepted_attempt is None
↔ accepted_handoff is None

accepted_attempt == N
→ attempts contains attempt N
→ attempt N.handoff exists
→ accepted_handoff.fingerprint == attempt N.handoff.fingerprint
→ accepted_handoff.source_attempt == N
```

历史 Handoff 保留在对应 `NodeAttemptRecord.handoff`；Writer reopen 只清除 current `accepted_*` authority，不删除历史 attempt artifact。

Attempt status 语义：

```text
dispatch commit
→ RUNNING

logical acceptance gate passes
→ ACCEPTED

attempt ends without acceptance
→ FAILED

task/user cancellation owns terminalization
→ CANCELLED
```

是否还有 Retry / Repair / Reverify 由 `NodeRuntimeState.logical_status` 决定；所以 `attempt.status == FAILED` 不推出 `Node.logical_status == FAILED`。

因此：

```text
same TaskNode
→ attempt 1 INITIAL
→ attempt 2 RETRY or REPAIR
```

而不是生成：

```text
implement
implement_repair_1
implement_repair_2
```

这种动态 DAG 节点。

#### Retry Semantics

P1 不定义 per-node retry-policy schema。Retry eligibility 与 budget 属于 Scheduler-owned Runtime config，TaskNode 不携带可由 Planner 改写的 retry authority。

Retry：

- objective 不变；
- ProviderAssignment 不变；
- compiled NodeExecutionPolicy 不变；
- live `prepare_node()` 仍重新做 backend revalidation；
- 只允许上一 attempt 属于 Scheduler-owned retry rules 允许的 transient/capped-clean class，且 `mutation_evidence == PROVEN_NONE`；
- 新 execution_id；
- 新 attempt number；
- 所有 evidence 重新生成，绝不沿用前一 attempt acceptance / receipt verdict。

#### Repair Semantics

Repair 是**同一 Write TaskNode 的新 attempt**，但输入额外携带 typed `RepairFeedback`。

保持不变：

```text
TaskNode.id
objective
required_capabilities
provider_id
compiled NodeExecutionPolicy authority ceiling
dependencies
```

允许变化：

```text
attempt execution_id
live narrowed effective policy
current WorkspaceRevision
RepairFeedback
dependency evidence staleness projection
```

Repair 不允许：

- 换 Provider；
- 增加 Capability；
- 扩大 Tool authority；
- 改写原 objective；
- 创建任意新 dependency；
- 回滚到 pre-attempt state。

Repair 还必须在 WRITE lock 内完成 Feedback freshness check；`RepairFeedback` 与普通 `NodeHandoff` 一样属于 revision-scoped state-dependent evidence，而不是永不过期的命令。

如果修复确实需要这些变化，P1 视为：

```text
PLAN_INVALIDATED / requires explicit replan
```

而 WRITE 之后 arbitrary replan 已关闭，因此默认 fail / restart-from-baseline。

#### Downstream Verification → Repair Attribution

P1 对 downstream verification failure 使用独立的：

```text
RepairAttributionResolver
```

而不是让 Scheduler 根据 Tester prose 直接生成 `RepairFeedback`。

先定义结构化 verification evidence：

```python
class VerificationCheckStatus(str, Enum):
    HOLDS = "holds"
    FAILED = "failed"
    UNVERIFIED = "unverified"

class VerificationCheckResult(BaseModel):
    check_id: str
    status: VerificationCheckStatus

    deterministic: bool

    # Runtime-owned evidence only.
    evidence_refs: tuple[EvidenceRef, ...] = ()

class VerificationResult(BaseModel):
    verification_node_id: str
    verification_execution_id: str
    verification_attempt: int

    observed_workspace_revision: WorkspaceRevision
    observed_repository_state_fingerprint: str

    checks: tuple[VerificationCheckResult, ...]

    # Must remain true for independent verifier semantics.
    repository_state_unchanged: bool

    fingerprint: str
```

`FAILED` 必须来自 Runtime 的 canonical deterministic checker；自由文本：

```text
"tests seem broken"
"probably caused by auth.py"
```

不能生成 authoritative failed check。

Repair attribution 的输出同样持久化：

```python
class RepairAttributionKind(str, Enum):
    UNIQUE_WRITER = "unique_writer"
    NO_OWNER = "no_owner"
    MULTI_WRITER = "multi_writer"
    SOURCE_INELIGIBLE = "source_ineligible"
    SCOPE_INVALIDATED = "scope_invalidated"

class RepairAttributionEvidence(BaseModel):
    source_verification_node_id: str
    source_verification_execution_id: str
    source_verification_attempt: int

    failed_check_ids: tuple[str, ...]
    candidate_write_node_ids: tuple[str, ...]

    target_write_node_id: str | None = None
    target_write_attempt: int | None = None

    observed_workspace_revision: WorkspaceRevision

    kind: RepairAttributionKind
    reason_codes: tuple[str, ...]

    task_dag_fingerprint: str
    fingerprint: str
```

该对象写入 `ExecutionEvidenceStore`，EvidenceRef.kind = `repair_attribution`。

##### Deterministic Resolver

P1 直接按下面顺序实现：

```python
def resolve_verification_repair_attribution(
    verification_node: TaskNode,
    source_attempt: NodeAttemptRecord,
    verification_result: VerificationResult,
    bindings: tuple[VerificationRepairBinding, ...],
    dag: TaskDAG,
    node_states: Mapping[str, NodeRuntimeState],
    evidence_store: ExecutionEvidenceStore,
) -> RepairAttributionEvidence:
    ...
```

###### Gate 1：source 必须是真正的 deterministic Verification failure

全部满足：

```text
verification_node.work_kind == VERIFICATION
verification_result belongs to source execution/attempt
verification_result evidence integrity valid
verification_result.repository_state_unchanged == true
at least one check.status == FAILED
every failed check is deterministic
no UNVERIFIED check is promoted to FAILED
source failure is verification failure, not backend/tool/policy execution failure
```

否则：

```text
SOURCE_INELIGIBLE
→ no automatic RepairFeedback
```

特别地：

- verifier backend crash；
- test command 根本没运行；
- acceptance evidence 缺失；
- verifier 修改 Git-visible Repository；
- 只有 Tester prose 声称失败；

都不能进入 writer attribution。

###### Gate 2：每个 failed check 必须解析 compiler-owned binding

对每个 `failed_check_id`：

```text
lookup VerificationRepairBinding
verify dag_structure_fingerprint
verify verification_node_id
```

任一 binding 缺失 / fingerprint 不一致：

```text
SOURCE_INELIGIBLE
```

禁止 fallback 到：

```text
nearest writer
last writer
path overlap
model guess
```

###### Gate 3：按 logical Node 求 candidate union

```python
candidate_sets = [
    set(binding.candidate_write_node_ids)
    for binding in failed_bindings
]
all_candidates = union(candidate_sets)
```

但“union 恰好一个”还不够。

P1 要求：

```text
EVERY failed check candidate set == {same single writer W}
```

也就是：

```python
if any(len(s) == 0 for s in candidate_sets):
    return NO_OWNER

if any(len(s) != 1 for s in candidate_sets):
    return MULTI_WRITER

owners = {only(s) for s in candidate_sets}

if len(owners) != 1:
    return MULTI_WRITER
```

这样可以阻止：

```text
check A → Writer 1
check B → Writer 2
```

被错误压成“挑一个最可能的 Writer”。

###### Gate 4：target 必须仍是当前 accepted logical Writer

设唯一 logical owner 为 `W`。

必须满足：

```text
TaskNode(W).work_kind == IMPLEMENTATION
W semantic authority includes REPOSITORY_MUTATION

NodeRuntimeState(W).logical_status == SUCCEEDED
accepted_attempt is not None
accepted_handoff is not None
accepted_handoff belongs to accepted_attempt
accepted attempt temporally precedes source verification attempt
```

注意：

> downstream verification repair target 是 logical Writer 的 **current accepted_attempt**，不是“最近执行过的 attempt”。

因此：

```text
attempt 1 transient clean fail
attempt 2 success
verification fail
→ target = attempt 2
```

旧 attempt 只留 Trace。

如果 writer 已经：

```text
REMEDIATION_PENDING
FAILED
BLOCKED
CANCELLED
```

则当前 attribution 不能再次创建新的 repair ownership。

###### Gate 5：排除 intervening distinct business Writer

即使 compiler binding 是 singleton，Runtime 仍做 defense-in-depth：

在 target accepted attempt 完成之后，到 verification 所观察 revision 之间，若存在**另一个 logical Node**：

```text
semantic authority = REPOSITORY_MUTATION
AND Git-visible RepositoryStateDigest actually changed
```

则：

```text
SCOPE_INVALIDATED
→ no automatic repair
```

这防止 DAG / phase normalization bug、异常 dispatch 或未来 topology 扩展后出现：

```text
Writer A accepted
Writer B later mutates repo
Verifier fails
→ still blame A
```

同一 logical Writer 的 REPAIR attempt 不按“distinct writer”计算；它由 `accepted_attempt` ownership 管理。

实现不维护第二套 repository-write ledger。Resolver 通过 `node_states[*].attempts` 的 pre/post WorkspaceRevision，并用 `evidence_store` resolve per-attempt RepositoryStateDigest / repository delta，查询 target accepted attempt 之后、verification observed revision 之前是否存在 distinct business Writer 的 Git-visible mutation。

###### Gate 6：成功 attribution 只代表 repair ownership

全部通过：

```text
kind = UNIQUE_WRITER
target_write_node_id = W
target_write_attempt = W.accepted_attempt
```

它只证明：

> 在 P1 当前 DAG / authority / accepted-attempt model 下，这组失败 verification obligations 只有一个合法 remediation owner。

它**不证明**：

> Writer W 在因果意义上制造了这个失败。

例如 baseline 本来就存在 bug 时：

```text
test failed before patch
```

不自动否定 Writer 的 repair ownership；如果任务 contract 要求该 Writer 修复它，那么 failure 仍表示该 obligation 尚未满足。

因此 P1 不把 baseline pass/fail comparison 用作 writer blame classifier。

##### Atomic Reopen Boundary

`UNIQUE_WRITER` 只代表 attribution 成功，不代表 Writer 一定可以立即 reopen。

实际 reopen 必须进入前文 **Writer Reopen vs Downstream Dispatch Race** gate，并与 consumer 的 final dispatch commit 在同一个 `SchedulerStateMutex` 上线性化：

```text
RepairAttributionEvidence
        ↓
SchedulerStateMutex
        ↓
inspect affected descendants / dispatch tickets
        ↓
┌──────────────────────────────────────────────┐
│ any affected COMMITTED/RUNNING or committed │
│ ordinary downstream success?                │
└───────────────┬──────────────────────────────┘
            yes │                      no
                ▼                       ▼
REPAIR_SCOPE_INVALIDATED      revoke pre-commit tickets
close task dispatch gate      revoke Writer authority
cancel/join active runs       acceptance_epoch += 1
Task FAILED                   Writer → REMEDIATION_PENDING
```

因此禁止两类窗口：

```text
create RepairFeedback
→ recompute READY
→ later revoke Writer
```

以及：

```text
consumer post-lock validation succeeds
→ Writer reopens
→ consumer enters backend
```

最终 authority boundary 是：

> **Writer reopen and downstream dispatch commit are mutually exclusive Scheduler state transactions.**

真正 REPAIR dispatch 时，仍然执行已经冻结的：

```text
RepairFeedback.observed_workspace_revision
vs
current revision under WRITE lock
```

freshness gate。

职责最终分离为：

```text
VerificationRepairBinding
→ compile-time ownership scope

RepairAttributionResolver
→ unique logical repair owner

Scheduler reopen race gate
→ whether old downstream consumption has crossed commit boundary

RepairFeedback freshness check
→ whether failure evidence still applies to current workspace state
```

##### Explicit Non-Attribution Rules

P1 明确禁止：

```text
"Tester failed after Coder"
→ therefore Coder is at fault

"stack trace points to file changed by Writer A"
→ therefore Writer A is unique owner

"Writer B ran last"
→ therefore repair Writer B

"Tester says Writer A caused it"
→ therefore repair Writer A
```

这些最多是 diagnostic hints。

#### Repair Trigger

P1 只允许：

```text
A. mutated WRITE Node own AcceptanceFailure
B. downstream deterministic VERIFICATION failure
   且可以唯一绑定到 single target WRITE Node
```

不允许：

- 纯 model reviewer opinion 自动触发 patch repair；
- 多 writer 情况下猜测“哪个 writer 导致测试失败”；
- UNVERIFIED 当作 deterministic failure 自动修代码。
- 已有普通 downstream logical success 消费旧 Writer Handoff 后再静默 reopen Writer；
- later business WRITE 已让 single-writer ownership 失效时继续自动 Repair。

`RepairFeedback` 增加 trigger ownership：

```python
class RepairTriggerKind(str, Enum):
    NODE_ACCEPTANCE = "node_acceptance"
    DOWNSTREAM_VERIFICATION = "downstream_verification"

class RepairFeedback(BaseModel):
    trigger_kind: RepairTriggerKind

    feedback_source_node_id: str
    feedback_source_execution_id: str
    feedback_source_attempt: int

    target_write_node_id: str
    target_write_attempt: int

    # Revision whose state the deterministic failure evidence actually observed.
    observed_workspace_revision: WorkspaceRevision

    # Authoritative check identities, not free-text blame statements.
    failed_check_ids: tuple[str, ...]

    verification_result: EvidenceRef | None
    acceptance_verdict: EvidenceRef | None

    # Required for DOWNSTREAM_VERIFICATION trigger.
    repair_attribution: EvidenceRef | None

    receipt_refs: tuple[ReceiptRef, ...]

    # Runtime-rendered bounded summaries only; not attribution authority.
    deterministic_failure_summaries: tuple[str, ...] = ()

    # Untrusted explanatory prose only.
    verifier_report: str | None

    fingerprint: str
```

#### Repair Loop

典型闭环：

```text
Implement attempt 1
      ↓
post revision R1
      ↓
Verify attempt 1
      ↓
deterministic failure @ R1/R2
      ↓
RepairFeedback
      ↓
Implement attempt 2 (REPAIR)
on CURRENT workspace revision
      ↓
post revision R3
      ↓
Verify attempt 2 (REVERIFY)
      ↓
fresh verdict only
```

若 Verification 自身因 physical WRITE class 产生非业务生成文件并推进 revision，Repair 仍从**当前 revision**开始；不会假装回到 Implement attempt 1 的 post revision。

#### Reverify Semantics

Repair 成功后：

- downstream VERIFICATION Node 使用同一个 immutable TaskNode；
- 新 attempt kind = `REVERIFY`；
- 原 verification attempt evidence 保留在 Trace；
- 旧 verification verdict 不进入新 success Handoff；
- Reviewer 若依赖 verification，只能消费最新 accepted verification attempt。

MVP：

```text
max_repairs_per_write = 1
```

优先只支持：

> **single-writer → deterministic failure → repair → reverify**

多 Writer repair、任意 rollback、Reviewer-only feedback 自动修复暂不做。

### 9.11 Execution-Time Replan Boundary

只有：

```text
PLAN_INVALIDATED
AND invalidating Node is READ
AND no WRITE has executed
AND replan budget remains
```

才能 replan。

一旦发生 WRITE，任意 replan 一期关闭。

### 9.12 Runtime Assembly Attestation

Compile-time Provider feasibility 基于：

```text
ProviderContract
+
BackendInventorySnapshot
+
Operator SubagentConfig
```

它只能达到：

```text
PREFLIGHT_FEASIBLE
```

DeerFlow 真正组装 Subagent 时还会执行：

- `SubagentConfig.tools` allowlist；
- `disallowed_tools` denylist；
- runtime authorization filter；
- Skill authorization；
- MCP / deferred tool assembly；
- middleware-declared tools；
- model resolution；
- Sandbox policy。

因此真实 assembly 可能与 preflight 不同。

#### Descriptor 不是默认白送

Pinned DeerFlow 中：

```text
SubagentExecutor.assembly_descriptor
```

默认是 `None`。

只有当前 extension snapshot 中存在：

```text
AgentAssemblyObserver
```

时，`_describe_assembly()` 才会真正构建 descriptor。

这是有意的性能优化，因为 descriptor 需要 hash：

- tool descriptions；
- tool JSON schemas；
- middleware policy；
- prompt；
- skills；
- model policies。

因此 A-SWE 不能假设 descriptor 永远存在。

#### A-SWE Attestation Extension

好消息是 `AgentAssemblyObserver` 属于公开：

```text
deerflow_extension_api.ExtensionRegistry
```

contract。

P1 增加一个极薄的 DeerFlow extension：

```python
@extension(api="0.2.0", name="a_swe_attestation")
def install(registry, config):
    registry.agent_assembly_observer(ASWEAssemblyObserver())
```

Observer 本身只做轻量记录即可。

它的关键作用之一是让 DeerFlow 构建：

```text
AgentAssemblyDescriptor
```

随后 A-SWE Adapter 从**当前 SubagentExecutor 实例**读取：

```text
executor.assembly_descriptor
```

避免自行重建 assembly 描述。

禁止：

- subclass SubagentExecutor 只为取 assembly；
- 直接调用 private `_describe_assembly()`；
- 根据 prompt / config 猜 actual tools。

#### AssemblyAttestation

建议映射：

```python
class AssemblyAttestation(BaseModel):
    provider_id: str
    node_id: str

    effective_model: str
    actual_tool_names: frozenset[str]
    candidate_skill_names: frozenset[str]

    middleware_names: tuple[str, ...]
    deferred_tool_names: frozenset[str]

    backend_fingerprint: str

    matches_node_policy: bool
    diagnostics: list[str]
```

DeerFlow `build_assembly_descriptor()` 会将：

```text
explicit bound tools
+
middleware.tools
```

合并后写入 descriptor，因此 descriptor.tools 可以覆盖最终 build-time declared tool set，而不是只看 `SubagentConfig.tools`。

至少检查：

```text
required_tools ⊆ actual tool descriptors
```

以及：

```text
actual business tools
⊆ NodeExecutionPolicy.allowed_business_tools

actual infrastructure tools
⊆ NodeExecutionPolicy.infrastructure_tool_names
```

同时可以检查：

- expected Contract Guard middleware / policy 是否存在；
- resolved model 是否符合 Node model policy；
- expected runtime ceilings 是否进入 effective policies。

Skill 只做 availability evidence：

```text
preferred_skills ⊆ enabled_skills
→ informational / warning
```

不能把它当成 Skill was used 的证明。

若 required tool 缺失：

```text
PROVIDER_ASSEMBLY_MISMATCH
```

Node 不得因为模型自报 completed 而被 A-SWE 接受。

#### Attestation 不是 Security Gate

DeerFlow 的 `AgentAssemblyObserver` 是 fail-open notification hook。

同时 descriptor 是 Agent assembly 结束时产生，不能把它当成真正的 pre-execution authorization barrier。

因此：

```text
Security / authority
→ operator config narrowing
→ runtime authorization
→ ContractGuardrailProvider
→ sandbox policy

AssemblyAttestation
→ runtime evidence
→ compatibility / validity gate
```

即：

> **Attestation 是 post-build / reproducibility evidence；真正阻止无效 Node 进入第一轮 LLM 的是 ASWENodeToolPolicyMiddleware 的 model-call admission gate。**

因此职责冻结为：

```text
BackendInventory
→ planning-time preflight

NodeToolPolicy first-model gate
→ runtime execution admission

DeerFlow AssemblyDescriptor
→ post-build attestation / reproducibility

ContractGuardrail
→ argument-sensitive action enforcement
```

不要让 AssemblyDescriptor 承担它当前 API 无法承担的 pre-execution control responsibility。

### 9.13 Node-Scoped Least Privilege

ExecutionPlanValidator 为每个 Node 编译独立 policy：

```python
class NodeExecutionPolicy(BaseModel):
    provider_id: str
    required_capabilities: tuple[str, ...]

    required_tools: tuple[str, ...]
    selected_optional_tools: tuple[str, ...]

    allowed_business_tools: tuple[str, ...]
    infrastructure_tool_names: tuple[str, ...]
    required_infrastructure_tools: tuple[str, ...]
    denied_tools: tuple[str, ...]

    preferred_skills: tuple[str, ...]

    tool_effects: dict[str, ToolEffect]
    workspace_access: WorkspaceAccess

    model_policy: str

    contract_guard_rules: tuple[str, ...]
    post_node_invariants: tuple[str, ...]

    verification_commands: tuple[VerificationCommand, ...]
    bash_policy: BashCommandPolicy

    # True only when every load-bearing Node acceptance obligation has a
    # deterministic P1 checker.
    deterministic_acceptance_complete: bool

    timeout_seconds: int
    max_turns: int

    provider_contract_fingerprint: str
    planning_inventory_fingerprint: str
    task_contract_fingerprint: str

    fingerprint: str
```

`allowed_business_tools` 是该 Node 的**最大业务执行工具集**，不是“建议工具”。

```text
allowed_business_tools
=
required_tools
+
selected_optional_tools
```

Framework-generated helper 单独放入：

```text
infrastructure_tool_names
```

避免把业务权限和 Harness 自身 discovery machinery 混在一起。

例如 Recon Probe：

```text
allowed:
ls
glob
grep
read_file

denied:
bash
write_file
str_replace
task
```

#### Adapter 必须 Monotonic Narrowing

不能：

```text
Node allowed_tools
→ 直接覆盖 operator SubagentConfig.tools
```

必须：

```text
Operator allow
∩ Node allow

Operator deny
∪ Node deny
```

然后 Runtime authorization 还可以继续收窄。

因此：

> **NodeExecutionPolicy 永远不能扩大 DeerFlow Operator 已经设置的权限。**

#### Final Tool Visibility Backstop

Pinned DeerFlow 中 `SubagentConfig.tools` 只过滤 explicit / regular tools。

随后仍可能加入：

- generated `tool_search`；
- generated `describe_skill`；
- middleware-declared tools，例如 model-dependent / extension tool。

DeerFlow 自身的 `tool_declarations.py` 也明确说明：

> LangChain 会在 host explicit tool list 过滤之后，再把 `middleware.tools` 折入最终 ToolNode。

因此：

```text
SubagentConfig.tools
≠ complete final model-visible schema allowlist
```

P1 若要真正实现 Node-scoped least privilege，需要第二道 name-level policy。

##### 不能使用 packaged Extension Middleware 做 enforcement

公开 `deerflow_extension_api` 的 middleware contribution 在 pinned baseline 是 observational contract：

- host 强制向下游传 original request；
- 不能 veto tool call；
- 不能改写 model-visible tools；
- contributor failure fail-open。

因此它适合：

```text
Assembly Observer
Trace / Metrics
```

不适合：

```text
Node security enforcement
```

##### Trusted Configured Middleware

DeerFlow 另外提供 operator-owned：

```text
extensions.middlewares
```

这是 trusted `AgentMiddleware` customization：

- 直接实例化真实 AgentMiddleware；
- 同时进入 lead / subagent chain；
- 不经过 observational isolation wrapper；
- 可以修改 ModelRequest；
- 可以 veto ToolCall；
- 配置加载失败会让 agent build fail loudly。

A-SWE P1 可以增加：

```text
ASWENodeToolPolicyMiddleware
```

作为 trusted configured middleware。

##### NodeExecutionBindingStore

`SubagentExecutor` 没有任意 extra A-SWE runtime context 参数。

因此 P1 不滥用：

```text
authz_attributes
knowledge_scope
```

承载 A-SWE 业务 policy / handoff。

Adapter 使用进程内、短生命周期：

```python
@dataclass(frozen=True)
class NodeExecutionBinding:
    run_id: str
    execution_id: str

    policy: NodeExecutionPolicy
    invocation: NodeExecutionInvocation

class ToolCallAdmissionRecord(BaseModel):
    tool_call_id: str
    tool_name: str
    effect: ToolEffect

class NodeExecutionRuntimeOutcome:
    admission_checked: bool
    admission_failure: str | None
    missing_required_tools: tuple[str, ...]
    denied_tool_calls: list[dict]

    # Recorded before downstream handler invocation.
    admitted_tool_calls: list[ToolCallAdmissionRecord]
    admitted_tool_calls_truncated: bool

NodeExecutionBindingStore[run_id]
    = (NodeExecutionBinding, NodeExecutionRuntimeOutcome)
```

 文件安全约束；
- task/node id 可能包含 `:`、`/`、空格或其他 backend 非法字符；
- correlation 语义已经存在于 `NodeExecutionBinding` / Trace metadata，无需重复塞进 run_id；
- opaque run_id 更短，也避免把业务标识泄漏给不需要它的 DeerFlow storage path。

因此：

```text
run_id
→ execution-scoped opaque DeerFlow correlation key

task_id / node_id / attempt
→ NodeExecutionBinding + RuntimeEvent metadata
```

格式必须满足 DeerFlow 当前最严格已知 backend 的 safe-id 子集：

```regex
^[A-Za-z0-9_-]+$
```

P1 建议固定：

```text
aswe- + uuid4().hex
```

prefix 仍只用于 diagnostics；exact BindingStore membership 才是 authority。

并同时：

1. 写入 `NodeExecutionBindingStore[run_id]`；
2. 传给 `SubagentExecutor.run_id`。

Pinned SubagentExecutor 会把它写入：

```text
runtime.context["run_id"]
```

因此：

```text
ASWENodeToolPolicyMiddleware
ASWEHandoffContextMiddleware
```

都通过同一个 exact run_id lookup 获取当前 execution binding。

#### 为什么 Handoff 在进入 Store 前就 Render

Handoff evidence resolve / revision classification 发生在 Workspace lock granted 后。

如果让 DeerFlow middleware 每次 model call 自己：

```text
read EvidenceStore
recompute staleness
render dependency context
```

会引入：

- isolated-loop 文件 I/O；
- 每轮重复工作；
- middleware 内新的 TOCTOU；
- EvidenceStore / Core object 泄漏进 DeerFlow middleware。

因此：

```text
Workspace lock granted
      ↓
freeze execution_workspace_revision
      ↓
resolve EvidenceRefs
      ↓
deterministic HandoffRenderer
      ↓
bounded + neutralized dependency_context_text
      ↓
create immutable NodeExecutionInvocation
      ↓
register NodeExecutionBinding
      ↓
SubagentExecutor
```

`ASWEHandoffContextMiddleware` 每次 model call 只做：

```text
lookup exact run_id
→ read immutable dependency_context_text
→ inject request-scoped messages
```

不做磁盘 / EvidenceStore / Git I/O。

#### Store Lifecycle

```text
prepare backend resources
      ↓
acquire workspace access
      ↓
build immutable NodeExecutionInvocation
      ↓
register NodeExecutionBinding
      ↓
execute node
      ↓
Adapter reads terminal runtime outcome
      ↓
finally remove binding
      ↓
release workspace access
```

要求：

- exact `run_id` 作为唯一 key，不使用可碰撞的 node_id；
- immutable policy + immutable invocation；
- mutable outcome 独立并由 concurrency-safe holder 管理；
- Store 必须 cross-thread / cross-event-loop safe；
- P1 使用 `threading.Lock / RLock` 或等价同步 primitive 保护短临界区，**不能使用绑定单一 event loop 的 asyncio.Lock 作为共享 Store 锁**；
- middleware lookup 只做 O(1) 内存读取，锁内禁止文件 I/O / Git / await；
- outcome append/update 在相同同步边界内完成，Adapter 终态读取拿 snapshot copy；
- bounded / cleanup-safe；
- cancellation / timeout / exception 都必须 finally cleanup；
- ordinary DeerFlow run 没有 matching A-SWE binding → pass-through；
- `aswe-` run_id 但 exact binding 丢失 → fail closed；
- prefix 只用于 managed-run diagnostics，不是 authority；authority 来自 exact in-process binding；
- execution binding 不跨 process。

这个设计只承诺：

> **single-process P1 runtime。**

分布式 Worker 后续必须把 BindingStore 换成显式 durable / remote execution-context carrier。

Pinned DeerFlow 的 native subagent 可能运行在独立 persistent event-loop thread；BindingStore 的 producer（A-SWE Scheduler/Adapter）与 consumer（configured middleware）因此不保证同线程。这个 cross-loop boundary 是实现约束，不只是测试细节。

##### Middleware Enforcement

Pinned middleware order 采用：

> **first in list = outermost**

而 DeerFlow 在 Subagent chain 中先加入：

```text
SkillToolPolicyMiddleware
DeferredToolFilterMiddleware
...
configured extensions.middlewares
```

因此 `ASWENodeToolPolicyMiddleware` 作为 configured middleware 位于这些 schema filter 的内侧。

它在每一次 model call 看到的 `request.tools` 已经经过：

- active-skill tool policy；
- deferred MCP schema hiding；
- 前序 authorization / assembly filtering；
- middleware-declared tool folding。

随后 A-SWE 再执行自己的 final Node policy。

在 model-call boundary：

```text
current request.tools
        │
        ├─ verify eager required tools present
        │
        └─ intersect:
           Node allowed business tools
           +
           allowed framework infrastructure tools
        ↓
final model-visible tool schemas
```

###### First-Model Admission Gate

第一次 model call 前：

```text
required eager tools
      ⊆
current request.tools
```

必须成立。

否则：

```text
PROVIDER_ASSEMBLY_MISMATCH
```

并且不能让模型“先试试看”。

实现上不发明第二套 Agent termination protocol，但也**不抛普通 Exception / model request AdmissionError**。

Pinned DeerFlow 的 `LLMErrorHandlingMiddleware` 会捕获内层普通 `Exception`，进入自己的 LLM/provider retry-classification 与 fallback 路径。若 A-SWE 在这里直接 raise：

```text
Provider policy mismatch
→ 被包装成 LLM failure
```

Failure taxonomy 会失真。

因此 trusted Node middleware 在 required-tool closure 失效时采用：

```text
ASWENodeToolPolicyMiddleware
      ↓
DO NOT call downstream model handler
      ↓
return non-empty synthetic AIMessage / ModelResponse
      ↓
additional_kwargs:
  deerflow_error_fallback = true
  aswe_policy_failure = true
  aswe_failure_code = PROVIDER_ASSEMBLY_MISMATCH
  aswe_node_execution_id = <id>
```

设计理由：

1. synthetic response 不调用 `handler(request)`，因此 upstream LLM provider 零调用；
2. response content 必须非空，避免触发 DeerFlow empty-response retry；
3. DeerFlow `SubagentExecutor._extract_llm_error_fallback()` 已经把 terminal `deerflow_error_fallback=true` AIMessage 映射为 `SubagentStatus.FAILED`；
4. A-SWE 自有 marker 只用于精确 FailureTaxonomy，不修改 DeerFlow terminal contract；
5. 普通 DeerFlow LLM fallback 没有 `aswe_policy_failure`，Adapter 不会误分类。

Adapter 在 Result Mapping 时：

```text
SubagentResult.status == FAILED
AND terminal AIMessage.aswe_policy_failure == true
→ map as A-SWE policy / assembly failure

otherwise
→ preserve ordinary DeerFlow LLM / execution failure
```

如果未来 DeerFlow 提供正式公开的 typed node-admission failure contract，再评估替换；P1 不依赖不存在的 admission seam。
###### Revalidation on Every Model Turn

required tool availability 不只首轮检查。

Skill activation / authorization state可能在后续模型轮次继续收窄 Tool view。

所以每次 model call 都重新验证：

```text
(required eager business tools ∪ required infrastructure tools) ⊆ current request.tools
```

若中途不再成立：

```text
fail before next provider call
```

避免 Agent 在失去必要执行能力后继续消耗模型 token 并产生虚假完成报告。

在 tool-call boundary：

```text
tool call name
      ↓
Node policy check
      ↓
ALLOW / DENY
```

因此形成：

```text
Static pruning:
SubagentConfig.tools

Dynamic final visibility:
ASWENodeToolPolicyMiddleware

Identity authorization:
DeerFlow AuthorizationProvider

Argument-sensitive contract:
ContractGuardrailProvider
```

四层职责不同，禁止合并成一个大 Policy 类。

##### Framework Infrastructure Tools

至少区分：

```text
business tools
vs
framework infrastructure tools
```

例如 DeerFlow 生成的：

```text
tool_search
describe_skill
```

不应因为它们不是 CapabilityBinding.required_tools 就被误判成业务越权。

但 infrastructure allowlist 只能由 DeerFlow Adapter 根据当前 assembly mode 生成，不能由 LLM / Provider 自报。

`tool_search` 本身的 deferred catalog 已基于 SubagentConfig + authorization 后的候选集构建，因此允许该 helper 不等价于允许它重新引入已被 Node static pruning 移除的 ordinary tools。

#### Skill Narrowing

Node 可以只开放：

```text
preferred_skills
```

作为 `SubagentConfig.skills` discoverability scope。

如果 operator config 也有 Skill allowlist：

```text
Operator skill allow
∩ Node skill allow
```

但 Skill 缺失在 P1 默认不导致 Provider hard failure。

#### Runtime Ceiling Narrowing

```text
effective max_turns
= min(operator max_turns, node max_turns)

effective timeout
= min(operator timeout, node timeout)
```

A-SWE 不能提高 operator ceiling。

#### WorkspaceAccess

对于使用 `bash` 的 Node：

```text
workspace_access = WRITE
```

除非未来 Backend 明确提供可证明 read-only 的 shell contract。

Tester 因此默认不会和普通 READ Explorer 并行共享可变 Workspace。

---

### 9.14 Compiled Plan Descriptor / Fingerprint

最终 Executable TaskDAG 需要稳定 identity。

```python
class CompiledPlanDescriptor(BaseModel):
    repository_base_sha: str

    task_contract_fingerprint: str
    validated_plan_fingerprint: str

    capability_registry_fingerprint: str
    provider_registry_fingerprint: str
    node_policy_set_fingerprint: str

    task_dag_fingerprint: str

    # PlanRepair / PlanWarning are authoritative in specs/01-task-planning.md.
    repairs: tuple[PlanRepair, ...]
    warnings: tuple[PlanWarning, ...]

    fingerprint: str
```

所有：

- runtime-injected verification / review node；
- workspace ordering edge；
- acceptance canonicalization；
- access upgrade；
- normalization；

都必须进入 repair / normalization log。

Trace 最终关联：

```text
A-SWE Plan Fingerprint
        │
        ├── Node A → DeerFlow Assembly Fingerprint
        ├── Node B → DeerFlow Assembly Fingerprint
        └── Node C → DeerFlow Assembly Fingerprint
```

形成端到端 reproducibility evidence。

### 9.15 Node 执行流程

```text
NodeReady
   │
   ▼
Create revocable NodeDispatchTicket
(capture task dispatch epoch + dependency acceptance stamps)
   │
   ▼
Resolve Dependency Handoff Refs
   │
   ▼
ExecutionBackend.prepare_node()
   │
   ├── live backend revalidation
   ├── monotonic runtime narrowing
   ├── backend snapshot pinning
   └── stale preflight → revoke ticket / fail before workspace lock
   │
   ▼
Acquire WorkspaceAccess
   │
   ▼
Freeze execution_workspace_revision
   │
   ▼
Resolve / Render Dependency Handoffs
against frozen revision
   │
   ├── mark historical/stale handoffs
   └── build candidate immutable context
   │
   ▼
SchedulerStateMutex: FINAL DISPATCH COMMIT
   │
   ├── ticket active?
   ├── task dispatch epoch still current?
   ├── dependency acceptance stamps still exact?
   ├── if stale/revoked → no attempt, release lock, return PENDING
   └── if valid → allocate attempt/execution ids
                  READY → RUNNING
                  freeze NodeExecutionInvocation
   │
   ▼
WRITE / UNKNOWN-MUTATING → mandatory pre-attempt snapshot
   │
   ├── semantic READ_ONLY + physical WRITE
   │     → capture pre_repository_state_digest
   │
   ▼
ExecutionBackend.execute_prepared()
   │
   ├── NodeExecutionBindingStore bind immutable Invocation
   ├── DeerFlow Subagent assembly
   ├── first/every-model admission gate
   └── tool / contract enforcement
   │
   ▼
Runtime Assembly Attestation
   │
   ▼
WRITE / UNKNOWN-MUTATING
capture post-attempt snapshot
+ compute NodeWorkspaceDelta
   │
   ▼
Publish post_attempt_workspace_revision
(state-driven, regardless of acceptance)
   │
   ▼
Repository Invariant Check（mutating）
   │
   ├── semantic READ_ONLY + physical WRITE
   │     → compare RepositoryStateDigest
   │     → mutation => authority violation
   │
   ▼
Execution / Dirty-State Failure Classification
   │
   ├── clean safe retry
   ├── dirty-write fail
   └── completed path
   │
   ▼
Completed? Verify Full Self-Report Receipt Citations
   │
   ▼
Acceptance Check
(bind to post-attempt revision)
   │
   ▼
Execution Completeness Gate
   │
   ├── CLEAN + acceptance/invariants satisfied
   │     → logical success
   │
   ├── CAPPED + complete deterministic proof
   │     → success with EXECUTION_CAPPED_BUT_ACCEPTED
   │
   └── CAPPED without complete proof
         → retry / repair / fail according to mutation safety
   │
   ▼
Create NodeHandoff only for logically accepted attempt
(bind to post-attempt revision)
   │
   ▼
Verify Backend Execution Quiescent
   │
   ▼
Release Workspace Access
```

### 9.15.1 Workspace Lock 与 Backend Capacity 的资源顺序

Pinned DeerFlow native capacity 在：

```text
SubagentExecutor._aexecute()
      ↓
async with capacity.slot()
```

内部获取。

A-SWE Scheduler 则必须先拿 WorkspaceAccess，才能：

- freeze current WorkspaceRevision；
- resolve handoff staleness；
- capture pre-attempt evidence；
- 保证 execution context 与实际共享 Working Tree 一致。

因此 P1 冻结统一资源顺序：

```text
prepare backend
      ↓
(optional capacity-busy hint)
      ↓
acquire WorkspaceAccess
      ↓
freeze execution context
      ↓
enter DeerFlow execution
      ↓
DeerFlow capacity.slot()
```

#### Correctness

所有 A-SWE Node 都只采用：

```text
Workspace → Backend Capacity
```

禁止另一条 A-SWE 路径：

```text
Backend Capacity → wait Workspace
```

因此 A-SWE 自己不会形成：

```text
Node A holds Workspace, waits Capacity
Node B holds Capacity, waits Workspace
```

这种 ABBA resource deadlock。

外部普通 DeerFlow run 只占 native capacity，不占 A-SWE Workspace lock，也不会形成上述环。

#### Performance Trade-off

但统一顺序有明确代价：

```text
WRITE Node acquired Workspace
      ↓
backend saturated by unrelated work
      ↓
Node waits capacity queue
      ↓
Workspace remains exclusively locked
```

这叫：

```text
workspace lock hoarding while backend queued
```

它是 P1 的 throughput / latency trade-off，不是 correctness violation。

不能为了优化而在 P1 私自读取/占用 DeerFlow private waiter queue，或构建第二套“假 capacity reservation”。

#### Capacity Snapshot 仅作 Hint

Pinned `SubagentExecutionCapacity.snapshot()` 能返回：

```text
max_running
running
max_queued
queued
admission_policy
```

但 snapshot 是瞬时、racy observation，不是 reservation。

Scheduler 可在**拿 Workspace lock 之前**把它用于：

- backpressure hint；
- 延迟不必要的 dispatch；
- Trace / metrics；
- 避免在明显 saturated 时立即让 WRITE 抢锁。

但禁止：

```text
snapshot says free
→ assume slot reserved
```

真正 admission authority 仍是 DeerFlow `capacity.slot()`。

#### P1 Local Dispatch Budget

A-SWE 自身再设置：

```text
max_inflight_node_executions
<= pinned backend max_running
```

作为 control-plane budget，避免 A-SWE 自己制造超过 native capacity 的大量 queued executions。

它不是 DeerFlow capacity 的复制品：

- 不判断全进程真实 running count；
- 不替代 queue/reject policy；
- 不作为 execution admission evidence；
- external DeerFlow traffic 仍可能让 native backend saturated。

#### Metrics

至少记录：

```text
workspace_lock_wait_duration
workspace_lock_hold_duration
backend_capacity_wait_after_workspace_lock
backend_capacity_busy_before_lock
```

若：

```text
backend_capacity_wait_after_workspace_lock
```

长期占 Node duration 高比例，再在 P2 评估正式的 reservation / two-resource scheduler；P1 不提前引入。

原则：

> **Keep one resource order for correctness; measure lock hoarding before optimizing it.**

---

### 9.16 一期 Runtime Budget

所有预算必须属于 Runtime config，而不是 Prompt 建议。

P1 建议初始值：

```text
max_work_items = 8
max_inflight_node_executions = backend_capacity
max_parallel_read_nodes = min(3, max_inflight_node_executions)
planning_attempts = 2
execution_replans = 1        # pre-WRITE only
max_retries_per_node = 1
max_repairs_per_write = 1
```

其中 DeerFlow 当前 pinned baseline 的 native subagent runtime 默认：

```text
max_running = 3
```

A-SWE 不应把自身并行预算设置得高于 backend 实际 capacity。

### 9.17 一期不做

- arbitrary execution-time DAG spawning；
- dirty WRITE transactional rollback；
- unlimited replanning；
- multi-writer automatic repair；
- parallel write merge；
- distributed scheduler；
- cross-machine workspace lock；
- RL scheduling。

---
