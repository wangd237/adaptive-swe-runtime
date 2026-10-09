"""Step-3C deterministic semantic planning PoC coverage.

These verify bounded *semantic* phase/authority contracts, NOT Step-4
physical WRITE serialization, provider admission or post-node Git invariant.
"""
import pytest
from pydantic import ValidationError

from aswe.core.contracts.task import WorkKind
from aswe.planning.analyzer import TaskSpec, TaskType, Complexity, RiskLevel, StructuredReasoningResult
from aswe.planning.compiler import RuntimePolicyConfig, RuntimePolicyRule, ConstraintCompiler
from aswe.planning.contracts import make_task_request
from aswe.planning.planner import (
    SemanticPlanner, PlanningContext, WorkItemProposal, WorkPlanProposal,
)
from aswe.planning.profile import RepositoryProfile
from aswe.planning.validator import (
    SemanticPlanValidator, PlanValidationError, CoverageMode,
)


BASE_SHA = "1" * 40


def contract(*rules):
    config = RuntimePolicyConfig(policy_id="p3-tests", rules=tuple(
        RuntimePolicyRule(key=k, value=v) for k,v in rules
    ))
    return ConstraintCompiler(config).compile(
        request=make_task_request(request_id="p3-request", raw_text="Build a safe plan"),
        repository_base_sha=BASE_SHA,
    )


def item(id, kind, caps, deps=(), claims=(), intent=()):
    return WorkItemProposal(
        id=id, objective=f"bounded {id}", work_kind=kind,
        capability_hints=tuple(caps), depends_on=tuple(deps),
        coverage_claims=tuple(claims), acceptance_intent=tuple(intent),
    )


def prop(*items):
    return WorkPlanProposal(items=tuple(items), rationale="Planner proposal only")


def validate(*items, rules=(), max_items=8):
    c,a=contract(*rules)
    return SemanticPlanValidator(max_work_items=max_items).validate(
        proposal=prop(*items), contract=c, authority=a,
    )


def mutation():
    c,a=contract(("deliverables.required", {
        "description": "fix implementation", "effect": "repository_mutation",
    }))
    return c,a,next(x.id for x in c.constraints if x.key=="deliverables.required")


def gate_contract():
    c,a=contract(
        ("deliverables.required", {
            "description": "fix implementation", "effect": "repository_mutation",
        }),
        ("verification.required", ("unit",)),
        ("review.required", True),
    )
    grant=next(x.id for x in c.constraints if x.key=="deliverables.required")
    return c,a,grant


def run(c,a,*items,max_items=8):
    return SemanticPlanValidator(max_work_items=max_items).validate(
        proposal=prop(*items), contract=c, authority=a,
    )


def fail(code,c,a,*items):
    with pytest.raises(PlanValidationError) as e:
        run(c,a,*items)
    assert e.value.code==code


def test_p3_01_writer_precedes_bash_tester_by_semantic_phase():
    c,a,grant=mutation()
    p=run(c,a,
        item("coder", WorkKind.IMPLEMENTATION, ("code_modification",), claims=(grant,)),
        item("tester", WorkKind.VERIFICATION, ("regression_testing",), deps=("coder",)),
    )
    assert p.items[1].depends_on==("coder",)
    assert p.items[1].work_kind is WorkKind.VERIFICATION


def test_p3_02_tester_semantically_precedes_readonly_reviewer():
    c,a=contract()
    p=run(c,a,
        item("tester", WorkKind.VERIFICATION, ("regression_testing",)),
        item("reviewer", WorkKind.REVIEW, ("code_review",), deps=("tester",)),
    )
    assert p.items[1].depends_on==("tester",)
    assert p.items[0].work_kind is WorkKind.VERIFICATION
    assert p.items[1].work_kind is WorkKind.REVIEW


def test_p3_03_discovery_before_implementation():
    c,a,grant=mutation()
    p=run(c,a,
        item("explore", WorkKind.DISCOVERY, ("repo_exploration",)),
        item("coder", WorkKind.IMPLEMENTATION, ("code_modification",),
             deps=("explore",),claims=(grant,)),
    )
    assert p.items[1].depends_on == ("explore",)


