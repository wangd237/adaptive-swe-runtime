"""Step 3D: operator-authorized VerificationCommand / acceptance / final C09-C10.

Real CanonicalVerifier/temporary Git evidence for success, fail closed for
missing/UNVERIFIED evidence, and exactly bound execution contract fingerprints.
"""
from __future__ import annotations

import sys

import pytest
from pydantic import ValidationError

from aswe.core.contracts.constraint import ConstraintEnforcement
from aswe.core.fingerprint import fingerprint
from aswe.evaluation.contracts import (
    ContractLeafStatus, ContractLeafVerdict, build_contract_verdict,
)
from aswe.planning.acceptance import (
    AcceptanceCompiler, AcceptanceCompilationError, AcceptanceCriterionBinding,
    CompiledAcceptancePlan, ExecutionContractBinding, RuntimeVerificationRule,
    TrustedEvaluationFinding, VerificationCommandKind, SANDBOX_FEATURE,
    assert_final_contract_binding, bind_execution_contract,
    evaluate_compiled_contract,
)
from aswe.planning.compiler import ConstraintCompiler, RuntimePolicyConfig, RuntimePolicyRule
from aswe.planning.contracts import make_task_request
from aswe.planning.planner import WorkItemProposal, WorkPlanProposal
from aswe.planning.validator import SemanticPlanValidator
from aswe.core.contracts.task import WorkKind
from aswe.runtime.canonical_verifier import CanonicalVerifier
from aswe.runtime.finalization import TaskLogicalStatus, finalize_task
from aswe.evidence import LocalEvidenceStore
from tests.fakes import FakeExecutionBackend, FakeExecutionScenario
from tests.unit.test_scheduler_foundation import accept


BASE = "a" * 40


def compiled(*rules):
    contract, authority = ConstraintCompiler(
        RuntimePolicyConfig(policy_id="operator", rules=tuple(
            RuntimePolicyRule(key=k,value=v) for k,v in rules
        ))
    ).compile(
        request=make_task_request(request_id="check",raw_text="Validate the task"),
        repository_base_sha=BASE,
    )
    return contract,authority


def verify_contract():
    return compiled(("verification.required",("unit",)))


def unit_rule(*, exit_code=0):
    return RuntimeVerificationRule(
        check_key="unit",kind=VerificationCommandKind.TEST,
        argv=(sys.executable,"-c",f"raise SystemExit({exit_code})"),
    )


def validator_plan(contract, authority):
    proposal=WorkPlanProposal(items=(
        WorkItemProposal(id="verify",objective="run unit tests",
                         work_kind=WorkKind.VERIFICATION,
                         capability_hints=("regression_testing",)),
    ),rationale="verify")
    return SemanticPlanValidator().validate(
        proposal=proposal,contract=contract,authority=authority,
    )


def get_constraint(contract,key="verification.required"):
    return next(c for c in contract.constraints if c.key==key)


def test_d01_one_command_is_single_identity_for_criterion_allowlist_and_canonical_policy():
    contract,_=verify_contract()
    result=AcceptanceCompiler(rules=(unit_rule(),)).compile(contract=contract)
    assert len(result.commands)==len(result.criteria)==len(result.canonical_policies)==1
    command=result.commands[0]
    criterion=result.criteria[0]
    policy=result.canonical_policies[0]
    assert criterion.command_id==policy.check_id==command.id
    assert criterion.criterion=="tests_passed:"+command.command
    assert criterion.bash_exact_allowlist_entry==command.command
    assert criterion.command_policy_fingerprint==policy.fingerprint
    assert command.argv==policy.argv==unit_rule().argv
    assert command.source=="runtime_rule"
    assert result.required_sandbox_features==(SANDBOX_FEATURE,)


def test_d02_criterion_argv_or_policy_divergence_fails_at_compilation():
    contract,_=verify_contract()
    plan=AcceptanceCompiler(rules=(unit_rule(),)).compile(contract=contract)
    criterion=plan.criteria[0]
    with pytest.raises(ValidationError,match="ACCEPTANCE_COMMAND_POLICY_MISMATCH"):
        plan.model_copy(update={"criteria":(criterion.model_copy(
            update={"bash_exact_allowlist_entry":"pytest -k different"}
        ),)})
    with pytest.raises(ValidationError,match="ACCEPTANCE_COMMAND_POLICY_MISMATCH"):
        plan.model_copy(update={"canonical_policies":(
            plan.canonical_policies[0].model_copy(
                update={"argv":("pytest","-k","different")},
            ),
        )})
    with pytest.raises(ValidationError,match="ACCEPTANCE_COMMAND_POLICY_MISMATCH"):
        plan.model_copy(update={"criteria":()})


