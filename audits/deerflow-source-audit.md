# DeerFlow Source Audit / Phase 0 Architecture Freeze

> 本文件由原单体实施方案的 Phase 0 迁移并持续审计。PoC authority 位于 `tests/poc-matrix.md`，避免双重维护。

## P0 Design Freeze Status

```text
Architecture / Execution Semantics: DESIGN FROZEN
PoC Execution: PENDING
Real DeerFlow Shared-Workspace Integration: GO/NO-GO GATED
```

这里的 `DESIGN FROZEN` 只表示：

- authoritative schemas / ownership 已收口；
- P1 execution semantics 已无已知未决大项；
- Core/FakeBackend 实现可以开始。

它**不表示** DeerFlow integration PoC 已通过。

### P0 Consistency Sweep Result

本次 Design Freeze 对 active docs（不含 `archive/`）执行了静态一致性检查：

```text
duplicate authoritative class definitions     0
dangling project-internal annotation types   0
unbalanced fenced code blocks                0
broken relative document links               0
duplicate PoC ids                            0
malformed PoC table rows                     0
active pre-freeze status markers             0
PoC rows currently indexed                   332
```

同时已完成：

- README Schema Ownership Map；
- P0-1 ～ P0-7 状态统一为 `Design Frozen / PoC Execution Pending`；
- P0-4 contract/constraint PoC 分组补齐；
- P0-7 retry/repair/failure PoC 分组恢复；
- P0-Final static conformance checks；
- Master Plan Authoritative Coding Order；
- archive 明确降级为 historical reference only。

这些 manual/static checks 后续应转成 `POC-F*` 对应 CI/static tests，防止实现阶段重新引入 schema drift。

它**不表示** DeerFlow integration PoC 已通过。

在允许真实 DeerFlow backend 承担 P1 shared mutable Workspace 主链路前，至少必须通过既有关键 integration gates：

```text
POC-02 / POC-03 / POC-05 / POC-09
POC-R34 / R35 / R36 / R38
POC-R50 / R51
POC-R69 / R70 / R73
```

此外，Writer reopen / dispatch linearization 的：

```text
POC-R109 ~ POC-R126
```

必须先在 deterministic FakeBackend/Scheduler tests 中通过，再接入真实 backend。


### Phase 0：Integration Validation / Architecture Freeze

正式实现 Phase 1 前，先验证 A-SWE 对 DeerFlow 的关键假设。

#### P0-1：DeerFlow Integration PoC

状态：

```text
Design Frozen
PoC Execution Pending
```

冻结审计基线：

```text
deer-flow @ c0895d295bba34f6e95188fca380f555dabed891
```

PoC 矩阵：

> PoC 表已迁移至 [tests/poc-matrix.md](../tests/poc-matrix.md)。

Go / No-Go Tests：

```text
POC-02
POC-03
POC-05
POC-09
```

任何一个失败，都先修正 Adapter / Workspace 设计，不直接进入 Phase 1 主实现。

#### P0-2：Repository / Workspace Bootstrap Audit

状态：

```text
Design Frozen
PoC Execution Pending
```

审计后冻结链路：

```text
Repository Source
      ↓
WorkspaceSession Allocate
      ↓
Repository Bootstrap
      ↓
clone / materialize
      ↓
resolve requested_ref
      ↓
checkout exact resolved_base_sha
      ↓
verify clean repository
      ↓
capture baseline workspace snapshot
      ↓
Task DAG execution
      ↓
Repository Invariant Check
      ↓
Git ChangeSet + Workspace ChangeSet
      ↓
Evaluation / Patch Result
```

架构结论：

- DeerFlow thread workspace：直接复用；
- DeerFlow bash cwd：直接复用，Repository Root 放在 `/mnt/user-data/workspace`；
- Repository clone / checkout / base SHA freeze：A-SWE 实现；
- Repository invariant：A-SWE 实现；
- filesystem snapshot / diff：复用 DeerFlow `workspace_changes`；
- Git-aware Patch：A-SWE 实现；
- Fresh-shell Sandbox Profile：P1 deterministic regression reference execution environment；
- LocalSandbox：最简单的 trusted local/demo fresh-shell reference（host bash 必须显式允许）；
- Local AIO Container：仍可用于 Agent execution / shared Workspace isolation，但 pinned baseline 下不具备 native `deerflow_tests_passed_evidence`，不能作为完整 deterministic regression reference；
- public HTTPS repo / local fixture：MVP 必须支持；
- private repo credential：optional integration。

