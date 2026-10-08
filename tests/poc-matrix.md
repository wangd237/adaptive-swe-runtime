# Architecture Conformance PoC Matrix

> 本文件集中保存原单体实施方案 Phase 0 中的 PoC 表。PoC 行内容未改写；审计背景与 Go/No-Go 解释见 `../audits/deerflow-source-audit.md`。

## P0-1：DeerFlow Integration PoC

| PoC | 测试内容 | 必须验证 |
|---|---|---|
| POC-01 | 直接 `SubagentExecutor(repo-explorer)` | 不经过 Lead Agent 即可执行 |
| POC-02 | Explorer 写 `marker.txt` → Coder 读取 | 同 thread workspace |
| POC-03 | Coder 修改 Python 文件 → Tester pytest | 修改对后续 Node 可见；fresh-shell reference 下 tests_passed 可确定性成立 |
| POC-04 | 两个 READ Node 并发 | 能共享 Workspace / Sandbox |
| POC-05 | 两个 Subagent 并发 | 一个结束不会提前释放另一个正在使用的 Sandbox |
| POC-06 | timeout / cancel | capacity 与 sandbox lease 无泄漏 |
| POC-07 | tools / disallowed_tools | Provider 权限映射正确 |
| POC-08 | skills | discovery / activation 范围正确 |
| POC-09 | acceptance criteria | Adapter 可回接 DeerFlow checker |
| POC-10 | tool receipts | 可关联 node → execution evidence |
| POC-11 | sequential WRITE nodes | Repository 状态正确累计 |
| POC-12 | Local AIO release / reclaim | Workspace 文件仍连续可见 |
| POC-21 | Contract Guard：write_file 越界 path | tool 执行前 fail-closed deny |
| POC-22 | Contract Guard：str_replace forbidden manifest | tool 执行前 deny |
| POC-23 | Tester + bash | Node 被编译为 WRITE / exclusive |
| POC-24 | Verification bash 产生 source mutation | post-node Git invariant 能检测并 fail |
| POC-25 | Guard provider error under A-SWE constrained run | fail closed |
| POC-26 | ordinary DeerFlow non-A-SWE run | A-SWE Node policy 不误作用于无关 run |

## P0-2：Repository / Workspace Bootstrap Audit

| PoC | 测试内容 | 必须验证 |
|---|---|---|
| POC-13 | public repo → bootstrap | clone 到 workspace root |
| POC-14 | branch / tag → SHA | `resolved_base_sha` 稳定 |
| POC-15 | bootstrap clean check | 初始 working tree clean |
| POC-16 | Agent 修改后 invariant | HEAD 仍等于 base SHA |
| POC-17 | Agent 擅自 commit / checkout | invariant fail |
| POC-18 | final Git ChangeSet | tracked + untracked 完整 |
| POC-19 | baseline snapshot timing | clone 文件不进入 task diff |
| POC-20A | fresh-shell reference sandbox repo execution | clone / edit / pytest / deterministic tests_passed / diff 全链路成立 |
| POC-20B | Local AIO pytest execution | pytest 可运行，但 bash evidence shell_persistent=true，native tests_passed=UNVERIFIED |

## P0-3：Planning / DAG Architecture Audit

| PoC | 测试内容 | 必须验证 |
|---|---|---|
| POC-P3-01 | Coder WRITE + Tester bash WRITE | IMPLEMENTATION → VERIFICATION |
| POC-P3-02 | Tester WRITE + Reviewer READ | VERIFICATION → REVIEW，而不是 READ → WRITE |
| POC-P3-03 | Explorer READ + Coder WRITE | DISCOVERY → IMPLEMENTATION |
| POC-P3-04 | 两个同 phase WRITE 且无 edge | stable ordinal serialization |
| POC-P3-05 | Planner 显式 REVIEW → IMPLEMENTATION | PHASE_ORDER_CONTRADICTION |
| POC-P3-06 | 两个独立 DISCOVERY READ | 保持并行 |
| POC-P3-07 | mandatory verification/review 缺失 | Runtime 注入 reserved gate nodes |
| POC-P3-08 | Planner 使用 __aswe_ id | hard reject |
| POC-P3-09 | read-only analysis task + planner code_modification hint | CAPABILITY_AUTHORITY_VIOLATION |
| POC-P3-10 | bug-fix contract grants repository mutation | implementation capability 可通过 authority validation |
| POC-P3-11 | Tester bash modifies source | 虽有 WRITE lock但 post-node business-mutation invariant fail |
| POC-P3-12 | mutation WorkItem 无 mutation deliverable coverage | PLAN_INVALID |

## P0-4：TaskContract / Constraint Compiler Audit

| PoC | 测试内容 | 必须验证 |
|---|---|---|
| POC-C01 | Repository guidance 自称 mandatory / system authority | provenance 可验证但仍保持 REPOSITORY_GUIDANCE + SOFT，不允许 self-promotion |
| POC-C02 | user HARD 请求与 Runtime LOCKED policy 冲突 | CONTRACT_POLICY_CONFLICT；不静默降级执行 |
| POC-C03 | 两个 user-explicit HARD exact constraints 互斥 | CONTRACT_UNSATISFIABLE |
| POC-C04 | 未识别但明确的 user requirement | canonicalize 为 semantic.requirement + HARD，不静默丢弃 |
| POC-C05 | Runtime/User allowed-path scopes 同时存在 | effective allow scope 使用 intersection，不扩大权限 |
| POC-C06 | 多来源 forbidden path/action | effective deny 使用 union |
| POC-C07 | report-only TaskExecutionAuthority + code_modification work item | CAPABILITY_AUTHORITY_VIOLATION / PLAN_INVALID |
| POC-C08 | Contract 要求 verification/review，Planner 漏 gate | validator 单调注入 reserved runtime-owned gate，并记录 PlanRepair |
| POC-C09 | HARD/LOCKED final leaf = UNVERIFIED | ContractVerdict blocking；Task 不得 SUCCEEDED |
| POC-C10 | final ContractVerdict | task_contract_fingerprint 必须与执行所用 CompiledTaskContract 精确一致 |

