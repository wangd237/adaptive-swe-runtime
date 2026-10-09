"""Single source of semantic capability vocabulary, independent of Providers."""
from enum import Enum
from aswe.core.contracts._base import FrozenModel
from aswe.core.contracts.workspace import WorkspaceAccess

class CapabilityAuthorityClass(str,Enum):
    READ_ONLY="read_only"
    REPOSITORY_MUTATION="repository_mutation"
    EXTERNAL_SIDE_EFFECT="external_side_effect"

class CapabilitySpec(FrozenModel):
    id:str
    description:str
    workspace_effect_floor:WorkspaceAccess
    authority_class:CapabilityAuthorityClass
    default_acceptance_kind:str|None=None

def _spec(id,write=False):
    return CapabilitySpec(id=id,description=id.replace("_"," "),
        workspace_effect_floor=WorkspaceAccess.WRITE if write else WorkspaceAccess.READ,
        authority_class=(CapabilityAuthorityClass.REPOSITORY_MUTATION if write
                         else CapabilityAuthorityClass.READ_ONLY))
_CAPS=tuple(_spec(x,x in ("code_modification","test_generation")) for x in (
  "repo_exploration","code_search","bug_diagnosis","python_debugging",
  "database_analysis","architecture_analysis","code_modification",
  "test_generation","regression_testing","code_review"))
CAPABILITIES={x.id:x for x in _CAPS}
ALL_CAPABILITIES=frozenset(CAPABILITIES)
MUTATION_CAPABILITIES=frozenset(x.id for x in _CAPS
    if x.authority_class is CapabilityAuthorityClass.REPOSITORY_MUTATION)
READ_CAPABILITIES=ALL_CAPABILITIES-MUTATION_CAPABILITIES
