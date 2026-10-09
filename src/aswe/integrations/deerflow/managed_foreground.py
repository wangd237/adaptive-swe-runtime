"""5F-B trusted, bounded foreground verification-command admission.

NOT DeerFlow's free-form bash tool. Only run an exact command already sealed by
Step 3D AcceptanceCompiler and the selected NodeExecutionPolicy. The process
group is owned and drained by this host runner; no generated text can add an
executable or shell flags. No remote Sandbox or arbitrary daemon proof is made.
"""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import sys
from typing import Callable

from aswe.core.contracts.backend import NodeExecutionInvocation
from aswe.core.contracts import WorkspaceRevision
from aswe.planning.acceptance import CompiledAcceptancePlan, VerificationCommand, _validate_argv
from aswe.providers.policy import NodeExecutionPolicy
from aswe.core.fingerprint import fingerprint
from aswe.repository import RepositoryBinding, capture_repository_state
from aswe.core.ids import validate_safe_id


class ForegroundExecutionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ForegroundReceipt:
    task_id: str
    node_id: str
    execution_id: str
    attempt: int
    command_id: str
    command_fingerprint: str
    policy_fingerprint: str
    command_policy_fingerprint: str
    argv_fingerprint: str
    returncode: int | None
    timed_out: bool
    completion_observed: bool
    process_group_drained: bool
    pre_repository_fingerprint: str
    post_repository_fingerprint: str
    status: str
    stdout_sha256: str
    stderr_sha256: str
    observed_revision: WorkspaceRevision
    # This host observation is NOT a CanonicalVerifier HMAC verdict.
    authority: str = "runtime-foreground-command-observation"


class _Run:
    def __init__(self):
        self.completion = asyncio.Event()
        self.process: asyncio.subprocess.Process | None = None
        self.receipt: ForegroundReceipt | None = None
        self.drain_error = False
        self.finalizer: asyncio.Task[None] | None = None


