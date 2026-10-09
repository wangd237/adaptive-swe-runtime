"""Step 5C deterministic snapshot preparation tests; NO real subagent execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
import pytest

from aswe.integrations.deerflow.preparation import (
    DeerFlowPreparationBackend, DeerFlowPreparationError,
)
from aswe.capabilities.effects import DEERFLOW_USE_BY_CONTRACT
from aswe.integrations.deerflow.inventory import inventory_from_assembled_tools
from aswe.providers.policy import OperatorSurface
from tests.unit.test_step4_live_preflight_descriptor import artifacts


class ConfigPart:
    def __init__(self, **values):
        self.__dict__.update(values)
    def model_dump(self, **kwargs):
        return dict(self.__dict__)


class Model(ConfigPart):
    pass


class App(ConfigPart):
    def model_copy(self, *, deep=False):
        from copy import deepcopy
        return deepcopy(self)
    def get_model_config(self, name):
        return next((m for m in self.models if m.name == name), None)


@dataclass
class Sub:
    name: str
    description: str = "test"
    model: str = "inherit"
    max_turns: int = 100
    timeout_seconds: int = 100
    tools: list[str] | None = None
    disallowed_tools: list[str] = field(default_factory=list)
    skills: list[str] | None = None


def setup(*, selected_model="fake", sub_model="inherit"):
    *_, planning, _a, _providers, ops, policies, descriptor = artifacts()
    node = descriptor.task_dag.nodes[0]
    policy = policies[0]
    # Fake provider inventory remains separate from real DeerFlow identity.
    # Construct an independently sealed real inventory and rebind policy and
    # descriptor to it for this isolated preparation adapter contract test.
    from aswe.core.fingerprint import fingerprint
    from aswe.providers.inventory import BackendInventorySnapshot, inventory_fingerprint
    from aswe.planning.descriptor import CompiledPlanDescriptor
    from aswe.providers.policy import build_assignments
    obj = SimpleNamespace(name="read_file", func=lambda: None, coroutine=None, args_schema=None)
    tool_cfg = SimpleNamespace(name="read_file", use=DEERFLOW_USE_BY_CONTRACT["read_file"], group="file:read")
    app = App(tools=[tool_cfg], models=[Model(name="fake", use="test.provider:model", model="mock")],
              plugins=[], extensions=ConfigPart(), subagent_runtime=SimpleNamespace(max_running=2))
    def resolve(use):
        assert use == tool_cfg.use
        return obj
    live = inventory_from_assembled_tools(
        app_config=app, assembled_tools=[obj],
        resolve_implementation=resolve, active_agent_types=(policy.backend_agent_type,),
        sandbox=SimpleNamespace(persistent_shell_sessions=False),
    )
    # Rebuild the relevant immutable compiled artifacts using validated
    # fingerprints; not a replacement for production compile_plan_descriptor.
    updated = policy.model_dump(mode="python", exclude={"fingerprint"})
    updated.update(planning_inventory_fingerprint=live.fingerprint, model_name=selected_model)
    policy = type(policy)(**updated, fingerprint=fingerprint(updated))
    desc = descriptor.model_dump(mode="python", exclude={"fingerprint"})
    desc["planning_inventory_fingerprint"] = live.fingerprint
    desc["policies"] = (policy,)
    desc["assignments"] = build_assignments((policy,))
    descriptor = CompiledPlanDescriptor(**desc, fingerprint=fingerprint(desc))
    operator = OperatorSurface(provider_id=policy.provider_id,
                               allowed_tools=("read_file",), model_name=selected_model,
                               max_turns=5, timeout_seconds=10)
    env = {"app": app, "extensions": object(), "operator": operator,
           "sub_model": sub_model, "tools": [obj]}
    backend = DeerFlowPreparationBackend(
        task_id="task-5c", descriptor=descriptor, policy=policy,
        planning_inventory=live,
        config_supplier=lambda: env["app"],
        operator_supplier=lambda: env["operator"],
        sandbox_supplier=lambda: SimpleNamespace(persistent_shell_sessions=False),
        extensions_supplier=lambda: env["extensions"],
        subagent_resolver=lambda name, **kw: Sub(name=name, model=env["sub_model"]),
        model_resolver=lambda config, parent_model, **kw: (
            parent_model if config.model == "inherit" else config.model
        ),
        tool_assembler=lambda **kw: env["tools"],
        implementation_resolver=resolve,
        source_verifier=lambda: None,
    )
    return backend, node, env, obj


@pytest.mark.asyncio
async def test_preparation_pins_copied_config_and_tool_objects_no_execution():
    backend, node, env, obj = setup()
    prepared = await backend.prepare_node(node)
    entry = backend._pending[prepared.preparation_id][1]
    assert prepared.node_id == node.id and prepared.provider_id == node.provider_id
    assert entry.app_config is not env["app"]
    assert entry.tools == (obj,)
    assert entry.subagent_config.max_turns == 5
    assert entry.subagent_config.timeout_seconds == 10
    assert entry.allowed_tool_ids == ("read_file",)
    assert prepared.backend_snapshot_id == entry.binding_digest
    assert backend.pending_count == 1
    env["app"].models[0].model = "hot-reload"
    assert entry.model_config.model == "mock"
    with pytest.raises(DeerFlowPreparationError, match="REAL_DEERFLOW_EXECUTION_NOT_ENABLED"):
        await backend.execute_prepared(prepared, None)
    assert backend.pending_count == 0


@pytest.mark.asyncio
async def test_missing_or_replaced_model_fails_before_preparation():
    backend, node, env, _ = setup()
    env["sub_model"] = "replacement"
    with pytest.raises(DeerFlowPreparationError, match="SUBAGENT_MODEL_POLICY_MISMATCH"):
        await backend.prepare_node(node)
    assert backend.pending_count == 0
    env["sub_model"] = "inherit"
    env["app"].models.clear()
    with pytest.raises(DeerFlowPreparationError, match="MODEL_CONFIG_UNAVAILABLE"):
        await backend.prepare_node(node)


@pytest.mark.asyncio
async def test_required_tool_absent_or_impostor_denied():
    backend, node, env, obj = setup()
    env["tools"] = []
    with pytest.raises(Exception, match="BACKEND_PREFLIGHT_STALE"):
        await backend.prepare_node(node)
    env["tools"] = [SimpleNamespace(name=obj.name, func=lambda: None, coroutine=None, args_schema=None)]
    with pytest.raises(Exception, match="BACKEND_PREFLIGHT_STALE"):
        await backend.prepare_node(node)
    assert backend.pending_count == 0


@pytest.mark.asyncio
async def test_preparation_is_revocable_and_bounded():
    backend, node, env, obj = setup()
    backend.max_pending = 1
    prepared = await backend.prepare_node(node)
    with pytest.raises(DeerFlowPreparationError, match="PREPARATION_CAPACITY_EXHAUSTED"):
        await backend.prepare_node(node)
    backend.discard_preparation(prepared)
    assert backend.pending_count == 0
    with pytest.raises(DeerFlowPreparationError, match="PREPARED_EXECUTION_BINDING_MISMATCH"):
        backend.discard_preparation(prepared)


@pytest.mark.asyncio
async def test_preparation_model_and_tool_are_not_implicitly_rebound():
    backend, node, env, obj = setup()
    prepared = await backend.prepare_node(node)
    pinned = backend._pending[prepared.preparation_id][1]
    env["tools"] = []
    env["extensions"] = object()
    assert pinned.tools == (obj,)
    assert pinned.extensions is not env["extensions"]
    backend.discard_all()
    assert backend.pending_count == 0


@pytest.mark.asyncio
async def test_unknown_node_and_untrusted_config_fail_closed():
    backend, node, env, _ = setup()
    with pytest.raises(DeerFlowPreparationError, match="PREPARATION_NODE_POLICY_MISMATCH"):
        await backend.prepare_node(node.model_copy(update={"provider_id": "impostor"}))
    env["app"] = SimpleNamespace(models=[])
    with pytest.raises(DeerFlowPreparationError, match="APP_CONFIG_UNATTESTED"):
        await backend.prepare_node(node)
