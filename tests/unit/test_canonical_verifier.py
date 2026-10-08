"""Local Runtime canonical command execution and tamper/provenance gates."""
from __future__ import annotations

import subprocess
import sys

import pytest

from aswe.core.contracts import WorkspaceRevision
from aswe.evidence import LocalEvidenceStore
from aswe.repository import bootstrap_repository, capture_repository_state
from aswe.runtime.canonical_verifier import (
    CanonicalVerifier, CanonicalCommandPolicy, make_command_policy,
)


def git(path, *argv):
    subprocess.run(["git", "-C", str(path), *argv], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture
def canonical_workspace(tmp_path):
    src = tmp_path / "src-repository"
    src.mkdir()
    git(src, "init", "-b", "main")
    git(src, "config", "user.name", "Test")
    git(src, "config", "user.email", "test@example.invalid")
    (src / "source.py").write_text("BASELINE = True\n")
    git(src, "add", "-A")
    git(src, "commit", "-m", "baseline")
    binding = bootstrap_repository(src, tmp_path / "workspace", requested_ref="main")
    state = capture_repository_state(binding)
    revision = WorkspaceRevision(
        generation=0, base_sha=state.base_sha, head_sha=state.head_sha,
        head_matches_baseline=True, repository_state_fingerprint=state.fingerprint,
        dirty=False,
    )
    store = LocalEvidenceStore(tmp_path / "runtime", workspace_root=binding.repository_root)
    verifier = CanonicalVerifier(task_id="aswe-task-canonical", runtime_data_dir=tmp_path / "runtime",
                                 binding=binding, evidence_store=store)
    return binding, revision, store, verifier


def test_canonical_nonzero_exit_produces_attempt_attested_failed_evidence(canonical_workspace):
    _, rev, store, verifier = canonical_workspace
    policy = make_command_policy("unit-tests", (sys.executable, "-c", "import sys;sys.exit(1)"))
    ref, receipt = verifier.run(node_id="verify", execution_id="exec-v1", attempt=1,
                                policy=policy, revision=rev)
    assert receipt.status == "failed" and receipt.returncode == 1
    assert verifier.validate(ref, node_id="verify", execution_id="exec-v1",
                             attempt=1, revision=rev, check_id="unit-tests") == receipt
    restarted = CanonicalVerifier(task_id="aswe-task-canonical", runtime_data_dir=store.root,
                                  evidence_store=store, binding=verifier.binding)
    assert restarted.validate(ref, node_id="verify", execution_id="exec-v1",
                              attempt=1, revision=rev, check_id="unit-tests") == receipt


def test_successful_command_cannot_be_reclassified_as_failure(canonical_workspace):
    _, rev, _, verifier = canonical_workspace
    ref, receipt = verifier.run(
        node_id="verify", execution_id="e", attempt=1,
        policy=make_command_policy("check", (sys.executable, "-c", "pass")), revision=rev
    )
    assert receipt.status == "holds"
    assert verifier.validate(ref, node_id="verify", execution_id="e", attempt=1,
                             revision=rev, check_id="check").status == "holds"


def test_canonical_receipt_rejects_cross_execution_and_wrong_check(canonical_workspace):
    _, rev, _, verifier = canonical_workspace
    ref, _ = verifier.run(
        node_id="verify", execution_id="e", attempt=1,
        policy=make_command_policy("check", (sys.executable, "-c", "raise SystemExit(1)")),
        revision=rev,
    )
    with pytest.raises(ValueError, match="attempt identity"):
        verifier.validate(ref, node_id="verify", execution_id="foreign", attempt=1,
                          revision=rev, check_id="check")
    with pytest.raises(ValueError, match="provenance mismatch"):
        verifier.validate(ref, node_id="verify", execution_id="e", attempt=1,
                          revision=rev, check_id="wrong-check")


def test_repo_mutating_command_is_unverified_and_cannot_authorize_repair(canonical_workspace):
    binding, rev, _, verifier = canonical_workspace
    code = "from pathlib import Path;Path('source.py').write_text('TAMPER')"
    ref, receipt = verifier.run(
        node_id="verify", execution_id="e", attempt=1,
        policy=make_command_policy("unsafe", (sys.executable, "-c", code)),
        revision=rev,
    )
    assert receipt.status == "unverified"
    assert receipt.pre_repository_fingerprint != receipt.post_repository_fingerprint
    with pytest.raises(ValueError, match="canonical checker mutated repository"):
        verifier.validate(ref, node_id="verify", execution_id="e",
                          attempt=1, revision=rev, check_id="unsafe")


def test_compiler_command_policy_fingerprint_cannot_be_forged(canonical_workspace):
    with pytest.raises(ValueError, match="policy hash mismatch"):
        CanonicalCommandPolicy(check_id="verify", argv=("pytest", "-q"),
                               timeout_seconds=10, fingerprint="spoof")


def test_stale_revision_denies_command_before_execution(canonical_workspace):
    binding, rev, _, verifier = canonical_workspace
    stale = rev.model_copy(update={"repository_state_fingerprint": "stale"})
    with pytest.raises(ValueError, match="pre-state is stale"):
        verifier.run(node_id="verify", execution_id="e", attempt=1,
                     policy=make_command_policy("check", (sys.executable, "-c", "pass")),
                     revision=stale)