新增 P0-2 PoC：

> PoC 表已迁移至 [tests/poc-matrix.md](../tests/poc-matrix.md)。

P0-2 的目标不是让 Agent 学会 Git，而是让 Runtime 掌握 Repository execution identity 与可复现 baseline。

#### P0-3：Planning / DAG Architecture Audit

状态：

```text
Design Frozen
PoC Execution Pending
```

当前冻结结论：

- DeerFlow Plan Mode / Todo 不等于 SWE Task DAG；
- A-SWE 不使用 DeerFlow Lead Agent 自主 delegation 作为核心 topology authority；
- LLM 不直接生成最终可执行 TaskDAG；
- TaskSpec 中只保留 `capability_hints`；
- Repository Profile 在 Task Analyzer / Planner 前提供结构证据；
- 信息不足时允许 bounded read-only Recon Probe；
- Recon Probe 属于 Planning Infrastructure，不计入最终 TeamSpec；
- SemanticPlanner 不读取 Agent roster；
- Planner 输出 `WorkPlanProposal`；
- Runtime 通过 PlanValidator / Normalizer 生成 `ValidatedWorkPlan`；
- Capability Resolution 下沉到 WorkItem / Node Level；
- Team Builder 只生成 roster，不生成 topology；
- DAG Materializer 拥有最终执行 topology authority；
- Scheduler 不再做 task decomposition；
- DAG Edge 同时具有 control dependency 与 handoff data dependency；
- 共享 Workspace 的无依赖 WRITE Nodes 由 Materializer 确定性串行化；
- execution-time arbitrary DAG mutation 不属于 MVP；
- Plan validation 分为 Semantic 与 Execution 两阶段；
- unordered READ / WRITE 同样需要 deterministic dependency normalization；
- 旧的全局 READ→WRITE 默认顺序被废弃；
- WorkKind 与 WorkspaceAccess 分离；
- DAG ordering 优先遵守 DISCOVERY→IMPLEMENTATION→VERIFICATION→REVIEW 语义 phase；
- Reviewer READ 不得因为 access class 被错误排到 Tester/Writer 前；
- same-phase conflict 才使用 stable planner ordinal 做保守串行；
- Retry、Repair、Replan、Fail-Closed 必须分离；
- DeerFlow workspace snapshot 不是 transactional rollback；
- dirty WRITE failure 一期禁止自动 retry；
- Verification failure 使用 bounded repair，而不是重试 Tester；
- execution-time replan 只允许发生在首次 WRITE 前；
- DeerFlow AgentAssemblyDescriptor 用于 runtime assembly attestation；
- AgentAssemblyObserver 是 fail-open observer，不能作为安全 gate；
- Executable Plan 需要 canonical fingerprint 与 repair log。
- Task Analyzer / SemanticPlanner 的模型调用通过 provider-neutral ReasoningBackend；
- DeerFlow integration 优先复用公开 ModelInvoker 做 bounded structured reasoning；
- TaskSpec 与 authoritative TaskContract 分离；
- TaskContract / Constraint Compiler 进入下一轮 P0-4 审计。

P0-3 新增 deterministic compiler PoC：

> PoC 表已迁移至 [tests/poc-matrix.md](../tests/poc-matrix.md)。

下一步继续审计：

```text
Coverage Validation
+
Runtime Gate Compilation
+
Canonical Plan Fingerprint
```

的 deterministic rule set、repair boundary 与 bounded replan policy。

---

#### P0-4：TaskContract / Constraint Compiler Audit

状态：

```text
Design Frozen
PoC Execution Pending
```

目标：

