"""Runtime-owned isolated Docker Bash authority, distinct from DeerFlow host Bash.

This module deliberately does not insert any synthetic tool into upstream
get_available_tools(). A future production 5C composer must admit this
additional namespace explicitly and pin it into the descriptor and 5D.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aswe.capabilities.effects import ToolEffect
from aswe.providers.inventory import BackendToolInfo
from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend

DOCKER_BASH_IMPLEMENTATION_ID = "aswe.runtime.docker:bash.v1"
DOCKER_BASH_SOURCE = "aswe-runtime-docker"
DOCKER_BASH_CONTRACT_ID = "bash"


class DockerBashCapabilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class DockerBashCapability:
    """Trusted host-issued provision record, never from the model or YAML."""

    workspace_root: Path
    image: str

    @classmethod
    def from_backend(cls, backend: DockerCommandBackend) -> "DockerBashCapability":
        if not isinstance(backend, DockerCommandBackend):
            raise DockerBashCapabilityError("DOCKER_BASH_BACKEND_UNTRUSTED")
        root = Path(backend.workspace_root).resolve(strict=True)
        if root != backend.workspace_root or not root.is_dir():
            raise DockerBashCapabilityError("DOCKER_BASH_WORKSPACE_UNTRUSTED")
        if not isinstance(backend.image, str) or "@sha256:" not in backend.image:
            raise DockerBashCapabilityError("DOCKER_BASH_IMAGE_UNPINNED")
        return cls(workspace_root=root, image=backend.image)

    def assert_matches(self, backend: DockerCommandBackend) -> None:
        """Recheck resolved workspace and image before execution admission."""
        observed = type(self).from_backend(backend)
        if observed != self:
            raise DockerBashCapabilityError("DOCKER_BASH_CAPABILITY_DRIFT")

    def tool_info(self) -> BackendToolInfo:
        return BackendToolInfo(
            contract_id=DOCKER_BASH_CONTRACT_ID,
            configured_name=None,
            resolved_exposed_name=DOCKER_BASH_CONTRACT_ID,
            source=DOCKER_BASH_SOURCE,
            delivery="eager",
            implementation_id=DOCKER_BASH_IMPLEMENTATION_ID,
            group="runtime:isolated-command",
            provenance="aswe-runtime-owned-docker",
            effect=ToolEffect.WORKSPACE_MUTATING,
        )
