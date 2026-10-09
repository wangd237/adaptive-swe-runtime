"""5F-B exact compiler-owned foreground command, process-group drain tests.

These are local physical subprocess tests, not sandbox lease attestation.
"""
from __future__ import annotations

import asyncio
import sys

import pytest

from aswe.core.fingerprint import fingerprint
from aswe.core.contracts.backend import NodeExecutionInvocation
from aswe.planning.acceptance import (
    AcceptanceCriterionBinding, CompiledAcceptancePlan, VerificationCommandKind,
    _command, SANDBOX_FEATURE,
)
from aswe.runtime.canonical_verifier import make_command_policy
from aswe.providers.policy import NodeExecutionPolicy
from aswe.integrations.deerflow.managed_foreground import (
    ManagedForegroundVerifier, ForegroundExecutionError,
)
from tests.unit.test_step4_live_preflight_descriptor import artifacts
from tests.unit.test_deerflow_execution_evidence_step5f import invocation
from tests.unit.test_node_workspace_delta import repository as repository_fixture


def _approved(repo, argv, *, timeout=1.0, runtime_id="task5fb",
              can_run=None, allow_inline=False):
    plan0 = artifacts()
    base_policy = plan0[-2][0]
    command = _command(VerificationCommandKind.TEST, "runtime_rule",
                       fingerprint(("trusted", tuple(argv))),
                       tuple(argv), ("unit",))
    policy = make_command_policy(command.id, command.argv, timeout)
    criterion = AcceptanceCriterionBinding(
        command_id=command.id, criterion="tests_passed:" + command.command,
        bash_exact_allowlist_entry=command.command,
        command_policy_fingerprint=policy.fingerprint,
        check_keys=command.check_keys,
    )
    body = dict(
        task_contract_fingerprint=base_policy.task_contract_fingerprint,
        commands=(command,), criteria=(criterion,),
        canonical_policies=(policy,), unresolved_check_keys=(),
        required_sandbox_features=(SANDBOX_FEATURE,),
    )
    acceptance = CompiledAcceptancePlan(**body, fingerprint=fingerprint(body))
    fields = base_policy.model_dump(mode="python", exclude={"fingerprint"})
    fields["acceptance_fingerprint"] = acceptance.fingerprint
    fields["verification_exact_commands"] = (command.command,)
    fields["canonical_check_policy_fingerprints"] = (policy.fingerprint,)
    fields["allowed_business_tools"] = tuple(sorted(
        set(fields["allowed_business_tools"]) | {"bash"}
    ))
    fields["denied_tools"] = tuple(x for x in fields["denied_tools"] if x != "bash")
    exec_policy = NodeExecutionPolicy(**fields, fingerprint=fingerprint(fields))
    inv = invocation(repo).model_copy(update={
        "task_id": runtime_id, "node_id": exec_policy.node_id,
    })
    runner = ManagedForegroundVerifier(
        task_id=runtime_id, plan=acceptance, policy=exec_policy,
        repository=repo, execution_live_checker=can_run or (lambda _: True),
        allow_inline_python_in_tests=allow_inline,
    )
    return runner, inv, command


@pytest.mark.asyncio
async def test_compiled_foreground_process_returns_and_independent_signal(repository_fixture):
    runner, inv, cmd = _approved(
        repository_fixture, (sys.executable, "-m", "this")
    )
    receipt = await runner.run(
        invocation=inv, command_id=cmd.id, command=cmd.command
    )
    assert receipt.status == "holds" and receipt.returncode == 0
    assert receipt.completion_observed and receipt.process_group_drained
    assert receipt.execution_id == inv.execution_id
    assert await runner.await_completion(inv.execution_id) == receipt
    with pytest.raises(ForegroundExecutionError, match="FOREGROUND_COMMAND_REPLAY"):
        await runner.run(invocation=inv, command_id=cmd.id, command=cmd.command)


@pytest.mark.asyncio
async def test_no_prefix_matching_or_model_added_suffix(repository_fixture):
    runner, inv, cmd = _approved(
        repository_fixture, (sys.executable, "-m", "this")
    )
    for altered in (cmd.command + " & echo unsafe", cmd.command + " --other", "echo OK"):
        with pytest.raises(ForegroundExecutionError,match="FOREGROUND_COMMAND_NOT_ALLOWLISTED"):
            await runner.run(invocation=inv, command_id=cmd.id, command=altered)
    assert runner._runs == {}


