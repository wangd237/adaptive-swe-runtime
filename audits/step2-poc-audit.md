# Coding Step 2 — Exhaustive Frozen PoC Audit (R16–R26, R75–R128)

**Audit is complete; implementation exit is NOT automatically passed.**

- Total frozen PoCs audited: **65**
- PASS: **31** · PARTIAL: **18** · GAP: **16**
- PASS is scenario-specific evidence, not proof of DeerFlow or all acceptance semantics.
- Every PASS/PARTIAL maps to a real test symbol present on the audited branch.
- PARTIAL/GAP are blocking for full Step-2 closeout; do not change Specs to remove them.

| PoC | Audit | Evidence test | Finding / missing condition |
|---|---|---|---|
| POC-R16 | PASS | `test_scheduler_step2_exit.py::test_r16_r17_retry_then_exhausted_blocks_all_descendants` | 同一逻辑节点 transient-clean 重试；子节点保持等待 |
| POC-R17 | PASS | `test_scheduler_step2_exit.py::test_r16_r17_retry_then_exhausted_blocks_all_descendants` | 预算耗尽后依赖链 BLOCKED |
| POC-R18 | PASS | `test_scheduler_repair.py::test_unique_writer_attribution_is_persisted_and_reopen_revokes_authority` | 旧 Handoff 撤销和 Reviewer 回 PENDING |
| POC-R19 | PASS | `test_scheduler_repair.py::test_successful_nonverification_consumer_forbids_reopen` | 已成功消费的下游使 reopen fail closed |
| POC-R20 | PASS | `test_scheduler_step2_exit.py::test_r104_single_business_root_and_ten_blocked_consequences` | 多层阻塞与 root 独立聚合 |
| POC-R21 | GAP | — | 缺少 local-node cancel API 和独立下游传播测试 |
| POC-R22 | PASS | `test_scheduler_step2_exit.py::test_r22_user_cancel_joins_running_and_cancels_unstarted` | Task user cancel + active join + 未启动节点 CANCELLED |
| POC-R23 | PARTIAL | `test_scheduler_repair.py::test_repair_feedback_freshness_checked_under_workspace_lock` | 拒绝过期反馈已验证；refresh/reverify 或 REPAIR_FEEDBACK_STALE 规范处理未闭环 |
| POC-R24 | GAP | — | own AcceptanceFailure revision 改变后的确定性 acceptance 重评估未实现 |
| POC-R25 | GAP | — | 过期反馈刷新后失败必须生成新 refs/fingerprint 的流程未实现 |
| POC-R26 | GAP | — | 过期反馈刷新后已通过则取消 REPAIR 的分支未实现 |
| POC-R75 | PASS | `test_strict_canonical_repair.py::test_runtime_canonical_receipt_authorizes_exact_single_writer_reopen` | canonical failure + singleton owner + current accepted attempt |
| POC-R76 | GAP | — | 缺少多个 failed checks 同属唯一 Writer 的执行反例 |
| POC-R77 | PARTIAL | `test_scheduler_repair.py::test_multi_owner_binding_does_not_pick_one_writer` | 多候选拒绝已测；尚缺两个实际 business Writer 场景 |
| POC-R78 | PARTIAL | `test_scheduler_repair.py::test_multi_owner_binding_does_not_pick_one_writer` | 不选最后 Writer 的规则有结构性保护，缺实际最后执行序列 |
| POC-R79 | GAP | — | 缺少伪造 changed_paths 交集来证明 authority 不被缩小 |
| POC-R80 | PARTIAL | `test_scheduler_repair.py::test_verification_prose_cannot_provide_deterministic_check` | 禁止 prose 推断；尚缺带真实 self-report 的否定对照 |
| POC-R81 | GAP | — | 多个 check 中一项无 owner 的全局 NO_OWNER 行为未单测 |
| POC-R82 | GAP | — | 两个 checks 分属不同 Writer 的 MULTI_WRITER 未单测 |
| POC-R83 | GAP | — | 同一 Writer 重试 attempt2 接受后归因指向 attempt2 未单测 |
| POC-R84 | PARTIAL | `test_scheduler_repair.py::test_declared_unchanged_repository_must_match_before_and_after` | 检出前后 Git 指纹不一致；未构建 Tester 实际改 tracked 源码复现 |
| POC-R85 | PARTIAL | `test_scheduler_foundation.py::test_backend_exception_terminalizes_committed_attempt_and_quarantines` | backend crash 终态化已测；验证器无 deterministic verdict 的归因拒绝未串通 |
| POC-R86 | PARTIAL | `test_scheduler_repair.py::test_verification_prose_cannot_provide_deterministic_check` | 非 deterministic 检查拒绝；UNVERIFIED-only 特例未单测 |
| POC-R87 | GAP | — | physical WRITE 锁上的 semantic READ_ONLY Tester 不作为 business Writer 的专测缺失 |
| POC-R88 | GAP | — | 同一 provider 两个 logical business writers 不合并的专测缺失 |
| POC-R89 | GAP | — | 不同 Writer 中途改变 Git-visible state 的归因 scope invalidated 用例缺失 |
| POC-R90 | PASS | `test_scheduler_repair.py::test_unique_writer_attribution_is_persisted_and_reopen_revokes_authority` | reopen authority revoke 先于 READY 重算 |
| POC-R91 | PARTIAL | `test_finalization_extended.py::test_r97_ignored_cache_mutation_distinct_from_git_patch` | 稳定失败与 patch 维度已建；WRITE 已观察修改的完整结算链需单测 |
| POC-R92 | PASS | `test_scheduler_foundation.py::test_explicit_transient_with_unknown_mutation_is_not_retryable` | UNKNOWN mutation 关闭 task dispatch |
| POC-R93 | PASS | `test_scheduler_foundation.py::test_task_failclose_revokes_unrelated_ticket_and_blocks_ready_nodes` | 无关 READY 阻止并撤销 ticket |
| POC-R94 | PARTIAL | `test_scheduler_foundation.py::test_task_failclose_revokes_unrelated_ticket_and_blocks_ready_nodes` | 阻塞分支已测；专门 Reviewer 不再执行的调用计数用例缺失 |
| POC-R95 | PARTIAL | `test_task_finalization.py::test_failed_task_retains_unaccepted_patch_as_task_evidence` | Runtime-only finalizer + Git artifacts；尚缺禁止 Agent tool 的强负测 |
| POC-R96 | PASS | `test_task_finalization.py::test_failed_task_retains_unaccepted_patch_as_task_evidence` | FAILED + PATCH_PRESENT + RESIDUAL_UNACCEPTED |
| POC-R97 | PASS | `test_finalization_extended.py::test_r97_ignored_cache_mutation_distinct_from_git_patch` | ignored cache side effect 与 Git-clean 正交 |
| POC-R98 | PASS | `test_task_finalization.py::test_quarantine_never_reads_current_git_state` | QUARANTINED 不能检查 final Git |
| POC-R99 | PARTIAL | `test_finalization_extended.py::test_r108_quarantine_preserves_only_verified_historical_attempt_artifacts` | 历史 attempt evidence 可保留；具体 pre-quarantine RepositoryChangeSet 专测缺失 |
| POC-R100 | GAP | — | Review REQUEST_CHANGES 带 residual Git Patch 的任务级检查未实现 |
| POC-R101 | GAP | — | own AcceptanceFailure + physical mutation + 合法 deterministic Repair 仍可保持 remediation 的复杂条件未实现 |
| POC-R102 | GAP | — | 修复预算耗尽且 patch 存在的 root/终态联测未实现 |
| POC-R103 | PARTIAL | `test_scheduler_foundation.py::test_task_failclose_revokes_unrelated_ticket_and_blocks_ready_nodes` | Node/gate/blocks 同 mutex 已测；TaskLogicalStatus 终态事务尚非同步发布 |
| POC-R104 | PASS | `test_scheduler_step2_exit.py::test_r104_single_business_root_and_ten_blocked_consequences` | 1 root + 10 blocked consequences |
| POC-R105 | PASS | `test_task_finalization.py::test_failed_task_retains_unaccepted_patch_as_task_evidence` | TaskEvidenceRef 指向 ChangeSet，不拷贝 patch bytes |
| POC-R106 | PASS | `test_task_finalization.py::test_failed_task_retains_unaccepted_patch_as_task_evidence` | Task scope evidence，无 synthetic Node attempt |
| POC-R107 | PASS | `test_finalization_extended.py::test_r107_task_evidence_cannot_appear_as_node_attempt_handoff` | Pydantic schema 拒绝 TaskEvidenceRef→NodeHandoff |
| POC-R108 | PASS | `test_finalization_extended.py::test_r108_quarantine_preserves_only_verified_historical_attempt_artifacts` | 隔离不读 Git / 仅 last trusted refs |
| POC-R109 | PASS | `test_scheduler_repair.py::test_r109_ready_descendant_without_ticket_becomes_pending` | READY 无 ticket 返回 PENDING |
| POC-R110 | PASS | `test_scheduler_repair.py::test_preparing_ticket_is_revoked_without_precommit_attempt` | PREPARING revoke 无 attempt |
| POC-R111 | PASS | `test_scheduler_repair.py::test_waiting_workspace_ticket_revoked_without_cancel_backend` | WAITING revoke 无 backend cancel |
| POC-R112 | PASS | `test_scheduler_repair.py::test_locked_precommit_ticket_revoked_before_atomic_commit` | LOCKED_PRECOMMIT revoke + commit fail |
| POC-R113 | PASS | `test_scheduler_repair.py::test_consumer_commit_wins_then_reopen_fails_closed_even_prestart` | commit 赢则 scope invalidated |
| POC-R114 | PASS | `test_scheduler_repair.py::test_locked_precommit_ticket_revoked_before_atomic_commit` | reopen 赢则 commit 无 authority |
| POC-R115 | PASS | `test_scheduler_repair.py::test_consumer_commit_wins_then_reopen_fails_closed_even_prestart` | PRE_START 仍视为 COMMITTED |
| POC-R116 | PASS | `test_scheduler_repair.py::test_consumer_commit_wins_then_reopen_fails_closed_even_prestart` | failclose + cancel/join → FROZEN |
| POC-R117 | PASS | `test_scheduler_drain.py::test_cancel_acknowledgement_without_join_forces_quarantine` | 未完成 join 则 QUARANTINED |
| POC-R118 | PASS | `test_scheduler_repair.py::test_r118_old_epoch_ticket_never_reauthorizes_after_repair` | epoch 1→2→3 旧票不能恢复 |
| POC-R119 | PARTIAL | `test_scheduler_foundation.py::test_gate_close_after_claim_before_execution_creates_no_attempt` | gate epoch fence 已测，WAITING+LOCKED 同时并发缺复现 |
| POC-R120 | PARTIAL | `test_scheduler_repair.py::test_preparing_ticket_is_revoked_without_precommit_attempt` | 已有 PREPARING revoke，prepare_node 内阻塞屏障用例未测 |
| POC-R121 | PARTIAL | `test_scheduler_foundation.py::test_concurrent_claims_linearize_at_mutex` | mutex 短事务已审；缺恶意 hook 持锁 I/O/死锁反例 |
| POC-R122 | PASS | `test_scheduler_repair.py::test_full_single_writer_repair_and_fresh_reverify` | same logical node REPAIR→REVERIFY |
| POC-R123 | GAP | — | 被 fail-close cancel 的 consumer 留下副作用后对终态 disposition 的归因未验证 |
| POC-R124 | PASS | `test_scheduler_repair.py::test_r118_old_epoch_ticket_never_reauthorizes_after_repair` | same physical revision 下旧 epoch fence |
| POC-R125 | PARTIAL | `test_scheduler_foundation.py::test_commit_allocates_attempt_only_after_lock_and_publishes_handoff` | accepted + READY under mutex；publish/claim 并发专测缺失 |
| POC-R126 | PARTIAL | `test_scheduler_foundation.py::test_concurrent_claims_linearize_at_mutex` | claim atomicity 已测；与 reopen 同时争抢 ticket/stamps 的压力测试缺失 |
| POC-R127 | PASS | `test_task_finalization.py::test_user_cancel_keeps_residual_patch_but_not_business_success` | CANCELLED + residual patch 非 ACCEPTED |
| POC-R128 | PARTIAL | `test_scheduler_step2_exit.py::test_r128_user_cancel_without_quiescence_keeps_quarantined` | cancel→QUARANTINED 已测；TaskResult 不读 Git 的取消联合测试待补 |

## Current authorization

- Runtime Canonical Verifier executes exact argv without shell and signs persisted receipts; this local verifier does not replace the pinned DeerFlow acceptance/command guard integration.
- Typed RepairFeedback includes attempted source, immutable refs, bounded checker obligations and revision stamp; it is not a substitute for delayed-refresh behavior.
- TaskResult enforces contract fingerprint, quarantined prohibition on Git reads and unaccepted residual patch disposition.
- **Final Step-2 gate remains OPEN until every PARTIAL/GAP has direct executable conformance tests and the associated contract semantics are implemented.**

## Next remediation order

1. R21 / R23–R26 — local cancel and stale Feedback refresh/reverification.
2. R76–R89 — verification attribution ambiguity and chronology adversarial matrix.
3. R100–R103, R123 — Review/Acceptance/repair exhausted and cancelled-mutating consumer outcomes.
4. R119–R121, R125–R126 — true adversarial concurrency barriers (not static claims).
5. Re-run both Python CI versions; independent Step-2 implementation review, and only then close Step 2.
