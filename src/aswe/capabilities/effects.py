"""Trusted effects: Fake contracts and pinned DeerFlow ToolConfig.use remain DISTINCT."""
from enum import Enum
from aswe.core.contracts.workspace import WorkspaceAccess
from aswe.capabilities.registry import CAPABILITIES

class ToolEffect(str,Enum):
    READ_ONLY="read_only"
    WORKSPACE_MUTATING="workspace_mutating"
    EXTERNAL_SIDE_EFFECT="external_side_effect"
    UNKNOWN="unknown"

# Frozen pinned deer-flow c0895d29 config.example.yaml, ToolConfig.use
# (NOT config tool name, exposed name, schema hash or Python object ID).
DEERFLOW_USE_BY_CONTRACT={
    name:f"deerflow.sandbox.tools:{name}_tool"
    for name in ("ls","glob","grep","read_file","write_file","str_replace","bash")
}
# For legacy FakeBackend tests only, never a production implementation identity.
STANDARD_EFFECTS={f"config:{k}":(
    ToolEffect.READ_ONLY if k in ("ls","glob","grep","read_file")
    else ToolEffect.WORKSPACE_MUTATING) for k in DEERFLOW_USE_BY_CONTRACT}
DEERFLOW_EFFECTS={
    f"config:{use}":STANDARD_EFFECTS[f"config:{name}"]
    for name,use in DEERFLOW_USE_BY_CONTRACT.items()
}

def trusted_effect(info)->ToolEffect:
    """A config-namespace string cannot impersonate a deployed DeerFlow tool."""
    if info.delivery!="eager" or info.resolved_exposed_name!=info.contract_id:
        return ToolEffect.UNKNOWN
    if info.source=="fake-config":
        ident=f"config:{info.contract_id}"
        expected=STANDARD_EFFECTS.get(ident)
    elif info.source=="deerflow-config":
        use=DEERFLOW_USE_BY_CONTRACT.get(info.contract_id)
        ident=f"config:{use}" if use is not None else None
        expected=DEERFLOW_EFFECTS.get(ident) if ident else None
    else:
        return ToolEffect.UNKNOWN
    return expected if (expected is not None
                        and info.implementation_id==ident
                        and info.effect==expected) else ToolEffect.UNKNOWN

def access_for(capabilities,infos)->WorkspaceAccess:
    if any(CAPABILITIES[c].workspace_effect_floor is WorkspaceAccess.WRITE for c in capabilities):
        return WorkspaceAccess.WRITE
    return (WorkspaceAccess.READ if all(trusted_effect(t) is ToolEffect.READ_ONLY
            for t in infos) else WorkspaceAccess.WRITE)
