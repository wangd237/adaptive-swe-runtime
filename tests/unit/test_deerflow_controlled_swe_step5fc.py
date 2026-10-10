"""5F-C controlled workspace tools; deterministic provider-neutral tests.

A synthetic command backend is ONLY a test double; no test below attests
Docker isolation or native DeerFlow actual remote model credentials.
"""
import asyncio
from dataclasses import dataclass
from pathlib import Path
import pytest

from aswe.core.contracts.workspace import WorkspaceAccess
from aswe.core.fingerprint import fingerprint
from aswe.integrations.deerflow.controlled_swe import (
    ControlledSWEWorkspace, SWEExecutionDenied, ShellOutcome, DockerCommandBackend,
)
from tests.unit.test_step4_live_preflight_descriptor import artifacts
from tests.unit.test_deerflow_execution_evidence_step5f import invocation
from tests.unit.test_node_workspace_delta import repository as repository_fixture


class SyntheticSandbox:
    isolation_kind="docker-no-network"

    def __init__(self, root):
        self.workspace_root=Path(root).resolve()
        self.commands=[]
    async def run(self,command,*,timeout,max_output):
        self.commands.append((command,timeout,max_output))
        return ShellOutcome(exit_code=0,output="synthetic sandbox result")


def policy(*,tools=("read_file","write_file","str_replace","bash"),
           allowed_paths=None,forbidden_paths=(),max_changed_files=None):
    *_,policies,descriptor=artifacts(
        ("writer",__import__("aswe.core.contracts.task",fromlist=["WorkKind"]).WorkKind.IMPLEMENTATION,
         "code_modification"),
    )
    base=policies[0]
    fields=base.model_dump(mode="python",exclude={"fingerprint"})
    fields.update(
        allowed_business_tools=tools,required_business_tools=tuple(),
        denied_tools=tuple(),workspace_access=WorkspaceAccess.WRITE,
        allowed_paths=allowed_paths,forbidden_paths=forbidden_paths,
        max_changed_files=max_changed_files,
        verification_exact_commands=tuple(),canonical_check_policy_fingerprints=tuple(),
    )
    return type(base)(**fields,fingerprint=fingerprint(fields))


def env(repo, *,tools=("read_file","write_file","str_replace","bash"),
        runner=True,allowed_paths=None,forbidden_paths=(),max_changed_files=None):
    p=policy(tools=tools,allowed_paths=allowed_paths,
             forbidden_paths=forbidden_paths,max_changed_files=max_changed_files)
    i=invocation(repo).model_copy(update={"node_id":p.node_id})
    sandbox=SyntheticSandbox(repo.repository_root) if runner else None
    workspace=ControlledSWEWorkspace(
        invocation=i,policy=p,root=repo.repository_root,command_backend=sandbox,
    )
    return workspace,sandbox


@pytest.mark.asyncio
async def test_read_edit_and_isolated_dynamic_bash(repository_fixture):
    root=Path(repository_fixture.repository_root)
    (root/"module.py").write_text("def answer():\n    return 1\n")
    workspace,sandbox=env(repository_fixture)
    assert "return 1" in await workspace.read_file(path="/workspace/module.py")
    changed=await workspace.str_replace(
        path="/workspace/module.py",old_str="return 1",new_str="return 42"
    )
    assert changed=="updated module.py"
    assert "return 42" in (root/"module.py").read_text()
    assert "exit_code=0" in await workspace.bash(command="python -m unittest")
    assert sandbox.commands[0][0]=="python -m unittest"
    # Write back requires fresh read (no stale snapshot).
    with pytest.raises(SWEExecutionDenied,match="SWE_READ_BEFORE_WRITE_REQUIRED"):
        await workspace.write_file(path="module.py",content="return 0")
    await workspace.read_file(path="module.py")
    await workspace.write_file(path="module.py",content="return 43")
    assert (root/"module.py").read_text()=="return 43"


