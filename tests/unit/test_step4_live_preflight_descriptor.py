"""Step-4 Live Provider preflight, drift, policy sealing and descriptor adversarial tests."""
import pytest
from pydantic import ValidationError

from aswe.core.contracts.task import WorkKind
from aswe.core.contracts.workspace import WorkspaceAccess
from aswe.core.fingerprint import fingerprint
from aswe.planning.acceptance import AcceptanceCompiler
from aswe.planning.descriptor import compile_plan_descriptor, DescriptorMismatch
from aswe.providers.policy import (
    OperatorSurface,AdmissionError,compile_policies,build_assignments,build_team,
    NodeExecutionPolicy,
)
from aswe.providers.preflight import LivePreflightBackend,LivePreflightError,revalidate_live
from aswe.providers.inventory import fake_inventory,BackendInventorySnapshot,inventory_fingerprint
from aswe.providers.contracts import provider,CapabilityBinding
from aswe.providers.resolver import resolve_workplan
from aswe.runtime.state import NodeLogicalStatus
from aswe.runtime.dispatch import NodeDispatchTicketState
from tests.fakes import FakeExecutionBackend,FakeExecutionScenario
from tests.unit.test_step4_physical_p3 import build,stage4_providers
from tests.unit.test_scheduler_foundation import scheduler,accept


def artifacts(*items):
    c,plan,res,dag=build(*(items or (("explorer",WorkKind.DISCOVERY,"repo_exploration"),)),
                         needs_mutation=any(cap=="code_modification" for _,_,cap in items),
                         optional_bash=True)
    inv=fake_inventory()
    acceptance=AcceptanceCompiler().compile(contract=c)
    providers=stage4_providers(optional_bash=True)
    operators=tuple(OperatorSurface(provider_id=p.id,allowed_tools=(
        "read_file","bash","str_replace","submit_review_verdict"),
        model_name="fake",max_turns=15,timeout_seconds=45) for p in providers)
    policies=compile_policies(contract=c,plan=plan,resolved=res,inventory=inv,
                             acceptance=acceptance,providers=providers,operators=operators)
    descriptor=compile_plan_descriptor(contract=c,plan=plan,resolved=res,
                              inventory=inv,acceptance=acceptance,policies=policies)
    return c,plan,res,dag,inv,acceptance,providers,operators,policies,descriptor


def changed_inventory(inv,*,remove_tools=(),add_agent=None,remove_features=(),tool_override=None):
    body=inv.model_dump(mode="python",exclude={"fingerprint"})
    for name in remove_tools:body["candidate_tools"].pop(name)
    if add_agent:body["candidate_agent_types"]=frozenset(
        set(body["candidate_agent_types"])|{add_agent})
    body["sandbox_features"]=frozenset(set(body["sandbox_features"])-set(remove_features))
    if tool_override:
        key,new_value=tool_override
        body["candidate_tools"][key]=new_value
    return BackendInventorySnapshot(**body,fingerprint=inventory_fingerprint(body))


def test_policy_and_descriptor_deterministic_same_source_ids():
    c,p,r,d,i,a,providers,ops,policies,descriptor=artifacts(
        ("explorer",WorkKind.DISCOVERY,"repo_exploration"),
        ("writer",WorkKind.IMPLEMENTATION,"code_modification"),
        ("tester",WorkKind.VERIFICATION,"regression_testing"),
    )
    assert descriptor.task_dag==d
    assert len(descriptor.policies)==3
    assert descriptor.fingerprint==compile_plan_descriptor(
        contract=c,plan=p,resolved=r,inventory=i,acceptance=a,policies=policies).fingerprint
    assert descriptor.execution_contract_binding.task_contract_fingerprint==c.fingerprint
    assert {x.policy_fingerprint for x in descriptor.assignments}=={x.fingerprint for x in policies}
    assert {m.provider_id for m in descriptor.team.members}=={"explorer","coder","tester"}
    with pytest.raises(ValidationError,match="CompiledPlanDescriptor fingerprint mismatch"):
        descriptor.model_copy(update={"task_contract_fingerprint":"0"*64})


