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
    # Recognition is not authorization; only an independently witnessed grant
    # can be composed into the pinned native planning and preflight snapshots.
    assert trusted_effect(info) is ToolEffect.WORKSPACE_MUTATING


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


def test_composer_preserves_native_evidence_without_promoting_host_bash(tmp_path):
    from aswe.providers.inventory import BackendInventorySnapshot, inventory_fingerprint
    from aswe.integrations.deerflow.docker_bash_capability import compose_docker_bash_inventory
    backend = DockerCommandBackend(workspace_root=tmp_path, image="python@sha256:"+"1"*64)
    grant = DockerBashCapability.from_backend(backend)
    body = dict(
        backend_id="deerflow", captured_at="2026-10-10T00:00:00Z",
        candidate_agent_types=frozenset({"general-purpose"}),
        candidate_tools={}, candidate_skill_names=frozenset(),
        configured_model_names=frozenset({"test"}),
        sandbox_features=frozenset({"fresh_shell_per_command"}),
        max_parallel_executions=1,
    )
    native=BackendInventorySnapshot(**body, fingerprint=inventory_fingerprint(body))
    composed=compose_docker_bash_inventory(native=native,backend=backend,grant=grant)
    assert "bash" not in native.candidate_tools
    assert composed.candidate_tools["bash"].source=="aswe-runtime-docker"
    assert composed.fingerprint != native.fingerprint
    assert "aswe_runtime_docker_no_network" in composed.sandbox_features
    fake_host = native.model_dump(mode="python",exclude={"fingerprint"})
    fake_host["candidate_tools"]={"bash":grant.tool_info()}
    spoofed=BackendInventorySnapshot(**fake_host,fingerprint=inventory_fingerprint(fake_host))
    with pytest.raises(DockerBashCapabilityError,match="DOCKER_BASH_NATIVE_HOST_COLLISION"):
        compose_docker_bash_inventory(native=spoofed,backend=backend,grant=grant)
