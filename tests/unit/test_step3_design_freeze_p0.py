"""Design Freeze P0-A..D, tested against an actual temporary Git repository."""
import subprocess
from pathlib import Path
import pytest
from pydantic import ValidationError

from aswe.core.fingerprint import fingerprint
from aswe.planning.profiler import collect_repository_profile, RepositoryProfileError
from aswe.planning.analyzer import TaskSpec, TaskType, Complexity, RiskLevel, StructuredReasoningResult
from aswe.planning.analyzer_runtime import TaskAnalyzer,TaskAnalysis
from aswe.planning.context import build_planning_context,needs_recon
from aswe.planning.planner import PlanningContext,SemanticPlanner
from aswe.planning.contracts import TaskContractDraft,make_task_request
from aswe.planning.compiler import ConstraintCompiler,RuntimePolicyConfig
from aswe.planning.validator import PlanRepair,PlanWarning,ValidatedWorkPlan
from aswe.planning.profile import RepositoryProfile

def git(root,*args):
    return subprocess.check_output(["git","-C",str(root),*args],stderr=subprocess.DEVNULL).decode().strip()

@pytest.fixture
def repo(tmp_path):
    git(tmp_path,"init","-q")
    git(tmp_path,"config","user.email","test@example.com")
    git(tmp_path,"config","user.name","Test")
    (tmp_path/"src").mkdir()
    (tmp_path/"src"/"login.py").write_text("class UserService:\n    def login(self): return True\n")
    (tmp_path/"pytest.ini").write_text("[pytest]\n")
    (tmp_path/"AGENTS.md").write_text("read source only")
    git(tmp_path,"add",".")
    git(tmp_path,"commit","-qm","initial")
    return tmp_path

def task(t=TaskType.BUG_FIX,**kwargs):
    return TaskSpec(
        task_type=t,description="Fix login",domains=(),repository_level=True,
        complexity=kwargs.get("complexity",Complexity.MEDIUM),
        risk=kwargs.get("risk",RiskLevel.MEDIUM),testing_required=False,
        review_required=False,scope_hints=kwargs.get("scopes",()),
        capability_hints=(),planning_uncertainties=(),
    )

def test_p0a_git_head_profile_deterministic_and_anchor_resolved(repo):
    first=collect_repository_profile(repo,task_text="UserService login")
    assert first.base_sha==git(repo,"rev-parse","HEAD")
    assert first.tracked_file_count==3
    assert first.languages["Python"]==1
    assert first.manifests==()
    assert "pytest.ini" in first.test_configs and "AGENTS.md" in first.guidance_files
    assert any(m.anchor=="UserService" and m.path=="src/login.py" for m in first.task_anchor_matches)
    assert collect_repository_profile(repo,task_text="UserService login")==first
    (repo/"src"/"login.py").write_text("malicious injected content; UserService removed")
    # Must remain pinned to Git HEAD rather than dirty mutable worktree.
    assert collect_repository_profile(repo,task_text="UserService login")==first
    with pytest.raises(RepositoryProfileError):
        collect_repository_profile(repo,base_sha="0"*40)

def test_p0a_budget_and_noncommitted_paths_are_ignored(repo):
    (repo/"untracked.py").write_text("class NewUntracked: pass")
    p=collect_repository_profile(repo,task_text="NewUntracked",max_paths=2)
    assert p.truncated and p.tracked_file_count==3
    assert all(m.path!="untracked.py" for m in p.task_anchor_matches)

@pytest.mark.asyncio
async def test_p0b_analyzer_rules_and_candidate_nonpromotion(repo):
    profile=collect_repository_profile(repo,task_text="src/missing.py")
    class FakeReasoning:
        async def generate_structured(self,**kwargs):
            assert kwargs["purpose"]=="task_analyzer"
            return StructuredReasoningResult(data={
                "spec":task().model_dump(mode="json") | {"risk":"high"},
                "draft":{"candidates":[{"key":"deliverables.required",
                    "operator":"=", "value":{"effect":"repository_mutation"},
                    "origin_hint":"runtime_policy","modality_hint":"locked",
                    "evidence_quote":"model invented"}]},
            })
    request=make_task_request(request_id="r",raw_text="Fix src/missing.py and run regression tests")
    output=await TaskAnalyzer(FakeReasoning()).analyze(request=request,profile=profile)
    assert "code_modification" in output.spec.capability_hints
    assert output.spec.review_required and output.spec.testing_required
    assert "UNRESOLVED_TARGET:src/missing.py" in output.spec.planning_uncertainties
    assert output.draft.candidates[0].origin_hint=="runtime_policy"
    # Forged LLM candidate is not compiler provenance.
    from aswe.planning.constraints import ConstraintProvenanceError
    with pytest.raises(ConstraintProvenanceError):
        ConstraintCompiler(RuntimePolicyConfig(policy_id="p")).compile(
            request=request,repository_base_sha=profile.base_sha,
            user_candidates=output.draft.candidates,
        )

