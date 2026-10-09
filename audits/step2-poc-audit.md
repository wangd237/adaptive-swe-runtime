# Coding Step 2 — Frozen PoC Conformance Audit

**Result: 65 / 65 frozen Step 2 scenario PoCs PASS. This is a scenario-level conformance conclusion, not a DeerFlow integration certification.**

- Scope: POC-R16–R26 (11) and POC-R75–R128 (54)
- Source of truth: `audits/step2-poc-coverage.json`; frozen criteria: `tests/poc-matrix.md`
- Status: **PASS 65 · PARTIAL 0 · GAP 0**
- Each row names an executable test and the narrow behavior it establishes. FakeBackend remains the controlled execution seam.
- CI gate: Python 3.11/3.13 required on latest PR head, plus Spec/Code consistency review, before merge.
- Do not infer actual DeerFlow Sandbox admission, distributed backend quiescence, production tool permissions, or full agent autonomy from this matrix.

| PoC | Audit | Evidence test | Finding / covered condition |
|---|---|---|---|
| POC-R16 | PASS | `test_scheduler_step2_exit.py::test_r16_r17_retry_then_exhausted_blocks_all_descendants` | 同一逻辑节点 transient-clean 重试；子节点保持等待 |
| POC-R17 | PASS | `test_scheduler_step2_exit.py::test_r16_r17_retry_then_exhausted_blocks_all_descendants` | 预算耗尽后依赖链 BLOCKED |
| POC-R18 | PASS | `test_scheduler_repair.py::test_unique_writer_attribution_is_persisted_and_reopen_revokes_authority` | 旧 Handoff 撤销和 Reviewer 回 PENDING |
| POC-R19 | PASS | `test_scheduler_repair.py::test_successful_nonverification_consumer_forbids_reopen` | 已成功消费的下游使 reopen fail closed |
| POC-R20 | PASS | `test_scheduler_step2_exit.py::test_r104_single_business_root_and_ten_blocked_consequences` | 多层阻塞与 root 独立聚合 |
| POC-R21 | PASS | `test_scheduler_local_cancel.py::test_r21_running_local_cancel_joins_without_task_cancel` | 本地节点取消可 cancel+join；不取消全 Task；下游阻塞；precommit 撤销、dirty fail-close 和终态拒绝专测 |
| POC-R22 | PASS | `test_scheduler_step2_exit.py::test_r22_user_cancel_joins_running_and_cancels_unstarted` | Task user cancel + active join + 未启动节点 CANCELLED |
| POC-R23 | PASS | `test_stale_refresh_canonical.py::test_r23_r25_stale_failure_gets_new_attempt_refs_revision_then_repairs` | 旧反馈不得调度，自动规范 refresh 或严格 fail-close；fresh canonical revision 绑定 |
| POC-R24 | PASS | `test_own_acceptance_refresh.py::test_r24_stale_own_acceptance_failure_reruns_new_attested_check` | 实际发生写入的 Writer own AcceptanceFailure 经独立 canonical verdict 认证；R+1 stale 后重评估并重新生成 verdict/ref，HOLDS 时不执行多余 Repair |
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
| POC-R84 | PASS | `test_attribution_physical_negative.py::test_r84_real_verifier_tracked_mutation_invalidates_stable_git_attribution` | 真实临时 Git 库 Tester 修改 tracked source 后，Git digest 变化，旧 revision 的 canonical check 被拒且任务 fail-closed |
| POC-R85 | PASS | `test_attribution_physical_negative.py::test_r85_backend_crash_cannot_manufacture_a_verification_repair_owner` | 实际 Verifier backend crash 导致 QUARANTINED；即使伪造 deterministic tool proof 亦无法取得 REPAIR owner |
| POC-R86 | PASS | `test_multiwriter_adversarial.py::test_r86_unverified_only_provides_no_deterministic_repair_owner` | 仅 UNVERIFIED 没有合法自动修复归因 |
| POC-R87 | PASS | `test_multiwriter_adversarial.py::test_r87_physical_write_verifier_does_not_become_business_writer` | physical WRITE verifier 的 semantic WorkKind 不成为 business writer |
| POC-R88 | PASS | `test_multiwriter_adversarial.py::test_r77_r78_r88_real_two_writers_same_provider_last_writer_not_selected` | 两个实际 Writer 共用 Provider 也不合并 |
| POC-R89 | PASS | `test_r89_git_chronology.py::test_r89_actual_intervening_business_writer_changes_git_and_invalidates_attribution` | 真实 Git repo Writer B 修改 tracked 文件，Runtime 捕获 post digest；Canonical 归因 SCOPE_INVALIDATED |
| POC-R90 | PASS | `test_scheduler_repair.py::test_unique_writer_attribution_is_persisted_and_reopen_revokes_authority` | reopen authority revoke 先于 READY 重算 |
| POC-R91 | PASS | `test_p0c_terminal.py::test_r91_r94_r95_r103_dirty_writer_failed_reviewer_never_runs_and_patch_is_runtime_only` | 真实 Git tracked 修改 + dirty terminal WRITE、backend quiescent；Task FAILED，FROZEN 且显式 physical attribution complete 时 STABLE，不误 QUARANTINED |
| POC-R92 | PASS | `test_scheduler_foundation.py::test_explicit_transient_with_unknown_mutation_is_not_retryable` | UNKNOWN mutation 关闭 task dispatch |
| POC-R93 | PASS | `test_scheduler_foundation.py::test_task_failclose_revokes_unrelated_ticket_and_blocks_ready_nodes` | 无关 READY 阻止并撤销 ticket |
| POC-R94 | PASS | `test_p0c_terminal.py::test_r91_r94_r95_r103_dirty_writer_failed_reviewer_never_runs_and_patch_is_runtime_only` | Reviewer 被 TASK_FAIL_CLOSED 阻断；无 REVIEW claim，受撤销票无 backend execution，finalization 不重启 agent |
| POC-R95 | PASS | `test_p0c_terminal.py::test_r91_r94_r95_r103_dirty_writer_failed_reviewer_never_runs_and_patch_is_runtime_only` | FROZEN 后仅 deterministic finalizer 获取 Git digest/changeset/TaskEvidenceRef，失效 ticket 不执行其他 Agent |
| POC-R96 | PASS | `test_task_finalization.py::test_failed_task_retains_unaccepted_patch_as_task_evidence` | FAILED + PATCH_PRESENT + RESIDUAL_UNACCEPTED |
| POC-R97 | PASS | `test_finalization_extended.py::test_r97_ignored_cache_mutation_distinct_from_git_patch` | ignored cache side effect 与 Git-clean 正交 |
| POC-R98 | PASS | `test_task_finalization.py::test_quarantine_never_reads_current_git_state` | QUARANTINED 不能检查 final Git |
| POC-R99 | PASS | `test_p0c_terminal.py::test_r99_quarantine_preserves_preexisting_repository_changeset_only` | 实际历史 RepositoryChangeSet EvidenceRef 保留在 last_trusted_evidence_refs；QUARANTINED 不执行任何当前 Git probe |
| POC-R100 | PASS | `test_p0c_terminal.py::test_r100_review_request_changes_preserves_writer_patch_but_not_acceptance` | Runtime-injected typed ReviewGate 产生 source-bound ReviewVerdict(kind REVIEW_VERDICT) + REQUEST_CHANGES；Task FAILED，真实 Git patch 为 RESIDUAL_UNACCEPTED；伪造执行身份被拒绝 |
| POC-R101 | PASS | `test_p0c_terminal.py::test_r101_r102_mutating_own_repair_exhausted_freezes_with_unaccepted_real_patch` | 实际 WRITE mutation + Runtime canonical AcceptanceFailure 合法进入 REMEDIATION_PENDING，首次不 task fail-close |
| POC-R102 | PASS | `test_p0c_terminal.py::test_r101_r102_mutating_own_repair_exhausted_freezes_with_unaccepted_real_patch` | 第二次 actual WRITE/acceptance failed 耗尽 repair_count，Task FAILED，FROZEN，残余 tracked patch TaskEvidenceRef 及最新 Acceptance EvidenceRefs 可追溯 |
| POC-R103 | PASS | `test_p0c_terminal.py::test_r91_r94_r95_r103_dirty_writer_failed_reviewer_never_runs_and_patch_is_runtime_only` | _fail_close_locked 在 SchedulerStateMutex 一次事务中发布 TaskLogicalStatus=FAILED、gate epoch、failing Node 和 blocked nodes；仅 quiescence 后 FROZEN/final TaskResult |
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
| POC-R119 | PASS | `test_p0d_concurrency.py::test_r119_waiting_and_locked_tickets_revoked_by_same_failclose_epoch` | 真实物理 WRITE lock 下 WAITING + LOCKED_PRECOMMIT 同时存在；fail-close 同一 gate epoch 撤销两票且禁止 commit；额外测试 stuck holder timeout → QUARANTINED |
| POC-R120 | PASS | `test_p0d_concurrency.py::test_r120_prepare_barrier_revoked_before_workspace_or_execution` | asyncio.Event 阻塞 prepare_node，期间 fail-close；恢复后无 attempt / execute / Workspace 访问；票据保持 REVOKED |
| POC-R121 | PASS | `test_p0d_concurrency.py::test_r121_blocking_dependency_evidence_io_does_not_hold_state_mutex_or_loop` | threading.Event 同步慢 EvidenceChecker 在 to_thread 中执行；不持 SchedulerStateMutex / 不阻塞 event loop；并发 fail-close 及时发布且旧票不能 commit |
| POC-R122 | PASS | `test_scheduler_repair.py::test_full_single_writer_repair_and_fresh_reverify` | same logical node REPAIR→REVERIFY |
| POC-R123 | PASS | `test_p0c_terminal.py::test_r123_failclose_cancelled_consumer_patch_is_secondary_not_business_root` | 已运行 Consumer 被 scope-invalidated fail-close cancel+join，Node CANCELLED 非业务 root；真实 Git 副作用为 RESIDUAL_UNACCEPTED 并记 secondary diagnostics；不静止则 QUARANTINED |
| POC-R124 | PASS | `test_scheduler_repair.py::test_r118_old_epoch_ticket_never_reauthorizes_after_repair` | same physical revision 下旧 epoch fence |
| POC-R125 | PASS | `test_p0d_concurrency.py::test_r125_acceptance_publication_barrier_never_exposes_partial_stamp` | asyncio.Event 冻结 Writer trusted acceptance；consumer 尚 PENDING 时拒绝 claim；接受公布后 READY + accepted_attempt + accepted_handoff + epoch 原子一致 |
| POC-R126 | PASS | `test_p0d_concurrency.py::test_r126_claim_wins_mutex_before_reopen_revokes_complete_old_epoch_ticket` | SchedulerMutex 排队使 claim 赢得旧完整 stamp，reopen 随即 revoke；反序 reopen 先赢时 claim 不可再用旧 epoch；两路径均无非法 attempt |
| POC-R127 | PASS | `test_task_finalization.py::test_user_cancel_keeps_residual_patch_but_not_business_success` | CANCELLED + residual patch 非 ACCEPTED |
| POC-R128 | PASS | `test_p0c_terminal.py::test_r128_taskwide_user_cancel_uncertain_backend_results_in_quarantine_without_git_probe` | 真实 task-wide cancellation+unquiescent fake backend，TaskResult CANCELLED + QUARANTINED，Git state/change capture 被负测禁用 |