def test_tool_and_provider_static_preflight_operator_deny_fails_closed():
    c,p,r,d,inv,a,providers,ops,policies,desc=artifacts(
       ("tester",WorkKind.VERIFICATION,"regression_testing"))
    o=OperatorSurface(provider_id="tester",allowed_tools=("read_file",),model_name="fake")
    with pytest.raises(AdmissionError,match="PROVIDER_STATIC_CONTRACT_MISMATCH"):
        compile_policies(contract=c,plan=p,resolved=r,inventory=inv,
                         acceptance=a,providers=providers,operators=(o,))
    assert policies[0].workspace_access is WorkspaceAccess.WRITE


def test_model_unavailable_and_authorization_deny_preflight():
    c,p,r,d,inv,a,providers,ops,policies,_=artifacts(
       ("tester",WorkKind.VERIFICATION,"regression_testing"))
    with pytest.raises(AdmissionError,match="PROVIDER_MODEL_UNAVAILABLE"):
        compile_policies(contract=c,plan=p,resolved=r,inventory=inv,
          acceptance=a,providers=providers,
          operators=(OperatorSurface(provider_id="tester",model_name="missing"),))
    with pytest.raises(AdmissionError,match="PROVIDER_AUTHORIZATION_DENIED"):
        compile_policies(contract=c,plan=p,resolved=r,inventory=inv,
          acceptance=a,providers=providers,operators=(
             OperatorSurface(provider_id="tester",auth_enabled=True,
                             authorized_tools=frozenset({"bash"}),
                             authorized_models=frozenset()),))


def test_required_review_output_tool_respects_operator_denial():
    c,p,r,d,inv,a,providers,ops,policies,_=artifacts(
       ("reviewer",WorkKind.REVIEW,"code_review"))
    pol=policies[0]
    assert pol.required_infrastructure_tools==("submit_review_verdict",)
    with pytest.raises(AdmissionError,match="REQUIRED_INFRASTRUCTURE_TOOL_DENIED"):
        compile_policies(contract=c,plan=p,resolved=r,inventory=inv,
          acceptance=a,providers=providers,operators=(
           OperatorSurface(provider_id="reviewer",allowed_tools=("read_file",)),))


def test_preferred_skill_incompatible_with_required_bash_is_not_exposed():
    c,p,r,d,inv,a,providers,ops,policies,_=artifacts(
       ("tester",WorkKind.VERIFICATION,"regression_testing"))
    tester=provider("tester",(CapabilityBinding(
        capability_id="regression_testing",required_tools=("bash",),
        preferred_skills=("read-only-review",)),))
    raw=inv.model_dump(mode="python",exclude={"fingerprint"})
    raw["candidate_skill_names"]=frozenset({"read-only-review"})
    better=BackendInventorySnapshot(**raw,fingerprint=inventory_fingerprint(raw))
    from aswe.planning.compiler import project_execution_authority
    r2=resolve_workplan(plan=p,contract=c,authority=project_execution_authority(c),
                        inventory=better,providers=(tester,))
    policy=compile_policies(contract=c,plan=p,resolved=r2,inventory=better,acceptance=a,
        providers=(tester,),operators=(OperatorSurface(
             provider_id="tester",allowed_tools=("read_file","bash"),
             skill_allowed_tools={"read-only-review":("read_file",)}),))
    assert not policy[0].preferred_skills


def test_unrelated_live_inventory_drift_revalidated_and_diagnostic():
    *_,inv,a,providers,ops,policies,desc=artifacts(
       ("tester",WorkKind.VERIFICATION,"regression_testing"))
    new=changed_inventory(inv,add_agent="unrelated-role")
    fp,diagnostics,allowed=revalidate_live(
       policy=policies[0],planning=inv,live=new,
       operator=next(o for o in ops if o.provider_id=="tester"))
    assert diagnostics==("BACKEND_DRIFT_OBSERVED",)
    assert allowed==("bash",) and len(fp)==64


