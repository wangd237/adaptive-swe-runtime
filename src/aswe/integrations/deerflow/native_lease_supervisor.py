"""5F-B2: frozen DeerFlow SandboxLeaseManager scope witness (fail closed).

This does *not* magically attest remote shells or descendant processes.
A provider's release() call or an asyncio Task.done() is insufficient. For
positive quiescence the Runtime must additionally supply an independently
trusted executor-owned process/worker drain probe, scoped to the same run.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Callable, Awaitable

from aswe.core.contracts.backend import NodeExecutionInvocation
from aswe.integrations.deerflow.execution_evidence import QuiescenceObservation


def native_lease_task_id(invocation: NodeExecutionInvocation) -> str:
    """Match a host-chosen native SubagentResult.task_id to a Scheduler run."""
    data = (invocation.task_id + "/" + invocation.node_id + "/"
            + invocation.execution_id + "/" + str(invocation.attempt))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:24]


def native_lease_owner(invocation: NodeExecutionInvocation) -> str:
    return "subagent:" + native_lease_task_id(invocation)


@dataclass(frozen=True)
class _Scope:
    task_id: str
    execution_id: str
    owner_id: str
    native_finished: Callable[[], bool]


class NativeSandboxQuiescenceSupervisor:
    """Runtime-only live provider lease observation and external process gate.

    manager_lookup MUST return the actual upstream SandboxLeaseManager for the
    in-use provider; get_initialized_sandbox_provider is used to avoid
    accidentally creating a new provider and certifying its empty state.
    Local in-process providers may have no native process, but a positive
    process_tree_probe remains mandatory to close this scope. The probe itself
    is outside 5F-B2 trust, and production composition must attest it.
    """

    def __init__(
        self, *,
        initialized_provider: Callable[[], Any | None],
        manager_lookup: Callable[[Any], Any],
        process_tree_probe: Callable[[str, str], Awaitable[bool]] | None = None,
    ):
        self._provider = initialized_provider
        self._manager = manager_lookup
        self._process_probe = process_tree_probe
        self._scopes: dict[str, _Scope] = {}

    @classmethod
    def from_deerflow(cls, *,
                      process_tree_probe: Callable[[str, str], Awaitable[bool]] | None = None):
        try:
            from deerflow.sandbox.sandbox_provider import get_initialized_sandbox_provider
            from deerflow.sandbox.lease import get_sandbox_lease_manager
            from deerflow.sandbox import lease as lease_module
            from aswe.integrations.deerflow.inventory import assert_pinned_deerflow_source
            assert_pinned_deerflow_source(lease_module.__file__)
        except (ImportError, RuntimeError, ValueError) as exc:
            raise RuntimeError("PINNED_SANDBOX_LEASE_UNAVAILABLE") from None
        return cls(
            initialized_provider=get_initialized_sandbox_provider,
            manager_lookup=get_sandbox_lease_manager,
            process_tree_probe=process_tree_probe,
        )

    def register_execution(
        self, invocation: NodeExecutionInvocation, *,
        native_finished: Callable[[], bool],
    ) -> str:
        """Call before native task starts; no model-provided owner accepted."""
        if not isinstance(invocation, NodeExecutionInvocation):
            raise ValueError("NATIVE_LEASE_INVOCATION_UNTRUSTED")
        if (invocation.execution_id in self._scopes
                or not callable(native_finished)):
            raise ValueError("NATIVE_LEASE_SCOPE_REPLAY")
        owner = native_lease_owner(invocation)
        self._scopes[invocation.execution_id] = _Scope(
            task_id=invocation.task_id, execution_id=invocation.execution_id,
            owner_id=owner, native_finished=native_finished,
        )
        return owner

    async def inspect(self, *, task_id: str,
                      execution_id: str) -> QuiescenceObservation:
        scope = self._scopes.get(execution_id)
        finished = False
        released = False
        process_drained = False
        try:
            finished = bool(scope and scope.task_id == task_id
                            and scope.native_finished() is True)
        except Exception:
            finished = False
        if finished:
            try:
                # Absent/uninitialized provider cannot prove the process
                # never acquired another provider (or that a lease drained).
                provider = self._provider()
                if provider is not None:
                    manager = self._manager(provider)
                    released = manager.binding_for(scope.owner_id) is None
            except Exception:
                released = False
            if released and self._process_probe is not None:
                try:
                    process_drained = await self._process_probe(task_id, execution_id) is True
                except Exception:
                    process_drained = False
        complete = finished and released and process_drained
        return QuiescenceObservation(
            task_id=task_id, execution_id=execution_id,
            process_tree_drained=process_drained,
            sandbox_lease_released=released,
            tool_workers_drained=finished,
            complete=complete,
            provenance="runtime-sandbox-supervisor",
        )

    def release_execution(self, execution_id: str) -> None:
        self._scopes.pop(execution_id, None)
