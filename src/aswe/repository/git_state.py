"""Git object-model repository snapshots with an isolated temporary index.

Only ordinary non-bare, non-sparse worktrees without submodules are supported.
No command in this module mutates the repository's real index.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
from contextlib import contextmanager
from typing import Iterator

from pydantic import model_validator

from aswe.core.contracts._base import FrozenModel
from aswe.core.fingerprint import fingerprint


class GitCommandError(RuntimeError):
    pass


class GitFeatureUnsupported(GitCommandError):
    pass


def _git(root: Path | None, *args: str, index: Path | None = None, cwd: Path | None = None) -> bytes:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    command = ["git"]
    if root is not None:
        command.extend(["-C", str(root)])
    command.extend(args)
    try:
        proc = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=False)
    except OSError as exc:
        raise GitCommandError(f"git invocation failed: {args[0]}") from exc
    if proc.returncode:
        raise GitCommandError(
            f"git {args[0]} failed ({proc.returncode}): "
            + proc.stderr.decode("utf-8", "replace")[:700]
        )
    return proc.stdout


def _utf8(value: bytes) -> str:
    return value.decode("utf-8", errors="surrogateescape").strip()


class RepositoryBinding(FrozenModel):
    source_type: str
    remote_url: str | None = None
    requested_ref: str | None = None
    resolved_base_sha: str
    repository_root: str
    default_branch: str | None = None
    clean_at_bootstrap: bool

    @model_validator(mode="after")
    def valid_base(self) -> "RepositoryBinding":
        sha = self.resolved_base_sha
        if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("resolved base must be full SHA-1 commit id in P1")
        return self


class RepositoryInvariant(FrozenModel):
    git_repo_exists: bool
    head_sha: str
    head_matches_baseline: bool


class RepositoryStateDigest(FrozenModel):
    base_sha: str
    head_sha: str
    base_tree_oid: str
    working_tree_oid: str
    head_matches_baseline: bool
    dirty_vs_base: bool
    fingerprint: str


class RepositoryChangeSet(FrozenModel):
    base_sha: str
    head_sha: str
    head_matches_baseline: bool
    working_tree_oid: str
    tracked_diff: str
    changed_files: tuple[str, ...]
    untracked_files: tuple[str, ...]
    dirty: bool


def _validate_supported(root: Path, base_sha: str) -> None:
    bare = _utf8(_git(root, "rev-parse", "--is-bare-repository"))
    if bare != "false":
        raise GitFeatureUnsupported("bare Git repository unsupported in P1")
    for option in ("core.sparseCheckout", "index.sparse"):
        try:
            value = _utf8(_git(root, "config", "--get", option)).lower()
        except GitCommandError:
            value = ""
        if value == "true":
            raise GitFeatureUnsupported("UNSUPPORTED_SPARSE_CHECKOUT_P1")
    # Check Git-visible baseline rather than only .gitmodules on disk.
    entries = _git(root, "ls-tree", "-r", base_sha).splitlines()
    for entry in entries:
        if entry.startswith(b"160000 ") or entry.endswith(b"\t.gitmodules"):
            raise GitFeatureUnsupported("UNSUPPORTED_GIT_SUBMODULES_P1")


@contextmanager
def _temporary_index(root: Path, base_sha: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aswe-git-index-") as directory:
        index = Path(directory) / "index"
        _git(root, "read-tree", base_sha, index=index)
        # The isolated index starts at the original baseline, not at the real index.
        _git(root, "add", "-A", "--", ".", index=index)
        yield index


def _reject_unsupported_materialized_tree(root: Path, tree_oid: str) -> None:
    entries = _git(root, "ls-tree", "-r", tree_oid).splitlines()
    for entry in entries:
        if entry.startswith(b"160000 ") or entry.endswith(b"\t.gitmodules"):
            raise GitFeatureUnsupported("UNSUPPORTED_GIT_SUBMODULES_P1")


def _current_head(root: Path) -> str:
    head = _utf8(_git(root, "rev-parse", "--verify", "HEAD^{commit}"))
    if len(head) != 40:
        raise GitCommandError("expected a full Git SHA-1 commit")
    return head


def bootstrap_repository(
    source: str | Path, workspace_root: str | Path, *,
    requested_ref: str = "HEAD",
) -> RepositoryBinding:
    """Clone a local or HTTPS repository into a NEW worktree at an exact baseline.

    Never checks out an untrusted ref inside an existing working directory.
    """
    destination = Path(workspace_root).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("workspace root must be empty before cloning")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _git(None, "clone", "--no-local", "--no-checkout", "--", str(source), str(destination))
    try:
        # Remote-tracking refs cover typical branch names after clone.
        candidates = [requested_ref]
        if requested_ref not in ("HEAD",) and not requested_ref.startswith("refs/"):
            candidates.append("refs/remotes/origin/" + requested_ref)
        base_sha = None
        for candidate in candidates:
            try:
                base_sha = _utf8(_git(destination, "rev-parse", "--verify", candidate + "^{commit}"))
                break
            except GitCommandError:
                continue
        if base_sha is None:
            raise GitCommandError("requested repository ref is not resolvable")
        _validate_supported(destination, base_sha)
        _git(destination, "checkout", "--detach", base_sha)
        if _git(destination, "status", "--porcelain", "--untracked-files=all").strip():
            raise GitCommandError("repository not clean after bootstrap")
        return RepositoryBinding(
            source_type="git", remote_url=str(source), requested_ref=requested_ref,
            resolved_base_sha=base_sha, repository_root=str(destination),
            default_branch=None, clean_at_bootstrap=True,
        )
    except Exception:
        # Do not silently delete a partially bootstrapped repository.
        raise


def capture_repository_state(binding: RepositoryBinding) -> RepositoryStateDigest:
    root = Path(binding.repository_root).resolve()
    _validate_supported(root, binding.resolved_base_sha)
    head = _current_head(root)
    base_tree = _utf8(_git(root, "rev-parse", binding.resolved_base_sha + "^{tree}"))
    with _temporary_index(root, binding.resolved_base_sha) as index:
        working_tree = _utf8(_git(root, "write-tree", index=index))
    _reject_unsupported_materialized_tree(root, working_tree)
    if _current_head(root) != head:
        raise GitCommandError("HEAD changed during repository state capture")
    fields = {
        "base_sha": binding.resolved_base_sha,
        "head_sha": head,
        "base_tree_oid": base_tree,
        "working_tree_oid": working_tree,
        "head_matches_baseline": head == binding.resolved_base_sha,
        "dirty_vs_base": working_tree != base_tree,
    }
    return RepositoryStateDigest(**fields, fingerprint=fingerprint(fields))


def compare_repository_states(before: RepositoryStateDigest, after: RepositoryStateDigest,
                              repository_root: str | Path) -> tuple[str, ...]:
    if before.base_sha != after.base_sha:
        raise GitCommandError("cannot compare unrelated repository baselines")
    root = Path(repository_root).resolve()
    data = _git(root, "diff", "--no-renames", "--name-only", "-z",
                before.working_tree_oid, after.working_tree_oid)
    return tuple(sorted({p for p in data.decode("utf-8", "surrogateescape").split("\0") if p}))


def materialize_repository_changeset(binding: RepositoryBinding) -> RepositoryChangeSet:
    root = Path(binding.repository_root).resolve()
    state = capture_repository_state(binding)
    with _temporary_index(root, binding.resolved_base_sha) as index:
        tree = _utf8(_git(root, "write-tree", index=index))
        if tree != state.working_tree_oid or _current_head(root) != state.head_sha:
            raise GitCommandError("repository changed during changeset materialization")
        patch = _git(root, "diff", "--cached", "--binary", "--no-ext-diff",
                     binding.resolved_base_sha, index=index)
        paths = _git(root, "diff", "--cached", "--name-only", "--no-renames", "-z",
                     binding.resolved_base_sha, index=index)
        # The temporary index has staged every new file, so ls-files --others
        # would be empty. Newly introduced paths relative to the immutable
        # baseline are obtained from the same materialized index.
        untracked = _git(root, "diff", "--cached", "--diff-filter=A", "--no-renames",
                         "--name-only", "-z", binding.resolved_base_sha, index=index)
    return RepositoryChangeSet(
        base_sha=binding.resolved_base_sha, head_sha=state.head_sha,
        head_matches_baseline=state.head_matches_baseline,
        working_tree_oid=tree,
        tracked_diff=patch.decode("utf-8", "surrogateescape"),
        changed_files=tuple(sorted(set(filter(None, paths.decode("utf-8", "surrogateescape").split("\0"))))),
        untracked_files=tuple(sorted(set(filter(None, untracked.decode("utf-8", "surrogateescape").split("\0"))))),
        dirty=state.dirty_vs_base,
    )


def verify_repository_invariant(binding: RepositoryBinding) -> RepositoryInvariant:
    root = Path(binding.repository_root)
    exists = (root / ".git").exists()
    head = _current_head(root) if exists else ""
    return RepositoryInvariant(git_repo_exists=exists, head_sha=head,
                               head_matches_baseline=head == binding.resolved_base_sha)
