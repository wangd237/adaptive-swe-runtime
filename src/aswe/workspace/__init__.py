"""Task-scoped workspace lifecycle, access arbitration and mutation observations."""
from .session import WorkspaceLifecycle, WorkspaceSession, WorkspaceSessionStatus
from .access import WorkspaceAccessManager, WorkspaceClosedError
from .snapshot import FilesystemSnapshot, capture_filesystem_snapshot, changed_snapshot_paths
from .delta import MutationEvidence, NodeWorkspaceDelta, derive_node_workspace_delta

__all__ = [
    "WorkspaceLifecycle", "WorkspaceSession", "WorkspaceSessionStatus",
    "WorkspaceAccessManager", "WorkspaceClosedError",
    "FilesystemSnapshot", "capture_filesystem_snapshot", "changed_snapshot_paths",
    "MutationEvidence", "NodeWorkspaceDelta", "derive_node_workspace_delta",
]