- 冻结 ConstraintSource / authority model；
- 区分 runtime-policy / user-explicit / repository-guidance / inference；
- 定义 provenance validation；
- 定义 hard / soft constraint；
- 定义 conflict resolution；
- 定义 monotonic constraint repair；
- 定义 TaskContract 与 SemanticPlanner / PlanValidator 的接口；
- 定义 constraint trace / fingerprint。
- provenance authenticity 与 instruction authority 分离；
- compiler-owned provenance stamping；
- `LOCKED / HARD / SOFT` enforcement；
- repository guidance 默认 SOFT 且禁止 self-promotion；
- typed merge algebra；
- user/runtime/repository conflict matrix；
- unknown explicit requirement → semantic.requirement，不静默丢弃；
- Contract → Planner coverage → Execution Policy → Final Evaluation 闭环；
- undecidable contract leaf → UNVERIFIED，不自动视为满足。
- Contract constraint 必须声明 enforcement phase 与 guarantee；
- DeerFlow GuardrailMiddleware 可复用为 PRE_TOOL_GUARD；
- structured file tool path constraint 可执行前拦截；
- generic bash 不具备 read-only guarantee；
- WorkspaceAccess 必须综合 Capability + ToolEffect；
- P1 仅将“可证明只读”的 Node 编译为 READ；
- 使用 bash 的 Tester 默认 WRITE / exclusive；
- sensitive constraint 采用 plan + pre-tool + post-node + final evaluation defense-in-depth。

---

#### P0-5：Capability / Provider Contract Audit

状态：

```text
Design Frozen
PoC Execution Pending
```

冻结结论：

- Capability Registry 只保存 semantic vocabulary；
- P1 只有 AgentProvider 是 schedulable execution provider；
- Tool / Skill 是 AgentProvider 的 supporting resources；
- concrete Tool requirement 从 Provider CapabilityBinding 产生，而不是写死在 CapabilitySpec；
- Provider Registry 是 capability mapping 的 single source of truth；
- BackendInventorySnapshot 只提供 compile-time candidate resource preflight；
- `SubagentConfig.tools` 是 name-level allowlist，不是 actual-tool proof；
- A-SWE Node policy 只能 intersection / union 式继续收窄 operator SubagentConfig；
- A-SWE 不允许通过 Node policy 抬高 operator max_turns / timeout；
- Skill allowlist 只代表 discovery / activation scope，enabled skill 不等于 skill was used；
- Skill 在 P1 默认 optional enhancement，不参与 hard feasibility；
- DeerFlow AssemblyDescriptor 是 runtime evidence，不是默认存在；
- A-SWE 通过公开 AgentAssemblyObserver extension 开启 descriptor generation；
- AssemblyAttestation 是 compatibility / validity gate，不替代 authorization；
- direct SubagentExecutor 的 model authorization 需要 Adapter 显式 preflight；
- P1 对 denied model 使用 strict provider-infeasible 语义，不静默 fallback；
- `SubagentConfig.tools` 不能覆盖 generated / middleware-declared tool 的全部 visibility；
- packaged extension middleware 是 observational，不能承担 Node enforcement；
- strict Node tool visibility 使用 trusted `extensions.middlewares` + ASWENodeToolPolicyMiddleware；
- NodeExecutionBindingStore 用 unique A-SWE run_id 做进程内短生命周期 correlation；
- P1 明确限制为 single-process policy carrier；distributed carrier 后置。
- required hard Tool dependency 一期必须是 eager；deferred MCP 仅作为 optional enhancement；
- NodeToolPolicy 在每次 model call 重新验证 required eager tool availability；
- required-tool mismatch 使用 synthetic marked ModelResponse short-circuit，且不调用 upstream LLM handler；
- `deerflow_error_fallback` 负责复用 DeerFlow FAILED terminalization，A-SWE marker 负责精确 failure mapping；
- AssemblyDescriptor 定位为 attestation/reproducibility evidence，不作为 admission gate。
- `PREFLIGHT_FEASIBLE` 只是 planning-time 判断；NodeReady 后必须 live revalidate；
- DeerFlow execution 使用单一 AppConfig / Tool / Extension snapshot，避免 execution 内 config TOCTOU；
- fingerprint drift 本身不是 failure，重新验证 requirement 失败才是 `BACKEND_PREFLIGHT_STALE`；
- runtime 只允许 monotonic narrowing，不允许隐式扩权或 Provider rebinding；
- authorization 保持 live gate，不伪造 frozen policy snapshot。
- DeerFlow native Subagent 是 one-shot / no-checkpoint execution；
- Provider reuse 不等于 Agent session reuse；
- Semantic NodeBoundaryPolicy 必须 provider-neutral；
- Provider Assignment 不允许反向合并 / 拆分 WorkItem；
- cross-node context 只通过 explicit NodeHandoff / shared Workspace evidence 传递。
- P1 core hard-required Tool identity 以 `ToolConfig.use` 为稳定 anchor；
- Python object identity / Tool provenance label 不作为 Provider hard-feasibility authority；
- schema_hash 只用于 compatibility drift，不替代 implementation identity。
- DeerFlow WorkspaceChangeSet 只覆盖 scanner-visible filesystem scope，不是 sandbox/environment complete mutation oracle；
- P1 新增 `MutationEvidence = PROVEN_NONE | OBSERVED | UNKNOWN`；
- mutating/UNKNOWN tool 一旦实际执行但副作用不可完全观测，按 UNKNOWN 处理；
- WorkspaceRevision 对 OBSERVED / UNKNOWN 都推进；
- WRITE retry 只有 PROVEN_NONE 才可进入自动 retry 候选。

