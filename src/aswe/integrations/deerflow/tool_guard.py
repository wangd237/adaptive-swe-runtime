"""Step 5D: execution-scoped, fail-closed DeerFlow tool authority.

Single-process seam only. This module does not run a DeerFlow graph. Step 5E
must wire the guarded dispatch operations into *every* actual tool entry,
including middleware-declared tools, before enabling real execute_prepared().
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

from aswe.core.contracts.backend import NodeExecutionInvocation, NodeExecutionPreparation
from aswe.integrations.deerflow.preparation import (
    DeerFlowPreparationBackend, DeerFlowPreparationError, PinnedNodeResources,
    _tool_seal, _extension_seal,
)


class ToolBindingError(RuntimeError):
    """Never propagate secret-bearing AuthorizationProvider error text."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _deny(code: str) -> None:
    raise ToolBindingError(code)


def _auth_enabled(resources: PinnedNodeResources) -> bool:
    auth = getattr(resources.app_config, "authorization", None)
    if (auth is None or type(getattr(auth, "enabled", None)) is not bool
            or type(getattr(auth, "fail_closed", None)) is not bool):
        _deny("AUTHORIZATION_CONFIG_UNATTESTED")
    if auth.enabled and not auth.fail_closed:
        _deny("AUTHORIZATION_FAIL_OPEN_FORBIDDEN")
    return auth.enabled


def _principal_ok(principal: Any) -> bool:
    user = getattr(principal, "user_id", None)
    return (type(user) is str and bool(user.strip())) or getattr(
        principal, "is_internal", None
    ) is True


def _static_surface(resources: PinnedNodeResources) -> tuple[str, ...]:
    """No hidden activation, plugin, MCP, or deferred promotion in 5D scope."""
    resources.assert_intact()
    if (getattr(getattr(resources.app_config, "tool_search", None), "enabled", None)
            is not False):
        _deny("DYNAMIC_TOOL_DISCOVERY_UNSUPPORTED")
    # Native SubagentExecutor reads skills from registry unless explicitly
    # restricted. Null/None means ALL skills, never 'none'.
    if getattr(resources.subagent_config, "skills", None) != []:
        _deny("SKILL_ACTIVATION_UNSUPPORTED")
    if getattr(getattr(resources.app_config, "skill_evolution", None), "enabled", None) is not False:
        _deny("SKILL_EVOLUTION_UNSUPPORTED")
    extensions = resources.extensions
    if any(getattr(extensions, name) for name in (
        "middleware_contributors", "task_lifecycle", "system_model_observers",
        "agent_assembly_observers", "context_compaction_observers",
        "services", "routers", "plugins",
    )):
        _deny("DYNAMIC_EXTENSIONS_UNSUPPORTED")
    # User/deployment-scoped remote servers, late builtin/adapters and
    # extension plugin tools must never inherit a config tool's identity.
    tool_config = {cfg.name: cfg.use for cfg in getattr(resources.app_config, "tools", ())}
    if len(tool_config) != len(getattr(resources.app_config, "tools", ())):
        _deny("DUPLICATE_CONFIG_TOOL")
    for contract_id, tool in zip(resources.allowed_tool_ids, resources.tools):
        if (tool.name != contract_id or contract_id not in tool_config
                or tool_config[contract_id] not in {
                    "deerflow.sandbox.tools:ls_tool",
                    "deerflow.sandbox.tools:glob_tool",
                    "deerflow.sandbox.tools:grep_tool",
                    "deerflow.sandbox.tools:read_file_tool",
                    "deerflow.sandbox.tools:write_file_tool",
                    "deerflow.sandbox.tools:str_replace_tool",
                    "deerflow.sandbox.tools:bash_tool",
                }):
            _deny("DYNAMIC_TOOL_PROVENANCE_FORBIDDEN")
    if (len(resources.allowed_tool_ids) != len(resources.tools)
            or len(set(resources.allowed_tool_ids)) != len(resources.allowed_tool_ids)):
        _deny("TOOL_SURFACE_IDENTITY_MISMATCH")
    return resources.allowed_tool_ids


