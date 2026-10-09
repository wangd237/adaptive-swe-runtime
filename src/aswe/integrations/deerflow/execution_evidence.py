"""Step 5F: runtime-owned workspace evidence and external quiescence seam.

Neither model output nor an async task's termination can attest absence of
external descendants. The Runtime supplies an independent resource supervisor;
without one, all claims of quiescence remain UNKNOWN. Git/filesystem scans are
performed under the Scheduler's committed WorkspaceAccess lock, *outside*
SchedulerStateMutex and always by the host.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from aswe.core.contracts import AttemptEvidenceKind, EvidenceRef
from aswe.core.contracts.backend import NodeExecutionInvocation
from aswe.core.fingerprint import fingerprint
from aswe.evidence import LocalEvidenceStore
from aswe.repository import RepositoryBinding, RepositoryStateDigest, capture_repository_state
from aswe.workspace.delta import MutationEvidence, NodeWorkspaceDelta, derive_node_workspace_delta
from aswe.workspace.snapshot import FilesystemSnapshot, capture_filesystem_snapshot


class ExecutionEvidenceError(RuntimeError):
    """Safe stable reason, never leak Git stdout/credentials or model output."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class QuiescenceObservation:
    """Verified *by a trusted, external supervisor*, not a model/tool.

    Fields are signed only by trusted composition of the supervisor object;
    the dataclass itself is NOT an attestation or a capability token.
    """
    task_id: str
    execution_id: str
    process_tree_drained: bool
    sandbox_lease_released: bool
    tool_workers_drained: bool
    complete: bool
    provenance: str


class ResourceSupervisor(Protocol):
    async def inspect(self, *, task_id: str, execution_id: str) -> QuiescenceObservation:
        """Check external process/sandbox/task leases AFTER tool admission closed."""


@dataclass(frozen=True)
class ExecutionBaseline:
    invocation: NodeExecutionInvocation
    repository: RepositoryStateDigest
    filesystem: FilesystemSnapshot


@dataclass(frozen=True)
class ExecutionEvidenceReport:
    invocation: NodeExecutionInvocation
    quiescent: bool
    mutation_evidence: MutationEvidence
    evidence_ref: EvidenceRef | None
    tool_receipt_ref: EvidenceRef | None
    workspace_delta: NodeWorkspaceDelta | None
    post_repository: RepositoryStateDigest | None
    unknown_reasons: tuple[str, ...]


