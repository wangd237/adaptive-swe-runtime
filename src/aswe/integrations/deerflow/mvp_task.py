"""5F-C-B: committed Scheduler -> Native -> independent verification -> MVP report.

MVP is a separate delivery contract, NEVER NodeHandoff/ACCEPTED. The frozen
Scheduler's quiescence fail-close semantics remain intact, and any real
quarantine is surfaced truthfully. This Runner observes a single committed
attempt and runs the canonical verifier WHILE Scheduler owns WorkspaceAccess,
before Scheduler terminalizes the uncertain native execution.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from aswe.core.contracts import EvidenceRef, WorkspaceRevision
from aswe.core.contracts.backend import BackendTerminalStatus, NodeExecutionInvocation
from aswe.evidence import LocalEvidenceStore
from aswe.integrations.deerflow.native_execution import NativeExecutionRecord
from aswe.repository import (
    RepositoryBinding, capture_repository_state, materialize_repository_changeset
)
from aswe.runtime.canonical_verifier import (
    CanonicalCommandPolicy, CanonicalCommandReceipt, CanonicalVerifier,
)
from aswe.runtime.scheduler import SchedulerCore


class MVPIntegrationError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MVPTaskReport:
    task_id: str
    node_id: str
    execution_id: str | None
    attempt: int | None
    native_status: str
    verification_status: str
    verification_check_id: str
    canonical_receipt_ref: EvidenceRef | None
    verified_returncode: int | None
    changed_files: tuple[str, ...]
    git_diff: str
    git_diff_truncated: bool
    workspace_state_fingerprint: str | None
    scheduler_node_status: str
    scheduler_failed: bool
    workspace_status: str
    quiescence_proven: bool
    delivery_status: str
    agent_tool_changed_paths: tuple[str, ...] = ()
    agent_dynamic_command_count: int = 0
    agent_last_dynamic_command_exit_code: int | None = None
    agent_verification_level: str = "not_observed"

    @property
    def tests_passed(self) -> bool:
        return self.verification_status == "passed"

    def to_dict(self) -> dict[str, Any]:
        """Human/API-facing MVP contract; separate from canonical TaskResult."""
        body = asdict(self)
        if self.canonical_receipt_ref is not None:
            body["canonical_receipt_ref"] = self.canonical_receipt_ref.model_dump(mode="json")
        body["tests_passed"] = self.tests_passed
        return body

    def to_json(self) -> str:
        """Stable machine-readable output for CLI/demo consumers."""
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


class _VerificationProbe:
    def __init__(self, *, delegate: Any, task_id: str, repository: RepositoryBinding,
                 verifier: CanonicalVerifier, policy: CanonicalCommandPolicy,
                 isolated_canonical_container: Any | None = None):
        self.delegate = delegate
        self.task_id = task_id
        self.repository = repository
        self.verifier = verifier
        self.policy = policy
        self.isolated_canonical_container = isolated_canonical_container
        self.result: Any | None = None
        self.invocation: NodeExecutionInvocation | None = None
        self.receipt: CanonicalCommandReceipt | None = None
        self.ref: EvidenceRef | None = None
        self.changes = None
        self.post_state = None
        self.verification_status = "not_run"
        self.verification_failure: str | None = None

    async def prepare_node(self, node: Any) -> Any:
        return await self.delegate.prepare_node(node)

    async def cancel_node(self, execution_id: str) -> None:
        await self.delegate.cancel_node(execution_id)

    def release_preparation(self, preparation: Any) -> None:
        closer = getattr(self.delegate, "release_preparation", None)
        if callable(closer):
            closer(preparation)

    async def execute_prepared(self, preparation: Any,
                               invocation: NodeExecutionInvocation) -> Any:
        if self.invocation is not None:
            raise MVPIntegrationError("MVP_EXECUTION_REPLAY")
        if invocation.task_id != self.task_id:
            raise MVPIntegrationError("MVP_TASK_IDENTITY_MISMATCH")
        self.invocation = invocation
        result = await self.delegate.execute_prepared(preparation, invocation)
        self.result = result

        # All host repo observations happen while the Scheduler holds its
        # exclusive workspace access, not in the model, tool or graph.
        self.post_state = await asyncio.to_thread(capture_repository_state, self.repository)
        self.changes = await asyncio.to_thread(materialize_repository_changeset, self.repository)
        if (not self.post_state.head_matches_baseline
                or self.post_state.base_sha != invocation.execution_workspace_revision.base_sha
                or self.changes.working_tree_oid != self.post_state.working_tree_oid):
            raise MVPIntegrationError("MVP_POST_REPOSITORY_DRIFT")

        if getattr(result, "terminal_status", None) is not BackendTerminalStatus.COMPLETED:
            self.verification_status = "not_run"
            return result

        # Run exact compiled command against observed post-mutation revision.
        # NEVER claim that the agent's own bash result equals this verdict.
        old = invocation.execution_workspace_revision
        revision = old.model_copy(update={
            "generation": old.generation + (1 if self.post_state.fingerprint !=
                                              old.repository_state_fingerprint else 0),
            "base_sha": self.post_state.base_sha,
            "head_sha": self.post_state.head_sha,
            "repository_state_fingerprint": self.post_state.fingerprint,
            "dirty": self.post_state.dirty_vs_base,
            "head_matches_baseline": self.post_state.head_matches_baseline,
        })
        try:
            if self.isolated_canonical_container is None:
                ref, receipt = await asyncio.to_thread(
                    self.verifier.run,
                    node_id=invocation.node_id, execution_id=invocation.execution_id,
                    attempt=invocation.attempt, policy=self.policy, revision=revision,
                )
            else:
                ref, receipt = await self.verifier.run_isolated_python(
                    node_id=invocation.node_id, execution_id=invocation.execution_id,
                    attempt=invocation.attempt, policy=self.policy, revision=revision,
                    container=self.isolated_canonical_container,
                )
            checked = await asyncio.to_thread(
                self.verifier.validate, ref,
                node_id=invocation.node_id, execution_id=invocation.execution_id,
                attempt=invocation.attempt, revision=revision,
                check_id=self.policy.check_id,
            )
            if checked != receipt:
                raise MVPIntegrationError("MVP_CANONICAL_RECEIPT_MISMATCH")
            self.ref, self.receipt = ref, receipt
            self.verification_status = {
                "holds": "passed",
                "failed": "failed",
                "unverified": "unverified",
            }.get(receipt.status, "unverified")
        except asyncio.CancelledError:
            raise
        except Exception:
            # No verifier witness is NOT test success. A broken canonical
            # verifier may never be replaced by the LLM's own stdout.
            self.verification_status = "unverified"
            self.verification_failure = "MVP_CANONICAL_VERIFICATION_UNAVAILABLE"
            self.ref, self.receipt = None, None
        return result


class MVPTaskRunner:
    """One committed SWE node with a real Core Scheduler, no fake Handoff.

    The canonical verifier & policy must be instantiated by the Runtime from
    a frozen acceptance compiler; this convenience orchestration does not
    manufacture those authorities from user/model input.
    """

    def __init__(self, *, scheduler: SchedulerCore, backend: Any,
                 repository: RepositoryBinding, verifier: CanonicalVerifier,
                 policy: CanonicalCommandPolicy,
                 execution_evidence_store: LocalEvidenceStore | None = None,
                 max_diff_chars: int = 32_000,
                 isolated_canonical_container: Any | None = None):
        if (not isinstance(scheduler, SchedulerCore)
                or not isinstance(repository, RepositoryBinding)
                or not isinstance(verifier, CanonicalVerifier)
                or not isinstance(policy, CanonicalCommandPolicy)
                or scheduler.task_id != verifier.task_id
                or Path(repository.repository_root).resolve() !=
                   Path(verifier.binding.repository_root).resolve()
                or Path(repository.repository_root).resolve() !=
                   Path(scheduler.workspace.lifecycle.current.workspace_root).resolve()
                or max_diff_chars < 1000 or max_diff_chars > 1_000_000):
            raise MVPIntegrationError("MVP_RUNTIME_AUTHORITY_MISMATCH")
        self.scheduler = scheduler
        self.backend = backend
        self.repository = repository
        self.verifier = verifier
        self.policy = policy
        self.evidence_store = execution_evidence_store
        self.max_diff_chars = max_diff_chars
        if isolated_canonical_container is not None:
            from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend
            if (not isinstance(isolated_canonical_container,DockerCommandBackend)
                    or Path(isolated_canonical_container.workspace_root).resolve() !=
                       Path(repository.repository_root).resolve()):
                raise MVPIntegrationError("MVP_CANONICAL_ISOLATION_UNTRUSTED")
        self.isolated_canonical_container = isolated_canonical_container
        self._ran = False

    async def run_node(self, node_id: str) -> MVPTaskReport:
        if self._ran:
            raise MVPIntegrationError("MVP_TASK_REPLAY")
        self._ran = True
        if node_id not in self.scheduler.nodes:
            raise MVPIntegrationError("MVP_NODE_UNKNOWN")

        probe = _VerificationProbe(
            delegate=self.backend, task_id=self.scheduler.task_id,
            repository=self.repository, verifier=self.verifier, policy=self.policy,
            isolated_canonical_container=self.isolated_canonical_container,
        )
        ticket = await self.scheduler.claim(node_id)
        invocation = await self.scheduler.run_claim(
            ticket, probe,
            # This is explicitly not an Acceptance/Handoff callback.
            accept=None, execution_evidence_store=self.evidence_store,
        )
        if invocation is None or probe.invocation is not invocation:
            raise MVPIntegrationError("MVP_COMMITTED_EXECUTION_MISSING")

        node_state = self.scheduler.states[node_id]
        execution = probe.result
        changes = probe.changes
        if changes is None or probe.post_state is None:
            raise MVPIntegrationError("MVP_GIT_OBSERVATION_MISSING")
        actual_native = getattr(execution, "terminal_status", None)
        terminal = getattr(actual_native, "value", "failed")
        if terminal not in ("completed", "failed", "cancelled", "timed_out"):
            terminal = "failed"

        diff = changes.tracked_diff
        complete_diff = len(diff) <= self.max_diff_chars
        quiescent = bool(getattr(execution, "quiescent", False))
        level = (
            "tests_passed_scheduler_quarantined"
            if probe.verification_status == "passed" and not quiescent
            else "tests_passed_unaccepted"
            if probe.verification_status == "passed"
            else "tests_failed"
            if probe.verification_status == "failed"
            else "unverified"
        )
        return MVPTaskReport(
            task_id=self.scheduler.task_id, node_id=node_id,
            execution_id=invocation.execution_id, attempt=invocation.attempt,
            native_status=terminal,
            verification_status=probe.verification_status,
            verification_check_id=self.policy.check_id,
            canonical_receipt_ref=probe.ref,
            verified_returncode=probe.receipt.returncode if probe.receipt else None,
            changed_files=changes.changed_files,
            git_diff=diff[:self.max_diff_chars],
            git_diff_truncated=not complete_diff,
            workspace_state_fingerprint=probe.post_state.fingerprint,
            scheduler_node_status=node_state.logical_status.value,
            scheduler_failed=self.scheduler.failed,
            workspace_status=self.scheduler.workspace.lifecycle.current.status.value,
            quiescence_proven=quiescent,
            delivery_status=level,
            agent_tool_changed_paths=tuple(
                getattr(getattr(execution,"development_summary",None),
                        "file_tool_changed_paths",())
            ),
            agent_dynamic_command_count=int(
                getattr(getattr(execution,"development_summary",None),
                        "dynamic_command_count",0)
            ),
            agent_last_dynamic_command_exit_code=getattr(
                getattr(execution,"development_summary",None),
                "last_dynamic_command_exit_code",None
            ),
            agent_verification_level=getattr(
                getattr(execution,"development_summary",None),
                "verification_level","not_observed"
            ),
        )