@pytest.mark.parametrize("change",["removed","impersonated","downgraded","missing_model","missing_provider"])
def test_live_required_tool_model_provider_drift_rejected(change):
    c,p,r,d,inv,a,providers,ops,policies,_=artifacts(
        ("tester",WorkKind.VERIFICATION,"regression_testing"))
    live=inv
    if change=="removed":live=changed_inventory(inv,remove_tools=("bash",))
    if change=="impersonated":
        swapped=inv.candidate_tools["bash"].model_copy(
            update={"implementation_id":"config:untrusted_module",
                    "resolved_exposed_name":"bash"})
        live=changed_inventory(inv,tool_override=("bash",swapped))
    if change=="downgraded":
        swapped=inv.candidate_tools["bash"].model_copy(update={"effect":"read_only"})
        live=changed_inventory(inv,tool_override=("bash",swapped))
    if change in ("missing_model","missing_provider"):
        raw=inv.model_dump(mode="python",exclude={"fingerprint"})
        if change=="missing_model":raw["configured_model_names"]=frozenset()
        else:raw["candidate_agent_types"]=frozenset()
        live=BackendInventorySnapshot(**raw,fingerprint=inventory_fingerprint(raw))
    with pytest.raises(LivePreflightError):
        revalidate_live(policy=policies[0],planning=inv,live=live,
            operator=next(o for o in ops if o.provider_id=="tester"))


def test_live_operator_can_narrow_ceiling_but_cannot_remove_required_or_model_auth():
    *_,inv,a,providers,ops,policies,desc=artifacts(
        ("tester",WorkKind.VERIFICATION,"regression_testing"))
    p=policies[0]
    low=OperatorSurface(provider_id="tester",allowed_tools=("bash",),
                        model_name="fake",max_turns=2,timeout_seconds=5)
    effective,diagnostics,allowed=revalidate_live(
        policy=p,planning=inv,live=inv,operator=low)
    assert len(effective)==64 and diagnostics==() and allowed==("bash",)
    with pytest.raises(LivePreflightError,match="BACKEND_PREFLIGHT_STALE"):
        revalidate_live(policy=p,planning=inv,live=inv,
            operator=OperatorSurface(provider_id="tester",allowed_tools=("read_file",)))
    with pytest.raises(LivePreflightError,match="PROVIDER_AUTHORIZATION_DENIED"):
        revalidate_live(policy=p,planning=inv,live=inv,
            operator=OperatorSurface(provider_id="tester",auth_enabled=True,
                                    authorized_tools=frozenset({"bash"}),
                                    authorized_models=frozenset()))


@pytest.mark.asyncio
async def test_live_preflight_stale_rejects_before_scheduler_commit(tmp_path):
    _,_,_,dag,inv,_,_,ops,policies,descriptor=artifacts(
        ("tester",WorkKind.VERIFICATION,"regression_testing"))
    core,manager=scheduler(tmp_path,*dag.nodes)
    backend=FakeExecutionBackend([FakeExecutionScenario()])
    wrapped=LivePreflightBackend(backend,descriptor=descriptor,policy=policies[0],planning_inventory=inv,
       live_inventory=lambda:changed_inventory(inv,remove_tools=("bash",)),
       live_operator=lambda:next(o for o in ops if o.provider_id=="tester"))
    ticket=await core.claim("tester")
    with pytest.raises(LivePreflightError,match="BACKEND_PREFLIGHT_STALE"):
        await core.run_claim(ticket,wrapped,accept=accept)
    assert core.states["tester"].attempts==()
    assert backend.records==[] and backend.preparations==[]
    assert core.tickets[ticket.ticket_id].state is NodeDispatchTicketState.REVOKED
    assert manager.active_accesses==0


@pytest.mark.asyncio
async def test_live_drift_unrelated_preparation_pinned_even_if_deployment_changes(tmp_path):
    _,_,_,dag,inv,_,_,ops,policies,descriptor=artifacts(
        ("tester",WorkKind.VERIFICATION,"regression_testing"))
    core,_=scheduler(tmp_path,*dag.nodes)
    backend=FakeExecutionBackend([FakeExecutionScenario()])
    state={"live":changed_inventory(inv,add_agent="unrelated")}
    wrapped=LivePreflightBackend(backend,descriptor=descriptor,policy=policies[0],planning_inventory=inv,
        live_inventory=lambda:state["live"],
        live_operator=lambda:next(o for o in ops if o.provider_id=="tester"))
    await core.run_claim(await core.claim("tester"),wrapped,accept=accept)
    assert core.states["tester"].logical_status is NodeLogicalStatus.SUCCEEDED
    assert len(backend.records)==1 and len(backend.preparations)==1
    assert backend.records[0].attempt==1
    # Live inventory consulted exactly at prepare, not silently rebinding at execution.
    assert wrapped.prepared=={}


