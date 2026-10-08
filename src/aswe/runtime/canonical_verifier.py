"""Runtime-owned canonical command verification (Step 2, FakeBackend-first).

A checker result is produced by an actual foreground argv execution, not a
model report, and bound to exact attempt/repository provenance. This local
adapter does not claim DeerFlow command-policy or sandbox compatibility.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import subprocess
from threading import RLock
from typing import Literal
from pydantic import Field, model_validator

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts import AttemptEvidenceKind, EvidenceRef, WorkspaceRevision
from aswe.core.fingerprint import canonical_json_bytes, fingerprint
from aswe.core.ids import validate_safe_id
from aswe.evidence import LocalEvidenceStore
from aswe.repository import RepositoryBinding, capture_repository_state


class CanonicalCommandPolicy(FrozenModel):
    check_id: str
    argv: tuple[str, ...]
    timeout_seconds: float = Field(default=15, gt=0, le=180)
    fingerprint: str

    @model_validator(mode="after")
    def validate_policy(self):
        if not self.check_id or not self.argv or any(not arg or "\x00" in arg for arg in self.argv):
            raise ValueError("canonical verification requires exact argv")
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("canonical command policy hash mismatch")
        return self


def make_command_policy(check_id: str, argv: tuple[str, ...], timeout_seconds: float = 15):
    fields = dict(check_id=check_id, argv=argv, timeout_seconds=timeout_seconds)
    return CanonicalCommandPolicy(**fields, fingerprint=fingerprint(fields))


class CanonicalCommandReceipt(FrozenModel):
    task_id: str
    node_id: str
    execution_id: str
    attempt: int = Field(ge=1)
    check_id: str
    command_policy_fingerprint: str
    argv_fingerprint: str
    returncode: int | None
    timed_out: bool
    stdout_sha256: str
    stderr_sha256: str
    pre_repository_fingerprint: str
    post_repository_fingerprint: str
    observed_revision: WorkspaceRevision
    status: Literal["holds", "failed", "unverified"]
    fingerprint: str
    attestation_hmac: str

    @model_validator(mode="after")
    def validate_fingerprint(self):
        data = self.model_dump(mode="json", exclude={"fingerprint", "attestation_hmac"})
        if self.fingerprint != fingerprint(data):
            raise ValueError("canonical command receipt digest invalid")
        return self


class CanonicalVerifier:
    """Single-task local verifier with a Runtime-private attestation key.

    The HMAC is an accidental/tamper and provenance barrier, not a security
    boundary against an attacker with arbitrary Runtime filesystem access.
    """

    def __init__(self, *, task_id: str, runtime_data_dir: str | Path,
                 evidence_store: LocalEvidenceStore, binding: RepositoryBinding):
        validate_safe_id(task_id)
        self.task_id = task_id
        self.binding = binding
        self.store = evidence_store
        data_root = Path(runtime_data_dir).resolve()
        workspace = Path(binding.repository_root).resolve()
        if data_root == workspace or data_root.is_relative_to(workspace):
            raise ValueError("canonical attestation must be outside agent workspace")
        path = data_root / "tasks" / task_id / "canonical_verifier.key"
        path.parent.mkdir(parents=True, exist_ok=True)
        with RLock():
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as file:
                    file.write(os.urandom(32))
                    file.flush()
                    os.fsync(file.fileno())
            except FileExistsError:
                pass
        self._key = path.read_bytes()
        if len(self._key) != 32:
            raise RuntimeError("invalid canonical verifier secret")

    def _mac(self, digest: str) -> str:
        return hmac.new(self._key, digest.encode("ascii"), hashlib.sha256).hexdigest()

    def run(self, *, node_id: str, execution_id: str, attempt: int,
            policy: CanonicalCommandPolicy, revision: WorkspaceRevision) -> tuple[EvidenceRef, CanonicalCommandReceipt]:
        """Executes exact policy argv; captures Git BEFORE and AFTER; no shell."""
        if not node_id or not execution_id or attempt < 1:
            raise ValueError("attempt provenance required")
        before = capture_repository_state(self.binding)
        if (revision.repository_state_fingerprint != before.fingerprint
                or revision.head_sha != before.head_sha
                or revision.base_sha != before.base_sha):
            raise ValueError("canonical verification pre-state is stale")
        timed_out = False
        returncode = None
        stdout = b""
        stderr = b""
        try:
            proc = subprocess.run(
                list(policy.argv), cwd=self.binding.repository_root, shell=False,
                capture_output=True, timeout=policy.timeout_seconds, check=False,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
            returncode = proc.returncode
            stdout, stderr = proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
        except OSError as exc:
            timed_out = True
            stderr = type(exc).__name__.encode()
        after = capture_repository_state(self.binding)
        unchanged = before.fingerprint == after.fingerprint
        status = "unverified" if timed_out or not unchanged else "holds" if returncode == 0 else "failed"
        fields = dict(
            task_id=self.task_id, node_id=node_id, execution_id=execution_id,
            attempt=attempt, check_id=policy.check_id,
            command_policy_fingerprint=policy.fingerprint,
            argv_fingerprint=fingerprint(policy.argv), returncode=returncode,
            timed_out=timed_out,
            stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            stderr_sha256=hashlib.sha256(stderr).hexdigest(),
            pre_repository_fingerprint=before.fingerprint,
            post_repository_fingerprint=after.fingerprint,
            observed_revision=revision, status=status,
        )
        digest = fingerprint(fields)
        receipt = CanonicalCommandReceipt(
            **fields, fingerprint=digest, attestation_hmac=self._mac(digest)
        )
        ref = self.store.put_attempt(
            task_id=self.task_id, node_id=node_id, execution_id=execution_id,
            attempt=attempt, kind=AttemptEvidenceKind.TOOL_RECEIPT_LEDGER,
            payload=receipt, workspace_revision=revision,
        )
        return ref, receipt

    def validate(self, ref: EvidenceRef, *, node_id: str, execution_id: str,
                 attempt: int, revision: WorkspaceRevision,
                 check_id: str) -> CanonicalCommandReceipt:
        if ref.kind is not AttemptEvidenceKind.TOOL_RECEIPT_LEDGER:
            raise ValueError("not a canonical tool ledger evidence reference")
        if (ref.source_node_id, ref.source_execution_id, ref.source_attempt) != (
            node_id, execution_id, attempt
        ):
            raise ValueError("canonical tool receipt attempt identity mismatch")
        if (ref.workspace_state_fingerprint != revision.repository_state_fingerprint
                or ref.workspace_revision_generation != revision.generation):
            raise ValueError("canonical tool receipt workspace revision mismatch")
        parsed = CanonicalCommandReceipt.model_validate(self.store.get(ref))
        if (parsed.task_id != self.task_id or parsed.node_id != node_id
                or parsed.execution_id != execution_id or parsed.attempt != attempt
                or parsed.check_id != check_id or parsed.observed_revision != revision):
            raise ValueError("canonical receipt payload provenance mismatch")
        if not hmac.compare_digest(parsed.attestation_hmac, self._mac(parsed.fingerprint)):
            raise ValueError("invalid Runtime canonical tool attestation")
        if (parsed.pre_repository_fingerprint != revision.repository_state_fingerprint
                or parsed.post_repository_fingerprint != revision.repository_state_fingerprint):
            raise ValueError("canonical checker mutated repository")
        if parsed.status == "failed" and (parsed.returncode is None or parsed.returncode == 0 or parsed.timed_out):
            raise ValueError("contradictory canonical failure verdict")
        return parsed
