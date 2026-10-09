"""Step 5A pinned-DeerFlow inventory identity: no model/network execution.

All stubs represent the exact ToolConfig.use / loaded-tool source contract at
DeerFlow c0895d295bba34f6e95188fca380f555dabed891. These are not claims of
live provider/LLM/Skill/authorization integration.
"""
from __future__ import annotations

import sys
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace,ModuleType
from unittest.mock import Mock
import pytest

from aswe.capabilities.effects import (
    DEERFLOW_USE_BY_CONTRACT,ToolEffect,trusted_effect,access_for)
from aswe.core.contracts.workspace import WorkspaceAccess
from aswe.integrations.deerflow import PINNED_DEERFLOW_COMMIT
from aswe.integrations.deerflow.inventory import (
    inventory_from_assembled_tools,capture_deerflow_inventory,
    DeerFlowInventoryError)
from aswe.providers.inventory import fake_inventory


def config(names=("read_file","bash"),*,overrides=None):
    overrides=overrides or {}
    tools=[SimpleNamespace(name=k,use=overrides.get(k,DEERFLOW_USE_BY_CONTRACT[k]),
                           group=("bash" if k=="bash" else "file:read"))
           for k in names]
    return SimpleNamespace(tools=tools,models=(SimpleNamespace(name="model"),),
        subagent_runtime=SimpleNamespace(max_running=3))


def mounted(c,names=("read_file","bash"),*,sandbox=False,
            observed=None,resolve=None,at=None):
    objects={x.name:SimpleNamespace(name=x.name,func=lambda:None,
                                    args_schema=None,coroutine=None)
             for x in c.tools}
    if observed is None:observed=tuple(objects.values())
    if resolve is None:resolve={k.use:objects[k.name] for k in c.tools}
    snapshot=inventory_from_assembled_tools(
        app_config=c,assembled_tools=observed,
        resolve_implementation=resolve.__getitem__,active_agent_types=("coder",),
        sandbox=SimpleNamespace(persistent_shell_sessions=sandbox),
        captured_at=at or datetime(2026,10,9,tzinfo=timezone.utc))
    return snapshot,objects


def test_real_tool_use_identity_differs_from_fake_and_is_authoritative():
    deployed,objects=mounted(config())
    tool=deployed.candidate_tools["read_file"]
    assert tool.implementation_id=="config:deerflow.sandbox.tools:read_file_tool"
    assert tool.provenance=="deerflow@"+PINNED_DEERFLOW_COMMIT
    assert tool.source=="deerflow-config"
    assert trusted_effect(tool) is ToolEffect.READ_ONLY
    bash=deployed.candidate_tools["bash"]
    assert trusted_effect(bash) is ToolEffect.WORKSPACE_MUTATING
    assert access_for((),(tool,)) is WorkspaceAccess.READ
    assert access_for((),(tool,bash)) is WorkspaceAccess.WRITE
    legacy=fake_inventory().candidate_tools["read_file"]
    assert legacy.source=="fake-config"
    assert legacy.implementation_id=="config:read_file"
    assert trusted_effect(legacy) is ToolEffect.READ_ONLY
    # Production source may never use Fake implementation ID as authority.
    assert trusted_effect(legacy.model_copy(update={"source":"deerflow-config"})) is ToolEffect.UNKNOWN
    assert trusted_effect(tool.model_copy(update={"source":"fake-config"})) is ToolEffect.UNKNOWN


def test_unconfigured_or_filtered_tool_cannot_be_fabricated():
    c=config()
    one,objects=mounted(c)
    snap,_=mounted(c,observed=(objects["read_file"],),
                   resolve={x.use:objects[x.name] for x in c.tools})
    assert "bash" not in snap.candidate_tools
    assert "read_file" in snap.candidate_tools
    assert "deerflow_tests_passed_evidence" in snap.sandbox_features


def test_same_exposed_name_different_config_use_is_unknown():
    c=config(overrides={"read_file":"other.tool:pretend_read_file"})
    snap,_=mounted(c)
    ref=snap.candidate_tools["read_file"]
    assert ref.effect is ToolEffect.UNKNOWN
    assert trusted_effect(ref) is ToolEffect.UNKNOWN


def test_assembly_impostor_with_same_name_and_schema_cannot_gain_read_proof():
    c=config(names=("read_file",))
    legitimate=SimpleNamespace(name="read_file",func=lambda:None,
                               args_schema=None,coroutine=None)
    impostor=SimpleNamespace(name="read_file",func=lambda:None,
                             args_schema=None,coroutine=None)
    snap,_=mounted(c,observed=(impostor,),
                  resolve={c.tools[0].use:legitimate})
    assert snap.candidate_tools["read_file"].effect is ToolEffect.UNKNOWN
    assert trusted_effect(snap.candidate_tools["read_file"]) is ToolEffect.UNKNOWN


