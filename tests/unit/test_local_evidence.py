from __future__ import annotations
import hashlib
import json
import pytest
from pydantic import ValidationError

from aswe.core.contracts import AttemptEvidenceKind, TaskEvidenceKind, WorkspaceRevision
from aswe.evidence import EvidenceIntegrityError, LocalEvidenceStore


def revision():
    return WorkspaceRevision(
        generation=2, base_sha="a" * 40, head_sha="a" * 40,
        head_matches_baseline=True, repository_state_fingerprint="repo-2", dirty=True
    )


def test_attempt_evidence_persists_after_store_restart(tmp_path):
    store = LocalEvidenceStore(tmp_path / "runtime", workspace_root=tmp_path / "workspace")
    ref = store.put_attempt(
        task_id="aswe-task-1", node_id="node/complex", execution_id="exec-1", attempt=2,
        kind=AttemptEvidenceKind.VERIFICATION_RESULT, payload={"checks": [1, 2]},
        workspace_revision=revision(),
    )
    assert len(ref.content_sha256) == 64
    assert ref.workspace_revision_generation == 2
    assert LocalEvidenceStore(tmp_path / "runtime").get(ref) == {"checks": [1, 2]}


def test_task_evidence_uses_distinct_provenance_and_survives_restart(tmp_path):
    store = LocalEvidenceStore(tmp_path / "runtime")
    ref = store.put_task(
        task_id="aswe-task-1", finalization_id="aswe-final-1",
        kind=TaskEvidenceKind.FINAL_REPOSITORY_STATE,
        payload={"tree": "deadbeef"}, workspace_revision=revision(),
    )
    assert ref.task_id == "aswe-task-1"
    assert "source_node_id" not in type(ref).model_fields
    assert LocalEvidenceStore(tmp_path / "runtime").get(ref) == {"tree": "deadbeef"}


def test_unknown_workspace_evidence_remains_revision_independent(tmp_path):
    store = LocalEvidenceStore(tmp_path)
    ref = store.put_attempt(
        task_id="task", node_id="explorer", execution_id="exec", attempt=1,
        kind=AttemptEvidenceKind.REPORT_RECEIPT_VERDICT,
        payload={"resolved": False}, workspace_revision=None,
    )
    assert ref.workspace_revision_generation is None
    assert ref.workspace_state_fingerprint is None


def test_tamper_payload_is_detected_and_never_returned(tmp_path):
    store = LocalEvidenceStore(tmp_path)
    ref = store.put_attempt(
        task_id="task", node_id="writer", execution_id="exec", attempt=1,
        kind=AttemptEvidenceKind.REPOSITORY_CHANGESET, payload={"ok": True},
        workspace_revision=revision(),
    )
    artifact = store._artifact_path(ref.evidence_id)
    record = json.loads(artifact.read_text())
    record["payload"] = {"ok": False}
    artifact.write_text(json.dumps(record))
    with pytest.raises(EvidenceIntegrityError, match="content integrity"):
        store.get(ref)


def test_forged_reference_metadata_is_rejected(tmp_path):
    store = LocalEvidenceStore(tmp_path)
    ref = store.put_attempt(
        task_id="task", node_id="writer", execution_id="exec", attempt=1,
        kind=AttemptEvidenceKind.ACCEPTANCE_VERDICT, payload={"pass": True},
        workspace_revision=revision(),
    )
    forged = ref.model_copy(update={"source_attempt": 2})
    with pytest.raises(EvidenceIntegrityError, match="provenance"):
        store.get(forged)


def test_store_rejects_workspace_path_and_unsafe_id(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        LocalEvidenceStore(tmp_path / "workspace" / "data", workspace_root=tmp_path / "workspace")
    store = LocalEvidenceStore(tmp_path / "data")
    with pytest.raises(ValueError, match="unsafe"):
        store.put_task(
            task_id="../escape", finalization_id="final",
            kind=TaskEvidenceKind.FINAL_CONTRACT_VERDICT,
            payload={}, workspace_revision=None,
        )


def test_publish_cannot_silently_overwrite_existing_evidence(tmp_path, monkeypatch):
    store = LocalEvidenceStore(tmp_path)
    payload = dict(task_id="task", node_id="n", execution_id="e", attempt=1,
                   kind=AttemptEvidenceKind.ACCEPTANCE_VERDICT, payload={"x": 1},
                   workspace_revision=None)
    ref = store.put_attempt(**payload)
    monkeypatch.setattr(LocalEvidenceStore, "_new_id", staticmethod(lambda _: ref.evidence_id))
    with pytest.raises(Exception, match="collision"):
        store.put_attempt(**payload)
    assert store.get(ref) == {"x": 1}


def test_payload_canonicalization_and_hash_are_deterministic(tmp_path):
    store = LocalEvidenceStore(tmp_path)
    ref = store.put_task(
        task_id="task", finalization_id="final",
        kind=TaskEvidenceKind.FINAL_CONTRACT_VERDICT,
        payload={"b": [2, 1], "a": {"x": True}}, workspace_revision=None,
    )
    from aswe.core.fingerprint import canonical_json_bytes
    assert ref.content_sha256 == hashlib.sha256(
        canonical_json_bytes({"a": {"x": True}, "b": [2, 1]})
    ).hexdigest()