class ManagedForegroundVerifier:
    """One trusted invocation → one exact, directly executed foreground argv.

    Cancellation/timeout must not be confused with resource cleanup. A
    separate completion signal is set only after the runner's finally/drain.
    The signal remains available after task.cancel(), unlike cancelled
    concurrent.futures.Future handles in upstream DeerFlow.
    """

    def __init__(self, *, task_id: str, plan: CompiledAcceptancePlan,
                 policy: NodeExecutionPolicy, repository: RepositoryBinding,
                 execution_live_checker: Callable[[NodeExecutionInvocation], bool],
                 allow_inline_python_in_tests: bool = False):
        if not isinstance(plan, CompiledAcceptancePlan) or not isinstance(policy, NodeExecutionPolicy):
            raise ForegroundExecutionError("FOREGROUND_COMPILED_AUTHORITY_REQUIRED")
        validate_safe_id(task_id)
        self.task_id = task_id
        self.plan, self.policy, self.repository = plan, policy, repository
        self.execution_live_checker = execution_live_checker
        self.allow_inline_python_in_tests = allow_inline_python_in_tests
        self._runs: dict[str, _Run] = {}
        self._claimed: set[tuple[str, str]] = set()
        self.root = Path(repository.repository_root).resolve()
        if (not self.root.is_dir()
                or policy.acceptance_fingerprint != plan.fingerprint
                or len(plan.commands) != 1  # bounded 5F-B: single command per execution
                or policy.verification_exact_commands != tuple(
                    item.command for item in plan.commands
                )
                or policy.canonical_check_policy_fingerprints != tuple(
                    item.fingerprint for item in plan.canonical_policies
                )):
            raise ForegroundExecutionError("FOREGROUND_POLICY_PLAN_MISMATCH")

    def _trusted(self, invocation: NodeExecutionInvocation) -> bool:
        if not isinstance(invocation, NodeExecutionInvocation):
            return False
        try:
            return self.execution_live_checker(invocation) is True
        except Exception:
            return False

    def _command(self, invocation, *, command_id: str, command: str) -> VerificationCommand:
        if (not self._trusted(invocation) or invocation.node_id != self.policy.node_id
                or invocation.task_id != self.task_id):
            raise ForegroundExecutionError("FOREGROUND_SCHEDULER_COMMIT_REQUIRED")
        selected = next((c for c in self.plan.commands if c.id == command_id), None)
        if (selected is None or selected.command != command
                or command not in self.policy.verification_exact_commands
                or "bash" not in self.policy.allowed_business_tools
                or "bash" in self.policy.denied_tools):
            raise ForegroundExecutionError("FOREGROUND_COMMAND_NOT_ALLOWLISTED")
        _validate_argv(selected.argv)
        executable = Path(selected.argv[0]).name.lower()
        if executable in ("bash", "sh", "zsh", "cmd", "powershell", "pwsh"):
            raise ForegroundExecutionError("FOREGROUND_INTERPRETER_NOT_ALLOWED")
        # Secondary defense only: detached work cannot be proven quiescent by
        # a local process-group drain. The primary authority is still exact,
        # Runtime-compiled command identity.
        if executable in (
            "nohup", "setsid", "disown", "screen", "tmux", "systemctl",
            "service", "docker", "podman", "daemon", "supervisord",
        ):
            raise ForegroundExecutionError("UNSUPPORTED_BACKGROUND_EXECUTION")
        if (not self.allow_inline_python_in_tests
                and any(a in ("-c", "-e", "--eval") for a in selected.argv[1:])):
            raise ForegroundExecutionError("FOREGROUND_INTERPRETER_NOT_ALLOWED")
        return selected

    @staticmethod
    def _group_alive(pid: int) -> bool:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    async def _drain(self, proc: asyncio.subprocess.Process) -> bool:
        if sys.platform == "win32":
            # Host process-group proof requires Unix setsid/killpg.
            return False
        pgid = proc.pid
        if self._group_alive(pgid):
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=1)
        except asyncio.TimeoutError:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=1)
            except asyncio.TimeoutError:
                return False
        # Reap residual same-process-group children, if any. Processes that
        # escaped via setsid are excluded by the trusted foreground policy.
        for _ in range(20):
            if not self._group_alive(pgid):
                return True
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                return True
            await asyncio.sleep(0.01)
        return not self._group_alive(pgid)

    @staticmethod
    def _hash_output(file: object) -> str:
        file.seek(0)
        checksum = hashlib.sha256()
        while True:
            chunk = file.read(65536)
            if not chunk:
                break
            checksum.update(chunk)
        return checksum.hexdigest()

    async def run(self, *, invocation: NodeExecutionInvocation,
                  command_id: str, command: str) -> ForegroundReceipt:
        selected = self._command(invocation, command_id=command_id, command=command)
        key = (invocation.execution_id, command_id)
        if key in self._claimed:
            raise ForegroundExecutionError("FOREGROUND_COMMAND_REPLAY")
        self._claimed.add(key)
        if invocation.execution_id in self._runs:
            raise ForegroundExecutionError("FOREGROUND_EXECUTION_ALREADY_ACTIVE")
        marker = _Run()
        self._runs[invocation.execution_id] = marker
        try:
            before = capture_repository_state(self.repository)
            revision = invocation.execution_workspace_revision
            if (before.fingerprint != revision.repository_state_fingerprint
                    or before.head_sha != revision.head_sha
                    or before.base_sha != revision.base_sha):
                raise ForegroundExecutionError("FOREGROUND_PRESTATE_DRIFT")
        except Exception:
            marker.completion.set()
            raise

        # TemporaryFile() is an unlinked host file OUTSIDE the agent repo.
        # It captures actual stdout/stderr without buffering arbitrarily large
        # subprocess output in memory or storing sensitive raw logs.
        stdout_file = tempfile.TemporaryFile(mode="w+b")
        stderr_file = tempfile.TemporaryFile(mode="w+b")
        timed_out, cancelled = False, False
        exitcode: int | None = None
        spawn_task: asyncio.Task[asyncio.subprocess.Process] | None = None

        async def finalize() -> None:
            """Independent completion owner: task cancellation cannot fake it."""
            drained = False
            try:
                if spawn_task is not None:
                    try:
                        proc = await asyncio.shield(spawn_task)
                        marker.process = proc
                        drained = await self._drain(proc)
                    except OSError:
                        marker.drain_error = True
                    except Exception:
                        marker.drain_error = True
                after = capture_repository_state(self.repository)
                status = (
                    "unverified" if cancelled or timed_out or not drained
                    or before.fingerprint != after.fingerprint
                    else "holds" if exitcode == 0 else "failed"
                )
                marker.receipt = ForegroundReceipt(
                    task_id=invocation.task_id, node_id=invocation.node_id,
                    execution_id=invocation.execution_id, attempt=invocation.attempt,
                    command_id=selected.id, command_fingerprint=selected.fingerprint,
                    policy_fingerprint=self.policy.fingerprint,
                    command_policy_fingerprint=self.plan.canonical_policies[0].fingerprint,
                    argv_fingerprint=fingerprint(selected.argv), returncode=exitcode,
                    timed_out=timed_out, completion_observed=True,
                    process_group_drained=drained, status=status,
                    pre_repository_fingerprint=before.fingerprint,
                    post_repository_fingerprint=after.fingerprint,
                    stdout_sha256=self._hash_output(stdout_file),
                    stderr_sha256=self._hash_output(stderr_file),
                    observed_revision=revision,
                )
            finally:
                stdout_file.close()
                stderr_file.close()
                marker.completion.set()

        try:
            # Shield subprocess registration from cancellation: a process
            # spawned but not yet returned must still be joined and drained.
            spawn_task = asyncio.create_task(asyncio.create_subprocess_exec(
                *selected.argv, cwd=str(self.root),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=stdout_file, stderr=stderr_file,
                start_new_session=True,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            ))
            try:
                marker.process = await asyncio.shield(spawn_task)
            except OSError:
                raise ForegroundExecutionError("FOREGROUND_EXEC_SPAWN_FAILED") from None
            try:
                exitcode = await asyncio.wait_for(
                    marker.process.wait(),
                    timeout=self.plan.canonical_policies[
                        self.plan.commands.index(selected)
                    ].timeout_seconds
                )
            except asyncio.TimeoutError:
                timed_out = True
            except asyncio.CancelledError:
                cancelled = True
                raise
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            # The finalizer is the *sole* owner of the separate completion
            # event. Repeated cancellation may abandon the caller but cannot
            # forge a positive drain or completed receipt.
            marker.finalizer = asyncio.create_task(finalize())
            await asyncio.shield(marker.finalizer)
        if marker.receipt is None:
            raise ForegroundExecutionError("FOREGROUND_RECEIPT_UNAVAILABLE")
        return marker.receipt

    def attest_canonical(
        self, *, invocation: NodeExecutionInvocation, verifier: object,
    ):
        """Restricted Runtime bridge, requires finalized owner receipt."""
        from aswe.runtime.canonical_verifier import CanonicalVerifier

        marker = self._runs.get(invocation.execution_id)
        if (not isinstance(verifier, CanonicalVerifier)
                or verifier.task_id != self.task_id
                or Path(verifier.binding.repository_root).resolve() != self.root
                or marker is None or not marker.completion.is_set()
                or marker.finalizer is None or not marker.finalizer.done()
                or marker.receipt is None
                or not self._trusted(invocation)):
            raise ForegroundExecutionError("FOREGROUND_CANONICAL_ATTESTATION_UNAVAILABLE")
        receipt = marker.receipt
        if (receipt.node_id != invocation.node_id
                or receipt.attempt != invocation.attempt
                or receipt.execution_id != invocation.execution_id
                or receipt.observed_revision != invocation.execution_workspace_revision
                or receipt.command_id != self.plan.commands[0].id):
            raise ForegroundExecutionError("FOREGROUND_CANONICAL_ATTESTATION_MISMATCH")
        return verifier.attest_foreground_observation(
            observed=receipt, policy=self.plan.canonical_policies[0],
            revision=invocation.execution_workspace_revision,
        )

    async def await_completion(self, execution_id: str, *,
                               timeout: float = 5) -> ForegroundReceipt | None:
        """Independent completion fence, not simply a cancelled task/Future."""
        marker = self._runs.get(execution_id)
        if marker is None:
            raise ForegroundExecutionError("FOREGROUND_EXECUTION_NOT_REGISTERED")
        try:
            await asyncio.wait_for(marker.completion.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise ForegroundExecutionError("FOREGROUND_QUIESCENCE_UNPROVEN") from None
        return marker.receipt

    async def cancel(self, execution_id: str) -> None:
        marker = self._runs.get(execution_id)
        if marker is not None and marker.process is not None:
            await self._drain(marker.process)