新增 PoC：

> PoC 表已迁移至 [tests/poc-matrix.md](../tests/poc-matrix.md)。

---

#### P0-6：NodeHandoff / Cross-Node Context Audit

状态：

```text
Design Frozen
PoC Execution Pending
```

当前冻结结论：

- DeerFlow native Subagent 是 one-shot execution，跨 Node 无隐式 conversation continuity；
- NodeHandoff 分离 model self-report 与 Runtime evidence；
- self-report 永远是 untrusted data；
- changed_paths / untracked_paths 不接受 Agent 自报，来自 Git / Workspace deterministic evidence；
- Handoff 绑定 WorkspaceRevision；
- WorkspaceRevision 使用 monotonic generation + repository state fingerprint，不能只看 HEAD；
- historical receipt 不能作为下游自身 execution proof；
- model-facing handoff 必须 bounded + neutralized；
- hidden/framework handoff injection 不能依赖 DeerFlow InputSanitizationMiddleware 自动处理；
- Handoff projection 使用独立 ASWEHandoffContextMiddleware；
- 不复用 operator-owned prompt_overlay 承载 runtime handoff；
- system channel 只放固定 authority contract，真实 handoff payload 放 hidden HumanMessage；
- Handoff hidden HumanMessage 使用 DeerFlow server-owned provenance metadata 显式标记 producer/content kind；
- authority SystemMessage 的 A-SWE provenance 只在 coalescing 前成立；最终 merged SystemMessage provenance 由 DeerFlow system_coalescing 接管；
- Handoff projection request-scoped，不写回 child graph messages state；

