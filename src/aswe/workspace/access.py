"""Writer-preferred task-local workspace arbitration; no Scheduler decisions."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from aswe.core.contracts import WorkspaceAccess
from .session import WorkspaceLifecycle, WorkspaceSessionStatus


class WorkspaceClosedError(RuntimeError):
    pass


class WorkspaceAccessManager:
    """Shared readers / exclusive writer, with revocable waiting requests.

    Ordinary access is permitted only while the session is READY or ACTIVE.
    close_dispatch() denies new/waiting access; freezing requires no holders.
    """

    def __init__(self, lifecycle: WorkspaceLifecycle):
        self.lifecycle = lifecycle
        self._condition = asyncio.Condition()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0
        self._dispatch_closed = False

    @property
    def active_accesses(self) -> int:
        return self._readers + int(self._writer)

    @property
    def dispatch_closed(self) -> bool:
        return self._dispatch_closed

    def _check_gate(self) -> None:
        if self._dispatch_closed or self.lifecycle.current.status not in (
            WorkspaceSessionStatus.READY, WorkspaceSessionStatus.ACTIVE
        ):
            raise WorkspaceClosedError("workspace ordinary dispatch is closed")

    @asynccontextmanager
    async def access(self, mode: WorkspaceAccess) -> AsyncIterator[None]:
        if not isinstance(mode, WorkspaceAccess):
            mode = WorkspaceAccess(mode)
        granted = False
        async with self._condition:
            self._check_gate()
            if mode is WorkspaceAccess.WRITE:
                self._waiting_writers += 1
                try:
                    while self._writer or self._readers > 0:
                        await self._condition.wait()
                        self._check_gate()
                    self._check_gate()
                    self._writer = True
                    granted = True
                finally:
                    self._waiting_writers -= 1
                    self._condition.notify_all()
            else:
                while self._writer or self._waiting_writers > 0:
                    await self._condition.wait()
                    self._check_gate()
                self._check_gate()
                self._readers += 1
                granted = True
        try:
            yield
        finally:
            if granted:
                async with self._condition:
                    if mode is WorkspaceAccess.WRITE:
                        self._writer = False
                    else:
                        self._readers -= 1
                    self._condition.notify_all()

    async def close_dispatch(self) -> None:
        async with self._condition:
            self._dispatch_closed = True
            self._condition.notify_all()

    async def terminalize(self, *, quiescence_proven: bool) -> WorkspaceSessionStatus:
        """Only a caller that owns backend quiescence proof may request FROZEN."""
        async with self._condition:
            self._dispatch_closed = True
            if quiescence_proven and self.active_accesses:
                raise RuntimeError("cannot freeze while workspace access holders are active")
            target = (WorkspaceSessionStatus.FROZEN if quiescence_proven
                      else WorkspaceSessionStatus.QUARANTINED)
            self.lifecycle.transition(target)
            self._condition.notify_all()
            return target