def test_p0b_planning_context_gate_no_llm_or_write_tools(repo):
    known=collect_repository_profile(repo,task_text="src/login.py")
    resolved=build_planning_context(task=task(complexity=Complexity.LOW,
                                              risk=RiskLevel.LOW,scopes=("src/login.py",)),
                                     profile=known)
    assert resolved.context_complete and resolved.recon_report is None
    unknown=collect_repository_profile(repo,task_text="unknown_never_here")
    pending=build_planning_context(task=task(),profile=unknown)
    assert not pending.context_complete and "RECON_REQUIRED" in pending.unresolved_questions
    actual=build_planning_context(task=task(),profile=unknown,root=repo)
    assert actual.recon_report is not None
    assert all(f.confidence=="observed" for f in actual.recon_report.findings)
    assert not actual.context_complete
    assert PlanningContext.model_validate(actual.model_dump(mode="json"))==actual
    with pytest.raises(ValidationError,match="PlanningContext fingerprint mismatch"):
        actual.model_copy(update={"context_complete":True})
    with pytest.raises(RepositoryProfileError):
        build_planning_context(task=task(),profile=unknown,root=repo/"not-a-repository")

def contract_for(text,*,hints=()):
    request=make_task_request(request_id="r",raw_text=text)
    return ConstraintCompiler(RuntimePolicyConfig(policy_id="p")).compile(
        request=request,repository_base_sha="a"*40,
        task_spec=task().model_copy(update={"capability_hints":tuple(hints)}),
    )

@pytest.mark.parametrize("text",[
    "Fix the connection leak.",
    "Repair connection pooling bug.",
    "Implement pagination support.",
    "修复登录时的错误",
])
def test_p0c_direct_user_mutation_granted(text):
    c,a=contract_for(text)
    assert a.repository_mutation_allowed
    leaf=next(x for x in c.constraints if x.key=="deliverables.required")
    assert leaf.provenance.evidence[0].quote==text
    assert leaf.provenance.provenance_verified

@pytest.mark.parametrize("text",[
    "Analyze why the connection leaks.",
    "Please explain how to fix the connection leak.",
    "Do not fix the connection leak.",
    "Fix the bug, but don't change code.",
    "If we fix the bug, what changes?",
    "Here is a sample: Fix the connection leak",
    "“Fix the connection leak”",
    "Fix the connection leak?",
    "修复示例：不要修改代码",
    "仅分析连接泄漏，不要修复",
])
def test_p0c_analysis_negation_examples_do_not_grant_write(text):
    _,a=contract_for(text,hints=("code_modification",))
    assert not a.repository_mutation_allowed

def test_p0d_deep_immutable_authority_and_repair_payload():
    from aswe.planning.compiler import RuntimePolicyRule
    source={"nested":{"list":["mutable"]}}
    # Contrived valid nested payload goes through compiler-owned warnings.
    first,_=ConstraintCompiler(RuntimePolicyConfig(
        policy_id="p",rules=(
            RuntimePolicyRule(key="repo.paths.allowed",value=("src/**",)),
        ),
    )).compile(request=make_task_request(request_id="x",raw_text="Analyze"),
               repository_base_sha="a"*40)
    c,_=contract_for("Fix the leak.")
    val=c.constraints[0].value
    assert isinstance(val,tuple)
    with pytest.raises((TypeError,AttributeError)):
        val.append("changed")
    p=PlanRepair(code="REPAIR",details={"nested":{"source":[1,2]}})
    with pytest.raises(TypeError):
        p.details["nested"]["source"]=()
    with pytest.raises(TypeError):
        p.details["new"]="added"
    assert p.details["nested"]["source"]==(1,2)
    w=PlanWarning(code="WARNING",details={"deep":{"x":["read"]}})
    with pytest.raises(TypeError):
        w.details["deep"]["x"]=("write",)
    assert fingerprint(p)==fingerprint(p.model_copy())