def test_descriptor_rejects_self_signed_provider_swap_and_policy_downgrade():
    c,p,r,d,inv,a,providers,ops,policies,_=artifacts(
        ("tester",WorkKind.VERIFICATION,"regression_testing"))
    bad=policies[0].model_dump(mode="json",exclude={"fingerprint"})
    bad["workspace_access"]="read"
    from aswe.providers.policy import NodeExecutionPolicy
    forged=NodeExecutionPolicy(**bad,fingerprint=fingerprint(bad))
    with pytest.raises(DescriptorMismatch,match="EXECUTION_DESCRIPTOR_POLICY_DRIFT"):
        compile_plan_descriptor(contract=c,plan=p,resolved=r,inventory=inv,
                                acceptance=a,policies=(forged,))


def test_poc40_explicit_optional_bash_upgrades_physical_write_and_stamps_policy():
    from aswe.planning.compiler import project_execution_authority
    from aswe.providers.resolver import resolve_workplan
    c,p,r,d,inv,a,providers,ops,policies,_=artifacts(
        ("explorer",WorkKind.DISCOVERY,"repo_exploration"))
    assert policies[0].workspace_access is WorkspaceAccess.READ
    chosen=resolve_workplan(plan=p,contract=c,authority=project_execution_authority(c),
        inventory=inv,providers=stage4_providers(optional_bash=True),
        selected_optional_by_node={"explorer":("bash",)})
    assert chosen.nodes[0].workspace_access is WorkspaceAccess.WRITE
    assert chosen.nodes[0].selected_optional_tools==("bash",)
    assert chosen.nodes[0].policy_fingerprint!=r.nodes[0].policy_fingerprint
    upgraded=compile_policies(contract=c,plan=p,resolved=chosen,inventory=inv,
        acceptance=a,providers=providers,operators=ops)
    assert upgraded[0].workspace_access is WorkspaceAccess.WRITE
    assert "bash" in upgraded[0].allowed_business_tools
    digest=compile_plan_descriptor(contract=c,plan=p,resolved=chosen,
        inventory=inv,acceptance=a,policies=upgraded)
    assert digest.task_dag.nodes[0].workspace_access is WorkspaceAccess.WRITE
    # A disappearance after prepare only narrows the optional tool;
    # upper-bound physical WRITE lock class is deliberately preserved.
    live=changed_inventory(inv,remove_tools=("bash",))
    op=next(o for o in ops if o.provider_id=="explorer")
    _,diag,allowed=revalidate_live(policy=upgraded[0],planning=inv,live=live,operator=op)
    assert diag==("BACKEND_DRIFT_OBSERVED",)
    assert allowed==("read_file",)


def test_live_preflight_never_rebinds_to_alternate_provider_when_required_tool_missing():
    *_,inv,a,providers,ops,policies,desc=artifacts(
        ("tester",WorkKind.VERIFICATION,"regression_testing"))
    live=changed_inventory(inv,remove_tools=("bash",))
    with pytest.raises(LivePreflightError,match="BACKEND_PREFLIGHT_STALE"):
        revalidate_live(policy=policies[0],planning=inv,live=live,
            operator=next(o for o in ops if o.provider_id=="tester"))
    assert policies[0].provider_id=="tester"


def test_adversarial_provider_same_id_but_changed_bindings_is_not_authorized():
    c,p,r,d,inv,a,providers,ops,policies,_=artifacts(
        ("tester",WorkKind.VERIFICATION,"regression_testing"))
    replaced=provider("tester",(CapabilityBinding(
        capability_id="regression_testing",required_tools=("read_file",)),))
    # Valid signature under a new contract is insufficient: the Planner's
    # resource binding explicitly seals the ORIGINAL provider identity.
    with pytest.raises(AdmissionError,match="PROVIDER_STATIC_CONTRACT_MISMATCH"):
        compile_policies(contract=c,plan=p,resolved=r,inventory=inv,
                         acceptance=a,providers=(replaced,),
                         operators=(next(o for o in ops if o.provider_id=="tester"),))