class ExecutionEvidenceCollector:
    """Host-only collector: never accept snapshots/revisions from native model.

    In a 5F developer harness, an injected ResourceSupervisor is a test
    double. Production-grade proof requires an independently validated sandbox
    process/lease supervisor in 5G; no default positive supervisor is shipped.
    """

    def __init__(self, *, repository: RepositoryBinding,
                 evidence_store: LocalEvidenceStore,
                 supervisor: ResourceSupervisor | None = None,
                 max_paths: int = 10000):
        self.repository = repository
        self.evidence_store = evidence_store
        self.supervisor = supervisor
        self.max_paths = max_paths
        self.root = Path(repository.repository_root).resolve()
        if max_paths < 1 or not self.root.is_dir():
            raise ValueError("invalid physical workspace scan boundary")
        if evidence_store.root == self.root or evidence_store.root.is_relative_to(self.root):
            raise ValueError("evidence store must be outside the workspace")
        self._claimed: set[str] = set()

    async def begin(self, invocation: NodeExecutionInvocation) -> ExecutionBaseline:
        """Must run *after* Scheduler commit, while holding WorkspaceAccess."""
        if invocation.execution_id in self._claimed:
            raise ExecutionEvidenceError("EVIDENCE_BASELINE_REPLAY")
        self._claimed.add(invocation.execution_id)  # fail-closed even on scan failure
        try:
            repo, fs = await asyncio.gather(
                asyncio.to_thread(capture_repository_state, self.repository),
                asyncio.to_thread(capture_filesystem_snapshot, self.root,
                                  max_paths=self.max_paths),
            )
            expected = invocation.execution_workspace_revision
            if (repo.fingerprint != expected.repository_state_fingerprint
                    or repo.head_sha != expected.head_sha
                    or repo.base_sha != expected.base_sha
                    or not repo.head_matches_baseline):
                raise ExecutionEvidenceError("EVIDENCE_PRECOMMIT_REVISION_DRIFT")
            # An incomplete baseline may still show a change, but will NEVER
            # prove no mutation; this is preserved in the post-attribution.
            return ExecutionBaseline(invocation=invocation, repository=repo,
                                     filesystem=fs)
        except ExecutionEvidenceError:
            raise
        except Exception:
            raise ExecutionEvidenceError("EVIDENCE_BASELINE_CAPTURE_FAILED") from None

    async def finish(self, baseline: ExecutionBaseline, *,
                     guard: object, native_task_done: bool) -> ExecutionEvidenceReport:
        """Trust external resource closure, not coroutine completion/ToolReport.

        On unknown quiescence we still persist *observations* for diagnostics,
        never transform them into proven_no_mutation or an accepted handoff.
        """
        inv = baseline.invocation
        reasons: list[str] = []
        observation = None
        if not native_task_done:
            reasons.append("NATIVE_TASK_NOT_JOINED")
        try:
            lock = guard._call_lock
            with lock:
                pending = len(guard._pending_calls)
                closed = guard.closed
        except Exception:
            pending, closed = -1, False
        if not closed or pending:
            reasons.append("INFLIGHT_TOOL_CALLS_UNQUIESCED")
        if self.supervisor is None:
            reasons.append("EXTERNAL_RESOURCE_SUPERVISOR_MISSING")
        else:
            try:
                observation = await self.supervisor.inspect(
                    task_id=inv.task_id, execution_id=inv.execution_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                reasons.append("EXTERNAL_RESOURCE_SUPERVISOR_FAILED")
            if observation is not None and (
                not isinstance(observation, QuiescenceObservation)
                or observation.task_id != inv.task_id
                or observation.execution_id != inv.execution_id
                or observation.provenance not in ("runtime-sandbox-supervisor",)
                or observation.complete is not True
                or observation.process_tree_drained is not True
                or observation.sandbox_lease_released is not True
                or observation.tool_workers_drained is not True
            ):
                reasons.append("EXTERNAL_RESOURCE_QUIESCENCE_UNPROVEN")
        receipts = ()
        try:
            receipts = guard.receipt_snapshot()
            if not isinstance(receipts, tuple) or any(
                not isinstance(item, dict)
                or item.get("execution_id") != inv.execution_id
                or item.get("status") not in ("completed", "failed", "denied", "cancelled")
                for item in receipts
            ):
                reasons.append("TOOL_RECEIPT_LEDGER_UNATTESTED")
                receipts = ()
        except Exception:
            reasons.append("TOOL_RECEIPT_LEDGER_UNAVAILABLE")
        quiescent = not reasons
        try:
            # Snapshot AFTER resource verification; no subprocess/worktree
            # mutation is allowed between this observation and Scheduler finish.
            post_repo, post_fs = await asyncio.gather(
                asyncio.to_thread(capture_repository_state, self.repository),
                asyncio.to_thread(capture_filesystem_snapshot, self.root,
                                  max_paths=self.max_paths),
            )
            delta, revision = derive_node_workspace_delta(
                node_id=inv.node_id, execution_id=inv.execution_id,
                attempt=inv.attempt,
                before_revision=inv.execution_workspace_revision,
                before_filesystem=baseline.filesystem, after_filesystem=post_fs,
                before_repository=baseline.repository, after_repository=post_repo,
                repository_root=str(self.root),
                # 5D/5E physically prohibit mutating tools. If this condition
                # changes, fail rather than guessing an effect from names.
                mutating_tool_admitted=False,
            )
            if (not post_repo.head_matches_baseline
                    or post_repo.base_sha != baseline.repository.base_sha):
                reasons.append("EVIDENCE_REPOSITORY_BASELINE_BROKEN")
                quiescent = False
            if delta.attribution_truncated:
                reasons.append("EVIDENCE_SCANNER_INCOMPLETE")
            # Frozen Spec 03 §3.2.2: truncation is UNKNOWN even when a
            # subset of changed paths was positively observed. The partial
            # observations remain in the persisted delta, never promoted
            # into complete attempt attribution.
            mutation = (delta.mutation_evidence
                        if quiescent and not delta.attribution_truncated
                        else MutationEvidence.UNKNOWN)
            receipt_ref = self.evidence_store.put_attempt(
                task_id=inv.task_id, node_id=inv.node_id,
                execution_id=inv.execution_id, attempt=inv.attempt,
                kind=AttemptEvidenceKind.TOOL_RECEIPT_LEDGER,
                payload={
                    "authority": "host-toolcallguard-not-model",
                    "task_id": inv.task_id, "execution_id": inv.execution_id,
                    "attempt": inv.attempt,
                    "receipts": receipts,
                    "pending_call_count": pending,
                    "no_native_sandbox_command_receipts": True,
                },
                workspace_revision=revision,
            )
            self.evidence_store.get(receipt_ref)
            evidence = self.evidence_store.put_attempt(
                task_id=inv.task_id, node_id=inv.node_id,
                execution_id=inv.execution_id, attempt=inv.attempt,
                kind=AttemptEvidenceKind.WORKSPACE_CHANGESET,
                payload={
                    "authority": "host-snapshot-not-agent",
                    "task_id": inv.task_id, "node_id": inv.node_id,
                    "execution_id": inv.execution_id, "attempt": inv.attempt,
                    "pre_repository_fingerprint": baseline.repository.fingerprint,
                    "post_repository_fingerprint": post_repo.fingerprint,
                    "pre_filesystem_fingerprint": baseline.filesystem.fingerprint,
                    "post_filesystem_fingerprint": post_fs.fingerprint,
                    "delta": delta.model_dump(mode="json"),
                    "quiescence_proven": quiescent,
                    "mutation_evidence": mutation.value,
                    "unknown_reasons": tuple(reasons),
                },
                workspace_revision=revision,
            )
            # Read-after-write prevents mistaken acceptance if persistence
            # failed or a reference was swapped.
            self.evidence_store.get(evidence)
            return ExecutionEvidenceReport(
                invocation=inv, quiescent=quiescent,
                mutation_evidence=mutation, evidence_ref=evidence,
                tool_receipt_ref=receipt_ref, workspace_delta=delta, post_repository=post_repo,
                unknown_reasons=tuple(reasons),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return ExecutionEvidenceReport(
                invocation=inv, quiescent=False,
                mutation_evidence=MutationEvidence.UNKNOWN,
                evidence_ref=None, tool_receipt_ref=None, workspace_delta=None,
                post_repository=None,
                unknown_reasons=tuple(reasons) + ("EVIDENCE_POST_CAPTURE_FAILED",),
            )
