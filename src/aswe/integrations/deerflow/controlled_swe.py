"""5F-C: explicitly approved SWE coding profile and isolated command boundary.

The profile does not trust DeerFlow's native host-bash flag, global sandbox
singleton, user-supplied absolute paths, or LLM-proposed tool implementations.
All tools are freshly constructed *after* Scheduler Commit from a pinned 5C
tool name/contract; the original 5C tool objects remain sealed and are never
invoked for mutations. Bash MUST delegate to a separately provisioned,
network-disabled container backend. A local shell is not a valid backend.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import os
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Protocol, Any

from aswe.core.contracts.backend import NodeExecutionInvocation
from aswe.core.contracts.workspace import WorkspaceAccess
from aswe.providers.policy import NodeExecutionPolicy

TOOLS = frozenset({"read_file", "write_file", "str_replace", "bash"})


class SWEExecutionDenied(RuntimeError):
    def __init__(self, code: str):
        self.code=code
        super().__init__(code)


@dataclass(frozen=True)
class ShellOutcome:
    exit_code: int | None
    output: str
    timed_out: bool = False


class IsolatedCommandBackend(Protocol):
    """Trusted host-owned adapter. Implementations must never invoke host Bash."""

    @property
    def isolation_kind(self) -> str: ...
    @property
    def workspace_root(self) -> Path: ...

    async def run(self, command: str, *, timeout: float, max_output: int) -> ShellOutcome: ...


class DockerCommandBackend:
    """Disposable no-network Docker process with only one writable repo mount.

    Image must be an immutable locally cached SHA256 reference (pull disabled).
    No host Docker socket, credentials, SSH auth, home or runtime data mounts.
    This is a development isolation policy, NOT a formal sandbox escape proof.
    """

    isolation_kind = "docker-no-network"

    def __init__(self, *, workspace_root: Path, image: str,
                 memory_mb: int = 512, pids_limit: int = 64):
        root=Path(workspace_root).resolve(strict=True)
        if (not root.is_dir() or not image or "@sha256:" not in image
                or any(ch.isspace() for ch in image)
                or memory_mb < 128 or memory_mb > 4096
                or pids_limit < 16 or pids_limit > 512):
            raise SWEExecutionDenied("SWE_DOCKER_CONFIGURATION_INVALID")
        self.workspace_root=root
        self.image=image
        self.memory_mb=memory_mb
        self.pids_limit=pids_limit

    async def run(self, command: str, *, timeout: float, max_output: int) -> ShellOutcome:
        if not isinstance(command,str) or not command.strip() or len(command)>10000:
            raise SWEExecutionDenied("SWE_COMMAND_INVALID")
        if timeout <= 0 or timeout > 120 or max_output < 1 or max_output > 64000:
            raise SWEExecutionDenied("SWE_COMMAND_BUDGET_INVALID")
        if self.workspace_root.resolve(strict=True) != self.workspace_root:
            raise SWEExecutionDenied("SWE_WORKSPACE_ROOT_DRIFT")
        # Docker CLI arguments are constructed by the Runtime, never the LLM.
        # The dynamic shell is INSIDE the disposable container only.
        if sys.platform != "linux":
            raise SWEExecutionDenied("SWE_DOCKER_PLATFORM_UNSUPPORTED")
        if "," in str(self.workspace_root):
            raise SWEExecutionDenied("SWE_DOCKER_WORKSPACE_PATH_INVALID")
        container_name="aswe-"+secrets.token_hex(12)
        args=[
            "docker","run","--rm","--pull=never","--network=none",
            "--name",container_name,
            "--read-only","--cap-drop=ALL","--security-opt=no-new-privileges",
            "--pids-limit",str(self.pids_limit),
            "--memory",f"{self.memory_mb}m","--cpus=1",
            "--user",f"{os.getuid()}:{os.getgid()}",
            "--mount",f"type=bind,src={self.workspace_root},dst=/workspace",
            "--tmpfs","/tmp:rw,nosuid,nodev,size=64m",
            "--workdir","/workspace",self.image,
            "/bin/sh","-lc",command,
        ]
        # Write to an unlinked host file, not a potentially unbounded
        # subprocess PIPE. A timeout/cancel also issues docker rm -f against
        # the Runtime-generated container identity (not a model argument).
        with tempfile.TemporaryFile(mode="w+b") as output:
            try:
                process=await asyncio.create_subprocess_exec(
                    *args,stdin=asyncio.subprocess.DEVNULL,
                    stdout=output,stderr=asyncio.subprocess.STDOUT,
                )
            except OSError:
                raise SWEExecutionDenied("SWE_DOCKER_UNAVAILABLE") from None
            try:
                try:
                    await asyncio.wait_for(process.wait(),timeout=timeout)
                    timed_out=False
                except asyncio.TimeoutError:
                    timed_out=True
                except asyncio.CancelledError:
                    timed_out=True
                    raise
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                if timed_out:
                    try:
                        cleaner=await asyncio.create_subprocess_exec(
                            "docker","rm","-f",container_name,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        cleanup_status=await asyncio.wait_for(cleaner.wait(),timeout=5)
                        if cleanup_status!=0:
                            raise SWEExecutionDenied("SWE_DOCKER_CLEANUP_UNVERIFIED")
                    except (OSError,asyncio.TimeoutError):
                        raise SWEExecutionDenied("SWE_DOCKER_CLEANUP_UNVERIFIED") from None
            output.seek(0)
            raw=output.read(max_output)
            return ShellOutcome(
                exit_code=None if timed_out else process.returncode,
                output=raw.decode("utf-8","replace"),
                timed_out=timed_out,
            )


class ControlledSWEWorkspace:
    """One committed execution's file operations + explicit isolated Bash.

    No unbounded host shell, implicit parent paths, symlinks, or global tool
    registries. This trusted host object is composed by the Runtime, not a
    model-requested object. File writes are attribution scoped to the
    Scheduler-owned worktree; existing files require current read-before-write.
    """

    def __init__(self, *, invocation: NodeExecutionInvocation,
                 policy: NodeExecutionPolicy, root: Path,
                 command_backend: IsolatedCommandBackend | None,
                 max_file_bytes: int = 80_000, max_output_chars: int = 12_000):
        if not isinstance(invocation,NodeExecutionInvocation) or not isinstance(policy,NodeExecutionPolicy):
            raise SWEExecutionDenied("SWE_AUTHORITY_UNATTESTED")
        if policy.node_id != invocation.node_id or policy.workspace_access is not WorkspaceAccess.WRITE:
            raise SWEExecutionDenied("SWE_WRITE_POLICY_REQUIRED")
        root=Path(root).resolve(strict=True)
        if not root.is_dir() or max_file_bytes<1 or max_file_bytes>1_000_000:
            raise SWEExecutionDenied("SWE_WORKSPACE_INVALID")
        if command_backend is not None and (
            getattr(command_backend,"isolation_kind",None) != "docker-no-network"
            or Path(command_backend.workspace_root).resolve(strict=True) != root
        ):
            raise SWEExecutionDenied("SWE_ISOLATED_BASH_BACKEND_REQUIRED")
        if "bash" in policy.allowed_business_tools and command_backend is None:
            raise SWEExecutionDenied("SWE_BASH_ISOLATION_REQUIRED")
        if "bash" in policy.allowed_business_tools and (
            policy.allowed_paths is not None or policy.forbidden_paths
        ):
            # A general shell inside the workspace can bypass per-file path
            # rules; until container-level submounts exist this is incompatible.
            raise SWEExecutionDenied("SWE_BASH_PATH_POLICY_UNSUPPORTED")
        self.invocation=invocation
        self.policy=policy
        self.root=root
        self.command_backend=command_backend
        self.max_file_bytes=max_file_bytes
        self.max_output_chars=max_output_chars
        self._reads: dict[str,str]={}
        self._changes: set[str]=set()

    def _path(self, value: str, *, create: bool=False) -> tuple[Path,str]:
        if not isinstance(value,str) or not value or "\x00" in value or "\\" in value:
            raise SWEExecutionDenied("SWE_PATH_INVALID")
        p=Path(value)
        if p.is_absolute():
            # Use /workspace as the only model-visible absolute path.
            try:rel=p.relative_to("/workspace")
            except ValueError:raise SWEExecutionDenied("SWE_PATH_OUTSIDE_WORKSPACE") from None
        else:
            rel=p
        if not rel.parts or any(part in ("..",".git") for part in rel.parts):
            raise SWEExecutionDenied("SWE_PATH_OUTSIDE_WORKSPACE")
        resolved=self.root.joinpath(*rel.parts)
        if not resolved.is_relative_to(self.root):
            raise SWEExecutionDenied("SWE_PATH_OUTSIDE_WORKSPACE")
        # Avoid following links to host files. This is a locked single-owner
        # worktree requirement; a hostile concurrent writer still needs OS
        # isolation and cannot be justified by Python path checks alone.
        current=self.root
        for part in rel.parts:
            current=current/part
            if current.is_symlink():
                raise SWEExecutionDenied("SWE_SYMLINK_PATH_FORBIDDEN")
        allowed=self.policy.allowed_paths
        name=rel.as_posix()
        if (allowed is not None and
                not any(name==x.rstrip("/") or name.startswith(x.rstrip("/")+"/") for x in allowed)):
            raise SWEExecutionDenied("SWE_PATH_NOT_ALLOWED")
        if any(name==x.rstrip("/") or name.startswith(x.rstrip("/")+"/")
               for x in self.policy.forbidden_paths):
            raise SWEExecutionDenied("SWE_PATH_FORBIDDEN")
        return resolved,name

    def _read(self,path:Path)->str:
        if not path.is_file():
            raise SWEExecutionDenied("SWE_FILE_MISSING")
        if path.stat().st_size > self.max_file_bytes:
            raise SWEExecutionDenied("SWE_FILE_TOO_LARGE")
        try:return path.read_text(encoding="utf-8")
        except (UnicodeError,OSError):raise SWEExecutionDenied("SWE_FILE_UNREADABLE") from None

    async def read_file(self, *, path: str, start_line: int|None=None,
                        end_line: int|None=None) -> str:
        target,name=self._path(path)
        source=self._read(target)
        self._reads[name]=hashlib.sha256(source.encode()).hexdigest()
        lines=source.splitlines(keepends=True)
        if start_line is not None or end_line is not None:
            a=start_line or 1; b=end_line or len(lines)
            if a<1 or b<a: raise SWEExecutionDenied("SWE_LINE_RANGE_INVALID")
            source="".join(lines[a-1:b])
        return source[:self.max_output_chars]

    def _write(self,target:Path,name:str,body:str)->str:
        if not isinstance(body,str) or len(body.encode("utf-8"))>self.max_file_bytes:
            raise SWEExecutionDenied("SWE_FILE_TOO_LARGE")
        if target.exists():
            old=self._read(target)
            if self._reads.get(name)!=hashlib.sha256(old.encode()).hexdigest():
                raise SWEExecutionDenied("SWE_READ_BEFORE_WRITE_REQUIRED")
        if self.policy.max_changed_files is not None and (
            name not in self._changes and len(self._changes)>=self.policy.max_changed_files
        ):
            raise SWEExecutionDenied("SWE_CHANGED_FILE_LIMIT_EXCEEDED")
        target.parent.mkdir(parents=True,exist_ok=True)
        target,name=self._path(name,create=True)
        try:
            # Opening with O_NOFOLLOW denies direct final-component symlinks.
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o644)
            with os.fdopen(fd,"w",encoding="utf-8") as out:out.write(body)
        except OSError:
            raise SWEExecutionDenied("SWE_WRITE_FAILED") from None
        self._reads.pop(name,None)
        self._changes.add(name)
        return f"updated {name}"

    async def write_file(self, *, path:str, content:str) -> str:
        target,name=self._path(path,create=True)
        if self.policy.max_changed_files is not None and (
            name not in self._changes and len(self._changes)>=self.policy.max_changed_files
        ):
            raise SWEExecutionDenied("SWE_CHANGED_FILE_LIMIT_EXCEEDED")
        return self._write(target,name,content)

    async def str_replace(self, *, path:str, old_str:str, new_str:str,
                          replace_all:bool=False) -> str:
        target,name=self._path(path)
        source=self._read(target)
        if not old_str or old_str not in source:
            raise SWEExecutionDenied("SWE_REPLACE_TARGET_NOT_FOUND")
        if not replace_all and source.count(old_str)!=1:
            raise SWEExecutionDenied("SWE_REPLACE_AMBIGUOUS")
        updated=source.replace(old_str,new_str, -1 if replace_all else 1)
        return self._write(target,name,updated)

    async def bash(self, *, command:str) -> str:
        if self.command_backend is None:
            raise SWEExecutionDenied("SWE_BASH_ISOLATION_REQUIRED")
        outcome=await self.command_backend.run(
            command, timeout=min(self.policy.timeout_seconds,60),
            max_output=self.max_output_chars,
        )
        # Output status must stay explicit; model can retry after a failure.
        return f"exit_code={outcome.exit_code}; timed_out={outcome.timed_out}\n{outcome.output}"

    def make_tools(self, original_names: tuple[str,...]) -> tuple[Any,...]:
        """Physical LangChain wrappers preserve pinned contract names exactly."""
        if any(name not in TOOLS or name not in self.policy.allowed_business_tools
               for name in original_names):
            raise SWEExecutionDenied("SWE_TOOL_NOT_IN_PROFILE")
        try:from langchain_core.tools import StructuredTool
        except ImportError:raise SWEExecutionDenied("SWE_LANGCHAIN_NOT_INSTALLED") from None
        specs={
            "read_file":(self.read_file,"Read UTF-8 source file in the isolated workspace."),
            "write_file":(self.write_file,"Write a source file after reading current contents."),
            "str_replace":(self.str_replace,"Replace exactly matching source text after read."),
            "bash":(self.bash,"Run a dynamically chosen command inside a network-disabled isolated container."),
        }
        return tuple(StructuredTool.from_function(
            coroutine=specs[name][0],name=name,description=specs[name][1]
        ) for name in original_names)
