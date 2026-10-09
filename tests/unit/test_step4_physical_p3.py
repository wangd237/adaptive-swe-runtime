"""Frozen P3 physical Step-4 integrations: real TaskDAG, Scheduler and Git."""
import pytest
from pathlib import Path

from aswe.core.contracts.task import WorkKind
from aswe.core.contracts.workspace import WorkspaceAccess
from aswe.planning.contracts import make_task_request
from aswe.planning.compiler import ConstraintCompiler,RuntimePolicyConfig,RuntimePolicyRule
from aswe.planning.planner import WorkPlanProposal,WorkItemProposal
from aswe.planning.validator import SemanticPlanValidator
from aswe.planning.dag import materialize_task_dag
from aswe.providers.contracts import provider,CapabilityBinding
from aswe.providers.inventory import fake_inventory,BackendToolInfo
from aswe.providers.resolver import resolve_workplan,ProviderFeasibilityError
from aswe.providers.invariants import PostNodeGitInvariantBackend
from aswe.capabilities.effects import ToolEffect
from aswe.core.contracts.backend import BackendTerminalStatus
from aswe.runtime.state import NodeLogicalStatus
from aswe.repository import capture_repository_state
from tests.fakes import FakeExecutionBackend,FakeExecutionScenario,MutationEvidence
from tests.unit.test_scheduler_foundation import scheduler,accept
from tests.unit.test_canonical_verifier import canonical_workspace


def stage4_providers(*,optional_bash=False):
    return (
        provider("coder",(CapabilityBinding(
            capability_id="code_modification",required_tools=("read_file","str_replace"),
        ),)),
        provider("explorer",(CapabilityBinding(
            capability_id="repo_exploration",required_tools=("read_file",),
            optional_tools=("bash",) if optional_bash else (),
        ),)),
        provider("reviewer",(CapabilityBinding(
            capability_id="code_review",required_tools=("read_file",),
        ),)),
        provider("tester",(CapabilityBinding(
            capability_id="regression_testing",required_tools=("bash",),
        ),)),
    )


def item(id,kind,cap,claims=(),deps=()):
    return WorkItemProposal(id=id,objective=id,work_kind=kind,
        capability_hints=(cap,),coverage_claims=claims,depends_on=deps)


def build(*descriptions,needs_mutation=True,optional_bash=False):
    rules=(RuntimePolicyRule(key="deliverables.required",
           value={"effect":"repository_mutation","description":"fix"}),
          ) if needs_mutation else ()
    c,authority=ConstraintCompiler(RuntimePolicyConfig(
        policy_id="p4",rules=rules,
    )).compile(request=make_task_request(request_id="p4",raw_text="stage4 test"),
              repository_base_sha="a"*40)
    grant=next((x.id for x in c.constraints if x.key=="deliverables.required"),None)
    reqs=tuple(item(id,kind,cap,claims=(grant,) if cap=="code_modification" else ())
               for id,kind,cap in descriptions)
    plan=SemanticPlanValidator().validate(
        proposal=WorkPlanProposal(items=reqs,rationale="neutral"),
        contract=c,authority=authority,
    )
    resolved=resolve_workplan(plan=plan,contract=c,authority=authority,
         providers=stage4_providers(optional_bash=optional_bash),
         inventory=fake_inventory())
    dag=materialize_task_dag(plan=plan,resolved=resolved)
    return c,plan,resolved,dag


def node(dag,name):return next(x for x in dag.nodes if x.id==name)


def test_p3_01_02_03_materialized_phase_edges_and_physical_workspace_effect():
    c,p,res,dag=build(
        ("explore",WorkKind.DISCOVERY,"repo_exploration"),
        ("writer",WorkKind.IMPLEMENTATION,"code_modification"),
        ("tester",WorkKind.VERIFICATION,"regression_testing"),
        ("reviewer",WorkKind.REVIEW,"code_review"),
    )
    assert node(dag,"writer").dependencies==("explore",)
    assert "writer" in node(dag,"tester").dependencies
    assert "tester" in node(dag,"reviewer").dependencies
    assert node(dag,"explore").workspace_access is WorkspaceAccess.READ
    assert node(dag,"writer").workspace_access is WorkspaceAccess.WRITE
    assert node(dag,"tester").workspace_access is WorkspaceAccess.WRITE  # bash!
    assert node(dag,"tester").work_kind is WorkKind.VERIFICATION
    assert node(dag,"reviewer").workspace_access is WorkspaceAccess.READ
    assert dag.topological_order==("explore","writer","tester","reviewer")
    assert materialize_task_dag(plan=p,resolved=res)==dag


@pytest.mark.asyncio
async def test_p3_01_02_03_real_scheduler_stage_barriers(tmp_path):
    _,_,_,dag=build(
        ("explore",WorkKind.DISCOVERY,"repo_exploration"),
        ("writer",WorkKind.IMPLEMENTATION,"code_modification"),
        ("tester",WorkKind.VERIFICATION,"regression_testing"),
        ("reviewer",WorkKind.REVIEW,"code_review"),
    )
    core,_=scheduler(tmp_path,*dag.nodes)
    assert core.states["writer"].logical_status is NodeLogicalStatus.PENDING
    for predecessor,next_item in (("explore","writer"),("writer","tester"),("tester","reviewer")):
        assert core.states[predecessor].logical_status is NodeLogicalStatus.READY
        await core.run_claim(await core.claim(predecessor),
            FakeExecutionBackend([FakeExecutionScenario()]),accept=accept)
        assert core.states[predecessor].logical_status is NodeLogicalStatus.SUCCEEDED
        assert core.states[next_item].logical_status is NodeLogicalStatus.READY


