"""Independent provider JSON compatibility path, without paid model calls."""
from types import SimpleNamespace

import pytest

from aswe.integrations.deerflow.json_compat import invoke_structured_compat
from aswe.integrations.deerflow.dev_team_planner import ProposedTeam
from aswe.integrations.deerflow.dev_llm_explorer import ExplorerFinding


class OpenAIInvalidRequestError(Exception):
    pass


class RejectStructuredOnly:
    def __init__(self,output):
        self.output=output
        self.calls=[]
    def with_structured_output(self,schema):
        return self
    async def ainvoke(self,messages):
        self.calls.append(messages)
        if len(self.calls)==1:
            raise OpenAIInvalidRequestError("synthetic unsupported tools")
        return SimpleNamespace(content=self.output)


@pytest.mark.asyncio
async def test_planner_fallback_to_plain_json_does_not_lose_requirements():
    model=RejectStructuredOnly(
        '```json\n{"needs_explorer":true,"coder_objective":"Fix the bug",'
        '"explorer_objective":"Inspect modules","rationale":"Cross module"}\n```')
    result=await invoke_structured_compat(
        model,ProposedTeam,[("system","You plan"),("human","Task")])
    assert result.needs_explorer
    assert result.coder_objective=="Fix the bug"
    assert len(model.calls)==2
    assert "Required JSON schema:" in str(model.calls[-1])


@pytest.mark.asyncio
async def test_explorer_fallback_filters_to_structured_diagnosis():
    model=RejectStructuredOnly(
        '{"relevant_paths":["orders.py"],'
        '"diagnosis":"Duplicate cancellation",'
        '"suggested_approach":"Check idempotency"}')
    finding=await invoke_structured_compat(
        model,ExplorerFinding,[("system","Read only"),("human","Inspect")])
    assert finding.relevant_paths==("orders.py",)


@pytest.mark.asyncio
async def test_network_error_does_not_trigger_extra_billable_retry():
    class Timeout:
        def with_structured_output(self,schema):
            return self
        async def ainvoke(self,messages):
            raise TimeoutError("simulated timeout")
    with pytest.raises(TimeoutError):
        await invoke_structured_compat(Timeout(),ProposedTeam,[("human","task")])



@pytest.mark.asyncio
async def test_validation_error_in_provider_structured_payload_gets_one_json_retry():
    class PartialSchema:
        def __init__(self):
            self.calls=0
        def with_structured_output(self,schema):
            return self
        async def ainvoke(self,messages):
            self.calls+=1
            if self.calls==1:
                return SimpleNamespace(content='{"relevant_paths":["orders.py"]}')
            return SimpleNamespace(content=(
                '{"relevant_paths":["orders.py"],'
                '"diagnosis":"Idempotency bug",'
                '"suggested_approach":"Return false on repeated cancel"}'))
    model=PartialSchema()
    answer=await invoke_structured_compat(
        model,ExplorerFinding,[("system","Read only"),("human","Look at source")])
    assert answer.diagnosis=="Idempotency bug"
    assert model.calls==2