- 多 parent handoff deterministic merge，保留 source provenance；
- repair feedback 使用独立 typed contract；
- Handoff fingerprint 与 Workspace state fingerprint 分离。
- DeerFlow receipt 必须 execution-scoped，不保存裸 rN；
- `rN` 是可重编号 display id；durable ReceiptRef 使用 immutable receipt-ledger EvidenceRef + ledger index；tool_call_id / short hashes 只作 correlation/freshness consistency 字段；
- changeset / acceptance / verification 由 ExecutionEvidenceStore 持有；
- EvidenceRef immutable 且 attempt-scoped；
- retry / repair 不覆盖旧 attempt evidence；
- Direct SubagentExecutor 绕过 task_tool receipt citation verification，Adapter 必须显式回接；
- citation verdict 只属于 advisory execution evidence，不等于 acceptance；
- report citation verification 必须发生在 Handoff truncation 之前；
- Handoff staleness final classification 必须发生在 Workspace lock granted 之后；
- 每个 Node attempt 冻结 pre-execution WorkspaceRevision；
- WRITE / UNKNOWN-mutating attempt 的 before/after snapshot 为 mandatory；
- Node changed_paths 来自 per-attempt NodeWorkspaceDelta，不从 cumulative baseline diff 推断；
- snapshot attribution truncated 时按 unknown-dirty 处理 retry，并保守推进 revision；
- WorkspaceRevision advancement 由实际/未知 mutation 决定，不由 Node success 决定；
- acceptance / verification / invariant evidence 绑定 post-attempt revision；
- failed dirty WRITE 也先产生新的 dirty post revision；
- EvidenceRef 是 persistence reference，HandoffEvidenceProjection 才是模型消费视图；
- state-dependent evidence 按 WorkspaceRevision 标记 CURRENT / HISTORICAL；
- historical acceptance / verification 不得渲染成 current-state proof；
- Repair 是 immutable Write TaskNode 的新 attempt，不是动态新增 DAG Node；
- Retry 与 Repair 共享 attempt ledger，但触发条件完全不同；
- repair/reverify 全部生成 fresh execution/evidence，旧 verdict 只保留 Trace；
- P1 repair 只支持 deterministic failure + unique single writer target；
- post-lock dependency projection 通过 provider-neutral NodeExecutionInvocation 进入 Backend；
- DeerFlow Adapter 用 exact run_id 绑定 immutable NodeExecutionBinding；
- Handoff middleware 不在 isolated loop 读取 EvidenceStore / Git；
- run_id prefix 不是 authority，exact BindingStore entry 才是 authority。
- physical WorkspaceAccess 与 semantic repository-mutation authority 分离；
- VERIFICATION/REVIEW 等 READ_ONLY authority Node 可因 bash 获得 WRITE lock，但 Git-visible patch 必须保持不变；
- DeerFlow backend `completed` 不等于 A-SWE logical success；
- `completed + stop_reason` 映射为 `CAPPED`；
- capped partial 只有完整 deterministic acceptance + invariants 全通过时才可带 warning 接受；
- mandatory REVIEW / 无 deterministic completeness proof 的 DISCOVERY capped run 不得静默成功；
- 未接受的 capped partial 保留 evidence，但不产生 normal success Handoff。
- mandatory Review 不解析自由文本 verdict，使用 A-SWE-owned structured direct-return Tool；
- ReviewDecision 是 semantic evidence，Runtime 拥有 revision/execution envelope；
- mandatory Review 只接受 CLEAN completion + valid ReviewVerdict + repository state unchanged。
- structured direct-return Review 不运行普通 prose receipt verifier；
- ReviewEvidenceResolver 使用 `SubagentResult.tool_receipts` 的 fail-closed citing-turn ledger snapshot 解析 rN，并持久化为 ledger-backed ReceiptRef；
- mandatory APPROVE 至少需要一个成功 inspection receipt，防止 zero-inspection approval。
- BindingStore 横跨 Scheduler loop 与 DeerFlow isolated subagent loop，P1 使用 thread-safe 同步而非 loop-bound asyncio.Lock。
- DeerFlow SummarizationMiddleware 只压缩 graph state；request-scoped Handoff projection 不进入 summary_text；
- final merged SystemMessage provenance 由 system_coalescing 接管，不能把 final producer_kind 误当 A-SWE provenance；
- ExecutionEvidenceStore 与 RunEventStore / ExtensionData 职责分离：evidence 是 artifact，trace 是 event stream；
- LocalEvidenceStore 使用 atomic publish + full SHA-256 integrity verification；
- runtime task/thread/run/evidence filesystem identities 使用 opaque validated safe ids；
- DeerFlow receipt short hashes 是 freshness stamps；durable receipt address 使用 immutable receipt-ledger EvidenceRef + ledger_index。

新增 PoC：

> PoC 表已迁移至 [tests/poc-matrix.md](../tests/poc-matrix.md)。

---

#### P0-7：Retry / Repair / Failure Propagation Audit

状态：

```text
Design Frozen
PoC Execution Pending
```

已确认的第一条边界：

