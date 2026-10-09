"""Step 5B: real DeerFlow API-shaped model-only structured reasoning contract tests.

No model API key, outbound calls, subagent/workspace execution or tool use.
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from types import ModuleType,SimpleNamespace
from pydantic import BaseModel
import pytest

from aswe.integrations.deerflow.model_invoker import (
    ModelInvoker, DeerFlowReasoningBackend, ModelInvocationError)
from aswe.planning.analyzer import ReasoningBackend


SCHEMA={"type":"object","properties":{
    "items":{"type":"array","items":{"type":"string"}}},
    "required":["items"],"additionalProperties":False}


class Profile(BaseModel):
    name:str="plan"
    use:str="tests.fake:Model"
    model:str="test-model"
    temperature:float=0.1


class Config:
    def __init__(self,*,model="plan",authorized=False):
        self.models=[Profile(name=model)]
        self.authorization=SimpleNamespace(enabled=authorized)
    def get_model_config(self,name):
        return next((x for x in self.models if x.name==name),None)


class FakeModel:
    def __init__(self,output='{"items":["read_only"]}',*,delay=0,
                 usage=None,tool_calls=None,invalid_tool_calls=None):
        self.output=output
        self.calls=[]
        self.delay=delay
        self.usage=usage or {}
        self.tool_calls=tool_calls
        self.invalid_tool_calls=invalid_tool_calls
    async def ainvoke(self,messages):
        self.calls.append(messages)
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.output,Exception):
            raise self.output
        return SimpleNamespace(content=self.output,usage_metadata=self.usage,
                               tool_calls=self.tool_calls,
                               invalid_tool_calls=self.invalid_tool_calls)


def invoker(*,model=None,config=None,config_supplier=None,role_models=None,
            auth_supplier=None,principal_supplier=None,timeout=1.):
    target=model or FakeModel()
    cfg=config or Config()
    factory_calls=[]
    def factory(**kwargs):
        factory_calls.append(kwargs)
        return target
    item=ModelInvoker(
        app_config_supplier=config_supplier or (lambda:cfg),
        model_factory=factory,
        messages_factory=lambda system,context:[("system",system),("human",context)],
        role_models=role_models or {"task_analyzer":"plan",
                                    "semantic_plan_proposal":"plan"},
        authorization_provider_supplier=auth_supplier or (lambda:None),
        principal_supplier=principal_supplier or (lambda:None),
        source_verifier=lambda:None,
        timeout_seconds=timeout)
    return item,target,factory_calls


async def call(item,*,purpose="task_analyzer",role=None,content='{"source":"request"}',
               schema=SCHEMA):
    return await DeerFlowReasoningBackend(item).generate_structured(
        purpose=purpose,model_role=role,system_prompt="Propose data only",
        data_context=content,response_schema=schema)


@pytest.mark.asyncio
async def test_model_only_invoker_invokes_trusted_exact_name_and_schema():
    item,model,created=invoker(model=FakeModel(
        '{"items":["x"]}',usage={"input_tokens":22,"output_tokens":11,
                                 "total_tokens":33,"bad":"ignore"}))
    backend=DeerFlowReasoningBackend(item)
    assert callable(backend.generate_structured)  # Protocol intentionally lacks @runtime_checkable
    out=await call(item)
    assert out.data=={"items":("x",)}
    assert out.model_role=="task_analyzer"
    assert out.provider_model=="plan"
    assert out.usage=={"input_tokens":22,"output_tokens":11,"total_tokens":33}
    assert created[0]["name"]=="plan"
    assert created[0]["thinking_enabled"] is False
    assert created[0]["attach_tracing"] is False
    assert len(model.calls)==1
    assert model.calls[0][0][0]=="system"
    assert "untrusted proposal" in model.calls[0][0][1]
    assert model.calls[0][1]==("human",'{"source":"request"}')
    with pytest.raises(TypeError):
        out.data["items"]=("forged",)


@pytest.mark.asyncio
async def test_only_trusted_model_roles_can_choose_provider_profile():
    item,model,created=invoker(role_models={
        "task_analyzer":"plan", "semantic_plan_proposal":"other"})
    with pytest.raises(ModelInvocationError,match="MODEL_CONFIG_UNAVAILABLE"):
        await call(item,purpose="semantic_plan_proposal")
    assert not created
    with pytest.raises(ModelInvocationError,match="MODEL_ROLE_NOT_CONFIGURED"):
        await call(item,role="some-new-provider-id")
    with pytest.raises(ModelInvocationError,match="MODEL_ROLE_NOT_CONFIGURED"):
        await call(item,purpose="custom_tool_binding")
    assert not model.calls and not created


@pytest.mark.asyncio
@pytest.mark.parametrize(("output","reason"),[
    ('{"items":["x"]} trailing',"MODEL_OUTPUT_INVALID_JSON"),
    ('```json\n{"items":["x"]}\n```',"MODEL_OUTPUT_INVALID_JSON"),
    ('{"items":["x"],"items":["y"]}',"MODEL_OUTPUT_INVALID_JSON"),
    ('{"items":[NaN]}',"MODEL_OUTPUT_INVALID_JSON"),
    ('{"items":17}',"MODEL_OUTPUT_SCHEMA_MISMATCH"),
    ('{"items":["x"],"authority":"allow_write"}',"MODEL_OUTPUT_SCHEMA_MISMATCH"),
    ('[]',"MODEL_OUTPUT_NOT_OBJECT"),
    (["looks","structured"],"MODEL_OUTPUT_NOT_JSON_TEXT"),
])
async def test_bad_model_output_cannot_bypass_structured_schema(output,reason):
    item,_,_=invoker(model=FakeModel(output))
    with pytest.raises(ModelInvocationError,match=reason):
        await call(item)


@pytest.mark.asyncio
async def test_invalid_schema_and_oversize_request_fail_without_model():
    item,model,created=invoker()
    with pytest.raises(ModelInvocationError,match="INVALID_REASONING_SCHEMA"):
        await call(item,schema={"type":"not-json-schema-type"})
    with pytest.raises(ModelInvocationError,match="REASONING_CONTEXT_TOO_LARGE"):
        await call(item,content="x"*300001)
    assert not created and not model.calls


@pytest.mark.asyncio
async def test_no_default_model_fallback_and_profile_drift_fail_closed():
    item,_,created=invoker(config=Config(model="different"))
    with pytest.raises(ModelInvocationError,match="MODEL_CONFIG_UNAVAILABLE"):
        await call(item)
    assert created==[]
    initial=Config()
    changed=Config()
    changed.models[0].temperature=0.9
    calls=iter([initial,changed])
    item,model,created=invoker(config_supplier=lambda:next(calls))
    with pytest.raises(ModelInvocationError,match="MODEL_CONFIG_DRIFT"):
        await call(item)
    assert not created and not model.calls


@pytest.mark.asyncio
async def test_authorization_config_drift_refuses_before_model_creation():
    a,b=Config(),Config(authorized=True)
    calls=iter((a,b))
    item,model,created=invoker(config_supplier=lambda:next(calls))
    with pytest.raises(ModelInvocationError,match="MODEL_AUTHORIZATION_CONFIG_DRIFT"):
        await call(item)
    assert not created and not model.calls


@pytest.mark.asyncio
async def test_enabled_authorization_missing_principal_denies_without_model():
    item,model,created=invoker(config=Config(authorized=True))
    with pytest.raises(ModelInvocationError,match="MODEL_PRINCIPAL_UNTRUSTED"):
        await call(item)
    assert not created and not model.calls


class FakeAuthProvider:
    def __init__(self,*,allow=True,visible=True,raises=False):
        self.allow=allow
        self.visible=visible
        self.raises=raises
        self.requests=[]
    def filter_resources(self,principal,resource,candidates):
        assert resource=="model"
        if self.raises:raise RuntimeError("SECRET_FROM_PROVIDER")
        return candidates if self.visible else []
    async def aauthorize(self,request):
        self.requests.append(request)
        if self.raises:raise RuntimeError("SECRET_FROM_PROVIDER")
        return SimpleNamespace(allow=self.allow)


def auth_module(monkeypatch):
    pkg=ModuleType("deerflow")
    pkg.__path__=[]
    auth=ModuleType("deerflow.authz")
    auth.__path__=[]
    provider=ModuleType("deerflow.authz.provider")
    provider.AuthzRequest=lambda **kw:SimpleNamespace(**kw)
    for n,v in (("deerflow",pkg),("deerflow.authz",auth),
                ("deerflow.authz.provider",provider)):
        monkeypatch.setitem(sys.modules,n,v)


@pytest.mark.asyncio
@pytest.mark.parametrize(("visible","allowed","raises"),[
    (False,True,False),(True,False,False),(True,True,True),
])
async def test_live_model_use_authorization_fail_closed(monkeypatch,visible,allowed,raises):
    auth_module(monkeypatch)
    provider=FakeAuthProvider(allow=allowed,visible=visible,raises=raises)
    item,model,created=invoker(config=Config(authorized=True),
        auth_supplier=lambda:provider,
        principal_supplier=lambda:SimpleNamespace(user_id="owner"))
    with pytest.raises(ModelInvocationError,match="MODEL_AUTHORIZATION_DENIED"):
        await call(item)
    assert not created and not model.calls


@pytest.mark.asyncio
async def test_trusted_live_principal_and_provider_allow_exact_model_use(monkeypatch):
    auth_module(monkeypatch)
    provider=FakeAuthProvider()
    item,model,created=invoker(config=Config(authorized=True),
        auth_supplier=lambda:provider,
        principal_supplier=lambda:SimpleNamespace(user_id="owner"))
    out=await call(item)
    assert out.provider_model=="plan"
    assert provider.requests[0].resource=="model"
    assert provider.requests[0].target=="plan"
    assert provider.requests[0].action=="use"
    assert len(created)==1 and len(model.calls)==1


@pytest.mark.asyncio
async def test_disabled_auth_does_not_invoke_unauthorized_provider():
    def unexpected():
        raise AssertionError("must not resolve auth when disabled")
    item,model,_=invoker(auth_supplier=unexpected)
    assert (await call(item)).data=={"items":("read_only",)}
    assert model.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("field",["tool_calls","invalid_tool_calls"])
async def test_model_cannot_escape_structured_channel_via_tool_calls(field):
    kwargs={field:[{"name":"bash","args":{"command":"rm -rf /"}}]}
    item,model,_=invoker(model=FakeModel(**kwargs))
    with pytest.raises(ModelInvocationError,match="MODEL_TOOL_CALL_FORBIDDEN"):
        await call(item)


@pytest.mark.asyncio
async def test_timeout_and_transport_errors_are_explicit_not_fake_results():
    item,_,_=invoker(model=FakeModel(delay=0.2),timeout=0.01)
    with pytest.raises(ModelInvocationError,match="MODEL_INVOCATION_TIMEOUT"):
        await call(item)
    item,_,_=invoker(model=FakeModel(ValueError("sensitive API response")))
    with pytest.raises(ModelInvocationError,match="MODEL_INVOCATION_FAILED") as err:
        await call(item)
    assert "sensitive" not in str(err.value)


@pytest.mark.asyncio
async def test_async_cancellation_propagates_without_attempting_retry():
    class Block:
        def __init__(self):
            self.entered=asyncio.Event()
        async def ainvoke(self,messages):
            self.entered.set()
            await asyncio.Event().wait()
    model=Block()
    item,_,created=invoker(model=model)
    task=asyncio.create_task(call(item))
    await asyncio.wait_for(model.entered.wait(),1.)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(created)==1


def test_model_timeout_budget_and_empty_roles_rejected():
    with pytest.raises(ValueError):
        invoker(timeout=-1)
    with pytest.raises(ValueError):
        invoker(role_models={"task_analyzer":""})


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe",[
    {"$ref":"https://untrusted.example/schema.json"},
    {"$ref":"file:///etc/passwd"},
    {"$dynamicRef":"https://untrusted.example/x"},
    {"$id":"https://untrusted.example/anchor"},
])
async def test_schema_refs_must_remain_local_no_remote_resolution(unsafe):
    item,model,created=invoker()
    with pytest.raises(ModelInvocationError,match="EXTERNAL_SCHEMA_REFERENCE_FORBIDDEN"):
        await call(item,schema=unsafe)
    assert not created and not model.calls


@pytest.mark.asyncio
async def test_pydantic_local_defs_are_accepted_by_schema_policy():
    class Result(BaseModel):
        class Leaf(BaseModel):
            answer:str
        payload:Leaf
    output=json.dumps({"payload":{"answer":"safe"}})
    item,model,created=invoker(model=FakeModel(output))
    result=await call(item,schema=Result.model_json_schema())
    assert result.data["payload"]["answer"]=="safe"
    assert len(created)==1


@pytest.mark.asyncio
async def test_task_analyzer_consumes_model_invoker_without_authority_promotion():
    from aswe.planning.analyzer_runtime import TaskAnalyzer
    from aswe.planning.contracts import make_task_request
    from aswe.planning.profile import RepositoryProfile
    raw={
        "spec":{
            "task_type":"bug_fix","description":"Fix login",
            "domains":[],"repository_level":True,"complexity":"medium",
            "risk":"medium","testing_required":False,"review_required":False,
            "scope_hints":[],"capability_hints":[],"planning_uncertainties":[]
        },
        "draft":{"candidates":[]},
    }
    model=FakeModel(json.dumps(raw))
    item,_,factory_calls=invoker(model=model)
    profile=RepositoryProfile(
        base_sha="a"*40,tracked_file_count=0,top_level_tree=(),
        languages={},manifests=(),test_configs=(),build_configs=(),
        ci_configs=(),guidance_files=(),test_framework_hints=(),
        build_system_hints=(),task_anchor_matches=(),truncated=False,
    )
    result=await TaskAnalyzer(DeerFlowReasoningBackend(item)).analyze(
        request=make_task_request(request_id="fix",raw_text="Fix login"),
        profile=profile,
    )
    assert result.spec.task_type.value=="bug_fix"
    assert "code_modification" in result.spec.capability_hints
    # The hint is NOT an authorization grant; contract compilation alone owns it.
    from aswe.planning.compiler import ConstraintCompiler,RuntimePolicyConfig
    c,authority=ConstraintCompiler(RuntimePolicyConfig(policy_id="p")).compile(
        request=make_task_request(request_id="a",raw_text="Analyze login"),
        repository_base_sha="a"*40,task_spec=result.spec)
    assert not authority.repository_mutation_allowed
    assert len(factory_calls)==1


@pytest.mark.asyncio
async def test_from_deerflow_matches_frozen_source_factory_and_langchain_messages(monkeypatch):
    """Verify imports/call signature of the pinned DeerFlow factory with API-shaped stubs."""
    import aswe.integrations.deerflow.inventory as inventory
    factory_calls=[]
    verified=[]
    model=FakeModel('{"items":["ok"]}')
    cfg=Config()
    packages=("deerflow","deerflow.models","deerflow.authz",
              "langchain_core")
    for name in packages:
        module=ModuleType(name)
        module.__path__=[]
        monkeypatch.setitem(sys.modules,name,module)
    fac_mod=ModuleType("deerflow.models.factory")
    fac_mod.__file__="/frozen/deerflow/models/factory.py"
    monkeypatch.setitem(sys.modules,"deerflow.models.factory",fac_mod)
    sys.modules["deerflow.models"].factory=fac_mod
    def real_factory_shape(**kwargs):
        factory_calls.append(kwargs)
        return model
    sys.modules["deerflow.models"].create_chat_model=real_factory_shape
    cfg_mod=ModuleType("deerflow.config")
    cfg_mod.get_app_config=lambda:cfg
    monkeypatch.setitem(sys.modules,"deerflow.config",cfg_mod)
    auth_mod=ModuleType("deerflow.authz.runtime")
    auth_mod.resolve_authorization_provider=lambda config:None
    monkeypatch.setitem(sys.modules,"deerflow.authz.runtime",auth_mod)
    msg_mod=ModuleType("langchain_core.messages")
    msg_mod.SystemMessage=lambda *,content:("system",content)
    msg_mod.HumanMessage=lambda *,content:("human",content)
    monkeypatch.setitem(sys.modules,"langchain_core.messages",msg_mod)
    monkeypatch.setattr(inventory,"assert_pinned_deerflow_source",
                        lambda path:verified.append(path))
    actual=ModelInvoker.from_deerflow(
        role_models={"task_analyzer":"plan"},principal_supplier=lambda:None)
    result=await call(actual)
    assert result.data=={"items":("ok",)}
    assert len(factory_calls)==1
    assert factory_calls[0]["app_config"] is not cfg
    assert factory_calls[0]["name"]=="plan"
    assert factory_calls[0]["attach_tracing"] is False
    assert factory_calls[0]["thinking_enabled"] is False
    assert len(verified)==2
    assert verified==[fac_mod.__file__,fac_mod.__file__]


@pytest.mark.asyncio
async def test_semantic_planner_model_proposal_is_still_blocked_by_contract_validator():
    from aswe.planning.analyzer import TaskSpec
    from aswe.planning.planner import SemanticPlanner,PlanningContext
    from aswe.planning.profile import RepositoryProfile
    from aswe.planning.compiler import ConstraintCompiler,RuntimePolicyConfig
    from aswe.planning.contracts import make_task_request
    from aswe.planning.validator import SemanticPlanValidator,PlanValidationError
    c,a=ConstraintCompiler(RuntimePolicyConfig(policy_id="read-only")).compile(
       request=make_task_request(request_id="r",raw_text="Analyze login"),
       repository_base_sha="a"*40)
    profile=RepositoryProfile(
        base_sha="a"*40,tracked_file_count=0,top_level_tree=(),
        languages={},manifests=(),test_configs=(),build_configs=(),
        ci_configs=(),guidance_files=(),test_framework_hints=(),
        build_system_hints=(),task_anchor_matches=(),truncated=False,
    )
    task=TaskSpec(
        task_type="analysis",description="Analyze login",domains=(),
        repository_level=True,complexity="low",risk="low",
        testing_required=False,review_required=False,scope_hints=(),
        capability_hints=("code_modification",),planning_uncertainties=(),
    )
    fabricated={
      "items":[{"id":"bad_writer","objective":"Change source code",
                "work_kind":"implementation",
                "capability_hints":["code_modification"],
                "depends_on":[],"coverage_claims":[],"acceptance_intent":[]}],
      "rationale":"The model recommends changing files",
    }
    inv,model,created=invoker(model=FakeModel(json.dumps(fabricated)))
    proposal=await SemanticPlanner(DeerFlowReasoningBackend(inv)).propose(
        task=task,contract=c,context=PlanningContext(repository_profile=profile),
        capability_catalog=("code_modification","repo_exploration"))
    assert proposal.items[0].capability_hints==("code_modification",)
    with pytest.raises(PlanValidationError,match="CAPABILITY_AUTHORITY_VIOLATION"):
        SemanticPlanValidator().validate(proposal=proposal,contract=c,authority=a)
    assert len(created)==1


@pytest.mark.asyncio
async def test_json_numeric_overflow_is_not_valid_model_evidence():
    schema={"type":"object","properties":{"score":{"type":"number"}},
            "required":["score"],"additionalProperties":False}
    item,model,created=invoker(model=FakeModel('{"score":1e309}'))
    with pytest.raises(ModelInvocationError,match="MODEL_OUTPUT_INVALID_JSON"):
        await call(item,schema=schema)
    assert len(created)==1 and len(model.calls)==1