def test_p3_04_unordered_same_phase_mutating_items_keep_ordinals_without_fake_provider_edges():
    c,a,grant=mutation()
    p=run(c,a,
        item("one", WorkKind.IMPLEMENTATION, ("code_modification",), claims=(grant,)),
        item("two", WorkKind.IMPLEMENTATION, ("code_modification",), claims=(grant,)),
    )
    assert tuple(x.planner_ordinal for x in p.items)==(0,1)
    assert p.items[0].depends_on==p.items[1].depends_on==()
    # Step 4 must add deterministic physical WRITE serialization.


def test_p3_05_explicit_review_to_implementation_is_hard_phase_contradiction():
    c,a,grant=mutation()
    fail("PHASE_ORDER_CONTRADICTION",c,a,
        item("review", WorkKind.REVIEW, ("code_review",)),
        item("writer", WorkKind.IMPLEMENTATION, ("code_modification",),
             deps=("review",),claims=(grant,)),
    )


def test_p3_06_independent_discovery_remains_parallel_without_forced_edges():
    c,a=contract()
    p=run(c,a,
        item("read_a", WorkKind.DISCOVERY, ("repo_exploration",)),
        item("read_b", WorkKind.DISCOVERY, ("code_search",)),
    )
    assert all(x.depends_on==() for x in p.items)
    assert p.repairs==()


def test_p3_07_c08_missing_required_gates_are_runtime_owned_monotonic_injected():
    c,a,grant=gate_contract()
    validator=SemanticPlanValidator()
    p=validator.validate(proposal=prop(
        item("coder", WorkKind.IMPLEMENTATION, ("code_modification",),claims=(grant,)),
    ),contract=c,authority=a)
    assert [x.id for x in p.items]==["coder","__aswe_verify","__aswe_review"]
    v,r=p.items[1:]
    assert (v.work_kind, v.capability_hints, v.depends_on, v.runtime_owned)==(
        WorkKind.VERIFICATION,("regression_testing",),("coder",),True,
    )
    assert (r.work_kind, r.capability_hints, r.depends_on, r.runtime_owned)==(
        WorkKind.REVIEW,("code_review",),("__aswe_verify",),True,
    )
    assert tuple(x.code for x in p.repairs)==(
        "INJECT_VERIFICATION_GATE","INJECT_REVIEW_GATE",
    )
    coverage=validator.coverage_map(plan=p, contract=c)
    assert len(coverage)==3
    assert {x.constraint_id for x in coverage}=={x.id for x in c.constraints}
    assert next(x for x in coverage if x.work_item_ids==("__aswe_review",)).mode is CoverageMode.RUNTIME_ENFORCED
    assert p==validator.validate(proposal=prop(
        item("coder", WorkKind.IMPLEMENTATION, ("code_modification",),claims=(grant,)),
    ),contract=c,authority=a)


def test_p3_07_legal_existing_gates_are_recognized_without_extra_nodes():
    c,a,grant=gate_contract()
    validator=SemanticPlanValidator()
    p=validator.validate(proposal=prop(
        item("coder", WorkKind.IMPLEMENTATION, ("code_modification",),claims=(grant,)),
        item("check", WorkKind.VERIFICATION, ("regression_testing",),deps=("coder",)),
        item("review", WorkKind.REVIEW, ("code_review",),deps=("check",)),
    ),contract=c,authority=a)
    assert len(p.items)==3 and p.repairs==()
    assert len(validator.coverage_map(plan=p,contract=c))==3


def test_p3_07_injected_verifier_forces_new_review_after_it():
    c,a,grant=gate_contract()
    p=run(c,a,
        item("writer", WorkKind.IMPLEMENTATION, ("code_modification",),claims=(grant,)),
        item("bad_verification",WorkKind.VERIFICATION,("regression_testing",)),
        item("review",WorkKind.REVIEW,("code_review",),deps=("bad_verification",)),
    )
    assert [x.id for x in p.items][-2:]==["__aswe_verify","__aswe_review"]
    assert "__aswe_verify" in p.items[-1].depends_on


def test_p3_08_planner_may_not_impersonate_reserved_gate():
    c,a=contract()
    fail("PLAN_INVALID",c,a,
        item("__aswe_verify", WorkKind.VERIFICATION, ("regression_testing",)),
    )