def test_d03_missing_check_cannot_be_silently_assumed_passing():
    contract,_=verify_contract()
    plan=AcceptanceCompiler().compile(contract=contract)
    assert plan.commands==()
    assert plan.unresolved_check_keys==("unit",)
    assert plan.required_sandbox_features==()
    verdict=evaluate_compiled_contract(contract=contract)
    assert verdict.all_required_satisfied is False
    assert verdict.blocking_constraint_ids==(get_constraint(contract).id,)
    assert verdict.leaves[0].status is ContractLeafStatus.UNVERIFIED


def test_d04_repository_profile_cannot_inject_arbitrary_command():
    from aswe.planning.profile import RepositoryProfile
    contract,_=verify_contract()
    profile=RepositoryProfile(
        base_sha=BASE,tracked_file_count=1,top_level_tree=(),
        languages={},manifests=(),test_configs=("pytest.ini",),
        build_configs=(),ci_configs=(),guidance_files=(),
        test_framework_hints=("pytest",),
        build_system_hints=(),task_anchor_matches=(),truncated=False,
    )
    off=AcceptanceCompiler().compile(contract=contract,profile=profile)
    assert off.unresolved_check_keys==("unit",)
    enabled=AcceptanceCompiler(enable_profile_pytest=True).compile(contract=contract,profile=profile)
    assert enabled.commands[0].command=="pytest -q"
    assert enabled.commands[0].source=="repository_profile"
    wrong=profile.model_copy(update={"base_sha":"b"*40})
    blocked=AcceptanceCompiler(enable_profile_pytest=True).compile(contract=contract,profile=wrong)
    assert blocked.unresolved_check_keys==("unit",)


def test_d05_unsupported_shell_metacharacters_and_interpreters_rejected():
    contract,_=verify_contract()
    for argv in (("bash","-c","echo ok"),("pytest;rm","-q"),("pytest","-q\nrm")):
        with pytest.raises(AcceptanceCompilationError,match="VERIFICATION_COMMAND_UNSAFE"):
            AcceptanceCompiler(rules=(RuntimeVerificationRule(
                check_key="unit",kind=VerificationCommandKind.TEST,argv=argv
            ),)).compile(contract=contract)


def test_d06_duplicate_operator_rule_fail_closed():
    contract,_=verify_contract()
    with pytest.raises(AcceptanceCompilationError,match="ACCEPTANCE_COMMAND_POLICY_MISMATCH"):
        AcceptanceCompiler(rules=(unit_rule(),unit_rule(exit_code=1))).compile(contract=contract)


def test_d07_execution_binding_covers_contract_plan_and_acceptance_policy():
    contract,authority=verify_contract()
    p=validator_plan(contract,authority)
    acceptance=AcceptanceCompiler(rules=(unit_rule(),)).compile(contract=contract)
    binding=bind_execution_contract(contract=contract,plan=p,acceptance=acceptance)
    assert binding.task_contract_fingerprint==contract.fingerprint
    assert binding.acceptance_plan_fingerprint==acceptance.fingerprint
    assert binding.validated_work_plan_fingerprint==p.fingerprint
    assert binding.execution_policy_fingerprint
    assert bind_execution_contract(contract=contract,plan=p,acceptance=acceptance)==binding
    with pytest.raises(ValidationError,match="execution contract binding fingerprint mismatch"):
        binding.model_copy(update={"task_contract_fingerprint":"0"*64})


def test_c09_hard_locked_unverified_and_missing_proof_must_block_success():
    contract,authority=compiled(
        ("verification.required",("unit",)),
        ("review.required",True),
    )
    check=get_constraint(contract)
    review=get_constraint(contract,"review.required")
    assert check.enforcement is ConstraintEnforcement.LOCKED
    findings=(TrustedEvaluationFinding(
        constraint_id=check.id,status=ContractLeafStatus.SATISFIED,
        # A self-reported success with no refs is NOT proof:
    ),)
    verdict=evaluate_compiled_contract(contract=contract,findings=findings)
    assert not verdict.all_required_satisfied
    assert verdict.blocking_constraint_ids==(check.id,review.id) or verdict.blocking_constraint_ids==tuple(sorted((check.id,review.id)))
    assert all(v.status is ContractLeafStatus.UNVERIFIED for v in verdict.leaves)
    with pytest.raises(AcceptanceCompilationError,match="CONTRACT_VERDICT_INVALID"):
        evaluate_compiled_contract(
            contract=contract,
            findings=(TrustedEvaluationFinding(
                constraint_id="fabricated",status=ContractLeafStatus.SATISFIED,
            ),),
        )


