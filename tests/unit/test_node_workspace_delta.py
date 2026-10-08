from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from aswe.core.contracts import WorkspaceRevision
from aswe.repository import bootstrap_repository, capture_repository_state
from aswe.workspace import (
    MutationEvidence, capture_filesystem_snapshot, derive_node_workspace_delta,
)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture
def repository(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "A-SWE Test")
    git(source, "config", "user.email", "test@example.invalid")
    (source / ".gitignore").write_text(".cache/\n")
    (source / "a.txt").write_text("baseline")
    git(source, "add", "-A")
    git(source, "commit", "-m", "baseline")
    binding = bootstrap_repository(source, tmp_path / "workspace", requested_ref="main")
    return binding


def rev(digest, generation=0):
    return WorkspaceRevision(
        generation=generation, base_sha=digest.base_sha, head_sha=digest.head_sha,
        head_matches_baseline=digest.head_matches_baseline,
        repository_state_fingerprint=digest.fingerprint, dirty=digest.dirty_vs_base,
    )


def test_node_delta_reports_only_current_attempt_repository_changes(repository):
    root = Path(repository.repository_root)
    (root / "writer_a.txt").write_text("A")
    before_repo = capture_repository_state(repository)
    before_scan = capture_filesystem_snapshot(root)
    (root / "writer_b.txt").write_text("B")
    after_repo = capture_repository_state(repository)
    after_scan = capture_filesystem_snapshot(root)
    delta, new_rev = derive_node_workspace_delta(
        node_id="writer-b", execution_id="exec-b", attempt=1,
        before_revision=rev(before_repo, 8),
        before_filesystem=before_scan, after_filesystem=after_scan,
        before_repository=before_repo, after_repository=after_repo,
        repository_root=str(root), mutating_tool_admitted=True,
    )
    assert delta.repository_changed_paths == ("writer_b.txt",)
    assert "writer_a.txt" not in delta.repository_changed_paths
    assert delta.mutation_evidence is MutationEvidence.OBSERVED
    assert delta.before_revision_generation == 8
    assert new_rev.generation == 9
    assert new_rev.repository_state_fingerprint == after_repo.fingerprint


def test_scanner_excluded_cache_change_is_not_proven_none(repository):
    root = Path(repository.repository_root)
    before_repo = capture_repository_state(repository)
    before_scan = capture_filesystem_snapshot(root)
    (root / ".cache").mkdir()
    (root / ".cache" / "pytest-data").write_text("side-effect")
    after_repo = capture_repository_state(repository)
    after_scan = capture_filesystem_snapshot(root)
    delta, new_rev = derive_node_workspace_delta(
        node_id="tester", execution_id="exec", attempt=1,
        before_revision=rev(before_repo), before_filesystem=before_scan,
        after_filesystem=after_scan, before_repository=before_repo,
        after_repository=after_repo, repository_root=str(root),
        mutating_tool_admitted=True,
    )
    assert delta.changed_paths == ()
    assert delta.repository_changed_paths == ()
    assert delta.mutation_evidence is MutationEvidence.UNKNOWN
    assert new_rev.generation == 1


def test_delta_rejects_mismatched_prior_workspace_revision(repository):
    root = Path(repository.repository_root)
    digest = capture_repository_state(repository)
    scan = capture_filesystem_snapshot(root)
    prior = rev(digest).model_copy(update={"repository_state_fingerprint": "stale"})
    with pytest.raises(ValueError, match="pre-revision repository evidence mismatch"):
        derive_node_workspace_delta(
            node_id="node", execution_id="exec", attempt=1,
            before_revision=prior, before_filesystem=scan, after_filesystem=scan,
            before_repository=digest, after_repository=digest,
            repository_root=str(root), mutating_tool_admitted=False,
        )
