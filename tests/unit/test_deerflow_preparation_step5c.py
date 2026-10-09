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


@dataclass(frozen=True)
class StubLoadedExtensions:
    app_store: object = field(default_factory=object)
    middleware_contributors: tuple = ()
    task_lifecycle: tuple = ()
    system_model_observers: tuple = ()
    agent_assembly_observers: tuple = ()
    context_compaction_observers: tuple = ()
    services: tuple = ()
    routers: tuple = ()
    plugins: tuple = ()
    has_middleware_contributors: bool = False
    has_task_lifecycle: bool = False
    has_system_model_observers: bool = False
    has_agent_assembly_observers: bool = False
    needs_task_store: bool = False


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
    env = {"app": app, "extensions": StubLoadedExtensions(), "operator": operator,
           "sub_model": sub_model, "sub_tools": None, "sub_denied": [], "tools": [obj]}
    backend = DeerFlowPreparationBackend(
        task_id="task-5c", descriptor=descriptor, policy=policy,
        planning_inventory=live,
        config_supplier=lambda: env["app"],
        operator_supplier=lambda: env["operator"],
        sandbox_supplier=lambda: SimpleNamespace(persistent_shell_sessions=False),
        extensions_supplier=lambda: env["extensions"],
        subagent_resolver=lambda name, **kw: Sub(name=name, model=env["sub_model"],
                                                tools=env["sub_tools"],
                                                disallowed_tools=env["sub_denied"]),
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
    env["extensions"] = StubLoadedExtensions()
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

@pytest.mark.asyncio
async def test_native_agent_required_tool_deny_and_allowlist_fail_closed():
    backend, node, env, _ = setup()
    env["sub_denied"] = ["read_file"]
    with pytest.raises(DeerFlowPreparationError, match="SUBAGENT_REQUIRED_TOOL_RESTRICTED"):
        await backend.prepare_node(node)
    env["sub_denied"] = []
    env["sub_tools"] = ["some_other_tool"]
    with pytest.raises(DeerFlowPreparationError, match="SUBAGENT_REQUIRED_TOOL_RESTRICTED"):
        await backend.prepare_node(node)
    assert backend.pending_count == 0


@pytest.mark.asyncio
async def test_uncommitted_invocation_denied_and_consumed_once(tmp_path):
    from aswe.core.contracts.backend import NodeExecutionInvocation, NodeAttemptKind
    from tests.unit.test_scheduler_foundation import scheduler
    backend, node, env, tool = setup()
    core, _ = scheduler(tmp_path, node)
    backend.commit_checker = core.is_committed_invocation
    prepared = await backend.prepare_node(node)
    invocation = NodeExecutionInvocation(
        task_id="task-5c", node_id=node.id, attempt=1,
        attempt_kind=NodeAttemptKind.INITIAL,
        execution_id="e-not-committed", run_id="r-not-committed",
        execution_workspace_revision=core.revision, dispatch_ticket_id="t-fake",
        task_dispatch_epoch=core.gate.epoch,
        dependency_acceptance_stamps=(), dependency_context_text="",
        dependency_handoff_fingerprints=(), repair_feedback_text=None,
        context_fingerprint="test",
    )
    with pytest.raises(DeerFlowPreparationError, match="PREPARED_EXECUTION_BINDING_MISMATCH"):
        backend.claim_for_execution(prepared, invocation)
    assert backend.pending_count == 0
    with pytest.raises(DeerFlowPreparationError, match="PREPARED_EXECUTION_BINDING_MISMATCH"):
        backend.claim_for_execution(prepared, invocation)


@pytest.mark.asyncio
async def test_scheduler_precommit_revoke_releases_preparation(tmp_path):
    from tests.unit.test_scheduler_foundation import scheduler
    backend, node, _, _ = setup()
    core, _ = scheduler(tmp_path, node)
    ticket = await core.claim(node.id)
    await core.revoke(ticket.ticket_id)
    out = await core.run_claim(ticket, backend)
    assert out is None
    assert backend.pending_count == 0
    assert core.states[node.id].attempts == ()


@pytest.mark.asyncio
async def test_real_scheduler_commit_gates_one_shot_claim(tmp_path):
    from tests.unit.test_scheduler_foundation import scheduler, accept
    from tests.fakes.backend import FakeExecutionBackend, FakeExecutionScenario
    backend, node, env, tool = setup()
    core, _ = scheduler(tmp_path, node)
    # Production host constructs the backend with its Scheduler task identity.
    backend.task_id = core.task_id
    backend.commit_checker = core.is_committed_invocation
    fake = FakeExecutionBackend([FakeExecutionScenario()])
    captured = []

    class CommitBoundFake:
        async def prepare_node(self, selected):
            return await backend.prepare_node(selected)

        async def execute_prepared(self, preparation, invocation):
            assert core.is_committed_invocation(invocation)
            env["app"].models[0].model = "runtime hot-reload"
            captured.append(backend.claim_for_execution(preparation, invocation))
            with pytest.raises(DeerFlowPreparationError, match="PREPARED_EXECUTION_BINDING_MISMATCH"):
                backend.claim_for_execution(preparation, invocation)
            raw = await fake.prepare_node(node)
            return await fake.execute_prepared(raw, invocation)

        async def cancel_node(self, execution_id):
            await fake.cancel_node(execution_id)

        def discard_preparation(self, preparation):
            backend.discard_preparation(preparation)

    invocation = await core.run_claim(await core.claim(node.id), CommitBoundFake(), accept=accept)
    assert invocation is not None
    assert not core.is_committed_invocation(invocation)
    assert len(captured) == 1
    assert captured[0].app_config.models[0].model == "mock"
    assert backend.pending_count == 0


@pytest.mark.asyncio
async def test_app_tool_extension_tamper_rejected_on_claim(tmp_path):
    from tests.unit.test_scheduler_foundation import scheduler
    from aswe.core.contracts.backend import NodeExecutionInvocation, NodeAttemptKind
    backend, node, env, tool = setup()
    core, _ = scheduler(tmp_path, node)
    # Isolated tamper test only. The positive production-shaped execution uses
    # SchedulerCore.is_committed_invocation in test_real_scheduler_commit_gates...
    backend.commit_checker = lambda invocation: True
    def fixture_invocation(tag):
        return NodeExecutionInvocation(
            task_id="task-5c", node_id=node.id, attempt=1,
            attempt_kind=NodeAttemptKind.INITIAL,
            execution_id="e" + str(tag), run_id="r" + str(tag),
            execution_workspace_revision=core.revision,
            dispatch_ticket_id="fixture-commit",
            task_dispatch_epoch=0, dependency_acceptance_stamps=(),
            dependency_context_text="", dependency_handoff_fingerprints=(),
            repair_feedback_text=None, context_fingerprint="test",
        )
    for change in ("app", "sub", "tool", "extension"):
        prepared = await backend.prepare_node(node)
        pinned = backend._pending[prepared.preparation_id][1]
        if change == "app":
            pinned.app_config.models[0].model = "tampered"
        if change == "sub":
            pinned.subagent_config.max_turns += 1
        if change == "tool":
            tool.description = "altered-visible-contract"
        if change == "extension":
            object.__setattr__(pinned.extensions, "plugins", (("new", object()),))
        with pytest.raises(DeerFlowPreparationError, match="PREPARED_SNAPSHOT_MUTATED"):
            backend.claim_for_execution(prepared, fixture_invocation(change))
        if change == "tool":
            del tool.description
        if change == "extension":
            object.__setattr__(env["extensions"], "plugins", ())
        assert backend.pending_count == 0