## P0-5：Capability / Provider Contract Audit

| PoC | 测试内容 | 必须验证 |
|---|---|---|
| POC-27 | operator tools ∩ A-SWE Node tools | A-SWE 不会扩大 SubagentConfig 权限 |
| POC-28 | Provider 声明 required tool 但 backend inventory 缺失 | preflight fail，不进入 Team |
| POC-28A | 同名 config tool 覆盖标准 read_file | expected ToolConfig.use 不匹配 → PROVIDER_TOOL_IDENTITY_MISMATCH |
| POC-28B | ToolConfig.name 与 loaded tool.name 不一致 | inventory 使用 loaded exposed name，并记录 drift/warning |
| POC-28C | write_file 因 model budget 被 clone/改 description | implementation_id 仍稳定为 config:ToolConfig.use |
| POC-29 | 安装 A-SWE assembly observer | executor.assembly_descriptor 非空且 fingerprint 可读取 |
| POC-30 | runtime policy 在首轮前移除 required eager tool | NodeToolPolicy synthetic short-circuit；LLM provider 零调用；SubagentResult=FAILED |
| POC-31 | preferred skill enabled 但未 activation | 不误报 skill-used，也不把 Node 判失败 |
| POC-32 | authorization deny resolved model | direct-executor Adapter 在 LLM 调用前 strict fail，不静默 fallback |
| POC-33 | ordinary DeerFlow run | A-SWE attestation extension 不改变普通 Agent execution semantics |
| POC-34 | middleware-declared tool 不在 Node allowlist | model-visible schema 被 ASWENodeToolPolicyMiddleware 移除 |
| POC-35 | unauthorized tool call 绕过 model visibility | tool-call boundary 再次 deny |
| POC-36 | generated tool_search / describe_skill | 只允许 adapter-classified infrastructure helper |
| POC-37 | A-SWE managed run policy store miss | fail closed |
| POC-38 | Node cancellation / timeout | NodeExecutionBindingStore entry 一定 cleanup |
| POC-39 | optional bash 未选择 | READ Node 不因 Provider optional declaration 被升级 WRITE |
| POC-40 | optional bash 被选择 | WorkspaceAccess 自动升级 WRITE 且 fingerprint 改变 |
| POC-41 | required tool 被标记 deferred MCP | P1 compile-time reject：hard required tool 必须 eager |
| POC-42 | Skill activation 后收窄掉 required tool | 下一次 model call synthetic short-circuit；LLM 不再调用 |
| POC-43 | Node admission mismatch | terminal AIMessage 带 A-SWE marker；SubagentResult=FAILED；Adapter 精确映射 PROVIDER_ASSEMBLY_MISMATCH |
| POC-44 | NodeToolPolicy ordinary run store miss | pass-through；普通 DeerFlow 不受影响 |
| POC-45 | planning 后新增无关 Tool | inventory drift 被记录，但 Node 仍可 PREPARED |
| POC-46 | planning 后 required Tool 被移除 | prepare_node 返回 BACKEND_PREFLIGHT_STALE，LLM/Workspace 零副作用 |
| POC-47 | operator timeout/max_turns 收紧但仍可满足 | effective policy 单调收窄 |
| POC-48 | prepare 后 config 热更新 | execute_prepared 仍使用 prepare 阶段 pinned AppConfig snapshot |
| POC-49 | live authorization 在 execution 中改变 | runtime auth gate 生效，不依赖 stale planning verdict |
| POC-50 | Provider stale 但另一个 Provider 可用 | P1 不隐式切换，显式 fail/replan |
| POC-51 | 同一 Coder Provider 顺序执行两个 Node | 第二个 Node 不自动继承第一个模型上下文 |
| POC-52 | Node B 依赖 Node A | 只有显式 NodeHandoff / Workspace evidence 进入 B |
| POC-53 | 单 Provider 覆盖全部 WorkItem | TeamSpec 单成员，但 DAG Node 数与语义边界保持不变 |
| POC-54 | bash 执行但只改变 .venv / cache | scanner 可无 observed paths，但 mutation_evidence=UNKNOWN，revision 推进 |
| POC-55 | WRITE Node 在任何 mutating tool 前失败 | mutation_evidence=PROVEN_NONE，可按 Scheduler-owned retry rules 重试 |
| POC-56 | failed bash Node 且 scanner 显示 no changes | 不自动 retry；按 DIRTY_WRITE_FAILURE / UNKNOWN mutation fail closed |
| POC-57 | snapshot truncated 且无 observed changed path | changed_paths_complete=false；mutation_evidence=UNKNOWN；revision 推进 |
| POC-58 | Handoff via ParentContextSnapshot | 禁止作为 A-SWE 实现路径；compat test 确认正式路径不依赖该 carrier |
| POC-59 | 多轮 Node tool loop + summarization | request-scoped Handoff 每轮仍存在，但不进入 child state / compaction |
| POC-60 | task objective 与 dependency handoff 同时存在 | 两者为独立 HumanMessage provenance / trust domain |
| POC-61 | ExtensionData task scope 结束 | A-SWE evidence 仍可被 downstream Node resolve |
| POC-62 | DeerFlow RunEventStore backend=memory | A-SWE EvidenceStore durability 不随其消失 |
| POC-63 | Evidence 写入在 rename 前 crash | final path 不出现半写 JSON；orphan temp 可清理 |
| POC-64 | Evidence 文件被篡改/损坏 | get() full SHA-256 mismatch → typed integrity failure |
| POC-65 | EvidenceCreated trace event | event 携带 scope-aware EvidenceRef/TaskEvidenceRef metadata，不复制大 payload |
| POC-66 | A-SWE execution run_id | 符合 DeerFlow JsonlRunEventStore safe-id regex；无冒号/路径字符；并可创建 thread workspace |
| POC-70 | raw external user id 含 unsafe chars | 不直接作为 DeerFlow filesystem user_id |
| POC-71 | receipt tool_call_id 为空 | ReceiptRef 仍通过 ledger EvidenceRef + ledger_index 稳定解析 |
| POC-72 | 两个 execution 复用同一 tool_call_id | execution-owned ledger artifact 隔离，无跨 execution 歧义 |
| POC-73 | receipt short hash 字段相同 | 不作为 durable identity；EvidenceStore full SHA-256 保护 ledger integrity |
| POC-74 | receipt compaction 后 rN 变化 | 已持久化 citing-turn/terminal ledger index 不重新解释 |

