"""Physical Docker-isolated dynamic Bash smoke test for 5F-C.

Executed only in pinned native Python 3.12 CI, after pulling one explicitly
chosen development image. Source image's local digest is resolved and passed
into the runner. No GitHub, model, or application credentials are mounted.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess

import pytest

from aswe.integrations.deerflow.controlled_swe import (
    DockerCommandBackend, SWEExecutionDenied
)


def local_image_digest():
    proc=subprocess.run([
        "docker","image","inspect","--format",
        "{{index .RepoDigests 0}}","alpine:3.20"
    ],check=True,text=True,capture_output=True,timeout=15)
    image=proc.stdout.strip()
    assert image.startswith("alpine@sha256:")
    return image


@pytest.mark.asyncio
async def test_actual_docker_dynamic_command_is_networkless_and_workspace_bounded(tmp_path):
    root=tmp_path/"repo"
    root.mkdir()
    (root/"README.md").write_text("container-bound")
    image=local_image_digest()
    runtime=DockerCommandBackend(workspace_root=root,image=image)
    result=await runtime.run(
        "cat README.md; echo 'created inside sandbox' > generated.txt; "
        "test ! -w /etc; test ! -e /home/runner; echo done",
        timeout=20,max_output=1200,
    )
    assert result.exit_code==0 and not result.timed_out,result.output
    assert "container-bound" in result.output
    assert (root/"generated.txt").read_text().strip()=="created inside sandbox"
    assert not (tmp_path/"generated.txt").exists()

    # We accept arbitrary COMMAND text only inside this container, not host.
    bad=await runtime.run("cat /this/path/does/not/exist",timeout=20,max_output=1200)
    assert bad.exit_code != 0
    assert "exit_code=0" not in str(bad)

    timed=await runtime.run("sleep 5",timeout=0.1,max_output=1200)
    assert timed.timed_out and timed.exit_code is None