def _filter(provider: Any, principal: Any, resource: str, names: tuple[str, ...]) -> tuple[str, ...]:
    try:
        visible = provider.filter_resources(principal, resource, list(names))
    except Exception:
        _deny("AUTHORIZATION_VISIBILITY_FAILED")
    if (not isinstance(visible, list) or len(set(map(str, visible))) != len(visible)
            or any(type(x) is not str or x not in names for x in visible)):
        _deny("AUTHORIZATION_VISIBILITY_INVALID")
    return tuple(name for name in names if name in visible)


def _decision_ok(decision: Any) -> bool:
    return type(getattr(decision, "allow", None)) is bool and decision.allow is True


def _request(factory: Callable[..., Any], principal: Any, resource: str,
             action: str, target: str, context: dict[str, Any]) -> Any:
    try:
        return factory(principal=principal, resource=resource,
                       action=action, target=target, context=context)
    except Exception:
        _deny("AUTHORIZATION_REQUEST_FAILED")


@dataclass(frozen=True)
class BoundToolView:
    """The exact model-visible host tools; NEVER only a list of matching names."""
    names: tuple[str, ...]
    objects: tuple[Any, ...]
    object_seals: tuple[tuple[Any, ...], ...]

    def check_model_visible(self, actual: tuple[Any, ...]) -> None:
        """Call before model bind and again on compiled ToolNode registry."""
        if len(actual) != len(self.objects):
            _deny("MODEL_TOOL_SURFACE_DRIFT")
        for actual_tool, expected, seal in zip(actual, self.objects, self.object_seals):
            if actual_tool is not expected or _tool_seal(actual_tool) != seal:
                _deny("MODEL_TOOL_SURFACE_DRIFT")

    def check_middleware_declarations(self, middlewares: tuple[Any, ...]) -> None:
        """Deny *all* additional middleware-declared tools until 5E hooks exist.

        Pure metadata check does not validate arbitrary LangChain middleware
        effects that inject tools invisibly. 5E must inspect compiled ToolNode.
        """
        for middleware in middlewares:
            declared = getattr(middleware, "tools", None)
            if declared is None:
                continue
            if not isinstance(declared, (tuple, list)):
                _deny("MIDDLEWARE_TOOL_DECLARATION_UNKNOWN")
            if declared:
                _deny("MIDDLEWARE_TOOL_DECLARATION_FORBIDDEN")