- DeerFlow `SubagentResult.status.is_terminal` 早于 executor `finally` cleanup 完成；
- A-SWE Scheduler 禁止以 polling terminal status 直接释放 Workspace lock；
- public `execute()` 的 timeout 路径也不能统一视为 quiescent return；
- pinned DeerFlow 当前没有 public quiescence/join seam；
- 直接等待/copy private `_background_futures` 也不够，因为 `Future.cancel()` 可早于 coroutine cleanup 完成；
- P1 需要极薄 DeerFlow compatibility patch：独立 completion signal，只在 background execution coroutine 真正退出后置位；
- `execute_prepared()` 对 Core 承诺 return == backend quiescent；
- `cancel_node()` 对 Core 承诺 return == cancelled execution quiescent，而不是 signal-only；
- completion proof 丢失时 WorkspaceSession → QUARANTINED，停止后续 dispatch。
- DeerFlow ToolProgress / ToolReceipt 都属于 post-handler evidence，不能证明 cancellation 前“未启动 mutating tool”；
- ASWENodeToolPolicyMiddleware 必须在 allowed tool call 进入 downstream handler 前记录 ToolCallAdmissionRecord；
- `PROVEN_NONE` 需要完整 pre-handler admission audit + complete no-change snapshot；receipt absence 不构成 clean proof。
- DeerFlow sandbox-backed sync work通过 shield + drain 防止 worker outlive execution holder；
- A-SWE quiescence join 可以作为 core sandbox tool 的 workspace-lock release fence；
- external MCP/plugin/custom side effect 不继承该保证，默认不参与 automatic clean retry。
- AIO healthy release 进入 warm pool，container remains running；
- AIO scoped shell cleanup 是 best-effort，异常被吞掉，不能作为 strict process-quiescence proof；
- completion signal 只证明 executor-owned quiescence，不证明任意 detached process / container stop；
- P1 managed bash 因此只允许 Runtime-compiled EXACT foreground command set；arbitrary free-form bash 禁用；
- Git-visible Repository state 使用 temporary index + `git write-tree` canonical OID，不自行目录哈希；
- semantic READ_ONLY pre/post invariant 比较 per-attempt working_tree_oid；
- parent tree OID 不覆盖 dirty submodule working state，因此 P1 bootstrap 显式拒绝 submodule / sparse checkout。
- background/daemon/detached workflow 在 P1 视为 unsupported，除非未来提供更强 process-group/container lifecycle proof。
- Attempt failure 与 Logical Node failure 分离；有合法 remediation 时 Node=REMEDIATION_PENDING；
- ordinary dependency 只由当前 SUCCEEDED + accepted_attempt/handoff 满足；
- Writer reopen for Repair 会立即撤销旧 accepted handoff 的 dependency authority；
- P1 不支持已提交普通 downstream success 后的隐式 descendant rollback；此时 Repair scope invalidated。
- RepairFeedback 是 revision-scoped deterministic evidence；真正 REPAIR dispatch 前必须在 WRITE lock 内做 freshness check；
- stale verification/acceptance feedback 不能直接变成 current repair instruction；必须 refresh/reverify 或 fail closed。
- downstream verification attribution 定义为 repair ownership，不宣称 causal blame；
- attribution candidate 只来自 immutable DAG 中的 semantic REPOSITORY_MUTATION IMPLEMENTATION ancestors，不按 last-writer / path overlap / model prose 猜测；
- 每个 failed deterministic check 都必须有 compiler-owned VerificationRepairBinding；所有 failed check 必须解析到同一个 singleton logical Writer 才允许 automatic repair；
- downstream repair target 使用该 Writer 当前 accepted_attempt；旧 retry/repair attempt 不作为 current owner；
- distinct intervening business Writer 若在 target acceptance 后改变 Git-visible Repository state，则 attribution scope invalidated；
- RepairAttributionEvidence 持久化并进入 RepairFeedback；Writer reopen 必须先经过 downstream dispatch-race gate，并与 consumer dispatch commit 在 SchedulerStateMutex 上线性化。
- direct SubagentExecutor terminal vocabulary 固定为 completed/failed/cancelled/timed_out；polling_timed_out 不进入 Adapter backend status；
- `stop_reason` 与 terminal status 正交；FAILED 也可能是 capped execution；
- capacity `admission_failure` 只映射 backend admission，不与 policy/preflight/model auth failure 混用；
- DeerFlow overall timeout 包含 capacity queue wait；
- `started_at is None` 是 pinned background path 的 PRE_START 强信号；
- PRE_START timeout / admission failure 可证明 backend 未进入 model/tool/sandbox execution；
- TIMED_OUT 必须结合 execution_phase 解释，不能统一视为 started execution timeout；
- SubagentResult first-terminal-wins 会隐藏“COMPLETED 后 cleanup tail 触发 outer timeout”的竞态；
- completion compatibility outcome 必须独立记录 outer_timeout_fired；
- COMPLETED + lifecycle deadline overrun 可继续 deterministic evaluation，但不得记为 clean within-budget completion。
- SubagentExecutor 只有 acceptance_criteria 非空时才采集 bash execution evidence；
- native tests_passed 明确要求 shell_persistent=False；True/None 均 UNVERIFIED；
- AIO pinned baseline persistent_shell_sessions=True，因此不能承担 P1 load-bearing native tests_passed reference path；
- sandbox execution capability 与 deterministic-evidence capability 分离；
- VerificationCommand 同时驱动 tests_passed criterion 与 BashCommandPolicy exact command，避免 command identity drift。
- A-SWE P1 统一资源顺序为 Workspace → DeerFlow native capacity，避免内部 ABBA；
- capacity snapshot 只能做 pre-lock backpressure hint，不能当 reservation；
- P1 接受 backend saturation 时的 Workspace lock hoarding，并以 metrics 量化，不自建第二套 capacity controller。
- NodeExecutionResult 使用 exhaustive typed status/stop-reason mapping，未知值视为 BACKEND_CONTRACT_MISMATCH。
- DIRTY_WRITE_FAILURE 与 Workspace QUARANTINED 分离：前者可在 quiescence 已证明时冻结稳定 residual state，后者表示 late mutation 仍不可排除。
- WorkspaceSession 增加 FROZEN：terminal dispatch closed、backend quiescent，只允许 Runtime-owned deterministic finalization。
- workspace-compromising terminal failure 触发 task-wide fail closed；不只阻塞 DAG descendants，也阻塞同 WorkspaceSession 中尚未执行的独立 branch。
- task-wide fail closed 后禁止 Reviewer / Explorer / Tester / 任意 Agent diagnostic run；只允许不经 AgentProvider/LLM/MCP 的 deterministic finalization。
- Task outcome、Workspace disposition、Repository disposition、Patch disposition 正交建模。
- Task FAILED 且 Git-visible patch 存在时必须标记 RESIDUAL_UNACCEPTED；残留 patch 不满足 TaskContract、不解锁 downstream、不伪装成功。
- QUARANTINED workspace 禁止新的 workspace-touching finalizer；TaskResult 只能聚合 quarantine 前已经持久化的 trusted evidence。
- remaining PENDING/READY/REMEDIATION_PENDING nodes 在 task-wide dirty fail-close 时统一 BLOCKED，block_reason=TASK_FAIL_CLOSED，root failure ownership 保持唯一。
- terminal TaskResult 持有 structured root_failures、blocked/cancelled node ids 和 final repository evidence refs，不复制 patch bytes。
- attempt-scoped EvidenceRef 不扩权为 task finalizer provenance；terminal repository artifacts 使用独立 TaskEvidenceRef。
- QUARANTINED 不创建伪 final TaskEvidenceRef；只能保留 quarantine 前 last_trusted EvidenceRef，并标为历史观察。
- post-lock Handoff revalidation 不能单独关闭 reopen race；consumer dispatch commit 与 Writer reopen 必须共享 SchedulerStateMutex 作为 linearization point。
- READY Node 在真正 dispatch commit 前保持 logical READY；prepare / wait-lock / locked-precommit 使用独立 revocable NodeDispatchTicket，不提前创建 NodeAttemptRecord。
- NodeRuntimeState 增加 acceptance_epoch；accepted authority publish/revoke/new publish 都递增，consumer 通过 DependencyAcceptanceStamp 冻结 upstream authority generation。
- TaskDispatchGate 使用 epoch 防止 task fail-close 后旧 READY/waiting ticket 越过 commit boundary。
- pre-commit ticket 可 revoke：不消耗 attempt/retry/repair budget，不调用 backend cancel；prepared object 必须可安全 discard。
- affected consumer 一旦 COMMITTED/RUNNING，P1 不实现 cancel-clean-and-repair；Writer reopen 判 REPAIR_SCOPE_INVALIDATED(reason=ACTIVE_DOWNSTREAM_DISPATCH)。
- COMMITTED 即使 DeerFlow execution_phase=PRE_START，也视为越过 P1 rollback-free dispatch boundary。
- active downstream 导致 repair scope invalidated 时，先 close task dispatch gate，再 cancel/join committed runs；全部 quiescent 后才可 Workspace→FROZEN，否则 QUARANTINED。
- Writer reopen 成功 transaction 内同时 revoke affected pre-commit tickets、清除 current accepted_attempt/handoff、acceptance_epoch+1、Writer→REMEDIATION_PENDING、source verifier→REMEDIATION_PENDING，并 recompute affected READY。
- WorkspaceRevision 与 DependencyAcceptanceStamp 是两个独立 fence：前者保护 physical workspace state，后者保护 accepted dependency authority。
- accepted_attempt/handoff publication + acceptance_epoch increment + dependent READY recomputation 必须在 SchedulerStateMutex 下原子完成。
- READY predicate check + DependencyAcceptanceStamp capture + single active dispatch-ticket claim 也必须在同一 SchedulerStateMutex transaction 内完成，禁止先算 READY 后晚取 stamps。