## P0-6：NodeHandoff / Cross-Node Context Audit

| PoC | 测试内容 | 必须验证 |
|---|---|---|
| POC-H01 | Agent 自报修改不存在文件 | changed_paths 不采信 self-report |
| POC-H02 | WRITE Node 成功修改文件 | generation +1，Handoff revision 匹配新 state |
| POC-H03 | READ Node | generation 不变化 |
| POC-H04 | 上游 receipt 传给下游 | 只作为 historical reference，不进入下游 own receipts |
| POC-H05 | self_report 含 framework/injection tag | 下游模型看到 neutralized data |
| POC-H06 | hidden handoff message | 显式 sanitizer 生效，不依赖 generic user-input middleware |
| POC-H07 | 两个并行 parent handoff | canonical order + provenance preserved |
| POC-H08 | handoff revision 落后 current workspace | 标记 stale，不静默当 current fact |
| POC-H09 | verification failure → repair | 使用 typed RepairFeedback，不只拼自由文本 |
| POC-H10 | handoff 超预算 | prose truncate，evidence/revision 不丢失 |
| POC-H11 | A-SWE managed run | middleware 注入 static authority SystemMessage + hidden handoff HumanMessage |
| POC-H12 | ordinary DeerFlow run | ASWEHandoffContextMiddleware pass-through |
| POC-H13 | operator prompt_overlay 已配置 | A-SWE handoff 不修改 overlay 内容/顺序 |
| POC-H14 | handoff 中含 `<system>` / fake framework tag | renderer neutralize，不能逃逸到 authority channel |
| POC-H15 | 多轮 model call | handoff request-scoped 重投影，不写入 graph state/不重复累积 |
| POC-H16 | 两个 Node 都有 r3 receipt | ReceiptRef 通过 receipt-ledger EvidenceRef + ledger_index 消除歧义 |
| POC-H16A | 同一 execution compaction 后 receipt renumber | durable ref 仍由 immutable receipt ledger + ledger_index 解析，display rN 不作主键 |
| POC-H16B | receipt tool_call_id 为空 | ReceiptRef 仍通过 ledger EvidenceRef + ledger_index 稳定解析 |
| POC-H16C | 两个 execution 复用同一 tool_call_id | execution-owned ledger artifact 隔离，无跨 execution 歧义 |
| POC-H16D | receipt short hash 相同 | short hash 不作 durable identity；EvidenceStore full SHA-256 保护 ledger integrity |
| POC-H16E | ledger persistence failure | 不发布 child ReceiptRef / success Handoff，EVIDENCE_FINALIZATION_FAILURE |
| POC-H17 | Node retry attempt 2 成功 | Handoff 只引用 terminal attempt 2 evidence |
| POC-H18 | old attempt evidence | Trace 可查，但不自动进入新 Handoff |
| POC-H19 | Runtime restart 后读 Demo trace | file-backed EvidenceRef 仍可 resolve |
| POC-H20 | Agent 修改 workspace | 无法修改 workspace 外 Runtime evidence store |
| POC-H21 | Node 等待 WRITE lock 期间 revision 改变 | lock granted 后重新分类 handoff staleness |
| POC-H22 | 两个并行 READ Node | shared READ lock 下 execution_workspace_revision 保持一致 |
| POC-H23 | WRITE Node 执行 | pre revision 冻结，成功 mutation 后只发布一个新 post revision |
| POC-H24 | completed report 引用有效 `[rN tool]` | DeerFlow verifier 映射 citation_resolved=true |
| POC-H25 | report 引用 unknown / failed / wrong-anchor receipt | citation_resolved=false，写 Handoff warning |
| POC-H26 | action-looking report 无 receipt citation | no_citation_claims=true；不误当 acceptance failure |
| POC-H27 | receipts disabled / harvest None | receipt verdict absent，不伪造 verdict |
| POC-H28 | 长 report 尾部含 citation | 对完整 report 先 verify，再做 Handoff truncation |
| POC-H29 | Node A/B 顺序修改不同文件 | B 的 NodeWorkspaceDelta 不包含 A-only change |
| POC-H30 | Node B 再次修改 A 已改过的同一文件 | B 的 before/after delta 仍能归属该修改 |
| POC-H31 | Workspace snapshot truncated | changed_paths_complete=false + warning；失败 WRITE 不 retry |
| POC-H32 | truncated mutating attempt 无 observed files | WorkspaceRevision 仍保守 +1 |
| POC-H33 | binary/sensitive/large changed file | path mutation 仍记录，diff content 可 unavailable |
| POC-H34 | Handoff System/Human injection | hidden HumanMessage provenance=aswe_handoff_context；pre-coalescing SystemMessage 可识别 A-SWE producer |
| POC-H34A | SystemMessageCoalescing 后 provider-bound request | merged SystemMessage reserved provenance=system_coalescing，不误断言为 A-SWE producer |
| POC-H35 | caller 伪造 DeerFlow provenance keys | host sanitization 不允许其伪装为 A-SWE injected context |
| POC-H36 | WRITE 修改成功但 acceptance fail | WorkspaceRevision 已 +1，Repair 观察新 revision |
| POC-H37 | WRITE execution fail 且留下 mutation | 发布 dirty post revision 后 fail closed |
| POC-H38 | WRITE complete 且无 mutation、snapshot complete | pre/post revision 相同 |
| POC-H39 | AcceptanceVerdict EvidenceRef | revision/fingerprint 指向 post-attempt state |
| POC-H40 | NodeWorkspaceDelta | 同时记录 before/after generation |
| POC-H41 | 下游只有 Acceptance EvidenceRef | renderer 输出 compact hold/fail/UNVERIFIED 摘要而非 opaque id |
| POC-H42 | acceptance evidence revision < current | projection 显式 historical，不声称 current holds |
| POC-H43 | 完整 pytest log 很大 | 默认 Handoff 只渲染 bounded verification summary + EvidenceRef |
| POC-H44 | criterion 含换行/伪造 checklist | projection collapse + neutralize，不能伪造 Runtime verdict line |
| POC-H45 | receipt evidence stale by workspace revision | 保留“调用曾发生”事实，但不升级为 current-state proof |
| POC-H46 | transient clean WRITE failure | 同 Node 新 RETRY attempt；DAG 不变 |
| POC-H47 | own acceptance failure after mutation | 同 Write Node 新 REPAIR attempt，current revision 不回滚 |
| POC-H48 | downstream verification fail | RepairFeedback 精确绑定 source attempt + target writer attempt |
| POC-H49 | repair succeeded | Verification 同 Node 以 REVERIFY 新 attempt 执行，旧 verdict 不复用 |
| POC-H50 | 两个 writer 都可能致因 | P1 不自动 repair，fail / explicit restart path |
| POC-H51 | repair 需要额外 Tool/Capability | 不扩权，判 plan invalidated / unsupported repair |
| POC-H52 | post-lock handoff projection | NodeExecutionInvocation fingerprint 固定且传入 execute_prepared |
| POC-H53 | 两个并发 A-SWE Node | exact run_id 分别读取自己的 immutable binding，无 context 串线 |
| POC-H54 | aswe- run_id 但 binding 丢失 | managed run fail closed |
| POC-H55 | ordinary DeerFlow run 无 binding | 两个 A-SWE middleware 都 pass-through |
| POC-H56 | 多轮 model call | middleware 不读 Git/EvidenceStore，只复用 immutable rendered context |
| POC-H57 | cancellation / timeout | finally 删除 execution binding，无 store leak |
| POC-H58 | Scheduler loop 写 binding、isolated subagent loop 读 | 无 cross-loop lock error / context 串线 |
| POC-H59 | 并发 middleware outcome update | snapshot consistency，锁内无 await/I/O |
| POC-H60 | 强制触发 subagent summarization | 每次 model request 仍有且只有一份 A-SWE dependency projection |
| POC-H61 | summarization 后检查 child graph state | Handoff projection 未持久写入 messages state |
| POC-H62 | SystemMessageCoalescing | A-SWE authority note 与 DeerFlow system blocks 合并后仍保持单一 leading system message |
| POC-H63 | Tester 运行 pytest 产生 ignored cache | WorkspaceRevision 可变化，但 RepositoryStateDigest 不变，verification 可继续 |
| POC-H64 | Tester 修改 tracked source 后 tests pass | REPOSITORY_MUTATION_AUTHORITY_VIOLATION，不能接受 |
| POC-H65 | Tester 创建 non-ignored source file | RepositoryStateDigest 改变，fail closed |
| POC-H66 | verifier 自身污染 repo | 不生成指向 writer 的 RepairFeedback |
| POC-H67 | Reviewer/Discovery 意外改 repo | 同一 semantic mutation invariant fail closed |
| POC-H68 | completed + turn_capped + 无 acceptance | logical Node 不成功；proven-clean READ 可 bounded retry |
| POC-H69 | completed + token_capped + 全部 deterministic acceptance holds | success + EXECUTION_CAPPED_BUT_ACCEPTED warning |
| POC-H70 | capped WRITE 已 mutation 且无完整 proof | 不 blind retry；fail closed |
| POC-H71 | mandatory REVIEW + loop_capped | review gate unsatisfied |
| POC-H72 | capped run 未被接受 | partial result/evidence 保留，但不生成 normal success Handoff |
| POC-H73 | capped run acceptance 含 UNVERIFIED | 不允许提升为 success |
| POC-H74 | capped clean retry | new attempt/evidence；Runtime 不自动提高 operator guard budget |
| POC-H75 | clean Reviewer 最终调用 submit_review_verdict(APPROVE) | structured verdict 入 EvidenceStore，review gate satisfied |
| POC-H76 | Reviewer 自由文本说 approved 但未调用 submit tool | review gate unsatisfied |
| POC-H77 | submit_review_verdict schema invalid | direct-return Tool error → execution/review failure |
| POC-H78 | Reviewer REQUEST_CHANGES | REVIEW_GATE_REJECTED；保留 findings，不自动修代码 |
| POC-H79 | Reviewer UNVERIFIED | REVIEW_GATE_UNVERIFIED |
| POC-H80 | Reviewer capped 后曾产生 review prose | 不接受旧 prose / 非终态 verdict |
| POC-H81 | Reviewer verdict 伪造 revision/execution id | Tool/Runtime 覆盖并验证 authoritative envelope |
| POC-H82 | ordinary DeerFlow run | 不暴露 submit_review_verdict |
| POC-H83 | REVIEW Node 修改 Git-visible repo 后 APPROVE | mutation authority violation 优先，review 不通过 |
| POC-H84 | direct-return Review JSON 含 action-like words | 不运行普通 prose citation verifier，不误报 no_citation_claims |
| POC-H85 | Review APPROVE 无 basis receipts | REVIEW_GATE_UNVERIFIED |
| POC-H86 | Review 引用 citing-turn r3，后续 compaction renumber | `SubagentResult.tool_receipts` 保留原 citing-turn ledger；解析到同一 ledger index |
| POC-H87 | Review basis 引用 failed / unknown receipt | evidence_resolved=false，gate unsatisfied |
| POC-H88 | Review basis 只引用 submit_review_verdict 自身 | 不算 inspection evidence |
| POC-H89 | valid basis receipt | display rN 转 durable ReceiptRef 后入 ReviewVerdict |

