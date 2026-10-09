"""Bounded deterministic Git-at-HEAD repository reconnaissance.

The collector never reads uncommitted worktree content, executes project code,
or uses shell interpolation. A profile is pinned to the exact inspected commit.
"""
from __future__ import annotations
import re
import subprocess
from pathlib import Path
from aswe.planning.profile import AnchorMatch, RepositoryProfile

LANG_EXT={".py":"Python",".ts":"TypeScript",".tsx":"TypeScript",".js":"JavaScript",
          ".go":"Go",".rs":"Rust",".java":"Java",".cpp":"C++",".c":"C",".md":"Markdown"}
MANIFESTS={"pyproject.toml","package.json","Cargo.toml","go.mod","requirements.txt","setup.cfg","pom.xml"}
TESTS={"pytest.ini","tox.ini","jest.config.js","vitest.config.ts","pyproject.toml"}
BUILDS={"Makefile","Dockerfile","CMakeLists.txt","build.gradle","pyproject.toml"}
GUIDES={"AGENTS.md","CONTRIBUTING.md","CLAUDE.md","README.md"}
_RE_ANCHOR=re.compile(r"[A-Za-z_][A-Za-z_0-9./:-]{3,100}")

class RepositoryProfileError(ValueError):
    pass


def _git(root: Path, *args: str, max_bytes: int = 2000000) -> bytes:
    r=subprocess.run(["git","-C",str(root),*args], stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, timeout=10, check=False)
    if r.returncode:
        raise RepositoryProfileError("git snapshot unavailable")
    if len(r.stdout)>max_bytes:
        raise RepositoryProfileError("git inventory exceeds fixed budget")
    return r.stdout


def collect_repository_profile(root: str | Path, *, task_text: str = "",
                               base_sha: str | None = None, max_paths: int = 4096,
                               max_anchors: int = 12, max_probe_files: int = 48,
                               max_blob_bytes: int = 65536) -> RepositoryProfile:
    if min(max_paths,max_anchors,max_probe_files,max_blob_bytes) < 1:
        raise ValueError("positive budgets required")
    path=Path(root).resolve()
    head=_git(path,"rev-parse","HEAD").decode("ascii").strip()
    if base_sha is not None and head != base_sha:
        raise RepositoryProfileError("repository HEAD changed from requested base")
    # HEAD committed tree, not mutable Git index or worktree.
    records=_git(path,"ls-tree","-r","--name-only","-z",head,
                 max_bytes=2000000).decode("utf-8").split("\x00")
    names=sorted(x for x in records if x)
    truncated=len(names)>max_paths
    bounded=names[:max_paths]
    groups={x.split("/",1)[0] for x in bounded}
    languages:dict[str,int]={}
    for name in bounded:
        lang=LANG_EXT.get(Path(name).suffix)
        if lang: languages[lang]=languages.get(lang,0)+1
    def candidates(basenames: set[str]) -> tuple[str,...]:
        return tuple(x for x in bounded if Path(x).name in basenames)
    ci=tuple(x for x in bounded if x.startswith(".github/workflows/") or x==".gitlab-ci.yml")
    test_configs=candidates(TESTS)
    manifests=candidates(MANIFESTS)
    build_configs=candidates(BUILDS)
    framework=tuple(x for x,cond in (("pytest",any(Path(t).name in {"pytest.ini","pyproject.toml","tox.ini"} for t in test_configs)),
                                     ("jest",any("jest.config" in t for t in test_configs)))
                    if cond)
    anchors=tuple(dict.fromkeys(m.group(0) for m in _RE_ANCHOR.finditer(task_text)))[:max_anchors]
    matches:list[AnchorMatch]=[]
    budget=0
    for anchor in anchors:
        lower=anchor.lower()
        for name in bounded:
            if lower in name.lower():
                matches.append(AnchorMatch(anchor=anchor,match_kind="path",path=name))
                if len(matches)>=max_anchors: break
        if len(matches)>=max_anchors: break
    if len(matches)<max_anchors:
        # Only small, text-like source blobs pinned to HEAD; never execute.
        for name in bounded:
            if budget>=max_probe_files: break
            if Path(name).suffix.lower() not in LANG_EXT: continue
            budget+=1
            raw=_git(path,"show",f"{head}:{name}",max_bytes=max_blob_bytes+1)
            if len(raw)>max_blob_bytes:
                truncated=True
                continue
            for no,line in enumerate(raw.decode("utf-8","replace").splitlines(),1):
                for anchor in anchors:
                    if anchor in line and not any(x.path==name and x.anchor==anchor for x in matches):
                        matches.append(AnchorMatch(anchor=anchor,match_kind="string",path=name,
                                                   line=no,context=line[:180]))
                        if len(matches)>=max_anchors:break
                if len(matches)>=max_anchors:break
            if len(matches)>=max_anchors:break
        if budget>=max_probe_files and len(bounded)>budget:truncated=True
    return RepositoryProfile(base_sha=head, tracked_file_count=len(names),
        top_level_tree=tuple(sorted(groups)),languages=dict(sorted(languages.items())),
        manifests=manifests,test_configs=test_configs,build_configs=build_configs,
        ci_configs=ci,guidance_files=candidates(GUIDES),
        test_framework_hints=framework,
        build_system_hints=tuple(x for x,ok in (("make",bool(candidates({"Makefile"}))),
                                                    ("python",bool(candidates({"pyproject.toml"}))),
                                                    ("npm",bool(candidates({"package.json"})))) if ok),
        task_anchor_matches=tuple(matches),truncated=truncated)