def test_p3_09_c07_report_only_cannot_request_business_mutation_capability():
    c,a=contract(("deliverables.required",{"description":"explain","effect":"report_only"}))
    grant=next(x.id for x in c.constraints if x.key=="deliverables.required")
    fail("CAPABILITY_AUTHORITY_VIOLATION",c,a,
         item("writer", WorkKind.IMPLEMENTATION,("code_modification",), claims=(grant,)))


def test_p3_10_authorized_bug_fix_implementation_is_accepted():
    c,a,grant=mutation()
    p=run(c,a,
        item("patch",WorkKind.IMPLEMENTATION,("code_modification",),
             claims=(grant,),intent=("tests pass",)),
    )
    assert p.items[0].coverage_claims==(grant,)
    assert p.items[0].acceptance_intent==("tests pass",)


def test_p3_11_semantic_verification_not_equivalent_to_business_mutation():
    c,a,grant=mutation()
    p=run(c,a,
        item("writer",WorkKind.IMPLEMENTATION,("code_modification",),claims=(grant,)),
        item("tester",WorkKind.VERIFICATION,("regression_testing",),deps=("writer",)),
    )
    assert p.items[1].work_kind is WorkKind.VERIFICATION
    fail("PLAN_INVALID",c,a,
        item("writer",WorkKind.IMPLEMENTATION,("code_modification",),claims=(grant,)),
        item("tester",WorkKind.VERIFICATION,("regression_testing","code_modification"),deps=("writer",)),
    )
    # Real Tester bash post-node mutation invariant is Step 4/Runtime, not claimed here.


def test_p3_12_mutating_workitem_requires_matching_deliverable_coverage():
    c,a,grant=mutation()
    fail("PLAN_INVALID",c,a,
        item("writer",WorkKind.IMPLEMENTATION,("code_modification",)),
    )


def test_unknown_or_negative_claim_rejected_not_silently_dropped():
    c,a=contract(("repo.paths.forbidden",("secrets/**",)))
    blocked=next(x.id for x in c.constraints)
    fail("PLAN_INVALID",c,a,
        item("read",WorkKind.DISCOVERY,("repo_exploration",),claims=(blocked,)),
    )
    fail("PLAN_INVALID",c,a,
        item("read",WorkKind.DISCOVERY,("repo_exploration",),claims=("absent",)),
    )


def test_unknown_capability_and_wrong_review_semantic_phase_rejected():
    c,a=contract()
    fail("PLAN_INVALID",c,a,item("unknown",WorkKind.DISCOVERY,("planetary_tool",)))
    fail("PLAN_INVALID",c,a,item("review",WorkKind.REVIEW,("repo_exploration",)))


def test_cycle_and_missing_dependency_rejected():
    c,a=contract()
    fail("PLAN_INVALID",c,a,
        item("a",WorkKind.DISCOVERY,("repo_exploration",),deps=("b",)),
        item("b",WorkKind.DISCOVERY,("code_search",),deps=("a",)),
    )
    fail("PLAN_INVALID",c,a,
        item("a",WorkKind.DISCOVERY,("repo_exploration",),deps=("absent",)),
    )


def test_dependencies_are_monotonic_deduplicated_and_logged():
    c,a=contract()
    p=run(c,a,
        item("root",WorkKind.DISCOVERY,("repo_exploration",)),
        item("next",WorkKind.DISCOVERY,("code_search",),deps=("root","root")),
    )
    assert p.items[1].depends_on==("root",)
    assert p.repairs[0].code=="DEDUPE_DEPENDENCY"


def test_positive_semantic_obligation_requires_structural_claim():
    c,a=contract(("semantic.requirement","clear communication"))
    fail("PLAN_INVALID",c,a,item("report",WorkKind.DISCOVERY,("repo_exploration",)))
    claim=c.constraints[0].id
    p=run(c,a,item("report",WorkKind.DISCOVERY,("repo_exploration",),claims=(claim,)))
    assert p.items[0].coverage_claims==(claim,)


