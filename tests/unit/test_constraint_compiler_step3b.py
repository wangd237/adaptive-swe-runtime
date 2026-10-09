"""Frozen Step-3B conformance: C02/C03/C05/C06/C07 and regression negatives.

Recognized structured user requirements are allowed only when the quoted
directive occurs VERBATIM in immutable TaskRequestEnvelope.raw_text.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from aswe.core.contracts.constraint import ConstraintEnforcement
from aswe.planning.analyzer import TaskSpec, TaskType, Complexity, RiskLevel
from aswe.planning.contracts import (
    ConstraintCandidate, ConstraintOrigin, make_task_request,
)
from aswe.planning.compiler import (
    ConstraintCompiler, ContractCompilationError, RuntimePolicyConfig,
    RuntimePolicyRule, RepositoryGuidanceSource,
)
from aswe.planning.constraints import ConstraintProvenanceError
from aswe.planning.registry import canonical_value, normalize_path


BASE = "1" * 40


def req(*quotes):
    text = "\n".join(quotes or ("Analyze only",))
    return make_task_request(request_id="q-1", raw_text=text)


def candidate(quote, **attrs):
    return ConstraintCandidate(
        key=attrs.get("key", "fabricated.key"), operator="invented",
        value=attrs.get("value", "not actually user intent"),
        evidence_quote=quote, origin_hint="runtime_policy", modality_hint="locked",
        evidence_locator=attrs.get("locator"),
    )


def compiled(policy=(), quotes=(), guidance=()):
    request = req(*quotes)
    return ConstraintCompiler(RuntimePolicyConfig(
        policy_id="operator-runtime-v1", rules=tuple(
            RuntimePolicyRule(key=k, value=v) for k, v in policy
        ),
    )).compile(
        request=request, repository_base_sha=BASE,
        user_candidates=tuple(candidate(q) for q in quotes),
        guidance=tuple(guidance),
    )


def by_key(contract, key):
    return next(c for c in contract.constraints if c.key == key)


def test_c02_runtime_locked_deny_clashes_with_user_mutation_hard():
    with pytest.raises(ContractCompilationError) as e:
        compiled(
            policy=(("actions.forbidden", ("repository_mutation",)),),
            quotes=("deliverables.required: repository_mutation | fix leak",),
        )
    assert e.value.code == "CONTRACT_POLICY_CONFLICT"


def test_c02_no_soft_demotion_of_explicit_hard_requirement():
    with pytest.raises(ContractCompilationError, match="CONTRACT_POLICY_CONFLICT"):
        compiled(
            policy=(("repo.paths.allowed", ("docs/**",)),),
            quotes=(
                "deliverables.required: repository_mutation | fix authentication",
                "target.exact_path: src/auth/login.py",
            ),
        )


def test_c03_incompatible_user_exact_hard_constraints_are_unsatisfiable():
    with pytest.raises(ContractCompilationError) as e:
        compiled(quotes=(
            "target.exact_path: src/a.py",
            "target.exact_path: src/b.py",
        ))
    assert e.value.code == "CONTRACT_UNSATISFIABLE"


def test_c05_runtime_allow_and_user_allow_intersect_subtrees_not_literal_strings():
    contract, authority = compiled(
        policy=(("repo.paths.allowed", ("src/**",)),),
        quotes=(
            "repo.paths.allowed: src/auth/**",
            "deliverables.required: repository_mutation | fix authentication",
        ),
    )
    allowed = by_key(contract, "repo.paths.allowed")
    assert allowed.value == ("src/auth/**",)
    assert allowed.enforcement is ConstraintEnforcement.LOCKED
    assert allowed.provenance.provenance_verified
    assert len(allowed.provenance.evidence) == 2
    assert authority.repository_mutation_allowed
    assert len(authority.granting_constraint_ids) == 1
    assert authority.external_side_effects_allowed == frozenset()


def test_c05_unrelated_allow_scopes_do_not_widen_permissions():
    contract, authority = compiled(
        policy=(("repo.paths.allowed", ("src/**",)),),
        quotes=("repo.paths.allowed: docs/**",),
    )
    assert by_key(contract, "repo.paths.allowed").value == ()
    assert not authority.repository_mutation_allowed


def test_c05_global_wildcard_is_safe_and_exact_scope_wins():
    contract, _ = compiled(
        policy=(("repo.paths.allowed", ("**",)),),
        quotes=("repo.paths.allowed: src/auth/**",),
    )
    assert by_key(contract, "repo.paths.allowed").value == ("src/auth/**",)


def test_c06_forbidden_actions_and_paths_use_union_regardless_source():
    guide = RepositoryGuidanceSource(
        path="AGENTS.md",
        content="actions.forbidden: unsafe_shell\nrepo.paths.forbidden: secrets/**",
        candidates=(
            candidate("actions.forbidden: unsafe_shell"),
            candidate("repo.paths.forbidden: secrets/**"),
        ),
    )
    contract, _ = compiled(
        policy=(
            ("actions.forbidden", ("deploy",)),
            ("repo.paths.forbidden", ("private/**",)),
        ),
        quotes=(
            "actions.forbidden: delete_repo",
            "repo.paths.forbidden: generated/**",
        ),
        guidance=(guide,),
    )
    assert by_key(contract, "actions.forbidden").value == (
        "delete_repo", "deploy", "unsafe_shell",
    )
    assert by_key(contract, "repo.paths.forbidden").value == (
        "generated/**", "private/**", "secrets/**",
    )
    assert by_key(contract, "actions.forbidden").enforcement is ConstraintEnforcement.LOCKED


def test_c07_analysis_task_capability_hint_cannot_grant_mutation():
    contract, authority = compiled(
        quotes=("deliverables.required: report_only | explain connection leak",),
    )
    fake_analyzer = TaskSpec(
        task_type=TaskType.ANALYSIS, description="explain connection leak",
        domains=("backend",), repository_level=True,
        complexity=Complexity.MEDIUM, risk=RiskLevel.LOW,
        testing_required=False, review_required=False,
        scope_hints=(), capability_hints=("code_modification",),
        planning_uncertainties=(),
    )
    assert fake_analyzer.capability_hints == ("code_modification",)
    assert not authority.repository_mutation_allowed
    assert authority.granting_constraint_ids == ()
    assert by_key(contract, "deliverables.required").value[0].effect.value == "report_only"


def test_c07_repo_guidance_mutation_directive_cannot_grant_authority():
    src = RepositoryGuidanceSource(
        path="README.md",
        content="deliverables.required: repository_mutation | edit source",
        candidates=(candidate("deliverables.required: repository_mutation | edit source"),),
    )
    contract, authority = compiled(guidance=(src,))
    assert not authority.repository_mutation_allowed
    assert by_key(contract, "semantic.requirement").enforcement is ConstraintEnforcement.SOFT


def test_budget_ceilings_take_min_and_required_obligations_union():
    contract, _ = compiled(
        policy=(
            ("change.max_files", 8),
            ("verification.required", ("unit",)),
            ("review.required", True),
        ),
        quotes=(
            "change.max_files: 3",
            "verification.required: integration",
            "review.required: false",
        ),
    )
    assert by_key(contract, "change.max_files").value == 3
    assert by_key(contract, "verification.required").value == ("integration", "unit")
    assert by_key(contract, "review.required").value is True


def test_soft_exact_guidance_conflicts_with_hard_and_is_overridden_not_promoted():
    src = RepositoryGuidanceSource(
        path="CONTRIBUTING.md",
        content="target.exact_path: src/legacy.py",
        candidates=(candidate("target.exact_path: src/legacy.py"),),
    )
    contract, _ = compiled(
        quotes=("target.exact_path: src/new.py",), guidance=(src,),
    )
    assert by_key(contract, "target.exact_path").value == "src/new.py"
    assert {w["code"] for w in contract.warnings} == {"OVERRIDDEN_GUIDANCE"}


def test_compilation_is_order_independent_and_has_stable_fingerprint():
    p = (("actions.forbidden", ("deploy",)),)
    a, auth_a = compiled(policy=p, quotes=(
        "actions.forbidden: shell", "verification.required: regression",
    ))
    b, auth_b = compiled(policy=p, quotes=(
        "verification.required: regression", "actions.forbidden: shell",
    ))
    # Raw user text itself is immutable evidence: reorder naturally changes the
    # request hash, unlike reordering unordered policy/group contributors.
    assert a.fingerprint != b.fingerprint
    c, auth_c = compiled(policy=p, quotes=(
        "actions.forbidden: shell", "verification.required: regression",
    ))
    assert a == c and auth_a == auth_c
    with pytest.raises(ValidationError, match="compiled contract fingerprint mismatch"):
        a.model_copy(update={"repository_base_sha": "2" * 40})
    with pytest.raises(ValidationError, match="task execution authority fingerprint mismatch"):
        auth_a.model_copy(update={"repository_mutation_allowed": True})


def test_spoofed_user_locator_or_path_escape_fails_closed():
    request = req("repo.paths.allowed: src/**")
    policy = RuntimePolicyConfig(policy_id="p")
    with pytest.raises(ConstraintProvenanceError, match="locator"):
        ConstraintCompiler(policy).compile(
            request=request, repository_base_sha=BASE,
            user_candidates=(candidate("repo.paths.allowed: src/**",
                                       locator="raw_text:900:22"),),
        )
    for unsafe in ("../secrets", "/absolute", "src/../secret", "src/*/secret.py"):
        with pytest.raises(ValueError):
            normalize_path(unsafe, pattern=True)


def test_unknown_prose_with_model_forged_permission_is_semantic_not_authority():
    request = req("Please explain why the connection leaks.")
    c = candidate(request.raw_text, key="deliverables.required",
                  value={"effect": "repository_mutation"})
    contract, authority = ConstraintCompiler(
        RuntimePolicyConfig(policy_id="p"),
    ).compile(
        request=request, repository_base_sha=BASE,
        user_candidates=(c,),
    )
    assert not authority.repository_mutation_allowed
    assert by_key(contract, "semantic.requirement").value == (request.raw_text,)
    assert by_key(contract, "semantic.requirement").provenance.origin is ConstraintOrigin.USER_EXPLICIT


def test_report_only_task_quoting_structured_mutation_example_has_no_authority():
    example = "deliverables.required: repository_mutation | edit the source"
    raw = "Explain this sample directive without executing it: " + example
    contract, authority = ConstraintCompiler(
        RuntimePolicyConfig(policy_id="locked"),
    ).compile(
        request=make_task_request(request_id="analysis", raw_text=raw),
        repository_base_sha=BASE,
        user_candidates=(candidate(example),),
    )
    assert not authority.repository_mutation_allowed
    assert by_key(contract, "semantic.requirement").value == (example,)


def test_structured_directive_within_markdown_code_fence_is_only_semantic():
    example = "deliverables.required: repository_mutation | edit files"
    raw = "Analyze the following example:\n```text\n" + example + "\n```"
    contract, authority = ConstraintCompiler(RuntimePolicyConfig(policy_id="p")).compile(
        request=make_task_request(request_id="analysis", raw_text=raw),
        repository_base_sha=BASE,
        user_candidates=(candidate(example),),
    )
    assert not authority.repository_mutation_allowed
    assert by_key(contract, "semantic.requirement").value == (example,)


def test_locked_deny_all_paths_cannot_grant_repository_mutation():
    with pytest.raises(ContractCompilationError, match="CONTRACT_POLICY_CONFLICT"):
        compiled(policy=(("repo.paths.allowed", ()),),
                 quotes=("deliverables.required: repository_mutation | edit app",))
    with pytest.raises(ContractCompilationError, match="CONTRACT_POLICY_CONFLICT"):
        compiled(policy=(("repo.paths.forbidden", ("**",)),),
                 quotes=("deliverables.required: repository_mutation | edit app",))


def test_effective_allowed_subtree_fully_forbidden_is_policy_conflict():
    with pytest.raises(ContractCompilationError, match="CONTRACT_POLICY_CONFLICT"):
        compiled(
            policy=(("repo.paths.allowed", ("src/auth/**",)),
                    ("repo.paths.forbidden", ("src/**",))),
            quotes=("deliverables.required: repository_mutation | edit app",),
        )


def test_operator_authorized_high_risk_rule_generates_review_not_mutation():
    from aswe.planning.analyzer import TaskSpec, TaskType, Complexity, RiskLevel
    task = TaskSpec(
        task_type=TaskType.ANALYSIS, description="security risk assessment",
        domains=("security",), repository_level=True, complexity=Complexity.HIGH,
        risk=RiskLevel.HIGH, testing_required=False, review_required=False,
        scope_hints=(), capability_hints=("code_modification",),
        planning_uncertainties=(),
    )
    policy = RuntimePolicyConfig(policy_id="p", high_risk_requires_review=True)
    contract, authority = ConstraintCompiler(policy).compile(
        request=req("Analyze security risks"), repository_base_sha=BASE,
        task_spec=task,
    )
    review = by_key(contract, "review.required")
    assert review.value is True
    assert review.enforcement is ConstraintEnforcement.HARD
    assert review.provenance.origin is ConstraintOrigin.RUNTIME_DERIVED
    assert review.provenance.evidence[0].source_kind == "task_spec"
    assert not authority.repository_mutation_allowed

    off, _ = ConstraintCompiler(
        RuntimePolicyConfig(policy_id="p", high_risk_requires_review=False)
    ).compile(request=req("Analyze security risks"), repository_base_sha=BASE,
              task_spec=task)
    assert all(c.key != "review.required" for c in off.constraints)


def test_soft_test_command_user_beats_repository_and_runtime_default():
    guide = RepositoryGuidanceSource(
        path="CONTRIBUTING.md", content="preference.test_command: tox -q",
        candidates=(candidate("preference.test_command: tox -q"),),
    )
    request = req("preference.test_command: pytest -q")
    contract, _ = ConstraintCompiler(
        RuntimePolicyConfig(policy_id="p", rules=(
            RuntimePolicyRule(
                key="preference.test_command", value="python -m unittest",
                enforcement=ConstraintEnforcement.SOFT,
            ),
        )),
    ).compile(
        request=request, repository_base_sha=BASE,
        user_candidates=(candidate(request.raw_text),),
        guidance=(guide,),
    )
    chosen = by_key(contract, "preference.test_command")
    assert chosen.value == "pytest -q"
    assert chosen.enforcement is ConstraintEnforcement.SOFT
    assert chosen.provenance.origin is ConstraintOrigin.USER_EXPLICIT
    assert contract.warnings


def test_monotonic_merge_repairs_record_exact_inputs_and_result_digest():
    contract, _ = compiled(
        policy=(("repo.paths.allowed", ("src/**",)),
                ("change.max_files", 10)),
        quotes=("repo.paths.allowed: src/auth/**",
                "change.max_files: 2"),
    )
    assert {r["key"] for r in contract.compiler_repairs} == {
        "repo.paths.allowed", "change.max_files",
    }
    assert all(r["code"] == "MONOTONIC_MERGE" for r in contract.compiler_repairs)


def test_runtime_soft_preference_does_not_mislabel_user_hard_exact_constraint():
    c, _ = ConstraintCompiler(
        RuntimePolicyConfig(policy_id="p", rules=(
            RuntimePolicyRule(
                key="target.exact_path", value="src/legacy.py",
                enforcement=ConstraintEnforcement.SOFT,
            ),
        )),
    ).compile(
        request=req("target.exact_path: src/new.py"),
        repository_base_sha=BASE,
        user_candidates=(candidate("target.exact_path: src/new.py"),),
    )
    target = by_key(c, "target.exact_path")
    assert target.enforcement is ConstraintEnforcement.HARD
    assert target.provenance.origin is ConstraintOrigin.USER_EXPLICIT
    assert target.value == "src/new.py"


def test_external_side_effect_requirement_is_explicit_policy_conflict():
    with pytest.raises(ContractCompilationError) as err:
        compiled(quotes=("deliverables.required: external_side_effect | deploy production",))
    assert err.value.code == "CONTRACT_POLICY_CONFLICT"


def test_locked_wildcard_action_deny_conflicts_with_requested_mutation():
    with pytest.raises(ContractCompilationError) as err:
        compiled(policy=(("actions.forbidden", ("*",)),),
                 quotes=("deliverables.required: repository_mutation | fix code",))
    assert err.value.code == "CONTRACT_POLICY_CONFLICT"