## P0-A — Cancellation and stale deterministic feedback

- R21 differentiates local node cancellation from task-wide cancellation; descendants BLOCKED without turning an unrelated branch into business failure.
- R23–R26 exercise Canonical Verifier refreshed receipt, new EvidenceRef and WorkspaceRevision, updated feedback fingerprint, and skip unnecessary repair when fresh checks HOLDS. Revoked Writer acceptance cannot be silently restored.

## P0-B — Writer attribution and scope

- R76–R89 reject last-Writer, Provider-identity, file-path and model-prose heuristics as ownership authority.
- Verification attribution uses compiled check scope and current accepted Writer attempts. Real tracked-file mutation by an intervening Writer invalidates old deterministic scope.

## P0-C — Task terminal semantics

- R91/R94/R95/R99–R103/R123/R128 cover Repair budget exhausted with residual unaccepted patch, structured Review REQUEST_CHANGES, root failure versus cancelled-consumer consequence, and QUARANTINED restrictions.
- TaskLogicalStatus CLOSED/FAILED/CANCELLED decision is authored by Scheduler, not reverse-engineered from an Agent summary.
- Finalization of QUARANTINED must not inspect current Git state. Historical evidence stays historical; unaccepted patch is never business success.
- Cancellation racing a backend COMPLETED result must not create a second failure root or publish a late accepted Handoff.

## P0-D — Deterministic concurrency

- R119 tests WAITING_WORKSPACE/LOCKED_PRECOMMIT with one fail-close epoch, and waiting for a noncommitted physical holder before FROZEN.
- R120 tests a blocked preparation hook that returns after revocation without allocating an attempt.
- R121 tests blocking EvidenceChecker I/O outside SchedulerStateMutex and outside the event loop; dispatch commit rechecks authority after the I/O.
- R125 tests accepted Writer Handoff/epoch/attempt publication simultaneously with downstream READY visibility.
- R126 tests both Claim-first and Reopen-first interleavings; all old tickets become inert when Writer authority is revoked.

## Interpretation and limitations

Passing the frozen inventory is necessary but insufficient to certify a real DeerFlow integration. Step 3 must compile TaskContract and executable verification command authority from deterministic inputs. Step 4 owns Provider/Capability/DAG compilation; Step 5 owns a pinned DeerFlow adapter and integration Go/No-Go tests. Do not bypass that order.

See `audits/step2-finalization-review.md` for the separate source consistency review and its scope limitations.