@pytest.mark.asyncio
async def test_p3_04_ordinal_physical_writes_are_deterministically_serialized(tmp_path):
    c,p,res,dag=build(
        ("a_writer",WorkKind.IMPLEMENTATION,"code_modification"),
        ("b_writer",WorkKind.IMPLEMENTATION,"code_modification"),
    )
    assert node(dag,"a_writer").dependencies==()
    assert node(dag,"b_writer").dependencies==("a_writer",)
    assert dag.topological_order==("a_writer","b_writer")
    assert materialize_task_dag(plan=p,resolved=res).fingerprint==dag.fingerprint
    core,_=scheduler(tmp_path,*dag.nodes)
    assert core.states["b_writer"].logical_status is NodeLogicalStatus.PENDING
    await core.run_claim(await core.claim("a_writer"),
        FakeExecutionBackend([FakeExecutionScenario()]),accept=accept)
    assert core.states["b_writer"].logical_status is NodeLogicalStatus.READY


def test_optional_bash_does_not_upgrade_explorer_read_access():
    _,_,res,dag=build(("explorer",WorkKind.DISCOVERY,"repo_exploration"),
                      needs_mutation=False,optional_bash=True)
    physical=res.nodes[0]
    assert physical.workspace_access is WorkspaceAccess.READ
    assert physical.selected_optional_tools==()
    assert physical.allowed_tools==("read_file",)


def test_fake_inventory_alias_does_not_self_authorize_read_only():
    from aswe.providers.inventory import BackendInventorySnapshot,inventory_fingerprint
    _,plan,res,_=build(("explorer",WorkKind.DISCOVERY,"repo_exploration"),
                       needs_mutation=False)
    inv=fake_inventory()
    spoof=inv.candidate_tools["read_file"].model_copy(update={
        "implementation_id":"extension:malicious",
        "effect":ToolEffect.READ_ONLY,
    })
    body=inv.model_dump(mode="json",exclude={"fingerprint"})
    body["candidate_tools"]["read_file"]=spoof.model_dump(mode="json")
    forged=BackendInventorySnapshot(**body,fingerprint=inventory_fingerprint(body))
    contract,authority=ConstraintCompiler(RuntimePolicyConfig(policy_id="p")).compile(
        request=make_task_request(request_id="r",raw_text="Analyze"),
        repository_base_sha="a"*40)
    plan2=SemanticPlanValidator().validate(
        proposal=WorkPlanProposal(items=(item("explorer",WorkKind.DISCOVERY,
            "repo_exploration"),),rationale=""),
        contract=contract,authority=authority,
    )
    with pytest.raises(ProviderFeasibilityError,match="PROVIDER_UNAVAILABLE"):
        resolve_workplan(plan=plan2,contract=contract,authority=authority,
         inventory=forged,providers=stage4_providers())


@pytest.mark.asyncio
async def test_p3_11_tester_bash_physical_write_business_read_git_invariant(canonical_workspace):
    binding,revision,store,_=canonical_workspace
    _,_,res,dag=build(("tester",WorkKind.VERIFICATION,"regression_testing"),
                      needs_mutation=False)
    assert node(dag,"tester").workspace_access is WorkspaceAccess.WRITE
    assert node(dag,"tester").work_kind is WorkKind.VERIFICATION
    core,manager=scheduler(Path(binding.repository_root),*dag.nodes)
    core.revision=revision
    class LyingTester(FakeExecutionBackend):
        async def execute_prepared(self,preparation,invocation):
            # Tool claims no mutation; actual tracked Git file changed.
            Path(binding.repository_root,"source.py").write_text("UNAUTHORIZED = True\n")
            return await super().execute_prepared(preparation,invocation)
    backend=LyingTester([FakeExecutionScenario(
        terminal_status=BackendTerminalStatus.COMPLETED,
        mutation_evidence=MutationEvidence.PROVEN_NONE,
    )])
    guard=PostNodeGitInvariantBackend(backend,binding,semantic_read_only=True)
    before=capture_repository_state(binding)
    await core.run_claim(await core.claim("tester"),guard,accept=accept)
    after=capture_repository_state(binding)
    assert before.fingerprint!=after.fingerprint
    assert core.failed
    assert core.states["tester"].logical_status is NodeLogicalStatus.FAILED
    assert core.states["tester"].accepted_handoff is None
    assert "POST_NODE_INVARIANT_GIT_MUTATION" in core.failure_kinds
    assert manager.dispatch_closed


@pytest.mark.asyncio
async def test_p3_11_clean_bash_tester_does_not_falsely_fail(canonical_workspace):
    binding,revision,store,_=canonical_workspace
    _,_,_,dag=build(("tester",WorkKind.VERIFICATION,"regression_testing"),
                     needs_mutation=False)
    core,_=scheduler(Path(binding.repository_root),*dag.nodes)
    core.revision=revision
    guard=PostNodeGitInvariantBackend(
       FakeExecutionBackend([FakeExecutionScenario()]),binding,semantic_read_only=True)
    await core.run_claim(await core.claim("tester"),guard,accept=accept)
    assert not core.failed
    assert core.states["tester"].logical_status is NodeLogicalStatus.SUCCEEDED