审计目标：

```text
Backend terminal outcome
        ↓
Mutation / completeness classification
        ↓
Retry eligibility
        ↓
Repair eligibility
        ↓
Downstream failure propagation
        ↓
Final Node logical state
```

本阶段重点核验：

- DeerFlow SubagentResult terminalization 与 timeout / cancellation / cap semantics；
- clean retry 是否可被 execution evidence 可靠证明；
- failed / cancelled execution 的 receipt / bash evidence 可见性；
- WRITE failure 后 sandbox / process 是否可能继续产生 late side effect；
- Retry 与 DeerFlow execution capacity / cancellation cleanup 的边界；
- Repair feedback 是否会复用 stale verification / acceptance evidence；
- verification failure 如何唯一归因到 target writer；
- capped partial 的 logical-success gate 是否足够严格；
- downstream dependency 节点在 upstream FAILED / DIRTY / UNVERIFIED 时的传播规则；
- cancellation 是否能保证 binding / workspace lease / scheduler state 最终一致。

---

P0-7 Go/No-Go：

```text
POC-R34 / R35 / R36 / R38 / R50 / R51 / R69 / R70 / R73
```

必须通过。

若无法为 direct SubagentExecutor 建立 cancel-safe independent completion proof：

```text
Direct SubagentExecutor backend
→ NO-GO for P1 shared mutable Workspace scheduling
```

