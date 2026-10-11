"""Docker cleanup telemetry must be fail-closed, including --rm races.

The physical no-network Docker test is still the independent integration
witness; these tests only pin the deterministic host-side process protocol.
"""
from __future__ import annotations

import asyncio

import pytest

from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend


class Probe:
    def __init__(self, *, rc=0, names=b""):
        self.returncode = rc
        self.names = names

    async def communicate(self):
        return self.names, b""


@pytest.mark.asyncio
async def test_already_removed_is_safe_only_after_two_daemon_observations(monkeypatch):
    calls = []

    async def subprocess(*argv, **kwargs):
        calls.append(argv)
        return Probe(rc=0, names=b"")

    async def fast_sleep(_seconds):
        pass

    monkeypatch.setattr(asyncio, "create_subprocess_exec", subprocess)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    assert await DockerCommandBackend._container_absent_after_rm_failure(
        "aswe-123abc")
    assert len(calls) == 2
    assert all(c == (
        "docker", "container", "ls", "--all",
        "--filter", "name=^/aswe-123abc$",
        "--format", "{{.Names}}",
    ) for c in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("returncode,output", [
    (1, b""),  # Docker daemon unavailable/query rejected
    (0, b"aswe-123abc\n"),  # Container is still present
    (0, b"aswe-other\n"),  # Unexpected output: fail closed too
])
async def test_cleanup_probe_rejects_unproven_absence(
    monkeypatch, returncode, output,
):
    async def subprocess(*argv, **kwargs):
        return Probe(rc=returncode, names=output)

    async def fast_sleep(_seconds):
        pass

    monkeypatch.setattr(asyncio, "create_subprocess_exec", subprocess)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    assert not await DockerCommandBackend._container_absent_after_rm_failure(
        "aswe-123abc")


@pytest.mark.asyncio
async def test_cleanup_probe_rejects_late_reappearance(monkeypatch):
    count = 0

    async def subprocess(*argv, **kwargs):
        nonlocal count
        count += 1
        return Probe(names=b"" if count == 1 else b"aswe-123abc\n")

    async def fast_sleep(_seconds):
        pass

    monkeypatch.setattr(asyncio, "create_subprocess_exec", subprocess)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    assert not await DockerCommandBackend._container_absent_after_rm_failure(
        "aswe-123abc")
    assert count == 2


@pytest.mark.asyncio
async def test_cleanup_probe_daemon_os_error_is_not_assumed_clean(monkeypatch):
    async def subprocess(*argv, **kwargs):
        raise OSError("docker unavailable")

    async def fast_sleep(_seconds):
        pass

    monkeypatch.setattr(asyncio, "create_subprocess_exec", subprocess)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    assert not await DockerCommandBackend._container_absent_after_rm_failure(
        "aswe-123abc")


@pytest.mark.asyncio
@pytest.mark.parametrize("code,drained", [
    ("SWE_COMMAND_INVALID", True),
    ("SWE_DOCKER_CLEANUP_UNVERIFIED", False),
])
async def test_practical_resource_signal_distinguishes_preflight_from_cleanup(
    tmp_path, monkeypatch, code, drained,
):
    from aswe.integrations.deerflow.controlled_swe import SWEExecutionDenied
    backend=DockerCommandBackend(
        workspace_root=tmp_path, image="python@sha256:" + "0"*64)
    async def fail(command, *, timeout, max_output):
        raise SWEExecutionDenied(code)
    monkeypatch.setattr(backend, "_run_command", fail)
    with pytest.raises(SWEExecutionDenied, match=code):
        await backend.run("echo ok",timeout=1,max_output=100)
    assert backend._active_commands == 0
    assert backend.practical_resources_drained is drained


@pytest.mark.asyncio
async def test_cancelled_docker_command_never_proves_drained(tmp_path, monkeypatch):
    backend=DockerCommandBackend(
        workspace_root=tmp_path, image="python@sha256:"+"0"*64)
    async def cancel(command, *, timeout, max_output):
        raise asyncio.CancelledError
    monkeypatch.setattr(backend, "_run_command", cancel)
    with pytest.raises(asyncio.CancelledError):
        await backend.run("sleep 1",timeout=1,max_output=100)
    assert not backend.practical_resources_drained
