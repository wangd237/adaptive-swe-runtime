"""Real-world LLM Explorer schema failure is advisory, not task-fatal."""
import subprocess
from pathlib import Path

import pytest

from aswe.integrations.deerflow.dev_llm_explorer import (
    execute_llm_explorer, ExplorerFinding,
)


class InvalidStructuredExplorer:
    def __init__(self):
        self.calls=0

    def with_structured_output(self,schema):
        assert schema is ExplorerFinding
        return self

    async def ainvoke(self,messages):
        self.calls+=1
        # The provider returns a well-formed JSON object missing required
        # schema fields on both standard and plain-text fallback paths.
        return {"relevant_paths":["code.py"]}


class FailedTransportExplorer:
    def with_structured_output(self,schema):
        return self

    async def ainvoke(self,messages):
        raise TimeoutError("offline simulated transport outage")


@pytest.fixture
def repo(tmp_path):
    root=tmp_path/"source"
    root.mkdir()
    subprocess.run(["git","init",str(root)],check=True,capture_output=True)
    (root/"code.py").write_text("def answer():\n    return 1\n")
    subprocess.run(["git","-C",str(root),"add","-A"],
                   check=True,capture_output=True)
    subprocess.run(["git","-C",str(root),
                    "-c","user.name=Test",
                    "-c","user.email=test@example.invalid",
                    "commit","-m","initial"],check=True,capture_output=True)
    return root


@pytest.mark.asyncio
async def test_invalid_llm_advice_degrades_to_real_git_index(repo):
    model=InvalidStructuredExplorer()
    finding=await execute_llm_explorer(
        repository=repo,ref="HEAD",task="Investigate code.py",
        explorer_factory=lambda:model)
    assert finding.used_index_fallback
    assert finding.relevant_paths==("code.py",)
    assert "invalid structured" in finding.diagnosis
    assert model.calls==2


@pytest.mark.asyncio
async def test_unreachable_provider_does_not_fall_back_silently(repo):
    with pytest.raises(TimeoutError):
        await execute_llm_explorer(
            repository=repo,ref="HEAD",task="Investigate code.py",
            explorer_factory=FailedTransportExplorer)


@pytest.mark.asyncio
async def test_valid_llm_explorer_preserves_full_advice(repo):
    class ValidModel:
        def with_structured_output(self,schema):
            return self
        async def ainvoke(self,messages):
            return ExplorerFinding(
                relevant_paths=("code.py",),
                diagnosis="Return value is inconsistent",
                suggested_approach="Inspect callers")
    finding=await execute_llm_explorer(
        repository=repo,ref="HEAD",task="Inspect code.py",
        explorer_factory=ValidModel)
    assert not finding.used_index_fallback
    assert finding.diagnosis=="Return value is inconsistent"