def test_runtime_model_rebinding_and_required_schema_drift_fail_closed():
    *_,inv,a,providers,ops,policies,desc=artifacts(
       ("tester",WorkKind.VERIFICATION,"regression_testing"))
    p=policies[0]
    with pytest.raises(LivePreflightError,match="BACKEND_PREFLIGHT_STALE"):
        revalidate_live(policy=p,planning=inv,live=inv,
          operator=OperatorSurface(provider_id="tester",model_name="different"))
    changed=inv.candidate_tools["bash"].model_copy(update={"schema_hash":"schema-drift"})
    live=changed_inventory(inv,tool_override=("bash",changed))
    with pytest.raises(LivePreflightError,match="PROVIDER_TOOL_IDENTITY_MISMATCH"):
        revalidate_live(policy=p,planning=inv,live=live,
          operator=next(o for o in ops if o.provider_id=="tester"))


def test_core_tool_exposed_name_mismatch_is_not_identity_authority():
    from aswe.planning.compiler import project_execution_authority
    c,p,r,d,inv,a,providers,ops,policies,_=artifacts(
        ("explorer",WorkKind.DISCOVERY,"repo_exploration"))
    changed=inv.candidate_tools["read_file"].model_copy(
        update={"resolved_exposed_name":"unsafe_overlay"})
    rogue=changed_inventory(inv,tool_override=("read_file",changed))
    with pytest.raises(Exception):
        resolve_workplan(plan=p,contract=c,authority=project_execution_authority(c),
                         providers=providers,inventory=rogue)


def test_explicit_contract_tool_deny_overrides_provider_operator_allowlist():
    from aswe.planning.compiler import (
        ConstraintCompiler,RuntimePolicyConfig,RuntimePolicyRule,project_execution_authority)
    from aswe.planning.contracts import make_task_request
    from aswe.planning.planner import WorkPlanProposal,WorkItemProposal
    from aswe.planning.validator import SemanticPlanValidator
    from aswe.core.contracts.task import WorkKind
    c,authority=ConstraintCompiler(RuntimePolicyConfig(policy_id="deny-bash",rules=(
        RuntimePolicyRule(key="actions.forbidden",value=("bash",)),
    ))).compile(request=make_task_request(request_id="r",raw_text="Analyze"),
               repository_base_sha="a"*40)
    plan=SemanticPlanValidator().validate(
        proposal=WorkPlanProposal(items=(WorkItemProposal(
            id="tester",objective="test",work_kind=WorkKind.VERIFICATION,
            capability_hints=("regression_testing",)),),rationale=""),
        contract=c,authority=authority)
    inv=fake_inventory()
    res=resolve_workplan(plan=plan,contract=c,authority=authority,
                         providers=stage4_providers(),inventory=inv)
    with pytest.raises(AdmissionError,match="CONTRACT_TOOL_DENIED"):
        compile_policies(contract=c,plan=plan,resolved=res,inventory=inv,
            acceptance=AcceptanceCompiler().compile(contract=c),
            providers=stage4_providers(),
            operators=(OperatorSurface(provider_id="tester",allowed_tools=("bash",)),))


