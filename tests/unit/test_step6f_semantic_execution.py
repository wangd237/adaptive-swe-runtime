"""Step 6F real semantic plan compiler and independent Explorer boundaries."""
import subprocess

import pytest

from aswe.integrations.deerflow.adaptive_team import TeamDecision
from aswe.integrations.deerflow.dev_execution_plan import compile_developer_workplan
from aswe.integrations.deerflow.dev_llm_explorer import (
    ExplorerFinding, execute_llm_explorer,
)


@pytest.fixture
def committed_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git","init",str(root)],check=True,capture_output=True)
    for name in ("orders.py","inventory.py"):
        (root/name).write_text("def answer():\n    return 1\n")
    subprocess.run(["git","-C",str(root),"add","-A"],check=True)
    subprocess.run(["git","-C",str(root),"-c","user.name=CI",
                    "-c","user.email=ci@example.invalid",
                    "commit","-m","baseline"],check=True,capture_output=True)
    return root


def compile_for(repo, explorer):
    return compile_developer_workplan(
        repository=repo,ref="HEAD",task="Fix orders bug",workflow_id="task-test",
        decision=TeamDecision(
            roles=("explorer","coder","tester") if explorer else ("coder",),
            reason="test",complexity="medium" if explorer else "low",
            evidence_paths=()),
        coder_objective="Fix orders bug", explorer_objective="Explore orders.py")


def test_semantic_plan_is_validated_and_enforces_dependent_stages(committed_repo):
    plan = compile_for(committed_repo,True)
    assert plan.node_ids == ("explorer","coder","__aswe_verify")
    assert plan.plan.items[1].depends_on == ("explorer",)
    assert plan.plan.items[2].depends_on == ("coder",)
    assert plan.plan.items[2].runtime_owned
    with pytest.raises(ValueError,match="DEV_WORK_DEPENDENCY_NOT_SATISFIED"):
        plan.require_ready("coder",set())
    plan.require_ready("explorer",set())
    plan.require_ready("coder",{"explorer"})
    plan.require_ready("__aswe_verify",{"explorer","coder"})
    assert len(plan.plan.fingerprint)==64
    assert len(plan.contract_fingerprint)==64


def test_semantic_plan_minimal_team_preserves_canonical_gate(committed_repo):
    plan = compile_for(committed_repo,False)
    assert plan.node_ids==("coder","__aswe_verify")
    assert plan.plan.items[1].depends_on==("coder",)


class ExplorerModel:
    def __init__(self):
        self.prompts=[]
    def with_structured_output(self, schema):
        assert schema is ExplorerFinding
        return self
    async def ainvoke(self, messages):
        self.prompts.append(messages)
        return ExplorerFinding(
            relevant_paths=("orders.py","../../.env"),
            diagnosis="Orders returns the wrong value",
            suggested_approach="Inspect the callers and fix the return value")


@pytest.mark.asyncio
async def test_llm_explorer_reads_real_source_but_rejects_fabricated_paths(committed_repo):
    model=ExplorerModel()
    result=await execute_llm_explorer(
        repository=committed_repo,ref="HEAD",
        task="Investigate regression in orders.py",
        explorer_factory=lambda:model)
    assert result.relevant_paths==("orders.py",)
    assert "orders.py" in str(model.prompts)
    assert "return 1" in str(model.prompts)
    assert "../../.env" not in result.relevant_paths
    assert result.diagnosis=="Orders returns the wrong value"
