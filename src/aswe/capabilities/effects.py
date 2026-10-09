"""Trusted resolved implementation IDs determine tool effects, not exposed names."""
from enum import Enum
from aswe.core.contracts.workspace import WorkspaceAccess
from aswe.capabilities.registry import CAPABILITIES

class ToolEffect(str,Enum):
    READ_ONLY="read_only"
    WORKSPACE_MUTATING="workspace_mutating"
    EXTERNAL_SIDE_EFFECT="external_side_effect"
    UNKNOWN="unknown"

STANDARD_EFFECTS={f"config:{k}":(
  ToolEffect.READ_ONLY if k in ("ls","glob","grep","read_file")
  else ToolEffect.WORKSPACE_MUTATING)
  for k in ("ls","glob","grep","read_file","write_file","str_replace","bash")}

def trusted_effect(info)->ToolEffect:
    expected=STANDARD_EFFECTS.get(info.implementation_id)
    if (expected is None or info.implementation_id!="config:"+info.contract_id
            or info.delivery!="eager" or info.effect!=expected):
        return ToolEffect.UNKNOWN
    return expected

def access_for(capabilities,infos)->WorkspaceAccess:
    if any(CAPABILITIES[c].workspace_effect_floor is WorkspaceAccess.WRITE
           for c in capabilities):
        return WorkspaceAccess.WRITE
    return (WorkspaceAccess.READ if all(trusted_effect(t) is ToolEffect.READ_ONLY
            for t in infos) else WorkspaceAccess.WRITE)
