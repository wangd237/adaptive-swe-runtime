"""Deterministic Step 3D Acceptance compilation and contract-bound verdict.

No LLM-generated shell strings, provider roster, or DeerFlow imports.
CanonicalCommandPolicy is reused from Step 2 as the sole check execution
policy; the exact Bash criterion and command allowlist share one identity.
"""
from __future__ import annotations

from enum import Enum
import shlex
from typing import Literal

from pydantic import Field, model_validator

from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts.constraint import ConstraintEnforcement
from aswe.core.contracts import EvidenceRef, TaskEvidenceRef, WorkspaceRevision
from aswe.core.fingerprint import fingerprint
from aswe.evaluation.contracts import (
    ContractLeafStatus, ContractLeafVerdict, ContractVerdict, build_contract_verdict,
)
from aswe.planning.contracts import CompiledTaskContract
from aswe.planning.profile import RepositoryProfile
from aswe.planning.validator import ValidatedWorkPlan
from aswe.runtime.canonical_verifier import (
    CanonicalCommandPolicy, make_command_policy,
)

SANDBOX_FEATURE = "deerflow_tests_passed_evidence"
# A subset of known safe command shapes. Real tool/sandbox admission is Step 4/5.
_DANGEROUS = set(";|&><`$\n\r")


class AcceptanceCompilationError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


class VerificationCommandKind(str, Enum):
    TEST = "test"
    BUILD = "build"
    IMPORT_CHECK = "import_check"
    STATIC_CHECK = "static_check"


