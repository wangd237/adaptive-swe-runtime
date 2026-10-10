"""Real materializer + dependency-driven developer Scheduler semantics."""
import subprocess

import pytest

from aswe.integrations.deerflow.adaptive_team import TeamDecision
from aswe.integrations.deerflow.dev_execution_plan import compile_developer_workplan
from aswe.integrations.deerflow.dev_physical_dag import (
    DeveloperDagScheduler, PhysicalDeveloperDag)
from aswe.planning.dag import materialize_task_dag
from aswe.providers.inventory import fake_inventory
from aswe.providers.contracts import CapabilityBinding,provider
from aswe.providers.resolver import resolve_workplan


def compiled(tmp_path,need_explorer=True):
    repo=tmp_path/"source"
    repo.mkdir()
    subprocess.run(["git","init",str(repo)],capture_output=True,check=True)
    (repo/"code.py").write_text("x = 1\n")
    subprocess.run(["git","-C",str(repo),"add","-A"],check=True)
    subprocess.run(["git","-C",str(repo),"-c","user.name=CI",
                    "-c","user.email=ci@example.invalid","commit","-m","init"],
                   check=True,capture_output=True)
    roles=("explorer","coder","tester") if need_explorer else ("coder",)
    work=compile_developer_workplan(
        repository=repo,ref="HEAD",task="Fix code",
        workflow_id="workflow",decision=TeamDecision(
            roles=roles,reason="test",complexity="medium",evidence_paths=()),
        coder_objective="Fix code",explorer_objective="Explore code")
    # FakeInventory is confined to this *unit* test. Production physical
    # compilation observes actual pinned DeerFlow tool objects and Docker.
    inv=fake_inventory()
    ps=(
        provider("explorer",(CapabilityBinding(
            capability_id="repo_exploration",required_tools=("read_file",)),)),
        provider("coder",(CapabilityBinding(
            capability_id="code_modification",required_tools=("read_file","str_replace"),
            optional_tools=("bash",)),)),
        provider("tester",(CapabilityBinding(
            capability_id="regression_testing",required_tools=("bash",)),)),
    )
    selected={"coder":("bash",)}
    resolved=resolve_workplan(plan=work.plan,contract=work.contract,
        authority=work.authority,inventory=inv,providers=ps,
        selected_optional_by_node=selected)
    dag=materialize_task_dag(plan=work.plan,resolved=resolved,
                             inventory=inv,verification_check_ids=("cli-regression",))
    return DeveloperDagScheduler(PhysicalDeveloperDag(
        dag=dag,inventory_fingerprint=inv.fingerprint,
        resolved_fingerprint=resolved.fingerprint))


def test_scheduler_dispatches_actual_materialized_dag(tmp_path):
    scheduler=compiled(tmp_path)
    assert scheduler.physical.dag.topological_order==(
        "explorer","coder","__aswe_verify")
    with pytest.raises(ValueError,match="DEV_DAG_UPSTREAM_INCOMPLETE"):
        scheduler.dispatch("coder")
    assert scheduler.dispatch("explorer")==1
    scheduler.finish("explorer",verified=True)
    assert scheduler.dispatch("coder")==1
    scheduler.finish("coder",verified=True)
    assert scheduler.dispatch("__aswe_verify")==1
    scheduler.finish("__aswe_verify",verified=False)
    assert "__aswe_verify" not in scheduler.completed
    scheduler.reset_for_repair()
    assert scheduler.dispatch("coder")==2
    scheduler.finish("coder",verified=True)
    assert scheduler.dispatch("__aswe_verify")==2
    scheduler.finish("__aswe_verify",verified=True)
    assert scheduler.completed=={"explorer","coder","__aswe_verify"}


def test_minimal_coder_dag_has_no_explorer(tmp_path):
    scheduler=compiled(tmp_path,False)
    assert scheduler.physical.dag.topological_order==(
        "coder","__aswe_verify")
    assert scheduler.dispatch("coder")==1
    scheduler.finish("coder",verified=True)
    assert scheduler.dispatch("__aswe_verify")==1
    assert scheduler.physical.dag.verification_repair_bindings