@pytest.mark.asyncio
async def test_file_path_escape_symlink_git_and_protected_paths_denied(repository_fixture,tmp_path):
    ws,_=env(repository_fixture,tools=("read_file","write_file","str_replace"),
             runner=False,forbidden_paths=("secret",))
    root=Path(repository_fixture.repository_root)
    outside=tmp_path/"outside.txt"
    outside.write_text("do not overwrite")
    (root/"link.py").symlink_to(outside)
    for name in ("../outside.txt","/etc/passwd","/workspace/.git/config",
                 "link.py","secret/credential.txt"):
        with pytest.raises(SWEExecutionDenied):
            await ws.write_file(path=name,content="untrusted")
    assert outside.read_text()=="do not overwrite"
    assert not (root/"secret").exists()


@pytest.mark.asyncio
async def test_write_requires_fresh_read_and_limit_applies_before_mutation(repository_fixture):
    ws,_=env(repository_fixture,tools=("read_file","write_file","str_replace"),
             runner=False,max_changed_files=1)
    root=Path(repository_fixture.repository_root)
    await ws.write_file(path="one.py",content="x = 1")
    with pytest.raises(SWEExecutionDenied,match="SWE_CHANGED_FILE_LIMIT_EXCEEDED"):
        await ws.write_file(path="two.py",content="x = 2")
    assert not (root/"two.py").exists()
    (root/"unchanged.py").write_text("x = 1")
    with pytest.raises(SWEExecutionDenied,match="SWE_READ_BEFORE_WRITE_REQUIRED"):
        await ws.str_replace(path="unchanged.py",old_str="1",new_str="3")
    await ws.read_file(path="unchanged.py")
    with pytest.raises(SWEExecutionDenied,match="SWE_CHANGED_FILE_LIMIT_EXCEEDED"):
        await ws.str_replace(path="unchanged.py",old_str="1",new_str="3")
    assert (root/"unchanged.py").read_text()=="x = 1"


@pytest.mark.asyncio
async def test_bash_disabled_when_isolation_or_file_specific_policy_unavailable(repository_fixture):
    with pytest.raises(SWEExecutionDenied,match="SWE_BASH_ISOLATION_REQUIRED"):
        env(repository_fixture,runner=False)
    with pytest.raises(SWEExecutionDenied,match="SWE_BASH_FINE_GRAINED_POLICY_UNSUPPORTED"):
        env(repository_fixture,allowed_paths=("src",))
    with pytest.raises(SWEExecutionDenied,match="SWE_BASH_FINE_GRAINED_POLICY_UNSUPPORTED"):
        env(repository_fixture,forbidden_paths=("secret",))
    with pytest.raises(SWEExecutionDenied,match="SWE_BASH_FINE_GRAINED_POLICY_UNSUPPORTED"):
        env(repository_fixture,max_changed_files=1)


@pytest.mark.asyncio
async def test_policy_and_runtime_identity_required(repository_fixture):
    root=Path(repository_fixture.repository_root)
    p=policy(tools=("read_file","write_file"))
    inv=invocation(repository_fixture).model_copy(update={"node_id":"wrong"})
    with pytest.raises(SWEExecutionDenied,match="SWE_WRITE_POLICY_REQUIRED"):
        ControlledSWEWorkspace(invocation=inv,policy=p,root=root,
                               command_backend=None)
    ws,_=env(repository_fixture,tools=("read_file","write_file"),runner=False)
    assert ws.invocation.node_id==p.node_id


def test_docker_backend_never_accepts_unpinned_tag_or_host_command(repository_fixture):
    root=Path(repository_fixture.repository_root)
    for image in ("python:3.12-alpine","", "python:3.12 @sha256:fake"):
        with pytest.raises(SWEExecutionDenied,match="SWE_DOCKER_CONFIGURATION_INVALID"):
            DockerCommandBackend(workspace_root=root,image=image)


def test_swe_binding_store_requires_explicit_scheduler_workspace_root():
    from aswe.integrations.deerflow.tool_guard import NodeExecutionBindingStore
    from tests.unit.test_deerflow_preparation_step5c import setup
    prep,_,_,_=setup()
    with pytest.raises(ValueError,match="Scheduler Workspace root required"):
        NodeExecutionBindingStore(
            preparation_backend=prep,principal_supplier=lambda _:None,
            provider_supplier=lambda _:None,auth_request_factory=lambda **kw:kw,
            execution_live_checker=lambda _:True,
            swe_workspace_factory=lambda inv,res,pol:None,
        )