@pytest.mark.asyncio
async def test_uncommitted_invocation_fails_before_subprocess(repository_fixture):
    runner, inv, cmd = _approved(
        repository_fixture, (sys.executable, "-m", "this"),
        can_run=lambda _: False,
    )
    with pytest.raises(ForegroundExecutionError, match="FOREGROUND_SCHEDULER_COMMIT_REQUIRED"):
        await runner.run(invocation=inv, command_id=cmd.id, command=cmd.command)
    assert not runner._runs


@pytest.mark.asyncio
async def test_shell_interpreter_rejected_even_when_compiled(repository_fixture):
    with pytest.raises(Exception):
        _approved(repository_fixture, ("bash", "-c", "echo hi"))
    runner, inv, cmd = _approved(
        repository_fixture, (sys.executable, "-c", "print('ok')"),
        allow_inline=False,
    )
    with pytest.raises(ForegroundExecutionError, match="FOREGROUND_INTERPRETER_NOT_ALLOWED"):
        await runner.run(invocation=inv, command_id=cmd.id, command=cmd.command)


@pytest.mark.asyncio
async def test_timeout_drains_actual_process_group(repository_fixture):
    runner, inv, cmd = _approved(
        repository_fixture,
        (sys.executable, "-c", "__import__('time').sleep(3)"),
        timeout=0.05, allow_inline=True,
    )
    receipt = await runner.run(
        invocation=inv, command_id=cmd.id, command=cmd.command
    )
    assert receipt.status == "unverified" and receipt.timed_out
    assert receipt.completion_observed and receipt.process_group_drained
    assert await runner.await_completion(inv.execution_id) == receipt


@pytest.mark.asyncio
async def test_cancellation_does_not_assert_positive_before_drain(repository_fixture):
    runner, inv, cmd = _approved(
        repository_fixture,
        (sys.executable, "-c", "__import__('time').sleep(3)"),
        timeout=5, allow_inline=True,
    )
    task = asyncio.create_task(runner.run(
        invocation=inv, command_id=cmd.id, command=cmd.command
    ))
    for _ in range(200):
        marker = runner._runs.get(inv.execution_id)
        if marker is not None and marker.process is not None:
            break
        await asyncio.sleep(0.005)
    assert marker is not None and marker.process is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Task/Future.cancel() by itself is NOT the completion authority.
    observed = await runner.await_completion(inv.execution_id)
    assert observed is not None
    assert observed.process_group_drained and observed.status == "unverified"


@pytest.mark.asyncio
async def test_prestate_drift_failclosed_before_running(repository_fixture):
    from pathlib import Path
    runner, inv, cmd = _approved(repository_fixture, (sys.executable, "-m", "this"))
    (Path(repository_fixture.repository_root) / "UNAPPROVED.txt").write_text("changed")
    with pytest.raises(ForegroundExecutionError,match="FOREGROUND_PRESTATE_DRIFT"):
        await runner.run(invocation=inv, command_id=cmd.id, command=cmd.command)
    assert runner._runs[inv.execution_id].process is None


@pytest.mark.asyncio
async def test_known_detached_entrypoints_are_rejected_before_spawn(repository_fixture):
    runner, inv, cmd = _approved(repository_fixture, ("nohup", "sleep", "1"))
    with pytest.raises(ForegroundExecutionError, match="UNSUPPORTED_BACKGROUND_EXECUTION"):
        await runner.run(invocation=inv, command_id=cmd.id, command=cmd.command)
    assert runner._runs == {}


@pytest.mark.asyncio
async def test_approved_but_missing_executable_fails_closed(repository_fixture):
    runner, inv, cmd = _approved(
        repository_fixture, ("a-swe-nonexistent-executable-5fb",)
    )
    with pytest.raises(ForegroundExecutionError, match="FOREGROUND_EXEC_SPAWN_FAILED"):
        await runner.run(invocation=inv, command_id=cmd.id, command=cmd.command)
    observed = await runner.await_completion(inv.execution_id)
    assert observed is not None and observed.status == "unverified"
    assert observed.process_group_drained is False


