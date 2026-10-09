"""Pinned DeerFlow 2.0 read-only inventory adapter.

This is a real *tool-assembly observation*, not model invocation or evidence of
a fully admitted subagent. It requires actual AppConfig, get_available_tools
outputs, and exactly observed SubagentConfig objects. Never infer tool identity
from routing names, model prose, or config labels alone.
"""
from __future__ import annotations

from datetime import datetime,timezone
from typing import Any, Callable,Iterable
from aswe.core.fingerprint import fingerprint
from aswe.providers.inventory import (
    BackendInventorySnapshot,BackendToolInfo,inventory_fingerprint)
from aswe.capabilities.effects import DEERFLOW_USE_BY_CONTRACT,STANDARD_EFFECTS,ToolEffect
from aswe.integrations.deerflow import PINNED_DEERFLOW_COMMIT


class DeerFlowInventoryError(RuntimeError):
    """Cannot prove a pinned config/assembly identity; fail closed."""


def _schema_fingerprint(tool: Any) -> str | None:
    schema=getattr(tool,"args_schema",None)
    if schema is not None and hasattr(schema,"model_json_schema"):
        return fingerprint(schema.model_json_schema())
    # If no canonical schema is available, lack of schema alone must not
    # constitute an implementation identity or fabricated compatibility.
    return None


def _same_loaded_implementation(observed: Any, resolved: Any) -> bool:
    if observed is resolved:
        return True
    # DeerFlow clones write_file only to augment model-budget descriptions.
    # The cloned tool MUST retain the same callable identities. Merely matching
    # object type, public name, or args schema would allow tool impersonation.
    if type(observed) is not type(resolved) or observed.name!=resolved.name:
        return False
    for attr in ("func","coroutine"):
        fn=getattr(resolved,attr,None)
        if fn is not None and callable(fn) and getattr(observed,attr,None) is fn:
            return True
    return False


def _feature_set(sandbox: Any) -> frozenset[str]:
    """Use actual Sandbox semantics, not a sandbox config name guess."""
    state=getattr(sandbox,"persistent_shell_sessions",None)
    if state is False:
        return frozenset({"fresh_shell_per_command","deerflow_tests_passed_evidence"})
    if state is True:
        return frozenset({"persistent_shell_sessions"})
    return frozenset({"shell_session_semantics_unknown"})


