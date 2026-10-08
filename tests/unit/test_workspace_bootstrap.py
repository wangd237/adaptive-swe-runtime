from __future__ import annotations
from pathlib import Path
import subprocess

from aswe.workspace import bootstrap_task_workspace, capture_filesystem_snapshot, changed_snapshot_paths
from aswe.workspace.session import WorkspaceSessionStatus


def git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_runtime_bootstrap_baseline_snapshot_after_checkout(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "Tests")
    git(source, "config", "user.email", "tests@example.invalid")
    (source / "original.py").write_text("print(1)\n")
    git(source, "add", "-A")
    git(source, "commit", "-m", "base")

    output = bootstrap_task_workspace(
        task_id="aswe-task-123", thread_id="aswe-thread-123", user_id="aswe-user-123",
        source=source, workspace_root=tmp_path / "workspace", requested_ref="main",
    )
    assert output.session.status is WorkspaceSessionStatus.READY
    assert output.initial_revision.generation == 0
    assert not output.initial_revision.dirty
    assert output.baseline_repository_state.working_tree_oid == output.baseline_repository_state.base_tree_oid
    assert changed_snapshot_paths(
        output.baseline_filesystem_snapshot, capture_filesystem_snapshot(output.session.workspace_root)
    ) == ()
    (Path(output.session.workspace_root) / "next.py").write_text("print(2)\n")
    assert changed_snapshot_paths(
        output.baseline_filesystem_snapshot, capture_filesystem_snapshot(output.session.workspace_root)
    ) == ("next.py",)