def test_write_file_description_clone_same_implementation_allowed():
    c=config(names=("write_file",))
    fn=lambda:None
    src=SimpleNamespace(name="write_file",func=fn,coroutine=None,args_schema=None)
    clone=SimpleNamespace(name="write_file",func=fn,coroutine=None,args_schema=None)
    snap,_=mounted(c,observed=(clone,),resolve={c.tools[0].use:src})
    assert trusted_effect(snap.candidate_tools["write_file"]) is ToolEffect.WORKSPACE_MUTATING


def test_deployed_sandbox_provenance_controls_test_evidence():
    c=config()
    persistent,_=mounted(c,sandbox=True)
    unknown,_=mounted(c,sandbox=None)
    fresh,_=mounted(c,sandbox=False)
    assert "deerflow_tests_passed_evidence" not in persistent.sandbox_features
    assert "persistent_shell_sessions" in persistent.sandbox_features
    assert "deerflow_tests_passed_evidence" not in unknown.sandbox_features
    assert "shell_session_semantics_unknown" in unknown.sandbox_features
    assert "deerflow_tests_passed_evidence" in fresh.sandbox_features


def test_observation_timestamp_not_semantic_inventory_drift():
    c=config()
    a,objects=mounted(c,at=datetime(2026,10,9,tzinfo=timezone.utc))
    b,_=mounted(c,observed=tuple(objects.values()),
                resolve={x.use:objects[x.name] for x in c.tools},
                at=datetime(2026,10,11,tzinfo=timezone.utc))
    assert a.fingerprint==b.fingerprint
    assert a.captured_at!=b.captured_at
    extra,_=mounted(config(names=("read_file",)),
                    at=datetime(2026,10,9,tzinfo=timezone.utc))
    assert a.fingerprint!=extra.fingerprint


def test_unknown_tool_and_duplicate_name_fail_closed():
    c=config(names=("read_file",))
    with pytest.raises(DeerFlowInventoryError,match="ASSEMBLY_DUPLICATE_TOOL_NAME"):
        inventory_from_assembled_tools(
            app_config=c,assembled_tools=(SimpleNamespace(name="read_file"),
                                          SimpleNamespace(name="read_file")),
            resolve_implementation=lambda x:None,
            active_agent_types=("coder",),sandbox=SimpleNamespace())
    with pytest.raises(DeerFlowInventoryError,match="TOOL_IMPLEMENTATION_RESOLUTION_FAILED"):
        inventory_from_assembled_tools(
            app_config=c,assembled_tools=(SimpleNamespace(name="read_file"),),
            resolve_implementation=lambda x: (_ for _ in ()).throw(KeyError(x)),
            active_agent_types=("coder",),sandbox=SimpleNamespace())


def test_missing_model_and_invalid_capacity_fail_closed():
    c=config()
    c.subagent_runtime.max_running=0
    with pytest.raises(DeerFlowInventoryError,match="INVALID_BACKEND_CAPACITY"):
        mounted(c)


def test_lazy_real_capture_uses_real_api_shapes_and_checks_subagent_ids(monkeypatch):
    c=config()
    objs={x.use:SimpleNamespace(name=x.name,func=lambda:None,
          coroutine=None,args_schema=None) for x in c.tools}
    calls=[]
    def fake_get_tools(**kwargs):
        calls.append(kwargs)
        return list(objs.values())
    packages={
        "deerflow":{}, "deerflow.subagents":{},
        "deerflow.tools":{}, "langchain":{},
    }
    for name in packages:
        m=ModuleType(name)
        m.__path__=[]
        monkeypatch.setitem(sys.modules,name,m)
    vals={
      "langchain.tools":{"BaseTool":type("BaseTool",(),{})},
      "deerflow.subagents.registry":{"get_subagent_config":lambda name,**kwargs:
          SimpleNamespace(name=name) if name=="coder" else None},
      "deerflow.tools.tools":{"get_available_tools":fake_get_tools},
      "deerflow.reflection":{"resolve_variable":lambda use,expected:objs[use]},
    }
    for name,attributes in vals.items():
        m=ModuleType(name)
        for key,value in attributes.items():setattr(m,key,value)
        monkeypatch.setitem(sys.modules,name,m)
    captured=capture_deerflow_inventory(
        app_config=c,sandbox=SimpleNamespace(persistent_shell_sessions=False),
        provider_agent_types=("coder",))
    assert captured.candidate_agent_types==frozenset({"coder"})
    assert trusted_effect(captured.candidate_tools["bash"]) is ToolEffect.WORKSPACE_MUTATING
    assert calls[0]["include_mcp"] is False
    assert calls[0]["include_upload_tool"] is False
    assert calls[0]["app_config"] is c
    with pytest.raises(DeerFlowInventoryError,match="PROVIDER_AGENT_TYPE_UNAVAILABLE"):
        capture_deerflow_inventory(app_config=c,
           sandbox=SimpleNamespace(persistent_shell_sessions=False),
           provider_agent_types=("missing",))
