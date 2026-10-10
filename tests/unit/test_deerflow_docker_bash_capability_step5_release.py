"""P0-01 standalone provision contract; no positive 5C admission claimed."""
from pathlib import Path

import pytest

from aswe.capabilities.effects import ToolEffect, trusted_effect
from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend
from aswe.integrations.deerflow.docker_bash_capability import (
    DockerBashCapability, DockerBashCapabilityError,
    DOCKER_BASH_IMPLEMENTATION_ID,
)


def test_runtime_docker_identity_cannot_impersonate_host_bash(tmp_path):
    backend = DockerCommandBackend(
        workspace_root=tmp_path, image="python@sha256:" + "1" * 64,
    )
    grant = DockerBashCapability.from_backend(backend)
    grant.assert_matches(backend)
    info = grant.tool_info()
    assert info.effect is ToolEffect.WORKSPACE_MUTATING
    assert info.source == "aswe-runtime-docker"
    assert info.implementation_id == DOCKER_BASH_IMPLEMENTATION_ID
    assert info.implementation_id != "config:deerflow.sandbox.tools:bash_tool"
    # Until the real 5C composer validates grant provenance and seals its
    # descriptor, the frozen compiler intentionally fails closed.
    assert trusted_effect(info) is ToolEffect.UNKNOWN


def test_runtime_docker_grant_rejects_non_docker_backend(tmp_path):
    class ForgedBackend:
        workspace_root = tmp_path
        image = "python@sha256:" + "1" * 64
        isolation_kind = "docker-no-network"

    with pytest.raises(DockerBashCapabilityError, match="DOCKER_BASH_BACKEND_UNTRUSTED"):
        DockerBashCapability.from_backend(ForgedBackend())


def test_runtime_docker_grant_rejects_workspace_and_image_drift(tmp_path):
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    first = DockerCommandBackend(
        workspace_root=one, image="python@sha256:" + "1" * 64,
    )
    grant = DockerBashCapability.from_backend(first)
    different_root = DockerCommandBackend(
        workspace_root=two, image=first.image,
    )
    different_image = DockerCommandBackend(
        workspace_root=one, image="python@sha256:" + "2" * 64,
    )
    for replacement in (different_root, different_image):
        with pytest.raises(DockerBashCapabilityError, match="DOCKER_BASH_CAPABILITY_DRIFT"):
            grant.assert_matches(replacement)