def test_c10_substituted_execution_or_verdict_contract_is_rejected():
    contract,authority=verify_contract()
    plan=validator_plan(contract,authority)
    acceptance=AcceptanceCompiler(rules=(unit_rule(),)).compile(contract=contract)
    binding=bind_execution_contract(contract=contract,plan=plan,acceptance=acceptance)
    other,other_authority=compiled(("review.required",True))
    other_plan=validator_plan(other,other_authority)
    other_acceptance=AcceptanceCompiler().compile(contract=other)
    with pytest.raises(AcceptanceCompilationError,match="TASK_CONTRACT_FINGERPRINT_MISMATCH"):
        bind_execution_contract(contract=other,plan=plan,acceptance=acceptance)
    verdict=evaluate_compiled_contract(contract=contract)
    with pytest.raises(AcceptanceCompilationError,match="TASK_CONTRACT_FINGERPRINT_MISMATCH"):
        assert_final_contract_binding(
            contract=other,binding=binding,acceptance=acceptance,
            observed_execution_binding_fingerprint=binding.fingerprint,verdict=verdict,
        )
    with pytest.raises(AcceptanceCompilationError,match="TASK_CONTRACT_FINGERPRINT_MISMATCH"):
        assert_final_contract_binding(
            contract=contract,binding=binding,acceptance=acceptance,
            observed_execution_binding_fingerprint=other_acceptance.fingerprint,verdict=verdict,
        )
    with pytest.raises(AcceptanceCompilationError,match="TASK_CONTRACT_FINGERPRINT_MISMATCH"):
        evaluate_compiled_contract(
            contract=contract,execution_binding=binding,acceptance=acceptance,
            observed_execution_binding_fingerprint=other_acceptance.fingerprint,
        )


@pytest.mark.asyncio
async def test_c09_c10_real_canonical_attested_proof_and_finalization_binding(terminal_fixture):
    core,manager,repo_binding,store=terminal_fixture
    # The fixture's Git baseline is the authoritative contract repo base.
    c,a=ConstraintCompiler(RuntimePolicyConfig(
        policy_id="p",rules=(RuntimePolicyRule(
            key="verification.required",value=("unit",)
        ),)
    )).compile(
        request=make_task_request(request_id="final",raw_text="Verify real test"),
        repository_base_sha=core.revision.base_sha,
    )
    p=validator_plan(c,a)
    acceptance=AcceptanceCompiler(rules=(unit_rule(),)).compile(contract=c)
    binding=bind_execution_contract(contract=c,plan=p,acceptance=acceptance)
    await core.run_claim(
        await core.claim("writer"),FakeExecutionBackend([FakeExecutionScenario()]),accept=accept
    )
    attempt=core.states["writer"].attempts[-1]
    checker=CanonicalVerifier(task_id=core.task_id,runtime_data_dir=store.root,
                              evidence_store=store,binding=repo_binding)
    ref,receipt=checker.run(
        node_id="writer",execution_id=attempt.execution_id,attempt=attempt.attempt,
        policy=acceptance.canonical_policies[0],revision=core.revision,
    )
    assert receipt.status=="holds"
    checker.validate(
        ref,node_id="writer",execution_id=attempt.execution_id,attempt=attempt.attempt,
        revision=core.revision,check_id=acceptance.commands[0].id,
    )
    verified=(TrustedEvaluationFinding(
        constraint_id=get_constraint(c).id,status=ContractLeafStatus.SATISFIED,
        supporting_refs=(ref,),
    ),)
    cv=evaluate_compiled_contract(
        contract=c,findings=verified,
        execution_binding=binding,acceptance=acceptance,
        observed_execution_binding_fingerprint=binding.fingerprint,
    )
    assert cv.all_required_satisfied
    assert_final_contract_binding(
        contract=c,binding=binding,acceptance=acceptance,
        observed_execution_binding_fingerprint=binding.fingerprint,verdict=cv,
    )
    await core.complete_task()
    result=finalize_task(scheduler=core,binding=repo_binding,evidence_store=store,
                         contract_verdict=cv,expected_contract_fingerprint=binding.task_contract_fingerprint)
    assert result.status is TaskLogicalStatus.SUCCEEDED
    assert result.final_contract_verdict is not None
    assert store.get(result.final_contract_verdict)["task_contract_fingerprint"]==c.fingerprint
    # Same EvidenceRef from different compiled contract never authorizes success.
    c2,_=compiled(("verification.required",("integration",)))
    wrong=finalize_task(scheduler=core,binding=repo_binding,evidence_store=store,
                        contract_verdict=cv,expected_contract_fingerprint=c2.fingerprint)
    assert wrong.status is TaskLogicalStatus.FAILED