class ToolCallGuard:
    """Process-local run guard, separate from the model and LangChain prompts.

    Invocation and principal are immutable host-owned *references*, not
    serialized bearer tokens. Always use an operator-supplied tool_call_id,
    never a name or ID picked from the model's proposed tool arguments.
    """

    def __init__(self, *, invocation: NodeExecutionInvocation,
                 resources: PinnedNodeResources, view: BoundToolView,
                 principal: Any, provider: Any,
                 request_factory: Callable[..., Any], auth_enabled: bool):
        self.invocation = invocation
        self.resources = resources
        self.view = view
        self.principal = principal
        self.provider = provider
        self.request_factory = request_factory
        self.auth_enabled = auth_enabled
        self.closed = False
        self._pending_calls: set[str] = set()
        self._used_call_ids: set[str] = set()

    def close(self) -> None:
        """Revoke future calls. In-flight provider/native tool quiescence is 5E."""
        self.closed = True

    def _validate(self, *, tool: Any, tool_call_id: str, tool_input: Any) -> str:
        if self.closed:
            _deny("EXECUTION_BINDING_CLOSED")
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            _deny("TOOL_CALL_ID_REQUIRED")
        if tool_call_id in self._used_call_ids:
            _deny("TOOL_CALL_REPLAY")
        self.resources.assert_intact()
        self.view.check_model_visible(self.view.objects)
        if tool is None or not any(t is tool for t in self.view.objects):
            _deny("UNBOUND_TOOL_OBJECT")
        name = tool.name
        if name not in self.view.names:
            _deny("UNBOUND_TOOL_NAME")
        if tool_call_id in self._pending_calls:
            _deny("TOOL_CALL_REPLAY")
        # Disallow malformed opaque arguments that native AuthorizationProvider
        # cannot assess as JSON-compatible values.
        if not isinstance(tool_input, (dict, str)):
            _deny("TOOL_INPUT_UNATTESTED")
        return name

    def _auth_request(self, name: str, call_id: str, tool_input: Any) -> Any:
        return _request(
            self.request_factory, self.principal, "tool", "call", name,
            {"run_id": self.invocation.run_id, "tool_call_id": call_id,
             "tool_input": tool_input, "is_subagent": True,
             "agent_id": self.resources.node_id,
             "execution_id": self.invocation.execution_id},
        )

    async def ainvoke(self, *, tool: Any, tool_call_id: str,
                      tool_input: dict | str, handler: Callable[[], Awaitable[Any]]) -> Any:
        """Guarantee no provided native handler is called on authorization deny."""
        name = self._validate(tool=tool, tool_call_id=tool_call_id, tool_input=tool_input)
        self._used_call_ids.add(tool_call_id)
        self._pending_calls.add(tool_call_id)
        try:
            if self.auth_enabled:
                try:
                    decision = await self.provider.aauthorize(
                        self._auth_request(name, tool_call_id, tool_input)
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _deny("AUTHORIZATION_CALL_FAILED")
                if not _decision_ok(decision):
                    _deny("AUTHORIZATION_CALL_DENIED")
            # A cancellation/close during async authorization must not launch
            # a tool. No await between this check and dispatch to handler.
            if self.closed:
                _deny("EXECUTION_BINDING_CLOSED")
            self.resources.assert_intact()
            return await handler()
        finally:
            self._pending_calls.discard(tool_call_id)

    def invoke(self, *, tool: Any, tool_call_id: str,
               tool_input: dict | str, handler: Callable[[], Any]) -> Any:
        """Synchronous tool path; never permits bypass through BaseTool.run."""
        name = self._validate(tool=tool, tool_call_id=tool_call_id, tool_input=tool_input)
        self._used_call_ids.add(tool_call_id)
        self._pending_calls.add(tool_call_id)
        try:
            if self.auth_enabled:
                try:
                    decision = self.provider.authorize(
                        self._auth_request(name, tool_call_id, tool_input)
                    )
                except Exception:
                    _deny("AUTHORIZATION_CALL_FAILED")
                if not _decision_ok(decision):
                    _deny("AUTHORIZATION_CALL_DENIED")
            if self.closed:
                _deny("EXECUTION_BINDING_CLOSED")
            self.resources.assert_intact()
            return handler()
        finally:
            self._pending_calls.discard(tool_call_id)


@dataclass(frozen=True)
class NodeExecutionBinding:
    execution_id: str
    preparation_id: str
    invocation: NodeExecutionInvocation
    resources: PinnedNodeResources
    tool_view: BoundToolView
    guard: ToolCallGuard


class NodeExecutionBindingStore:
    """Single-process, once-only bind after genuine Scheduler commit.

    The preparation backend itself checks Scheduler identity. This store does
    not allocate execution_id or commit attempts; it never invokes a model or
    a business tool. On any bind failure the 5C preparation is consumed and no
    binding is published.
    """

    def __init__(self, *, preparation_backend: DeerFlowPreparationBackend,
                 principal_supplier: Callable[[], Any],
                 provider_supplier: Callable[[Any], Any],
                 auth_request_factory: Callable[..., Any]):
        self.preparation_backend = preparation_backend
        self.principal_supplier = principal_supplier
        self.provider_supplier = provider_supplier
        self.auth_request_factory = auth_request_factory
        self._active: dict[str, NodeExecutionBinding] = {}
        self._used: set[str] = set()

    @classmethod
    def from_deerflow(cls, *, preparation_backend: DeerFlowPreparationBackend,
                      host_identity_supplier: Callable[[], Mapping[str, Any]]):
        """Native pinned AuthorizationProvider protocol; no user-supplied ID."""
        try:
            from deerflow.authz.principal import build_principal_from_context
            from deerflow.authz.provider import AuthzRequest, AuthorizationProvider
            from deerflow.authz.runtime import resolve_authorization_provider
            from deerflow.authz import runtime as runtime_module
            from aswe.integrations.deerflow.inventory import assert_pinned_deerflow_source
        except ImportError as exc:
            raise ToolBindingError("DEERFLOW_DEPENDENCY_UNAVAILABLE") from exc

        assert_pinned_deerflow_source(runtime_module.__file__)
        def principal_supplier():
            context = host_identity_supplier()
            if not isinstance(context, Mapping):
                _deny("HOST_PRINCIPAL_UNTRUSTED")
            config = preparation_backend.config_supplier()
            # Role default is only a presentation fallback: a trusted user_id
            # or trusted is_internal must be present regardless.
            return build_principal_from_context(
                context, default_role=config.authorization.default_role
            )

        def provider_supplier(config):
            obj = resolve_authorization_provider(config)
            if obj is not None and not isinstance(obj, AuthorizationProvider):
                _deny("AUTHORIZATION_PROVIDER_UNATTESTED")
            return obj

        return cls(
            preparation_backend=preparation_backend,
            principal_supplier=principal_supplier,
            provider_supplier=provider_supplier,
            auth_request_factory=AuthzRequest,
        )

    async def bind(self, *, preparation: NodeExecutionPreparation,
                   invocation: NodeExecutionInvocation) -> NodeExecutionBinding:
        if invocation.execution_id in self._used or invocation.execution_id in self._active:
            _deny("EXECUTION_BINDING_REPLAY")
        try:
            resources = self.preparation_backend.claim_for_execution(preparation, invocation)
        except DeerFlowPreparationError as exc:
            raise ToolBindingError(exc.code) from None
        self._used.add(invocation.execution_id)
        try:
            enabled = _auth_enabled(resources)
            names = _static_surface(resources)
            principal = self.principal_supplier()
            if not _principal_ok(principal):
                _deny("HOST_PRINCIPAL_UNTRUSTED")
            provider = None
            visible = names
            if enabled:
                provider = self.provider_supplier(resources.app_config.authorization)
                if provider is None:
                    _deny("AUTHORIZATION_PROVIDER_UNATTESTED")
                visible_model = await asyncio.to_thread(
                    _filter, provider, principal, "model", (resources.model_name,)
                )
                if visible_model != (resources.model_name,):
                    _deny("MODEL_VISIBILITY_DENIED")
                visible = await asyncio.to_thread(
                    _filter, provider, principal, "tool", names
                )
                # Required tools remain load-bearing even when hidden.
                required = self.preparation_backend.policy.required_business_tools
                if not set(required).issubset(visible):
                    _deny("REQUIRED_TOOL_VISIBILITY_DENIED")
                try:
                    verdict = await provider.aauthorize(
                        _request(self.auth_request_factory, principal, "model",
                                 "use", resources.model_name,
                                 {"run_id": invocation.run_id, "is_subagent": True})
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _deny("MODEL_AUTHORIZATION_FAILED")
                if not _decision_ok(verdict):
                    _deny("MODEL_AUTHORIZATION_DENIED")
            view_tools = tuple(t for t in resources.tools if t.name in visible)
            view = BoundToolView(
                names=tuple(t.name for t in view_tools),
                objects=view_tools,
                object_seals=tuple(_tool_seal(t) for t in view_tools),
            )
            # Bind once after all waits. Scheduler's owning task remains
            # active; the actual gate is the 5C claim before authorization.
            resources.assert_intact()
            guard = ToolCallGuard(
                invocation=invocation, resources=resources,
                view=view, principal=principal, provider=provider,
                request_factory=self.auth_request_factory, auth_enabled=enabled,
            )
            record = NodeExecutionBinding(
                execution_id=invocation.execution_id,
                preparation_id=preparation.preparation_id,
                invocation=invocation, resources=resources,
                tool_view=view, guard=guard,
            )
            self._active[invocation.execution_id] = record
            return record
        except asyncio.CancelledError:
            raise
        except ToolBindingError:
            raise
        except DeerFlowPreparationError as exc:
            raise ToolBindingError(exc.code) from None
        except Exception:
            _deny("EXECUTION_BINDING_FAILED")

    def lookup(self, execution_id: str) -> NodeExecutionBinding:
        binding = self._active.get(execution_id)
        if binding is None or binding.guard.closed:
            _deny("EXECUTION_BINDING_UNAVAILABLE")
        return binding

    def release(self, execution_id: str) -> None:
        binding = self._active.pop(execution_id, None)
        if binding is not None:
            binding.guard.close()

    def release_all(self) -> None:
        for execution_id in tuple(self._active):
            self.release(execution_id)

    @property
    def active_count(self) -> int:
        return len(self._active)
