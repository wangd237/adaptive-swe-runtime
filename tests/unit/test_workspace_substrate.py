from __future__ import annotations
import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from aswe.core.contracts import WorkspaceAccess
from aswe.workspace import (
    WorkspaceAccessManager, WorkspaceClosedError, WorkspaceLifecycle,
    WorkspaceSession, WorkspaceSessionStatus, capture_filesystem_snapshot,
    changed_snapshot_paths,
)


def lifecycle(tmp_path):
    session = WorkspaceSession(
        task_id="task-1", thread_id="thread-1", user_id="user-1",
        workspace_root=str(tmp_path.resolve()),
        status=WorkspaceSessionStatus.BOOTSTRAPPING,
    )
    state = WorkspaceLifecycle(session)
    state.mark_ready()
    state.transition(WorkspaceSessionStatus.ACTIVE)
    return state


@pytest.mark.asyncio
async def test_concurrent_readers_and_exclusive_writer(tmp_path):
    lock = WorkspaceAccessManager(lifecycle(tmp_path))
    start = asyncio.Event()
    leave = asyncio.Event()
    readers = []

    async def reader():
        async with lock.access(WorkspaceAccess.READ):
            readers.append(lock.active_accesses)
            start.set()
            await leave.wait()

    a = asyncio.create_task(reader())
    b = asyncio.create_task(reader())
    await start.wait()
    await asyncio.sleep(0)
    assert lock.active_accesses == 2

    writer_started = asyncio.Event()
    async def writer():
        async with lock.access(WorkspaceAccess.WRITE):
            writer_started.set()
            assert lock.active_accesses == 1

    w = asyncio.create_task(writer())
    await asyncio.sleep(0)
    assert not writer_started.is_set()
    leave.set()
    await asyncio.gather(a, b, w)
    assert writer_started.is_set()
    assert lock.active_accesses == 0


@pytest.mark.asyncio
async def test_dispatch_close_revokes_waiter_without_stealing_existing_lock(tmp_path):
    lock = WorkspaceAccessManager(lifecycle(tmp_path))
    async with lock.access(WorkspaceAccess.READ):
        waiter = asyncio.create_task(_try_writer(lock))
        await asyncio.sleep(0)
        assert not waiter.done()
        await lock.close_dispatch()
        with pytest.raises(WorkspaceClosedError):
            await waiter
    assert lock.active_accesses == 0


async def _try_writer(lock):
    async with lock.access(WorkspaceAccess.WRITE):
        return True


@pytest.mark.asyncio
async def test_frozen_requires_no_active_holder_and_quiescence(tmp_path):
    state = lifecycle(tmp_path)
    lock = WorkspaceAccessManager(state)
    async with lock.access(WorkspaceAccess.WRITE):
        with pytest.raises(RuntimeError, match="cannot freeze"):
            await lock.terminalize(quiescence_proven=True)
    assert await lock.terminalize(quiescence_proven=True) is WorkspaceSessionStatus.FROZEN
    state.assert_can_finalize()
    with pytest.raises(WorkspaceClosedError):
        async with lock.access(WorkspaceAccess.READ):
            pass
    state.transition(WorkspaceSessionStatus.CLOSED)


@pytest.mark.asyncio
async def test_quarantined_never_allows_workspace_finalization(tmp_path):
    state = lifecycle(tmp_path)
    lock = WorkspaceAccessManager(state)
    assert await lock.terminalize(quiescence_proven=False) is WorkspaceSessionStatus.QUARANTINED
    with pytest.raises(RuntimeError, match="requires proven FROZEN"):
        state.assert_can_finalize()
    with pytest.raises(WorkspaceClosedError):
        async with lock.access(WorkspaceAccess.READ):
            pass


def test_snapshot_detects_changed_files_and_excludes_cache(tmp_path):
    (tmp_path / "a.py").write_text("first")
    before = capture_filesystem_snapshot(tmp_path)
    (tmp_path / "a.py").write_text("second")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "ignored").write_text("cache")
    after = capture_filesystem_snapshot(tmp_path)
    assert changed_snapshot_paths(before, after) == ("a.py",)
    assert after.complete


def test_snapshot_limits_are_explicitly_incomplete(tmp_path):
    (tmp_path / "large").write_bytes(b"large" * 100)
    snap = capture_filesystem_snapshot(tmp_path, max_file_bytes=10)
    assert not snap.complete
    assert snap.entries[0].kind == "unobserved"


def test_workspace_session_rejects_unsafe_backend_identity(tmp_path):
    with pytest.raises((ValidationError, ValueError)):
        WorkspaceSession(task_id="../../bad", thread_id="thread", user_id="user",
            workspace_root=str(tmp_path.resolve()), status=WorkspaceSessionStatus.BOOTSTRAPPING)


def test_exact_snapshot_limit_is_not_false_truncation(tmp_path):
    (tmp_path / "a").write_text("a")
    (tmp_path / "b").write_text("b")
    exact = capture_filesystem_snapshot(tmp_path, max_paths=2)
    assert exact.complete
    (tmp_path / "c").write_text("c")
    too_many = capture_filesystem_snapshot(tmp_path, max_paths=2)
    assert not too_many.complete


@pytest.mark.asyncio
async def test_cancelled_lock_waiter_leaves_no_stale_writer_preference(tmp_path):
    manager = WorkspaceAccessManager(lifecycle(tmp_path))
    async with manager.access(WorkspaceAccess.READ):
        waiter = asyncio.create_task(_try_writer(manager))
        await asyncio.sleep(0)
        assert not waiter.done()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        async with manager.access(WorkspaceAccess.READ):
            assert manager.active_accesses == 2
    assert manager.active_accesses == 0


def test_public_lifecycle_transition_cannot_bypass_quiescence_gate(tmp_path):
    state = lifecycle(tmp_path)
    with pytest.raises(RuntimeError, match="requires WorkspaceAccessManager"):
        state.transition(WorkspaceSessionStatus.FROZEN)
    with pytest.raises(RuntimeError, match="requires WorkspaceAccessManager"):
        state.transition(WorkspaceSessionStatus.QUARANTINED)
    assert state.current.status is WorkspaceSessionStatus.ACTIVE


def test_terminal_initial_state_cannot_be_forged(tmp_path):
    with pytest.raises(ValueError, match="cannot be forged"):
        WorkspaceLifecycle(WorkspaceSession(
            task_id="task", thread_id="thread", user_id="user",
            workspace_root=str(tmp_path.resolve()), status=WorkspaceSessionStatus.FROZEN,
        ))
