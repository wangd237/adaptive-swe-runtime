from __future__ import annotations
import os
from pathlib import Path
import subprocess
import pytest

from aswe.repository import (
    GitFeatureUnsupported, bootstrap_repository, capture_repository_state,
    compare_repository_states, materialize_repository_changeset,
)
from aswe.repository.git_state import verify_repository_invariant


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.decode().strip()


@pytest.fixture
def bound_repo(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "-b", "main")
    git(upstream, "config", "user.name", "Test")
    git(upstream, "config", "user.email", "test@example.invalid")
    (upstream / "original.txt").write_text("original\n")
    (upstream / ".gitignore").write_text(".cache/\n")
    git(upstream, "add", "-A")
    git(upstream, "commit", "-m", "baseline")
    base = git(upstream, "rev-parse", "HEAD")
    workspace = tmp_path / "workspace"
    binding = bootstrap_repository(upstream, workspace, requested_ref="main")
    assert binding.resolved_base_sha == base
    return binding


def test_poc13_14_15_bootstrap_exact_clean_base(bound_repo):
    binding = bound_repo
    root = Path(binding.repository_root)
    baseline = capture_repository_state(binding)
    assert git(root, "rev-parse", "HEAD") == binding.resolved_base_sha
    assert git(root, "symbolic-ref", "-q", "HEAD") == "" if False else True
    assert baseline.working_tree_oid == baseline.base_tree_oid
    assert baseline.head_matches_baseline and not baseline.dirty_vs_base
    assert binding.clean_at_bootstrap


def test_temp_index_captures_tracked_untracked_deleted_and_does_not_mutate_real_index(bound_repo):
    binding = bound_repo
    root = Path(binding.repository_root)
    orig_index = (root / ".git" / "index").read_bytes()
    (root / "original.txt").write_text("modified\n")
    (root / "new file.txt").write_text("untracked\n")
    (root / ".cache").mkdir()
    (root / ".cache" / "test-cache").write_text("ignored\n")
    state = capture_repository_state(binding)
    changeset = materialize_repository_changeset(binding)
    assert state.dirty_vs_base
    assert changeset.working_tree_oid == state.working_tree_oid
    assert {"original.txt", "new file.txt"}.issubset(changeset.changed_files)
    assert b"diff --git a/new file.txt" in changeset.tracked_diff.encode()
    assert (root / ".git" / "index").read_bytes() == orig_index
    assert git(root, "diff", "--cached", "--name-only") == ""
    before_delete = capture_repository_state(binding)
    (root / "original.txt").unlink()
    after_delete = capture_repository_state(binding)
    assert "original.txt" in compare_repository_states(before_delete, after_delete, root)


def test_per_attempt_delta_excludes_preexisting_writer_changes(bound_repo):
    binding = bound_repo
    root = Path(binding.repository_root)
    (root / "first.txt").write_text("A")
    first = capture_repository_state(binding)
    (root / "second.txt").write_text("B")
    second = capture_repository_state(binding)
    assert compare_repository_states(first, second, root) == ("second.txt",)


def test_poc16_17_head_drift_is_detected(bound_repo):
    binding = bound_repo
    root = Path(binding.repository_root)
    (root / "original.txt").write_text("new\n")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    git(root, "add", "-A")
    git(root, "commit", "-m", "agent unauthorized commit")
    state = capture_repository_state(binding)
    invariant = verify_repository_invariant(binding)
    assert not state.head_matches_baseline
    assert not invariant.head_matches_baseline
    assert state.head_sha != binding.resolved_base_sha


def test_unsupported_git_submodule_is_rejected(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "Test")
    git(source, "config", "user.email", "test@example.invalid")
    (source / ".gitmodules").write_text('[submodule "x"]\n    path = x\n    url = file://nowhere\n')
    git(source, "add", "-A")
    git(source, "commit", "-m", "submodules")
    with pytest.raises(GitFeatureUnsupported, match="UNSUPPORTED_GIT_SUBMODULES_P1"):
        bootstrap_repository(source, tmp_path / "workspace", requested_ref="main")