不能用“terminal status + sleep 一下”替代。

---

#### P0-7 Design Freeze Conclusion

P0-7 的 execution semantics 已冻结：

```text
terminal outcome
→ mutation classification
→ retry/repair eligibility
→ handoff authority / dispatch race
→ failure propagation
→ task finalization
```

后续若 PoC 暴露 pinned DeerFlow implementation 与这些 contract 不兼容，优先动作是：

1. 修 DeerFlow compatibility Adapter/seam；
2. 若 contract 本身不可实现，再显式 reopen Design Freeze；
3. 禁止在实现代码里偷偷弱化 quiescence、evidence 或 fail-closed semantics。

状态保持：

```text
Design Frozen
PoC Execution Pending
```

#### P0-7.1 Deterministic Verification Sandbox Profile

P1 reference deployment 必须满足：

```text
shared Repository Workspace
+
required core tools
+
fresh_shell_per_command
+
deerflow_tests_passed_evidence
```

因此当前 pinned baseline：

| Sandbox | Agent/SWE execution | Native tests_passed load-bearing evidence | P1 reference status |
|---|---:|---:|---|
| LocalSandbox | Yes | Yes | ✅ trusted local/demo reference |
| AioSandbox | Yes | No (`persistent_shell_sessions=True`) | 🟡 execution supported, deterministic regression reference NO |
| E2B/OpenSandbox/Tenki/BoxLite | provider-dependent | declared fresh-shell | optional future profiles |

P1 不为了保留 AIO “默认”标签而绕过 DeerFlow checker。

未来若希望 AIO 成为完整 deterministic reference，可以新增单独：

```text
FreshShellVerificationBackend
```

在同一 Workspace 上由 Runtime 直接执行 canonical `VerificationCommand`，并产生独立 typed evidence；但这必须是新的明确验证 seam，不能把 AIO persistent-shell evidence 伪装成 native `tests_passed`。

DeerFlow acceptance checker 自身已经采用：

> persistent / unknown shell provenance → fail closed

A-SWE 保持这一边界。

---

P0-7 新增 PoC：

> PoC 表已迁移至 [tests/poc-matrix.md](../tests/poc-matrix.md)。