def test_acceptance_bash_exact_command_policy_and_sandbox_preflight():
    from tests.unit.test_acceptance_compiler_step3d import (
        verify_contract,unit_rule,validator_plan)
    from aswe.planning.compiler import project_execution_authority
    c,authority=verify_contract()
    plan=validator_plan(c,authority)
    acceptance=AcceptanceCompiler(rules=(unit_rule(),)).compile(contract=c)
    inv=fake_inventory()
    providers=stage4_providers()
    res=resolve_workplan(plan=plan,contract=c,authority=authority,inventory=inv,
                         providers=providers,
                         required_sandbox_features=acceptance.required_sandbox_features)
    operators=tuple(OperatorSurface(provider_id=x.id,
                     allowed_tools=("bash","read_file","submit_review_verdict"))
                    for x in providers)
    policy=compile_policies(contract=c,plan=plan,resolved=res,inventory=inv,
                    acceptance=acceptance,providers=providers,operators=operators)
    assert len(policy)==len(plan.items)
    verified=next(p for p in policy if p.verification_exact_commands)
    assert verified.verification_exact_commands==(acceptance.criteria[0].bash_exact_allowlist_entry,)
    assert verified.canonical_check_policy_fingerprints==(acceptance.canonical_policies[0].fingerprint,)
    assert verified.workspace_access is WorkspaceAccess.WRITE
    with pytest.raises(AdmissionError,match="REQUIRED_SANDBOX_EVIDENCE_UNAVAILABLE"):
        missing=fake_inventory(features=())
        res2=resolve_workplan(plan=plan,contract=c,authority=authority,
                              inventory=missing,providers=providers)
        compile_policies(contract=c,plan=plan,resolved=res2,inventory=missing,
                         acceptance=acceptance,providers=providers,operators=operators)
    with pytest.raises(Exception,match="REQUIRED_SANDBOX_EVIDENCE_UNAVAILABLE"):
        resolve_workplan(plan=plan,contract=c,authority=authority,inventory=missing,
             providers=providers,
             required_sandbox_features=acceptance.required_sandbox_features)


def test_runtime_node_ceiling_can_only_narrow_operator_ceiling():
    c,p,r,d,inv,a,providers,ops,policies,_=artifacts(
        ("tester",WorkKind.VERIFICATION,"regression_testing"))
    small=compile_policies(contract=c,plan=p,resolved=r,inventory=inv,
        acceptance=a,providers=providers,operators=ops,
        node_max_turns=3,node_timeout_seconds=8.)
    assert small[0].max_turns==3
    assert small[0].timeout_seconds==8.
    assert small[0].fingerprint!=policies[0].fingerprint


def test_live_backend_rejects_self_signed_policy_from_other_descriptor():
    _,_,_,dag,inv,_,_,ops,policies,descriptor=artifacts(
        ("tester",WorkKind.VERIFICATION,"regression_testing"))
    altered=policies[0].model_dump(mode="json",exclude={"fingerprint"})
    altered["max_turns"]=1
    forged=NodeExecutionPolicy(**altered,fingerprint=fingerprint(altered))
    with pytest.raises(LivePreflightError,match="DESCRIPTOR_POLICY_IDENTITY_MISMATCH"):
        LivePreflightBackend(FakeExecutionBackend(),descriptor=descriptor,
            policy=forged,planning_inventory=inv,
            live_inventory=lambda:inv,
            live_operator=lambda:next(o for o in ops if o.provider_id=="tester"))


def test_compiled_policy_applies_negative_path_scope_and_file_budget_to_every_node():
    from aswe.planning.compiler import ConstraintCompiler,RuntimePolicyConfig,RuntimePolicyRule
    from aswe.planning.contracts import make_task_request
    from aswe.planning.planner import WorkPlanProposal,WorkItemProposal
    from aswe.planning.validator import SemanticPlanValidator
    from aswe.planning.compiler import project_execution_authority
    c,a=ConstraintCompiler(RuntimePolicyConfig(policy_id="locked",rules=(
        RuntimePolicyRule(key="repo.paths.allowed",value=("src/**",)),
        RuntimePolicyRule(key="repo.paths.forbidden",value=("src/secrets/**",)),
        RuntimePolicyRule(key="change.max_files",value=3),
    ))).compile(request=make_task_request(request_id="path",raw_text="Analyze"),
               repository_base_sha="a"*40)
    p=SemanticPlanValidator().validate(proposal=WorkPlanProposal(items=(
        WorkItemProposal(id="explorer",objective="read",work_kind=WorkKind.DISCOVERY,
                         capability_hints=("repo_exploration",)),
        ),rationale=""),contract=c,authority=a)
    inv=fake_inventory()
    providers=stage4_providers()
    resolved=resolve_workplan(plan=p,contract=c,authority=a,inventory=inv,providers=providers)
    policy=compile_policies(contract=c,plan=p,resolved=resolved,inventory=inv,
                            acceptance=AcceptanceCompiler().compile(contract=c),
                            providers=providers,
                            operators=(OperatorSurface(provider_id="explorer",
                                    allowed_tools=("read_file",)),))
    assert policy[0].allowed_paths==("src/**",)
    assert policy[0].forbidden_paths==("src/secrets/**",)
    assert policy[0].max_changed_files==3
    descriptor=compile_plan_descriptor(contract=c,plan=p,resolved=resolved,
        inventory=inv,acceptance=AcceptanceCompiler().compile(contract=c),policies=policy)
    altered=policy[0].model_dump(mode="json",exclude={"fingerprint"})
    altered["forbidden_paths"]=[]
    forged=NodeExecutionPolicy(**altered,fingerprint=fingerprint(altered))
    with pytest.raises(DescriptorMismatch,match="EXECUTION_DESCRIPTOR_POLICY_DRIFT"):
        compile_plan_descriptor(contract=c,plan=p,resolved=resolved,inventory=inv,
             acceptance=AcceptanceCompiler().compile(contract=c),policies=(forged,))