def test_plan_budget_pre_reserves_runtime_gates():
    c,a,grant=gate_contract()
    fail("PLAN_INVALID",c,a,
        *[item(f"coder{i}",WorkKind.IMPLEMENTATION,("code_modification",),claims=(grant,))
          for i in range(7)]
    )


def test_digest_and_contract_binding_are_immutable():
    c,a,grant=mutation()
    p=run(c,a,item("coder",WorkKind.IMPLEMENTATION,("code_modification",),claims=(grant,)))
    with pytest.raises(ValidationError,match="fingerprint mismatch"):
        p.model_copy(update={"planner_rationale":"new reasoning"})
    other,_=contract(("review.required",True))
    with pytest.raises(PlanValidationError,match="contract/plan fingerprint"):
        SemanticPlanValidator().coverage_map(plan=p,contract=other)


def test_forged_execution_authority_is_rejected_even_with_valid_local_digest():
    from aswe.core.fingerprint import fingerprint
    from aswe.planning.contracts import TaskExecutionAuthority
    c,a=contract()
    body=dict(repository_mutation_allowed=True,external_side_effects_allowed=frozenset(),
              granting_constraint_ids=("fabricated",))
    forged=TaskExecutionAuthority(**body,fingerprint=fingerprint(body))
    fail("CAPABILITY_AUTHORITY_VIOLATION",c,forged,
        item("read",WorkKind.DISCOVERY,("repo_exploration",)))


@pytest.mark.asyncio
async def test_semantic_planner_backend_returns_only_untrusted_proposal():
    class FakeReasoning:
        async def generate_structured(self, *, purpose, system_prompt, data_context,
                                      response_schema, model_role=None):
            assert "provider_id" not in data_context
            assert purpose=="semantic_plan_proposal"
            return StructuredReasoningResult(data={
                "items":[{"id":"explain","objective":"Explain source",
                          "work_kind":"discovery","capability_hints":["repo_exploration"],
                          "depends_on":[],"coverage_claims":[],"acceptance_intent":[]}],
                "rationale":"from fake model",
            })
    profile=RepositoryProfile(
        base_sha=BASE_SHA,tracked_file_count=0,top_level_tree=(),languages={},
        manifests=(),test_configs=(),build_configs=(),ci_configs=(),
        guidance_files=(),test_framework_hints=(),build_system_hints=(),
        task_anchor_matches=(),truncated=False,
    )
    task=TaskSpec(
        task_type=TaskType.ANALYSIS,description="explain",domains=(),
        repository_level=True,complexity=Complexity.LOW,risk=RiskLevel.LOW,
        testing_required=False,review_required=False,scope_hints=(),
        capability_hints=(),planning_uncertainties=(),
    )
    c,a=contract()
    proposal=await SemanticPlanner(FakeReasoning()).propose(
        task=task, contract=c,context=PlanningContext(repository_profile=profile),
        capability_catalog=("repo_exploration",),
    )
    assert isinstance(proposal,WorkPlanProposal)
    assert SemanticPlanValidator().validate(
        proposal=proposal,contract=c,authority=a,
    ).items[0].id=="explain"


def test_independent_test_gate_cannot_be_replaced_by_regression_on_writer():
    c,a,grant=gate_contract()
    fail("PLAN_INVALID",c,a,
         item("writer",WorkKind.IMPLEMENTATION,
              ("code_modification","regression_testing"),claims=(grant,)),
    )


def test_review_capability_cannot_be_mixed_into_implementation_or_verification():
    c,a,grant=mutation()
    fail("PLAN_INVALID",c,a,
         item("writer",WorkKind.IMPLEMENTATION,
              ("code_modification","code_review"),claims=(grant,)),
    )
    fail("PLAN_INVALID",c,a,
         item("tester",WorkKind.VERIFICATION,("regression_testing","code_review")),
    )


def test_runtime_gate_overbudget_is_rejected_before_deep_cyclic_graph():
    c,a,grant=gate_contract()
    nodes=[item(f"writer{i}",WorkKind.IMPLEMENTATION,("code_modification",),
                deps=(f"writer{i+1}",) if i<6 else ("writer0",),
                claims=(grant,)) for i in range(7)]
    fail("PLAN_INVALID",c,a,*nodes)