def inventory_from_assembled_tools(
    *,
    app_config: Any,
    assembled_tools: Iterable[Any],
    resolve_implementation: Callable[[str],Any],
    active_agent_types: tuple[str,...],
    sandbox: Any,
    captured_at: datetime | None=None,
    backend_id: str="deerflow",
) -> BackendInventorySnapshot:
    """Derive only positively observed, first-winner deployed config tools.

    DeerFlow's get_available_tools deduplicates by exposed name, in priority
    order config -> builtin -> MCP -> ACP -> plugin; a same-name foreign tool
    must never inherit a core SWE tool's implementation identity.
    """
    tools=tuple(assembled_tools)
    winner={}
    for tool in tools:
        name=getattr(tool,"name",None)
        if not isinstance(name,str) or not name:
            raise DeerFlowInventoryError("ASSEMBLY_TOOL_NAME_UNKNOWN")
        if name in winner:
            raise DeerFlowInventoryError("ASSEMBLY_DUPLICATE_TOOL_NAME")
        winner[name]=tool
    config_tools=tuple(getattr(app_config,"tools",()))
    # It is intentional that the first matching config entry wins. A collision
    # with another config entry of the same exposed name cannot be promoted.
    claimed=set()
    recognized={}
    for cfg in config_tools:
        use=getattr(cfg,"use",None)
        label=getattr(cfg,"name",None)
        if not isinstance(use,str) or not isinstance(label,str):
            raise DeerFlowInventoryError("CONFIG_TOOL_USE_UNRESOLVED")
        if label in claimed:
            continue
        claimed.add(label)
        tool=winner.get(label)
        if tool is None:
            continue
        expected_use=DEERFLOW_USE_BY_CONTRACT.get(label)
        trusted=False
        if expected_use is not None and expected_use==use:
            try:
                reference=resolve_implementation(use)
            except Exception as exc:
                raise DeerFlowInventoryError("TOOL_IMPLEMENTATION_RESOLUTION_FAILED") from exc
            trusted=(getattr(reference,"name",None)==label
                     and _same_loaded_implementation(tool,reference))
        effect=(STANDARD_EFFECTS[f"config:{label}"]
                if trusted else ToolEffect.UNKNOWN)
        # Unknown implementation is recorded, never treated as a READ proof.
        recognized[label]=BackendToolInfo(
            contract_id=label,configured_name=label,
            resolved_exposed_name=tool.name,source="deerflow-config",
            delivery="eager",implementation_id=f"config:{use}",
            group=getattr(cfg,"group",None),
            schema_hash=_schema_fingerprint(tool),
            provenance=f"deerflow@{PINNED_DEERFLOW_COMMIT}",
            effect=effect)
    # Mark config mismatch as UNKNOWN even if name would collide with a built-in.
    # Unconfigured foreign tools are not fabricated as hard-required resources.
    models=frozenset(m.name for m in getattr(app_config,"models",())
                     if isinstance(getattr(m,"name",None),str))
    runtime=getattr(app_config,"subagent_runtime",None)
    capacity=getattr(runtime,"max_running",1)
    if isinstance(capacity,bool) or not isinstance(capacity,int) or capacity<1:
        raise DeerFlowInventoryError("INVALID_BACKEND_CAPACITY")
    if not active_agent_types or any(not isinstance(x,str) or not x for x in active_agent_types):
        raise DeerFlowInventoryError("UNRESOLVED_AGENT_TYPES")
    stamp=captured_at or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        raise DeerFlowInventoryError("NAIVE_SNAPSHOT_TIMESTAMP")
    body=dict(
        backend_id=backend_id,captured_at=stamp,
        candidate_agent_types=frozenset(active_agent_types),
        candidate_tools=recognized,candidate_skill_names=frozenset(),
        configured_model_names=models,sandbox_features=_feature_set(sandbox),
        max_parallel_executions=capacity)
    return BackendInventorySnapshot(**body,fingerprint=inventory_fingerprint(body))


def capture_deerflow_inventory(
    *, app_config:Any, sandbox:Any,
    provider_agent_types:tuple[str,...],extensions:Any=None
) -> BackendInventorySnapshot:
    """Inspect the real pinned get_available_tools and Subagent registry.

    Lazy imports prevent DeerFlow packages leaking into Core and allow Core CI
    to run without optional provider credentials or launching any model.
    """
    try:
        from langchain.tools import BaseTool
        from deerflow.reflection import resolve_variable
        from deerflow.subagents.registry import get_subagent_config
        from deerflow.tools.tools import get_available_tools
    except ImportError as exc:
        raise DeerFlowInventoryError("DEERFLOW_DEPENDENCY_UNAVAILABLE") from exc
    confirmed=[]
    for agent_type in provider_agent_types:
        if get_subagent_config(agent_type,app_config=app_config) is None:
            raise DeerFlowInventoryError("PROVIDER_AGENT_TYPE_UNAVAILABLE")
        if agent_type not in confirmed: confirmed.append(agent_type)
    # Eager tools only. Disabling optional MCP does not grant the Config tools
    # which were filtered by DeerFlow host-bash / knowledge / policy rules.
    observed=get_available_tools(app_config=app_config,include_mcp=False,
                                  subagent_enabled=False,
                                  include_upload_tool=False,
                                  extensions=extensions)
    return inventory_from_assembled_tools(
        app_config=app_config,assembled_tools=observed,
        resolve_implementation=lambda use: resolve_variable(use,BaseTool),
        active_agent_types=tuple(confirmed),sandbox=sandbox)