class VerificationCommand(FrozenModel):
    id: str = Field(min_length=1)
    kind: VerificationCommandKind
    command: str = Field(min_length=1)
    argv: tuple[str, ...]
    source: Literal["user_hard_requirement", "repository_profile", "runtime_rule"]
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    check_keys: tuple[str, ...] = Field(min_length=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_command(self):
        _validate_argv(self.argv)
        if self.command != shlex.join(self.argv):
            raise ValueError("ACCEPTANCE_COMMAND_POLICY_MISMATCH: exact argv != command")
        if tuple(sorted(set(self.check_keys))) != self.check_keys:
            raise ValueError("verification check keys not canonical")
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("VerificationCommand fingerprint mismatch")
        return self


def _validate_argv(argv: tuple[str, ...]) -> None:
    if (not argv or any(
        not isinstance(arg, str) or not arg or "\x00" in arg
        or any(ch in _DANGEROUS for ch in arg)
        for arg in argv
    )):
        raise AcceptanceCompilationError("VERIFICATION_COMMAND_UNSAFE",
                                         "empty argv, shell metacharacter or control character")
    if argv[0] in ("sh", "bash", "zsh", "cmd", "powershell", "pwsh"):
        raise AcceptanceCompilationError("VERIFICATION_COMMAND_UNSAFE",
                                         "shell interpreter is not a trusted deterministic test runner")


class RuntimeVerificationRule(FrozenModel):
    """Operator-owned map of requirement key to an exact safe command."""
    check_key: str = Field(min_length=1)
    kind: VerificationCommandKind
    argv: tuple[str, ...]
    timeout_seconds: float = Field(default=30.0, gt=0, le=180)


class AcceptanceCriterionBinding(FrozenModel):
    command_id: str
    criterion: str
    bash_exact_allowlist_entry: str
    command_policy_fingerprint: str
    check_keys: tuple[str, ...]


class CompiledAcceptancePlan(FrozenModel):
    task_contract_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    commands: tuple[VerificationCommand, ...]
    criteria: tuple[AcceptanceCriterionBinding, ...]
    canonical_policies: tuple[CanonicalCommandPolicy, ...]
    unresolved_check_keys: tuple[str, ...]
    required_sandbox_features: tuple[str, ...]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_identity(self):
        if len(self.commands) != len(self.criteria) or len(self.commands) != len(self.canonical_policies):
            raise ValueError("ACCEPTANCE_COMMAND_POLICY_MISMATCH: binding cardinality")
        if tuple(sorted(set(self.unresolved_check_keys))) != self.unresolved_check_keys:
            raise ValueError("duplicate unresolved verification requirement")
        for command, criterion, policy in zip(self.commands, self.criteria, self.canonical_policies):
            if (criterion.command_id != command.id
                    or criterion.criterion != "tests_passed:" + command.command
                    or criterion.bash_exact_allowlist_entry != command.command
                    or criterion.command_policy_fingerprint != policy.fingerprint
                    or criterion.check_keys != command.check_keys
                    or policy.check_id != command.id
                    or policy.argv != command.argv):
                raise ValueError("ACCEPTANCE_COMMAND_POLICY_MISMATCH: command/criterion/policy drift")
        features = (SANDBOX_FEATURE,) if self.commands else ()
        if self.required_sandbox_features != features:
            raise ValueError("acceptance sandbox evidence requirement mismatch")
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("CompiledAcceptancePlan fingerprint mismatch")
        return self


def _command(kind, source, source_hash, argv, keys):
    _validate_argv(argv)
    body = dict(
        id="verify-" + fingerprint((source, source_hash, kind.value, argv, keys))[:20],
        kind=kind, command=shlex.join(argv), argv=argv,
        source=source, source_fingerprint=source_hash,
        check_keys=tuple(sorted(set(keys))),
    )
    return VerificationCommand(**body, fingerprint=fingerprint(body))


class AcceptanceCompiler:
    """Pure compiler. All runnable commands must come from operator rules
    or a small compiler-owned repository-profile mapping. No Planner intent
    can introduce argv.
    """

    def __init__(self, *, rules: tuple[RuntimeVerificationRule, ...] = (),
                 enable_profile_pytest: bool = False):
        self.rules = rules
        self.enable_profile_pytest = enable_profile_pytest

    def compile(self, *, contract: CompiledTaskContract,
                profile: RepositoryProfile | None = None) -> CompiledAcceptancePlan:
        req = next((c for c in contract.constraints if c.key == "verification.required"), None)
        required = tuple(req.value) if req and req.enforcement is not ConstraintEnforcement.SOFT else ()
        if len({rule.check_key for rule in self.rules}) != len(self.rules):
            raise AcceptanceCompilationError("ACCEPTANCE_COMMAND_POLICY_MISMATCH",
                                             "duplicate operator rule for one check")
        rules = {x.check_key: x for x in self.rules}
        selected: list[tuple[str, str, VerificationCommandKind, tuple[str, ...], float, str]] = []
        unresolved: list[str] = []
        for key in required:
            rule = rules.get(key)
            if rule is not None:
                selected.append((key, "runtime_rule", rule.kind, rule.argv,
                                 rule.timeout_seconds, fingerprint(rule)))
                continue
            # The repository profile is untrusted context; only a literal
            # compiler-owned static command may be derived from known metadata.
            if (self.enable_profile_pytest and key in ("unit", "regression")
                    and profile is not None
                    and profile.base_sha == contract.repository_base_sha
                    and ("pytest.ini" in profile.test_configs
                         or "pyproject.toml" in profile.test_configs)
                    and "pytest" in profile.test_framework_hints):
                selected.append((key, "repository_profile", VerificationCommandKind.TEST,
                                 ("pytest", "-q"), 30.0, fingerprint(profile)))
            else:
                unresolved.append(key)
        commands: list[VerificationCommand] = []
        policies: list[CanonicalCommandPolicy] = []
        criteria: list[AcceptanceCriterionBinding] = []
        for key, source, kind, argv, timeout, proof in selected:
            cmd = _command(kind, source, proof, argv, (key,))
            policy = make_command_policy(cmd.id, cmd.argv, timeout)
            commands.append(cmd)
            policies.append(policy)
            criteria.append(AcceptanceCriterionBinding(
                command_id=cmd.id, criterion="tests_passed:" + cmd.command,
                bash_exact_allowlist_entry=cmd.command,
                command_policy_fingerprint=policy.fingerprint,
                check_keys=cmd.check_keys,
            ))
        order = sorted(range(len(commands)), key=lambda i: commands[i].id)
        body = dict(
            task_contract_fingerprint=contract.fingerprint,
            commands=tuple(commands[i] for i in order),
            criteria=tuple(criteria[i] for i in order),
            canonical_policies=tuple(policies[i] for i in order),
            unresolved_check_keys=tuple(sorted(unresolved)),
            required_sandbox_features=(SANDBOX_FEATURE,) if commands else (),
        )
        return CompiledAcceptancePlan(**body, fingerprint=fingerprint(body))


class ExecutionContractBinding(FrozenModel):
    """Immutable planning-to-execution snapshot descriptor (Step-4 admission input)."""
    task_contract_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    validated_work_plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    acceptance_plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    repository_base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_digest(self):
        if self.fingerprint != fingerprint(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("execution contract binding fingerprint mismatch")
        return self


def bind_execution_contract(*, contract: CompiledTaskContract, plan: ValidatedWorkPlan,
                            acceptance: CompiledAcceptancePlan) -> ExecutionContractBinding:
    if (plan.task_contract_fingerprint != contract.fingerprint
            or acceptance.task_contract_fingerprint != contract.fingerprint):
        raise AcceptanceCompilationError("TASK_CONTRACT_FINGERPRINT_MISMATCH",
                                         "plan and acceptance must use identical contract")
    fields = dict(
        task_contract_fingerprint=contract.fingerprint,
        validated_work_plan_fingerprint=plan.fingerprint,
        acceptance_plan_fingerprint=acceptance.fingerprint,
        execution_policy_fingerprint=fingerprint(tuple(
            (c.id, p.fingerprint, criterion.criterion,
             criterion.bash_exact_allowlist_entry)
            for c, p, criterion in zip(
                acceptance.commands, acceptance.canonical_policies, acceptance.criteria
            )
        )),
        repository_base_sha=contract.repository_base_sha,
    )
    return ExecutionContractBinding(**fields, fingerprint=fingerprint(fields))


class CanonicalCheckBinding(FrozenModel):
    """Attempt-scoped receipt mapping supplied only by the Runtime EvidenceStore."""
    command_id: str
    proof: EvidenceRef
    node_id: str
    execution_id: str
    attempt: int = Field(ge=1)
    observed_revision: "WorkspaceRevision"


def verified_canonical_check_finding(
    *, contract: CompiledTaskContract, acceptance: CompiledAcceptancePlan,
    verifier: "CanonicalVerifier", receipts: tuple[CanonicalCheckBinding, ...],
) -> "TrustedEvaluationFinding":
    """Convert real HMAC-attested CanonicalVerifier receipts into a leaf.

    Every required check must have a matching command, policy and authenticated
    attempt receipt. Missing/unresolved/non-quiescent checks are UNVERIFIED.
    Failed checks are VIOLATED, not silently treated as semantic success.
    """
    if acceptance.task_contract_fingerprint != contract.fingerprint:
        raise AcceptanceCompilationError("TASK_CONTRACT_FINGERPRINT_MISMATCH",
                                         "check plan contract drift")
    target = next((c for c in contract.constraints if c.key == "verification.required"), None)
    if target is None:
        raise AcceptanceCompilationError("CONTRACT_VERDICT_INVALID",
                                         "no verification requirement to evaluate")
    if len({r.command_id for r in receipts}) != len(receipts):
        raise AcceptanceCompilationError("CONTRACT_VERDICT_INVALID",
                                         "duplicate canonical command receipt")
    from aswe.runtime.canonical_verifier import CanonicalVerifier
    if not isinstance(verifier, CanonicalVerifier):
        raise AcceptanceCompilationError("CONTRACT_VERDICT_INVALID",
                                         "Runtime CanonicalVerifier required")
    supplied = {r.command_id: r for r in receipts}
    expected = {cmd.id for cmd in acceptance.commands}
    if set(supplied) - expected:
        raise AcceptanceCompilationError("CONTRACT_VERDICT_INVALID",
                                         "unexpected verification receipt")
    status = ContractLeafStatus.SATISFIED
    refs: list[EvidenceRef] = []
    diagnostics: list[str] = []
    if acceptance.unresolved_check_keys:
        status = ContractLeafStatus.UNVERIFIED
        diagnostics.append("UNRESOLVED_CHECKS:" + ",".join(acceptance.unresolved_check_keys))
    for cmd, policy in zip(acceptance.commands, acceptance.canonical_policies):
        bound = supplied.get(cmd.id)
        if bound is None:
            status = ContractLeafStatus.UNVERIFIED
            diagnostics.append("MISSING_CANONICAL_RECEIPT:" + cmd.id)
            continue
        receipt = verifier.validate(
            bound.proof, node_id=bound.node_id,
            execution_id=bound.execution_id, attempt=bound.attempt,
            revision=bound.observed_revision, check_id=cmd.id,
        )
        if receipt.command_policy_fingerprint != policy.fingerprint:
            raise AcceptanceCompilationError("ACCEPTANCE_COMMAND_POLICY_MISMATCH",
                                             "attested receipt does not match compiled check policy")
        refs.append(bound.proof)
        if receipt.status == "failed":
            status = ContractLeafStatus.VIOLATED
        elif receipt.status != "holds" and status is not ContractLeafStatus.VIOLATED:
            status = ContractLeafStatus.UNVERIFIED
    return TrustedEvaluationFinding(
        constraint_id=target.id, status=status,
        supporting_refs=tuple(refs), diagnostics=tuple(diagnostics),
    )


class TrustedEvaluationFinding(FrozenModel):
    """Runtime evaluator input, NOT agent self-report or success authority.

    If not backed by actual verified EvidenceRefs, SATISFIED is treated as
    UNVERIFIED by the reducer.
    """
    constraint_id: str
    status: ContractLeafStatus
    supporting_refs: tuple[EvidenceRef | TaskEvidenceRef, ...] = ()
    diagnostics: tuple[str, ...] = ()


def evaluate_compiled_contract(*, contract: CompiledTaskContract,
                               findings: tuple[TrustedEvaluationFinding, ...] = (),
                               execution_binding: ExecutionContractBinding | None = None,
                               acceptance: CompiledAcceptancePlan | None = None,
                               observed_execution_binding_fingerprint: str | None = None,
                               canonical_verifier: "CanonicalVerifier | None" = None,
                               canonical_receipts: tuple[CanonicalCheckBinding, ...] = (),
                               ) -> ContractVerdict:
    """Fail closed on missing leaf or stale execution contract identity.

    This is a pure reducer of trusted runtime findings. It does not itself
    authenticate tool receipts; that is CanonicalVerifier/evidence resolver's job.
    """
    if execution_binding is not None:
        if (acceptance is None
                or observed_execution_binding_fingerprint is None
                or execution_binding.task_contract_fingerprint != contract.fingerprint
                or execution_binding.repository_base_sha != contract.repository_base_sha
                or execution_binding.acceptance_plan_fingerprint != acceptance.fingerprint
                or observed_execution_binding_fingerprint != execution_binding.fingerprint):
            raise AcceptanceCompilationError("TASK_CONTRACT_FINGERPRINT_MISMATCH",
                                             "executing snapshot does not match compiled TaskContract")
    elif acceptance is not None or observed_execution_binding_fingerprint is not None:
        raise AcceptanceCompilationError("TASK_CONTRACT_FINGERPRINT_MISMATCH",
                                         "incomplete execution binding")
    mapping = {f.constraint_id: f for f in findings}
    if len(mapping) != len(findings) or set(mapping) - {c.id for c in contract.constraints}:
        raise AcceptanceCompilationError("CONTRACT_VERDICT_INVALID",
                                         "duplicate or unknown constraint finding")
    if canonical_receipts and (canonical_verifier is None or acceptance is None):
        raise AcceptanceCompilationError("CONTRACT_VERDICT_INVALID",
                                         "canonical receipts need matched verifier and acceptance")
    if canonical_verifier is not None:
        if acceptance is None:
            raise AcceptanceCompilationError("CONTRACT_VERDICT_INVALID",
                                             "canonical verifier needs a compiled acceptance plan")
        checked = verified_canonical_check_finding(
            contract=contract, acceptance=acceptance, verifier=canonical_verifier,
            receipts=canonical_receipts,
        )
        # No manually supplied Verification success may bypass the canonical
        # receipt resolver. Compiler-owned result replaces it unconditionally.
        mapping[checked.constraint_id] = checked
    leaves = []
    for c in contract.constraints:
        finding = mapping.get(c.id)
        status = finding.status if finding else ContractLeafStatus.UNVERIFIED
        refs = finding.supporting_refs if finding else ()
        if c.key == "verification.required" and canonical_verifier is None:
            # A nonempty EvidenceRef and a caller-supplied 'satisfied' string
            # do not authenticate deterministic test success.
            status = ContractLeafStatus.UNVERIFIED
        diagnostics = finding.diagnostics if finding else ("MISSING_TRUSTED_EVALUATION_EVIDENCE",)
        if c.key == "verification.required" and canonical_verifier is None:
            diagnostics = diagnostics + ("CANONICAL_VERIFICATION_MISSING",)
        if (status is ContractLeafStatus.SATISFIED and not refs
                and c.enforcement is not ConstraintEnforcement.SOFT):
            status = ContractLeafStatus.UNVERIFIED
            diagnostics = diagnostics + ("SATISFACTION_PROOF_MISSING",)
        leaves.append(ContractLeafVerdict(
            constraint_id=c.id, enforcement=c.enforcement, status=status,
            supporting_refs=refs, diagnostics=diagnostics,
        ))
    return build_contract_verdict(contract.fingerprint, tuple(leaves))


def assert_final_contract_binding(*, contract: CompiledTaskContract,
                                  binding: ExecutionContractBinding,
                                  acceptance: CompiledAcceptancePlan,
                                  observed_execution_binding_fingerprint: str,
                                  verdict: ContractVerdict) -> None:
    """Step-4/terminal caller must provide the active *Runtime-owned* stamp."""
    effective_policy = fingerprint(tuple(
        (c.id, p.fingerprint, criterion.criterion,
         criterion.bash_exact_allowlist_entry)
        for c, p, criterion in zip(
            acceptance.commands, acceptance.canonical_policies, acceptance.criteria
        )
    ))
    if (observed_execution_binding_fingerprint != binding.fingerprint
            or binding.execution_policy_fingerprint != effective_policy
            or binding.task_contract_fingerprint != contract.fingerprint
            or binding.repository_base_sha != contract.repository_base_sha
            or binding.acceptance_plan_fingerprint != acceptance.fingerprint
            or verdict.task_contract_fingerprint != contract.fingerprint
            or {c.id for c in contract.constraints} != {v.constraint_id for v in verdict.leaves}
            or any(v.enforcement != next(c.enforcement for c in contract.constraints
                                         if c.id == v.constraint_id) for v in verdict.leaves)):
        raise AcceptanceCompilationError("TASK_CONTRACT_FINGERPRINT_MISMATCH",
                                         "terminal verdict cannot be used for this execution")
