"""5F-D physical canonical-verification isolation, with a fake API key.

No remote model requests. This test runs actual Python in a real no-network
Docker container and proves the model key in the parent runner's environment
is not available as a child-container environment variable.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend
from aswe.runtime.canonical_verifier import make_command_policy
from aswe.repository import capture_repository_state
from tests.unit.test_deerflow_mvp_task_step5fcb import prepared_mvp
from tests.unit.test_node_workspace_delta import rev


def _digest() -> str:
    result=subprocess.run(
        ["docker","image","inspect","--format","{{index .RepoDigests 0}}",
         "python:3.12-slim"],
        check=True,capture_output=True,text=True,timeout=10,
    )
    digest=result.stdout.strip()
    assert digest.startswith("python@sha256:")
    return digest


@pytest.mark.asyncio
async def test_independent_canonical_python_cannot_see_llm_key(prepared_mvp,monkeypatch):
    repo,core,store,verifier,_policy=prepared_mvp
    monkeypatch.setenv("OPENAI_API_KEY","SENSITIVE_CANARY_DO_NOT_TRANSMIT")
    monkeypatch.setenv("SWE_LLM_API_KEY","SENSITIVE_CANARY_DO_NOT_TRANSMIT")
    root=Path(repo.repository_root)
    backend=DockerCommandBackend(workspace_root=root,image=_digest())
    policy=make_command_policy(
        "isolated-secret-canary",
        ("python","-c",
         "import os; assert os.getenv('OPENAI_API_KEY') is None;"
         "assert os.getenv('SWE_LLM_API_KEY') is None;"
         "print('NO_SECRET_PRESENT')"),
        timeout_seconds=12,
    )
    revision=rev(capture_repository_state(repo))
    ref,receipt=await verifier.run_isolated_python(
        node_id="writer",execution_id="isolated-canary-exec",attempt=1,
        policy=policy,revision=revision,container=backend,
    )
    assert receipt.status=="holds"
    assert receipt.returncode==0
    assert receipt.timed_out is False
    assert len(receipt.stdout_sha256)==64
    assert verifier.validate(
        ref,node_id="writer",execution_id="isolated-canary-exec",
        attempt=1,revision=revision,check_id=policy.check_id,
    )==receipt

    failure_policy=make_command_policy(
        "isolated-regression-failure",("python","-c","import sys;sys.exit(3)"),
        timeout_seconds=12,
    )
    ref2,failed=await verifier.run_isolated_python(
        node_id="writer",execution_id="isolated-canary-exec",attempt=2,
        policy=failure_policy,revision=revision,container=backend,
    )
    assert failed.status=="failed" and failed.returncode==3
    assert verifier.validate(
        ref2,node_id="writer",execution_id="isolated-canary-exec",
        attempt=2,revision=revision,check_id=failure_policy.check_id,
    )==failed


@pytest.mark.asyncio
async def test_docker_canonical_rejects_wrong_workspace_or_host_binary(prepared_mvp,tmp_path):
    repo,core,store,verifier,_=prepared_mvp
    other=tmp_path/"different-workspace"
    other.mkdir()
    wrong=DockerCommandBackend(workspace_root=other,image=_digest())
    revision=rev(capture_repository_state(repo))
    policy=make_command_policy("check",("python","-c","print('ok')"))
    with pytest.raises(ValueError,match="ISOLATED_CANONICAL_AUTHORITY_INVALID"):
        await verifier.run_isolated_python(
            node_id="writer",execution_id="different-workspace-exec",
            attempt=1,policy=policy,revision=revision,container=wrong,
        )
    rooted=DockerCommandBackend(
        workspace_root=Path(repo.repository_root),image=_digest())
    noncontainer=make_command_policy("bad-bin",("/usr/bin/bash","-c","true"))
    with pytest.raises(ValueError,match="ISOLATED_CANONICAL_AUTHORITY_INVALID"):
        await verifier.run_isolated_python(
            node_id="writer",execution_id="foreign-command-exec",
            attempt=1,policy=noncontainer,revision=revision,container=rooted,
        )