@pytest.mark.asyncio
async def test_real_foreground_receipt_is_signed_and_verified_by_runtime(
        repository_fixture, tmp_path):
    import hashlib
    from aswe.runtime.canonical_verifier import CanonicalVerifier
    from aswe.evidence import LocalEvidenceStore

    runner, inv, cmd = _approved(repository_fixture, (sys.executable, "-m", "this"))
    store = LocalEvidenceStore(tmp_path/"evidence-sign",
                               workspace_root=repository_fixture.repository_root)
    verifier = CanonicalVerifier(
        task_id=inv.task_id, runtime_data_dir=tmp_path/"runtime-private",
        evidence_store=store, binding=repository_fixture,
    )
    observed = await runner.run(invocation=inv, command_id=cmd.id, command=cmd.command)
    assert observed.completion_observed and observed.process_group_drained
    assert observed.stdout_sha256 != hashlib.sha256(b"").hexdigest()
    ref, signed = runner.attest_canonical(invocation=inv, verifier=verifier)
    assert signed.status == "holds"
    assert signed.stdout_sha256 == observed.stdout_sha256
    assert signed.command_policy_fingerprint == runner.plan.canonical_policies[0].fingerprint
    assert verifier.validate(ref, node_id=inv.node_id, execution_id=inv.execution_id,
                             attempt=inv.attempt,
                             revision=inv.execution_workspace_revision,
                             check_id=cmd.id) == signed

    # The persisted payload/fingerprint/HMAC must reject any tampered status.
    with pytest.raises(ValueError):
        verifier.attest_foreground_observation(
            observed=__import__("dataclasses").replace(
                observed, status="holds", process_group_drained=False
            ),
            policy=runner.plan.canonical_policies[0],
            revision=inv.execution_workspace_revision,
        )
    with pytest.raises(ForegroundExecutionError, match="FOREGROUND_CANONICAL_ATTESTATION_MISMATCH"):
        runner.attest_canonical(
            invocation=inv.model_copy(update={"attempt":99}), verifier=verifier)


@pytest.mark.asyncio
async def test_nonzero_and_timed_out_commands_never_sign_as_success(repository_fixture,tmp_path):
    from aswe.runtime.canonical_verifier import CanonicalVerifier
    from aswe.evidence import LocalEvidenceStore
    for idx,(args,limit,expected,inline) in enumerate((
        ((sys.executable, "-m", "aswe_nonexistent_module"), 1.0, "failed", False),
        ((sys.executable, "-c", "__import__('time').sleep(2)"), 0.05, "unverified", True),
    )):
        runner, inv, cmd = _approved(repository_fixture,args,timeout=limit,
                                      allow_inline=inline,runtime_id="task5fb" + str(idx))
        verifier = CanonicalVerifier(
            task_id=inv.task_id,runtime_data_dir=tmp_path/("private"+str(idx)),
            evidence_store=LocalEvidenceStore(tmp_path/("store"+str(idx)),
                                             workspace_root=repository_fixture.repository_root),
            binding=repository_fixture,
        )
        observed = await runner.run(invocation=inv, command_id=cmd.id, command=cmd.command)
        ref, receipt = runner.attest_canonical(invocation=inv,verifier=verifier)
        assert receipt.status == expected and receipt.status == observed.status
        assert receipt.attestation_hmac
        assert verifier.validate(ref,node_id=inv.node_id,
                                execution_id=inv.execution_id,
                                attempt=inv.attempt,
                                revision=inv.execution_workspace_revision,
                                check_id=cmd.id).status == expected


@pytest.mark.asyncio
async def test_repeated_cancel_does_not_forge_foreground_completion(repository_fixture,monkeypatch):
    """Even cancellation of the caller during cleanup leaves an owned finalizer."""
    runner,inv,cmd=_approved(
        repository_fixture,
        (sys.executable,"-c","__import__('time').sleep(3)"),
        timeout=5,allow_inline=True,
    )
    started=asyncio.Event()
    release=asyncio.Event()
    original=runner._drain
    async def paused(proc):
        started.set()
        await release.wait()
        return await original(proc)
    monkeypatch.setattr(runner,"_drain",paused)
    task=asyncio.create_task(runner.run(
        invocation=inv,command_id=cmd.id,command=cmd.command))
    for _ in range(300):
        marker=runner._runs.get(inv.execution_id)
        if marker is not None and marker.process is not None:
            break
        await asyncio.sleep(0.005)
    assert marker is not None and marker.process is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(started.wait(),1)
    assert marker.finalizer is not None and not marker.completion.is_set()
    with pytest.raises(ForegroundExecutionError,match="FOREGROUND_QUIESCENCE_UNPROVEN"):
        await runner.await_completion(inv.execution_id,timeout=0.03)
    release.set()
    receipt=await runner.await_completion(inv.execution_id,timeout=4)
    assert receipt is not None and receipt.completion_observed
    assert receipt.status == "unverified"
    assert receipt.process_group_drained
