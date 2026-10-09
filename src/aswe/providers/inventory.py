"""Deterministic FakeBackendInventory with implementation-backed tool identities."""
from datetime import datetime,timezone
from pydantic import Field,model_validator
from aswe.core.contracts._base import FrozenModel
from aswe.core.fingerprint import fingerprint
from aswe.capabilities.effects import ToolEffect,STANDARD_EFFECTS

def inventory_fingerprint(values) -> str:
    """Canonical identity independent of Pydantic set/datetime serialization."""
    data=dict(values)
    date=data["captured_at"]
    if isinstance(date,str):
        date=datetime.fromisoformat(date.replace("Z","+00:00"))
    data["captured_at"]=date.isoformat()
    for name in ("candidate_agent_types","candidate_skill_names",
                 "configured_model_names","sandbox_features"):
        data[name]=frozenset(data[name])
    return fingerprint(data)


class BackendToolInfo(FrozenModel):
    contract_id:str
    configured_name:str|None
    resolved_exposed_name:str
    source:str
    delivery:str
    implementation_id:str
    group:str|None=None
    schema_hash:str|None=None
    provenance:str|None=None
    effect:ToolEffect

class BackendInventorySnapshot(FrozenModel):
    backend_id:str
    captured_at:datetime
    candidate_agent_types:frozenset[str]
    candidate_tools:dict[str,BackendToolInfo]
    candidate_skill_names:frozenset[str]
    configured_model_names:frozenset[str]
    sandbox_features:frozenset[str]
    max_parallel_executions:int=Field(ge=1)
    fingerprint:str
    @model_validator(mode="after")
    def checked(self):
        if self.fingerprint!=inventory_fingerprint(self.model_dump(mode="python",exclude={"fingerprint"})):
            raise ValueError("inventory fingerprint mismatch")
        if any(k!=v.contract_id for k,v in self.candidate_tools.items()):
            raise ValueError("inventory Tool Contract ID mismatch")
        return self

def fake_inventory(*,agent_types=("coder","tester","reviewer","explorer"),
                   tools=("ls","glob","grep","read_file","write_file","str_replace","bash"),
                   features=("deerflow_tests_passed_evidence",)):
    ts={k:BackendToolInfo(contract_id=k,configured_name=k,
          resolved_exposed_name=k,source="fake-config",delivery="eager",
          implementation_id="config:"+k,effect=STANDARD_EFFECTS["config:"+k])
        for k in tools}
    body=dict(backend_id="static-fake",captured_at="2026-01-01T00:00:00Z",
        candidate_agent_types=frozenset(agent_types),candidate_tools=ts,
        candidate_skill_names=frozenset(),configured_model_names=frozenset({"fake"}),
        sandbox_features=frozenset(features),max_parallel_executions=4)
    return BackendInventorySnapshot(**body,fingerprint=inventory_fingerprint(body))