## P0-7：Retry / Repair / Failure Propagation Audit

> R69–R73 specifically cover the P0-7.1 deterministic-verification sandbox profile；其余 R-series 覆盖 execution lifecycle、retry/repair、dirty failure 与 dispatch-race semantics。

| PoC | 测试内容 | 必须验证 |
|---|---|---|
| POC-R01 | normal execution result 先 terminal、finally 延迟 | Workspace lock 直到 join/quiescence 后才释放 |
| POC-R02 | execute_async + completion join | returned NodeExecutionResult 时 underlying Future 已 done |
| POC-R03 | cancel 长运行 tool | cancel_node 不在 signal 时返回；等待 tool/stream cleanup 后返回 |
| POC-R04 | timeout execution | TIMED_OUT/FAILED mapping 之后无 executor-owned late workspace mutation |
| POC-R05 | terminal background result + delayed sandbox release | 下一个 WRITE Node 不提前启动 |
| POC-R06 | A-SWE execution_id 与 DeerFlow background id | 显式 mapping；provider/external id 不作为 registry ownership key |
| POC-R07 | background registry cleanup | 只在 completion join 后 cleanup，不删除仍 unwind 的 Future ownership |
| POC-R08 | bash 已进入 handler 后被 cancellation 打断、无 receipt | admission record 存在 → mutation_evidence=UNKNOWN |
| POC-R09 | mutating call 被外层 Guardrail 在 A-SWE gate 前 short-circuit | 无 A-SWE admission；结合 complete snapshot 可保持 clean candidate |
| POC-R10 | A-SWE admission 后内层 middleware short-circuit | 保守 UNKNOWN，不误判 PROVEN_NONE |
| POC-R11 | admitted-tool audit overflow / missing Binding outcome | mutation proof incomplete → UNKNOWN |
| POC-R12 | no receipt + no snapshot change | 单独不足以证明 PROVEN_NONE |
| POC-R13 | cancelled sandbox bash 内部 worker 延迟退出 | completion join 在 worker drain / lease cleanup 完成后才返回 |
| POC-R14 | admitted EXTERNAL_SIDE_EFFECT tool 后 execution failure | 即使 workspace 无变化也不判 PROVEN_NONE / 不自动 retry |
| POC-R15 | ordinary core read-only sandbox Node cancellation | quiescence 后无 executor-owned late workspace worker |
| POC-R16 | attempt transient fail 且 retry budget exists | Node=REMEDIATION_PENDING，下游保持 PENDING 而非 BLOCKED |
| POC-R17 | retry budget耗尽 | Node=FAILED，ordinary descendants 转 BLOCKED |
| POC-R18 | Writer SUCCEEDED 后 verification triggers repair | old accepted_handoff 立即失效；Reviewer 不可提前 READY |
| POC-R19 | Writer 已被普通 downstream SUCCEEDED 消费后再触发 repair | REPAIR_SCOPE_INVALIDATED，P1 fail closed |
| POC-R20 | upstream FAILED 有多层 descendants | descendants BLOCKED，但 Task aggregation 只保留 root failure ownership |
| POC-R21 | local node cancellation | node=CANCELLED；ordinary descendants BLOCKED |
| POC-R22 | task-wide cancellation | running nodes cancel+join；未运行 descendants=CANCELLED，不误标 business failure |
| POC-R23 | Verification failure @ R5，Repair lock 时 Workspace=R6 | 不向 Coder注入旧 failure；先 refresh/reverify 或 REPAIR_FEEDBACK_STALE |
| POC-R24 | own AcceptanceFailure 后 current revision 改变 | 重跑 deterministic acceptance；旧 Feedback 不原地复用 |
| POC-R25 | stale feedback refresh 后仍失败 | 创建新的 EvidenceRef / observed revision / fingerprint，再允许 REPAIR |
| POC-R26 | stale feedback refresh 后已通过 | 旧 RepairFeedback 作废，不执行多余 repair |
| POC-R27 | completed + turn_capped | terminal=COMPLETED，completeness=CAPPED，不自动等价 logical success |
| POC-R28 | failed + turn_capped | terminal=FAILED，completeness=CAPPED，保留 cap failure 语义 |
| POC-R29 | capacity reject / queue timeout | FAILED + admission_failure=true → failure_class=ADMISSION |
| POC-R30 | NodeToolPolicy synthetic failure | FAILED + A-SWE marker → POLICY_OR_ASSEMBLY，不误归类 LLM execution failure |
| POC-R31 | direct executor timeout | terminal=TIMED_OUT → failure_class=TIMEOUT |
| POC-R32 | direct executor cancellation | terminal=CANCELLED → failure_class=CANCELLED |
| POC-R33 | DeerFlow 新增未知 status / stop_reason | Adapter BACKEND_CONTRACT_MISMATCH，compat test fail |
| POC-R34 | result 先 terminal、completion signal 未 set | Scheduler 不释放 Workspace lock |
| POC-R35 | request_cancel 使 Future 先 cancelled | join 仍等待 independent completion signal |
| POC-R36 | timeout 触发 inner cancellation | signal 只在 sandbox lease + capacity unwind 后 set |
| POC-R37 | Future done-callback 已移除 `_background_futures` | completion signal 仍可 join 并取得 terminal result |
| POC-R38 | completion signal missing/corrupt | WorkspaceSession=QUARANTINED；后续 Node 零 dispatch |
| POC-R39 | cleanup_background_task | 只在 completion consumed 后移除 result/completion record |
| POC-R40 | ordinary DeerFlow task_tool | compatibility patch 不改变现有 polling/cancellation semantics |
| POC-R41 | capacity queue 中 overall timeout | TIMED_OUT + started_at=None → PRE_START |
| POC-R42 | capacity SubagentCapacityTimeout | FAILED + admission_failure=true + PRE_START |
| POC-R43 | slot acquired 后 execution timeout | TIMED_OUT + started_at!=None → STARTED，进入 mutation classification |
| POC-R44 | PRE_START timeout + snapshot truncated | 仍可由 execution-phase proof判 backend PROVEN_NONE |
| POC-R45 | started_at=None 但出现 admitted tool record | BACKEND_CONTRACT_MISMATCH，fail closed |
| POC-R46 | user cancel while queued | CANCELLED + PRE_START；workspace safe，但不自动 retry user cancellation |
| POC-R47 | AIO release_command_scope cleanup 内部失败 | completion 仍可能完成；Runtime 不声称 remote shell cleanup 被严格证明 |
| POC-R48 | AIO healthy provider.release | container 进入 warm pool且仍运行；quiescence attestation 不写“container stopped” |
| POC-R49 | Verification exact `pytest -q` | BashCommandPolicy allow；前台命令完成后进入 normal evidence path |
| POC-R50 | Agent 将允许命令改为 `pytest -q & ...` | exact command mismatch，pre-tool fail closed |
| POC-R51 | `nohup` / `setsid` / daemon / detached workflow | P1 contract reject / UNSUPPORTED_BACKGROUND_EXECUTION |
| POC-R52 | implementation Node 无 Runtime-approved bash command | bash denied，即使 Provider generic config 原本暴露 bash |
| POC-R53 | external MCP submitted async side effect | executor quiescence 不升级为 distributed side-effect quiescence；no auto retry |
| POC-R54 | backend 已 saturated 时 WRITE ready | snapshot 只延迟/提示，不声明已 reservation |
| POC-R55 | WRITE 已拿锁后等待 native capacity | 后续 Workspace Node 不越过锁；记录 backend_capacity_wait_after_workspace_lock |
| POC-R56 | 多个 A-SWE ready Node | max_inflight_node_executions 不超过 configured backend capacity |
| POC-R57 | external DeerFlow traffic 占满 capacity | A-SWE correctness 不变；可能 lock hoarding，但无 ABBA deadlock |
| POC-R58 | tracked modify/delete + nonignored untracked | temp-index working_tree_oid 改变，real index 不变 |
| POC-R59 | ignored cache only | working_tree_oid 不变，但 WorkspaceRevision 可因 physical evidence变化 |
| POC-R60 | Node A/B 顺序修改 | tree-to-tree diff 只归属当前 attempt 的 repository_changed_paths |
| POC-R61 | dirty submodule、gitlink SHA 不变 | bootstrap/feature gate 拒绝，不误判 clean |
| POC-R62 | sparse checkout active | P1 bootstrap fail with explicit unsupported feature |
| POC-R63 | semantic READ_ONLY Tester 改 tracked source | pre/post working_tree_oid 不同 → mutation authority violation |
| POC-R64 | result 先 COMPLETED、cleanup 尾部跨过 timeout | result 保持 COMPLETED，同时 outer_timeout_fired=true |
| POC-R65 | timeout 在 terminal result 前发生 | TIMED_OUT；outer_timeout_fired=true |
| POC-R66 | COMPLETED + deadline overrun + acceptance holds | 可 logical accept，但 Trace 标 BACKEND_LIFECYCLE_DEADLINE_OVERRUN |
| POC-R67 | completion outcome 丢失 timeout marker | compatibility test fail，不允许仅从 result.status 猜 |
| POC-R68 | acceptance_criteria=None 但 Agent 调 bash | SubagentResult.bash_executions=None；不能事后补 tests_passed |
| POC-R69 | LocalSandbox exact pytest | shell_persistent=false；native tests_passed checker 可产生 holds=true |
| POC-R70 | AioSandbox exact pytest | shell_persistent=true；native tests_passed checker 必须 UNVERIFIED |
| POC-R71 | custom sandbox shell semantics=None | native tests_passed fail closed为 UNVERIFIED |
| POC-R72 | VerificationCommand 与 BashCommandPolicy command 不一致 | ACCEPTANCE_COMMAND_POLICY_MISMATCH，compile-time fail |
| POC-R73 | verification Node required deerflow_tests_passed_evidence，但 backend 缺失 | Provider preflight fail before Workspace lock / execution |
| POC-R74 | cancel 发生在已 yielded passing pytest ToolMessage 之后 | 已发布 bash evidence 保留；是否接受仍由 terminal/completeness policy决定 |
| POC-R75 | single business Writer + one deterministic failed check | binding singleton → UNIQUE_WRITER，target=current accepted_attempt |
| POC-R76 | single Writer + multiple deterministic failed checks | 每个 check 都绑定同一 singleton Writer → UNIQUE_WRITER |
| POC-R77 | two business Writers → global verification fail | candidate set >1 → MULTI_WRITER；不生成 automatic RepairFeedback |
| POC-R78 | Writer B 是最后执行者但 A/B 都是 candidates | 禁止 last-writer heuristic；仍 MULTI_WRITER |
| POC-R79 | failed stack trace/path 只与 Writer A changed_paths 重合 | path overlap 不缩小 authority candidate set |
| POC-R80 | Tester prose 声称“Writer A caused failure” | self-report 不影响 attribution |
| POC-R81 | 一个 failed check 无 owner，另一个属于 Writer A | NO_OWNER / no automatic repair；不能只修可归因子集 |
| POC-R82 | failed checks 分别绑定 Writer A / Writer B | MULTI_WRITER；不任选其一 |
| POC-R83 | Writer attempt1 clean retry fail、attempt2 accepted，随后 verify fail | target_write_attempt=attempt2 |
| POC-R84 | Tester 修改 tracked repo 后测试失败 | repository_state_unchanged=false → SOURCE_INELIGIBLE；不归因 Writer |
| POC-R85 | verifier backend crash / test command 未形成 deterministic result | SOURCE_INELIGIBLE；不把 execution failure 当 verification failure |
| POC-R86 | verification only UNVERIFIED | 不触发 repair attribution |
| POC-R87 | semantic READ_ONLY Tester 有 physical WRITE lock | 不进入 business writer candidate set |
| POC-R88 | same Provider 执行两个 IMPLEMENTATION logical nodes | 仍是两个 candidates；Provider identity 不合并 ownership |
| POC-R89 | singleton Writer accepted 后，另一个 business Writer 改 Git-visible state，再运行 verifier | SCOPE_INVALIDATED；不沿用旧 singleton attribution |
| POC-R90 | UNIQUE_WRITER attribution 后 Scheduler reopen | Writer reopen + old handoff revoke 先于 READY recomputation，无旧 handoff 解锁窗口 |
| POC-R91 | WRITE execution terminal fail + mutation observed + quiescence proven | Task=FAILED；WorkspaceSession=FROZEN；WorkspaceDisposition=STABLE，不误标 QUARANTINED |
| POC-R92 | WRITE failure mutation UNKNOWN + no legal remediation | task-wide fail closed；剩余 ordinary nodes 不再 dispatch |
| POC-R93 | dirty root failure 时另有 unrelated READY branch | unrelated branch → BLOCKED + TASK_FAIL_CLOSED，不允许继续污染共享状态 |
| POC-R94 | dirty failure 后 planned Reviewer 尚未运行 | Reviewer 不 dispatch；不会为了“诊断”重新打开 Agent execution |
| POC-R95 | FROZEN dirty workspace finalization | 只允许 Runtime-owned repository digest / changeset / evidence aggregation |
| POC-R96 | dirty failed task + Git-visible patch present | TaskResult FAILED + PATCH_PRESENT + RESIDUAL_UNACCEPTED |
| POC-R97 | dirty failed task + only ignored/cache/environment mutation uncertainty | WorkspaceDisposition=STABLE_WITH_UNCERTAINTY；Repository=BASELINE_CLEAN；Patch=NONE |
| POC-R98 | quiescence proof missing after mutating failure | Workspace=QUARANTINED；禁止 workspace-touching finalizer |
| POC-R99 | QUARANTINED 但已有 pre-quarantine RepositoryChangeSet evidence | TaskResult 可引用旧 trusted artifact，但不得声明为重新观察的 current snapshot |
| POC-R100 | Review REQUEST_CHANGES after valid Writer patch | Task FAILED；patch 保留为 RESIDUAL_UNACCEPTED，不伪装 accepted |
| POC-R101 | AcceptanceFailure + mutation + legal deterministic Repair | Node=REMEDIATION_PENDING；不提前 task-wide fail closed |
| POC-R102 | Repair budget exhausted while repository patch remains | Task=FAILED；Workspace→FROZEN；residual patch reported |
| POC-R103 | terminal dirty fail-close state transaction | failing node FAILED + task FAILED + dispatch closed + remaining nodes BLOCKED 原子化 |
| POC-R104 | Task FAILED + 10 blocked descendants | TaskResult.root_failures 只记录真实 root；blocked nodes 作为 propagation consequences |
| POC-R105 | terminal TaskResult final_repository_changeset | 使用 TaskEvidenceRef 指向 immutable artifact，不复制完整 patch bytes |
| POC-R106 | FROZEN finalizer 生成 final repository changeset | 使用 task-scoped TaskEvidenceRef；不伪造 synthetic Node attempt |
| POC-R107 | TaskEvidenceRef 被尝试放入 NodeHandoff | schema/policy reject；task-finalization evidence 不进入 ordinary execution handoff |
| POC-R108 | QUARANTINED task finalization | 不创建声称 current-final 的 TaskEvidenceRef；仅保留 last_trusted attempt EvidenceRef |
| POC-R109 | Writer reopen 时 downstream READY 且尚无 dispatch ticket | accepted authority revoke 后 consumer → PENDING；无 attempt |
| POC-R110 | downstream ticket=PREPARING 时 Writer reopen | ticket REVOKED；prepared result discard；不创建 NodeAttemptRecord |
| POC-R111 | downstream ticket=WAITING_WORKSPACE 时 Writer reopen | lock wait 被取消/退出；ticket REVOKED；无 backend cancel |
| POC-R112 | downstream 已拿 lock、ticket=LOCKED_PRECOMMIT，reopen 先取得 SchedulerStateMutex | ticket REVOKED；consumer commit gate 失败并释放 lock；无 attempt |
| POC-R113 | downstream final dispatch commit 先取得 SchedulerStateMutex | consumer → RUNNING/COMMITTED；Writer reopen → REPAIR_SCOPE_INVALIDATED(ACTIVE_DOWNSTREAM_DISPATCH) |
| POC-R114 | Writer reopen transaction 先于 consumer commit | acceptance_epoch/handoff authority 改变；consumer commit 看到 stamp mismatch，不进入 backend |
| POC-R115 | consumer COMMITTED 但 DeerFlow 尚 PRE_START/排队 capacity | P1 仍视为跨越 dispatch boundary；不 retract attempt 后 repair |
| POC-R116 | ACTIVE_DOWNSTREAM_DISPATCH 导致 task fail-close | 先 close dispatch gate，再 cancel/join committed consumer；全部 quiescent 后才 FROZEN |
| POC-R117 | active consumer cancellation 无法证明 quiescence | Workspace→QUARANTINED；不得继续 repair/final workspace inspection |
| POC-R118 | Writer H1 publish→reopen→H2 publish | acceptance_epoch 1→2→3；旧 epoch=1 ticket 永久失效 |
| POC-R119 | task-wide fail-close 时已有 WAITING/LOCKED_PRECOMMIT tickets | TaskDispatchGate epoch 改变；所有旧 ticket commit fail |
| POC-R120 | prepare_node 期间 ticket 被 revoke | prepare_node 不产生 model/tool/workspace side effect；结果可直接 discard |
| POC-R121 | SchedulerStateMutex 持有期间 | 不等待 Workspace lock/backend capacity/I/O；避免 SchedulerMutex→Workspace 反向等待 |
| POC-R122 | source Verification failure 触发合法 reopen | source Verification→REMEDIATION_PENDING；repair success 后同 Node 用 REVERIFY fresh attempt |
| POC-R123 | running consumer 被 fail-close cancel 且留下 mutation | consumer 不是业务 root failure，但 mutation evidence 影响最终 Workspace/Repository disposition |
| POC-R124 | same WorkspaceRevision R，Writer H1 已 revoke 但 repair 尚未修改 workspace | revision check alone would pass；acceptance_epoch/handoff stamp 必须阻止旧 consumer commit |
| POC-R125 | Writer logical success publication 与 downstream READY recompute 并发 | accepted_attempt/handoff + acceptance_epoch increment + READY recompute 在同一 SchedulerStateMutex transaction |
| POC-R126 | READY Node claim 与 Writer reopen 并发 | READY check + dependency stamps capture + single ticket claim 原子化；ticket 不混合两代 authority |
| POC-R127 | task-wide cancellation 时 Git-visible patch 已存在 | Task=CANCELLED；PatchDisposition=RESIDUAL_UNACCEPTED，不得 ACCEPTED |
| POC-R128 | task-wide cancellation 后无法证明 active execution quiescence | Task=CANCELLED；WorkspaceDisposition=QUARANTINED；不读取 final workspace |

