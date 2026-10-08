# Coding Step 2 — Exhaustive Frozen PoC Audit (R16–R26, R75–R128)

**Audit is complete; implementation exit is NOT automatically passed.**

- Total frozen PoCs audited: **65**
- PASS: **46** · PARTIAL: **14** · GAP: **5**
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
| POC-R21 | PASS | `test_scheduler_local_cancel.py::test_r21_running_local_cancel_joins_without_task_cancel` | 已实现 local cancel + join、下游 BLOCKED；precommit 撤销及 dirty-state failclose 均有测试 |
| POC-R22 | PASS | `test_scheduler_step2_exit.py::test_r22_user_cancel_joins_running_and_cancels_unstarted` | Task user cancel + active join + 未启动节点 CANCELLED |
| POC-R23 | PASS | `test_stale_refresh_canonical.py::test_r23_r25_stale_failure_gets_new_attempt_refs_revision_then_repairs` | 旧反馈不得调度，自动规范 refresh 或严格 fail-close；fresh canonical revision 绑定 |
| POC-R24 | GAP | — | own AcceptanceFailure revision 改变后的确定性 acceptance 重评估未实现 |
| POC-R25 | PASS | `test_stale_refresh_canonical.py::test_r25_refresh_replaces_typed_feedback_with_new_evidence_fingerprint` | 新 REVERIFY attempt、attested receipt / EvidenceRefs / AttributionRef / feedback fingerprint 全部换代 |
| POC-R26 | PASS | `test_stale_refresh_canonical.py::test_r26_refresh_holds_never_dispatches_redundant_writer_repair` | 新 check HOLDS 时撤销旧反馈、零次额外 Writer 执行；不可凭旧 Handoff 假成功，转安全终态 |
| POC-R75 | PASS | `test_strict_canonical_repair.py::test_runtime_canonical_receipt_authorizes_exact_single_writer_reopen` | canonical failure + singleton owner + current accepted attempt |
| POC-R76 | PASS | `test_multiwriter_adversarial.py::test_r76_multiple_failed_checks_same_actual_single_writer` | 两个 failed checks 都由同一实际 business Writer 负责 |
| POC-R77 | PASS | `test_multiwriter_adversarial.py::test_r77_r78_r88_real_two_writers_same_provider_last_writer_not_selected` | 两个真实 business Writer，compiled candidate 非 singleton → MULTI_WRITER |
| POC-R78 | PASS | `test_multiwriter_adversarial.py::test_r77_r78_r88_real_two_writers_same_provider_last_writer_not_selected` | 后执行 Writer B 不成为 last-writer heuristic |
| POC-R79 | PASS | `test_multiwriter_adversarial.py::test_r79_r80_changed_path_or_tester_blame_do_not_override_compiled_owners` | 修改 accepted changed_paths 后仍不缩窄编译归因 scope |
| POC-R80 | PASS | `test_multiwriter_adversarial.py::test_r79_r80_changed_path_or_tester_blame_do_not_override_compiled_owners` | 真实 FakeBackend 测试描述宣称 Writer A 负责，解析器无权采信 |
| POC-R81 | PASS | `test_multiwriter_adversarial.py::test_r81_missing_one_owner_poison_entire_multi_check_verdict` | 一 check 无 owner 时全局 NO_OWNER |
| POC-R82 | PASS | `test_multiwriter_adversarial.py::test_r82_two_checks_bound_to_distinct_actual_writers_remain_ambiguous` | 分属 A/B 的 failed checks 全局 MULTI_WRITER |
| POC-R83 | PASS | `test_multiwriter_adversarial.py::test_r83_current_accepted_retry_attempt_not_historical_attempt_1` | writer retry accepted attempt2 优先于旧 attempt1 |
| POC-R84 | PARTIAL | `test_scheduler_repair.py::test_declared_unchanged_repository_must_match_before_and_after` | 检出前后 Git 指纹不一致；未构建 Tester 实际改 tracked 源码复现 |
| POC-R85 | PARTIAL | `test_scheduler_foundation.py::test_backend_exception_terminalizes_committed_attempt_and_quarantines` | backend crash 终态化已测；验证器无 deterministic verdict 的归因拒绝未串通 |
| POC-R86 | PASS | `test_multiwriter_adversarial.py::test_r86_unverified_only_provides_no_deterministic_repair_owner` | 仅 UNVERIFIED 没有合法自动修复归因 |
| POC-R87 | PASS | `test_multiwriter_adversarial.py::test_r87_physical_write_verifier_does_not_become_business_writer` | physical WRITE verifier 的 semantic WorkKind 不成为 business writer |
| POC-R88 | PASS | `test_multiwriter_adversarial.py::test_r77_r78_r88_real_two_writers_same_provider_last_writer_not_selected` | 两个实际 Writer 共用 Provider 也不合并 |
| POC-R89 | PARTIAL | `test_multiwriter_adversarial.py::test_r89_intervening_changed_business_writer_invalidates_singleton_scope` | 模拟可信 Writer post Git 指纹差异触发 invalidation；真实 Git 变更执行链尚缺 |
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

## P0-A / P0-B incremental notes

- R23/R25/R26 are scenario-specifically PASS with real temporary Git repos and Runtime canonical receipts, but R24 own AcceptanceFailure remains GAP.
- If refreshed checks now HOLDS, outdated REPAIR is cancelled; revoked Writer authority is not resurrected. Runtime fail-closes `REPAIR_SUPERSEDED_REPLAN_REQUIRED` rather than manufacturing a successful Task.
- R76–R83/R86–R88 now exercise actual logical Writers/check sets, except R84/R85/R89 remain PARTIAL for missing real-world mutation/crash chronology evidence.
- Do not infer Step 2 stage acceptance from these incremental results.

## Current authorization

- Runtime Canonical Verifier executes exact argv without shell and signs persisted receipts; this local verifier does not replace the pinned DeerFlow acceptance/command guard integration.
- Typed RepairFeedback includes attempted source, immutable refs, bounded checker obligations and revision stamp; it is not a substitute for delayed-refresh behavior.
- TaskResult enforces contract fingerprint, quarantined prohibition on Git reads and unaccepted residual patch disposition.
- **Final Step-2 gate remains OPEN until every PARTIAL/GAP has direct executable conformance tests and the associated contract semantics are implemented.**

## Next remediation order

1. R24 — own AcceptanceFailure stale deterministic re-evaluation (still GAP); R23/R25/R26 verified.
2. R84/R85/R89 — physical Git mutation, backend crash / attribution, and real intervening Writer chronology remain partial.
3. R100–R103, R123 — Review/Acceptance/repair exhausted and cancelled-mutating consumer outcomes.
4. R119–R121, R125–R126 — true adversarial concurrency barriers (not static claims).
5. Re-run both Python CI versions; independent Step-2 implementation review, and only then close Step 2.