def test_poc28_poc41_required_missing_or_deferred_tool_is_never_provider_feasible():
    from aswe.planning.compiler import project_execution_authority
    from aswe.providers.resolver import ProviderFeasibilityError
    c,p,r,d,inv,a,providers,ops,policies,_=artifacts(
        ("tester",WorkKind.VERIFICATION,"regression_testing"))
    for broken in ("removed","deferred"):
        if broken=="removed":
            bad=changed_inventory(inv,remove_tools=("bash",))
        else:
            altered=inv.candidate_tools["bash"].model_copy(update={
                "delivery":"deferred","source":"mcp"})
            bad=changed_inventory(inv,tool_override=("bash",altered))
        with pytest.raises(ProviderFeasibilityError,match="PROVIDER_UNAVAILABLE"):
            resolve_workplan(plan=p,contract=c,authority=project_execution_authority(c),
                             inventory=bad,providers=providers)


def test_poc53_same_provider_multiple_nodes_no_hidden_merge_or_context_reuse():
    from aswe.planning.compiler import (
        ConstraintCompiler,RuntimePolicyConfig,project_execution_authority)
    from aswe.planning.contracts import make_task_request
    from aswe.planning.planner import WorkPlanProposal,WorkItemProposal
    from aswe.planning.validator import SemanticPlanValidator
    from aswe.planning.dag import materialize_task_dag
    c,a=ConstraintCompiler(RuntimePolicyConfig(policy_id="reuse")).compile(
        request=make_task_request(request_id="q",raw_text="Analyze repo"),
        repository_base_sha="a"*40)
    proposal=WorkPlanProposal(items=(
        WorkItemProposal(id="discover",objective="inspect",work_kind=WorkKind.DISCOVERY,
                         capability_hints=("repo_exploration",)),
        WorkItemProposal(id="search",objective="locate",work_kind=WorkKind.DISCOVERY,
                         capability_hints=("code_search",)),
    ),rationale="two distinct bounded actions")
    plan=SemanticPlanValidator().validate(proposal=proposal,contract=c,authority=a)
    reused=provider("explorer",(
        CapabilityBinding(capability_id="repo_exploration",required_tools=("read_file",)),
        CapabilityBinding(capability_id="code_search",required_tools=("read_file",)),
    ))
    inv=fake_inventory()
    r=resolve_workplan(plan=plan,contract=c,authority=a,inventory=inv,
        providers=(reused,))
    accept_plan=AcceptanceCompiler().compile(contract=c)
    ps=compile_policies(contract=c,plan=plan,resolved=r,inventory=inv,
        providers=(reused,),acceptance=accept_plan,
        operators=(OperatorSurface(provider_id="explorer",
                                    allowed_tools=("read_file",)),))
    desc=compile_plan_descriptor(contract=c,plan=plan,resolved=r,
        inventory=inv,acceptance=accept_plan,policies=ps)
    assert len(desc.team.members)==1
    assert desc.team.members[0].selected_for_nodes==("discover","search")
    assert {x.id for x in desc.task_dag.nodes}=={"discover","search"}
    assert len(desc.assignments)==2
    assert len({x.node_id for x in ps})==2