## P0-Final：Design Freeze Static Conformance

| PoC | 测试内容 | 必须验证 |
|---|---|---|
| POC-F01 | active specs schema scan | 每个 authoritative class name 只定义一次；archive 不参与 source-of-truth scan |
| POC-F02 | TaskNode schema | immutable；无 mutable lifecycle / per-node retry-repair policy fields |
| POC-F03 | Planning output boundary | Capability Resolver / DAG Materializer 只消费 ValidatedWorkPlan，不回读 unvalidated WorkPlanProposal |
| POC-F04 | Handoff ownership | accepted_handoff 类型为 NodeHandoff；EvidenceRef 只引用其内部 authority artifacts |
| POC-F05 | TaskDAG fingerprint | VerificationRepairBinding 绑定 structure_fingerprint；final DAG fingerprint 不形成自引用 hash cycle |
| POC-F06 | preparation vs execution identity | prepare_node 只产生 preparation_id；attempt/execution_id/run_id 只在 dispatch commit 分配 |
| POC-F07 | EvidenceStore provenance | put_attempt→EvidenceRef；put_task→TaskEvidenceRef；terminal finalizer 不伪造 Node attempt |
| POC-F08 | TaskResult root failure | 使用 RootFailureRecord + supporting EvidenceRefs，不把 failure 本身伪装成 EvidenceRef |
| POC-F09 | Task success gate | final_contract_verdict 存在且 all_required_satisfied=true 才能 SUCCEEDED |
| POC-F10 | documentation graph | README/master/spec/audit/test 的相对链接全部可解析，active docs 不引用 archived monolith 作为 authority |
| POC-F11 | active Python schema annotation closure | 所有项目内 annotation type 都能解析到唯一 authoritative class；无 dangling type |
| POC-F12 | shared-contract import graph | NodeHandoff 不反向 import runtime module；ExecutionCompleteness 由 shared contract 单一拥有 |
