"""Step 5C: pinned DeerFlow preparation without granting real execution.

The Scheduler owns dispatch/attempt identity. This adapter creates an opaque
in-memory snapshot of explicit DeerFlow inputs before dispatch commit; only a
later 5D/5E execution adapter may consume the one-shot binding. No model,
subagent, or tool is invoked here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from copy import deepcopy
import secrets
from typing import Any, Callable

from aswe.core.contracts.backend import NodeExecutionInvocation, NodeExecutionPreparation
from aswe.core.fingerprint import fingerprint
from aswe.capabilities.effects import ToolEffect, trusted_effect
from aswe.integrations.deerflow.inventory import (
    DeerFlowInventoryError, _schema_fingerprint, inventory_from_assembled_tools,
)
from aswe.planning.descriptor import CompiledPlanDescriptor
from aswe.providers.inventory import BackendInventorySnapshot
from aswe.providers.policy import NodeExecutionPolicy, OperatorSurface
from aswe.providers.preflight import revalidate_live, LivePreflightError


class DeerFlowPreparationError(RuntimeError):
    """Stable, non-secret preparation failure code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _json_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _json_payload(value.model_dump(mode="json", exclude_none=True))
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _json_payload(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _json_payload(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_payload(v) for v in value]
    if isinstance(value, __import__("types").SimpleNamespace):
        return {k: _json_payload(v) for k, v in vars(value).items()}\n    return value


def _digest(value: Any) -> str:
    try:
        return fingerprint(_json_payload(value))
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise DeerFlowPreparationError("SNAPSHOT_CONTENT_UNATTESTED") from exc


def _tool_seal(tool: Any) -> tuple[Any, ...]:
    """Include object + callable identity as well as exposed schema."""
    fn = getattr(tool, "func", None)
    coroutine = getattr(tool, "coroutine", None)
    return (
        id(tool), getattr(tool, "name", None),
        id(fn) if fn is not None else None,
        id(coroutine) if coroutine is not None else None,
        _schema_fingerprint(tool),
    )


@dataclass(frozen=True)
class PinnedNodeResources:
    """Private, one-shot process-local binding; NOT a serializable authority.

    AppConfig/SubagentConfig are copied at preparation. Native tool instances
    and LoadedExtensions are retained by identity: their mutable internals are
    not certified immutable. The 5D ToolCallGuard must check every invocation.
    """
    node_id: str
    policy_fingerprint: str
    descriptor_fingerprint: str
    app_config: Any
    subagent_config: Any
    model_config: Any
    tools: tuple[Any, ...]
    extensions: Any
    model_name: str
    allowed_tool_ids: tuple[str, ...]
    effective_max_turns: int
    effective_timeout_seconds: float
    app_config_digest: str
    subagent_config_digest: str
    model_config_digest: str
    extension_config_digest: str
    tool_seals: tuple[tuple[Any, ...], ...]
    binding_digest: str


class DeerFlowPreparationBackend:
    """5C-only ExecutionBackend facade; real execute is deliberately NO-GO.

    Host supplies trusted, explicit configuration/registry/assembly seams.
    Production construction must use from_deerflow(), which pins the upstream
    source. A managed 5D/5E executor will claim a binding at dispatch commit.
    """

    def __init__(
        self, *, task_id: str, descriptor: CompiledPlanDescriptor,
        policy: NodeExecutionPolicy, planning_inventory: BackendInventorySnapshot,
        config_supplier: Callable[[], Any],
        operator_supplier: Callable[[], OperatorSurface],
        sandbox_supplier: Callable[[], Any],
        extensions_supplier: Callable[[], Any],
        subagent_resolver: Callable[..., Any],
        model_resolver: Callable[..., str],
        tool_assembler: Callable[..., list[Any]],
        implementation_resolver: Callable[[str], Any],
        source_verifier: Callable[[], None],
        max_pending: int = 32,
    ):
        if not isinstance(descriptor, CompiledPlanDescriptor):
            raise DeerFlowPreparationError("COMPILED_DESCRIPTOR_REQUIRED")
        if not isinstance(policy, NodeExecutionPolicy) or not isinstance(planning_inventory, BackendInventorySnapshot):
            raise DeerFlowPreparationError("COMPILED_POLICY_REQUIRED")
        nodes = {node.id: node for node in descriptor.task_dag.nodes}
        policies = {p.node_id: p for p in descriptor.policies}
        if (not task_id or policies.get(policy.node_id) != policy
                or policy.node_id not in nodes
                or nodes[policy.node_id].provider_id != policy.provider_id
                or nodes[policy.node_id].workspace_access != policy.workspace_access
                or descriptor.planning_inventory_fingerprint != planning_inventory.fingerprint
                or policy.planning_inventory_fingerprint != planning_inventory.fingerprint):
            raise DeerFlowPreparationError("DESCRIPTOR_POLICY_IDENTITY_MISMATCH")
        if not isinstance(max_pending, int) or isinstance(max_pending, bool) or max_pending < 1:
            raise ValueError("positive max_pending required")
        self.task_id = task_id
        self.descriptor = descriptor
        self.policy = policy
        self.planning = planning_inventory
        self.node = nodes[policy.node_id]
        self.config_supplier = config_supplier
        self.operator_supplier = operator_supplier
        self.sandbox_supplier = sandbox_supplier
        self.extensions_supplier = extensions_supplier
        self.subagent_resolver = subagent_resolver
        self.model_resolver = model_resolver
        self.tool_assembler = tool_assembler
        self.implementation_resolver = implementation_resolver
        self.source_verifier = source_verifier
        self.max_pending = max_pending
        self._pending: dict[str, tuple[NodeExecutionPreparation, PinnedNodeResources]] = {}
        self._claimed_execution_ids: set[str] = set()

    @classmethod
    def from_deerflow(cls, *, task_id: str, descriptor: CompiledPlanDescriptor,
                      policy: NodeExecutionPolicy, planning_inventory: BackendInventorySnapshot,
                      operator_supplier: Callable[[], OperatorSurface],
                      sandbox_supplier: Callable[[], Any], max_pending: int = 32):
        try:
            from langchain.tools import BaseTool
            from deerflow.config import get_app_config
            from deerflow.tools.tools import get_available_tools
            from deerflow.tools import tools as tool_module
            from deerflow.subagents.registry import get_subagent_config
            from deerflow.subagents.config import resolve_subagent_model_name
            from deerflow.reflection import resolve_variable
            from deerflow.extensions import get_loaded_extensions, LoadedExtensions
            from deerflow.subagents import executor as executor_module
            from aswe.integrations.deerflow.inventory import assert_pinned_deerflow_source
        except ImportError as exc:
            raise DeerFlowPreparationError("DEERFLOW_DEPENDENCY_UNAVAILABLE") from exc

        def verify():
            assert_pinned_deerflow_source(tool_module.__file__)
            assert_pinned_deerflow_source(executor_module.__file__)

        verify()
        def loaded_extensions():
            value = get_loaded_extensions()
            if not isinstance(value, LoadedExtensions):
                raise DeerFlowPreparationError("DEERFLOW_EXTENSIONS_UNATTESTED")
            return value

        return cls(
            task_id=task_id, descriptor=descriptor, policy=policy,
            planning_inventory=planning_inventory, config_supplier=get_app_config,
            operator_supplier=operator_supplier, sandbox_supplier=sandbox_supplier,
            extensions_supplier=loaded_extensions,
            subagent_resolver=get_subagent_config,
            model_resolver=resolve_subagent_model_name,
            tool_assembler=get_available_tools,
            implementation_resolver=lambda use: resolve_variable(use, BaseTool),
            source_verifier=verify, max_pending=max_pending,
        )

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def prepare_node(self, node: Any) -> NodeExecutionPreparation:
        if node != self.node:
            raise DeerFlowPreparationError("PREPARATION_NODE_POLICY_MISMATCH")
        if len(self._pending) >= self.max_pending:
            raise DeerFlowPreparationError("PREPARATION_CAPACITY_EXHAUSTED")
        try:
            self.source_verifier()
            # Deep copy before any dynamic registry/assembly resolution. The
            # original AppConfig can hot-reload immediately afterwards.
            supplied = self.config_supplier()
            if not callable(getattr(supplied, "model_copy", None)):
                raise DeerFlowPreparationError("APP_CONFIG_UNATTESTED")
            app = supplied.model_copy(deep=True)
            app_digest = _digest(app)
            extension_config_digest = _digest({
                "plugins": getattr(app, "plugins", None),
                "extensions": getattr(app, "extensions", None),
            })
            extensions = self.extensions_supplier()
            if extensions is None:
                raise DeerFlowPreparationError("DEERFLOW_EXTENSIONS_UNATTESTED")
            sub = self.subagent_resolver(self.policy.backend_agent_type, app_config=app)
            if sub is None or getattr(sub, "name", None) != self.policy.backend_agent_type:
                raise DeerFlowPreparationError("SUBAGENT_CONFIG_UNAVAILABLE")
            sub = deepcopy(sub)
            resolved_model = self.model_resolver(sub, self.policy.model_name, app_config=app)
            if resolved_model != self.policy.model_name:
                raise DeerFlowPreparationError("SUBAGENT_MODEL_POLICY_MISMATCH")
            getter = getattr(app, "get_model_config", None)
            model = getter(resolved_model) if callable(getter) else None
            if model is None or getattr(model, "name", None) != resolved_model:
                raise DeerFlowPreparationError("MODEL_CONFIG_UNAVAILABLE")
            model_digest = _digest(model)
            # 5C excludes MCP/deferred discovery; a later 5D can only tighten.
            # Passing pinned LoadedExtensions is mandatory, not global fallback.
            assembled = tuple(self.tool_assembler(
                app_config=app, extensions=extensions, include_mcp=False,
                subagent_enabled=False, include_upload_tool=False,
                model_name=resolved_model,
            ))
            if len({getattr(t, "name", None) for t in assembled}) != len(assembled):
                raise DeerFlowPreparationError("DUPLICATE_ASSEMBLED_TOOL_NAME")
            live = inventory_from_assembled_tools(
                app_config=app, assembled_tools=assembled,
                resolve_implementation=self.implementation_resolver,
                active_agent_types=tuple(sorted(self.planning.candidate_agent_types)),
                sandbox=self.sandbox_supplier(),
            )
            operator = self.operator_supplier()
            effective, diagnostics, allowed = revalidate_live(
                policy=self.policy, planning=self.planning,
                live=live, operator=operator,
            )
            # Even optional tool drift cannot widen the selected implementation.
            selected = []
            for contract_id in allowed:
                original = self.planning.candidate_tools.get(contract_id)
                current = live.candidate_tools.get(contract_id)
                if current is None or original is None:
                    continue
                identity = lambda t: (
                    t.implementation_id, t.resolved_exposed_name,
                    t.delivery, t.schema_hash, t.effect,
                )
                if identity(original) != identity(current):
                    if contract_id in self.policy.required_business_tools:
                        raise DeerFlowPreparationError("PROVIDER_TOOL_IDENTITY_MISMATCH")
                    continue
                if trusted_effect(current) in (ToolEffect.UNKNOWN, ToolEffect.EXTERNAL_SIDE_EFFECT):
                    raise DeerFlowPreparationError("UNTRUSTED_PREPARED_TOOL")
                selected.append(contract_id)
            if not set(self.policy.required_business_tools).issubset(selected):
                raise DeerFlowPreparationError("REQUIRED_TOOL_NOT_PINNED")
            by_name = {t.name: t for t in assembled}
            tools = tuple(by_name[live.candidate_tools[tid].resolved_exposed_name] for tid in selected)
            if len({id(t) for t in tools}) != len(tools):
                raise DeerFlowPreparationError("DUPLICATE_SELECTED_TOOL_OBJECT")
            # Native infrastructure review output is a separate 5F proof, never
            # manufactured by a config label or model completion.
            if self.policy.required_infrastructure_tools:
                raise DeerFlowPreparationError("INFRASTRUCTURE_BINDING_NOT_IMPLEMENTED")
            if self.policy.preferred_skills:
                raise DeerFlowPreparationError("SKILL_BINDING_NOT_IMPLEMENTED")
            turns = min(self.policy.max_turns, operator.max_turns)
            timeout = min(self.policy.timeout_seconds, operator.timeout_seconds)
            sub.max_turns = turns
            sub.timeout_seconds = timeout
            # SubagentExecutor _filter_tools enforces the same selected names.
            sub.tools = [t.name for t in tools]
            sub.disallowed_tools = [t.name for t in assembled if t.name not in sub.tools]
            sub_digest = _digest(sub)
            seals = tuple(_tool_seal(t) for t in tools)
            effective = fingerprint((effective, tuple(selected), turns, timeout))
            binding_digest = fingerprint((
                self.descriptor.fingerprint, self.policy.fingerprint,
                app_digest, sub_digest, model_digest, extension_config_digest,
                live.fingerprint, effective, tuple(selected), seals,
            ))
            resources = PinnedNodeResources(
                node_id=node.id, policy_fingerprint=self.policy.fingerprint,
                descriptor_fingerprint=self.descriptor.fingerprint,
                app_config=app, subagent_config=sub, model_config=model,
                tools=tools, extensions=extensions, model_name=resolved_model,
                allowed_tool_ids=tuple(selected), effective_max_turns=turns,
                effective_timeout_seconds=timeout,
                app_config_digest=app_digest, subagent_config_digest=sub_digest,
                model_config_digest=model_digest,
                extension_config_digest=extension_config_digest,
                tool_seals=seals, binding_digest=binding_digest,
            )
            token = "df-prep-" + secrets.token_hex(16)
            prepared = NodeExecutionPreparation(
                preparation_id=token, node_id=node.id, provider_id=node.provider_id,
                compiled_policy_fingerprint=self.policy.fingerprint,
                planning_inventory_fingerprint=self.planning.fingerprint,
                live_inventory_fingerprint=live.fingerprint,
                effective_policy_fingerprint=effective,
                backend_snapshot_id=binding_digest,
                drift_observed=bool(diagnostics),
                drift_diagnostics=diagnostics,
            )
            self._pending[token] = (prepared, resources)
            return prepared
        except (DeerFlowPreparationError, LivePreflightError, DeerFlowInventoryError):
            raise
        except Exception as exc:
            # Neither config contents nor provider error messages leave this boundary.
            raise DeerFlowPreparationError("DEERFLOW_PREPARATION_FAILED") from exc

    def claim_for_execution(self, preparation: NodeExecutionPreparation,
                            invocation: NodeExecutionInvocation) -> PinnedNodeResources:
        """Called exactly once after Scheduler commits a trusted invocation.

        5D/5E must carry these exact objects into SubagentExecutor; a fresh
        get_app_config/get_available_tools/get_loaded_extensions is forbidden.
        """
        entry = self._pending.pop(preparation.preparation_id, None)
        if entry is None or entry[0] != preparation:
            raise DeerFlowPreparationError("PREPARED_EXECUTION_BINDING_MISMATCH")
        resources = entry[1]
        if (invocation.task_id != self.task_id
                or invocation.node_id != self.node.id
                or preparation.node_id != self.node.id
                or preparation.provider_id != self.policy.provider_id
                or preparation.compiled_policy_fingerprint != self.policy.fingerprint
                or resources.policy_fingerprint != self.policy.fingerprint
                or resources.descriptor_fingerprint != self.descriptor.fingerprint
                or not invocation.execution_id or not invocation.run_id
                or invocation.execution_id in self._claimed_execution_ids):
            raise DeerFlowPreparationError("PREPARED_EXECUTION_BINDING_MISMATCH")
        if (_digest(resources.app_config) != resources.app_config_digest
                or _digest(resources.subagent_config) != resources.subagent_config_digest
                or _digest(resources.model_config) != resources.model_config_digest
                or _digest({
                    "plugins": getattr(resources.app_config, "plugins", None),
                    "extensions": getattr(resources.app_config, "extensions", None),
                }) != resources.extension_config_digest
                or tuple(_tool_seal(t) for t in resources.tools) != resources.tool_seals):
            raise DeerFlowPreparationError("PREPARED_SNAPSHOT_MUTATED")
        self._claimed_execution_ids.add(invocation.execution_id)
        return resources

    def discard_preparation(self, preparation: NodeExecutionPreparation) -> None:
        """Host-side revocation hook for noncommitted Scheduler tickets."""
        entry = self._pending.get(preparation.preparation_id)
        if entry is None or entry[0] != preparation:
            raise DeerFlowPreparationError("PREPARED_EXECUTION_BINDING_MISMATCH")
        del self._pending[preparation.preparation_id]

    def discard_all(self) -> None:
        """Release noncommitted snapshot references on fail-close or shutdown."""
        self._pending.clear()

    async def execute_prepared(self, preparation: NodeExecutionPreparation,
                               invocation: NodeExecutionInvocation) -> Any:
        # 5C is only snapshot pinning. DO NOT call claim_for_execution here:
        # no native ToolCallGuard, AuthorizationProvider, cleanup or quiescence.
        self.discard_all()
        raise DeerFlowPreparationError("REAL_DEERFLOW_EXECUTION_NOT_ENABLED")

    async def cancel_node(self, execution_id: str) -> None:
        # No execution has ever been launched by this 5C facade.
        return None
