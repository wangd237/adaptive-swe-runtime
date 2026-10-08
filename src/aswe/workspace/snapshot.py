"""Bounded deterministic filesystem observations; not a whole-sandbox oracle."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from aswe.core.contracts._base import FrozenModel
from aswe.core.fingerprint import fingerprint

_EXCLUDED = frozenset({
    ".git", ".venv", "venv", "node_modules", "build", "dist", "__pycache__",
    ".cache", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})


class SnapshotEntry(FrozenModel):
    path: str
    content_sha256: str | None
    kind: str
    mode: int


class FilesystemSnapshot(FrozenModel):
    entries: tuple[SnapshotEntry, ...]
    complete: bool
    fingerprint: str


def capture_filesystem_snapshot(root: str | Path, *, max_paths: int = 10000,
                                max_file_bytes: int = 10 * 1024 * 1024) -> FilesystemSnapshot:
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise ValueError("workspace root missing")
    if max_paths < 1 or max_file_bytes < 1:
        raise ValueError("scan limits must be positive")
    entries: list[SnapshotEntry] = []
    complete = True
    for current, dirs, files in os.walk(root_path, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _EXCLUDED)
        for filename in sorted(files + [d for d in dirs if (Path(current) / d).is_symlink()]):
            path = Path(current) / filename
            rel = path.relative_to(root_path).as_posix()
            if len(entries) >= max_paths:
                complete = False
                break
            try:
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    kind, raw = "symlink", os.readlink(path).encode("utf-8", "surrogateescape")
                elif stat.S_ISREG(info.st_mode) and info.st_size <= max_file_bytes:
                    kind, raw = "file", path.read_bytes()
                else:
                    complete = False
                    kind, raw = "unobserved", None
                digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
                entries.append(SnapshotEntry(path=rel, content_sha256=digest,
                                             kind=kind, mode=stat.S_IMODE(info.st_mode)))
            except OSError:
                complete = False
                entries.append(SnapshotEntry(path=rel, content_sha256=None,
                                             kind="unobserved", mode=0))
        if len(entries) >= max_paths:
            complete = False
            break
    result = tuple(sorted(entries, key=lambda x: x.path))
    return FilesystemSnapshot(entries=result, complete=complete, fingerprint=fingerprint({
        "entries": [entry.model_dump(mode="json") for entry in result],
        "complete": complete,
    }))


def changed_snapshot_paths(before: FilesystemSnapshot, after: FilesystemSnapshot) -> tuple[str, ...]:
    left = {x.path: x for x in before.entries}
    right = {x.path: x for x in after.entries}
    return tuple(sorted(p for p in left.keys() | right.keys() if left.get(p) != right.get(p)))
