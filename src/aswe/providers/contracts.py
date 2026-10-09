"""AgentProvider bindings never imply automatically delivered physical tools."""
from typing import Literal
from pydantic import model_validator
from aswe.core.contracts._base import FrozenModel
from aswe.core.fingerprint import fingerprint
from aswe.planning.immutable import deep_freeze

class CapabilityBinding(FrozenModel):
    capability_id:str
    required_tools:tuple[str,...]=()
    optional_tools:tuple[str,...]=()
    preferred_skills:tuple[str,...]=()
    notes:str|None=None

class AgentProvider(FrozenModel):
    id:str
    role:str
    backend:Literal["deerflow"]="deerflow"
    backend_agent_type:str
    capability_bindings:dict[str,CapabilityBinding]
    model_policy:Literal["operator_config_or_inherit"]="operator_config_or_inherit"
    cost_class:Literal["low","medium","high"]="medium"
    fingerprint:str

    @model_validator(mode="after")
    def check(self):
        if any(k!=v.capability_id for k,v in self.capability_bindings.items()):
            raise ValueError("capability binding key mismatch")
        if self.fingerprint!=fingerprint(self.model_dump(mode="json",exclude={"fingerprint"})):
            raise ValueError("provider fingerprint mismatch")
        object.__setattr__(self,"capability_bindings",deep_freeze(self.capability_bindings))
        return self

def provider(id,capabilities,*,role=None):
    bindings=tuple(capabilities)
    body=dict(id=id,role=role or id,backend="deerflow",
              backend_agent_type=role or id,
              capability_bindings={x.capability_id:x for x in bindings},
              model_policy="operator_config_or_inherit",cost_class="medium")
    return AgentProvider(**body,fingerprint=fingerprint(body))
