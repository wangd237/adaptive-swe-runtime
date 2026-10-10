"""Step 5D: execution-scoped, fail-closed DeerFlow tool authority.

Single-process seam only. This module does not run a DeerFlow graph. Step 5E
must wire the guarded dispatch operations into *every* actual tool entry,
including middleware-declared tools, before enabling real execute_prepared().
"""
from __future__ import annotations

import asyncio
import threading
from copy import deepcopy
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

from aswe.core.contracts.backend import NodeExecutionInvocation, NodeExecutionPreparation
from aswe.capabilities.effects import DEERFLOW_USE_BY_CONTRACT, STANDARD_EFFECTS, ToolEffect
from aswe.integrations.deerflow.controlled_swe import ControlledSWEWorkspace
from aswe.integrations.deerflow.docker_bash_capability import RuntimeDockerBashSource
from aswe.trace.minimal_events import LocalRuntimeEventSink
from aswe.integrations.deerflow.preparation import (
    DeerFlowPreparationBackend, DeerFlowPreparationError, PinnedNodeResources,
    _tool_seal, _extension_seal, _digest,
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
    if getattr(resources.app_config, "plugins", ()):
        _deny("CONFIGURED_PLUGINS_UNSUPPORTED")
    mcp_servers = getattr(getattr(resources.app_config, "extensions", None), "mcp_servers", {})
    if not isinstance(mcp_servers, Mapping):
        _deny("MCP_EXTENSION_CONFIG_UNATTESTED")
    if any(getattr(server, "enabled", True) is not False for server in mcp_servers.values()):
        _deny("MCP_EXTENSION_CONFIG_FORBIDDEN")
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
        if contract_id == "bash" and isinstance(tool, RuntimeDockerBashSource):
            if (getattr(resources, "docker_bash_grant", None) is None
                    or tool.grant != getattr(resources, "docker_bash_grant", None)):
                _deny("DOCKER_BASH_GRANT_MISMATCH")
            continue
        if (tool.name != contract_id or contract_id not in tool_config
                or tool_config[contract_id] != DEERFLOW_USE_BY_CONTRACT.get(contract_id)):
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


class ToolPolicyMiddleware:
    """Provider-neutral 5D surface gate; NOT a LangChain AgentMiddleware.

    Native wrappers and compiled-ToolNode enforcement are deliberately held
    for 5E. No caller may treat a validated raw tool as guard-wrapped.
    """

    def __init__(self, view: BoundToolView):
        self.view = view

    def validate_build_inputs(self, *, tools: tuple[Any, ...],
                              middleware: tuple[Any, ...] = ()) -> None:
        self.view.check_model_visible(tools)
        self.view.check_middleware_declarations(middleware)

    def validate_compiled_registry(self, registry: Mapping[str, Any]) -> None:
        # A middleware tool can shadow an ordinary tool by exposed name.
        # Same-name impostors are rejected by identity and schema seal.
        if not isinstance(registry, Mapping) or set(registry) != set(self.view.names):
            _deny("COMPILED_TOOL_REGISTRY_DRIFT")
        for tool, seal in zip(self.view.objects, self.view.object_seals):
            if registry[tool.name] is not tool or _tool_seal(tool) != seal:
                _deny("COMPILED_TOOL_REGISTRY_DRIFT")


class ToolCallGuard:
    """Process-local run guard, separate from the model and LangChain prompts.

    Invocation and principal are immutable host-owned *references*, not
    serialized bearer tokens. Always use an operator-supplied tool_call_id,
    never a name or ID picked from the model's proposed tool arguments.
    """

    def __init__(self, *, invocation: NodeExecutionInvocation,
                 resources: PinnedNodeResources, view: BoundToolView,
                 principal: Any, provider: Any,
                 request_factory: Callable[..., Any], auth_enabled: bool,
                 policy: Any,
                 execution_live_checker: Callable[[NodeExecutionInvocation], bool],
                 swe_runtime: ControlledSWEWorkspace | None = None,
                 trace_sink: LocalRuntimeEventSink | None = None):
        if trace_sink is not None and trace_sink.task_id != invocation.task_id:
            _deny("TOOL_TRACE_TASK_MISMATCH")
        self.trace_sink = trace_sink
        self.invocation = invocation
        self.resources = resources
        self.view = view
        self.swe_runtime = swe_runtime
        self._swe_runtime_anchor = swe_runtime
        if swe_runtime is not None and (
            not isinstance(swe_runtime, ControlledSWEWorkspace)
            or swe_runtime.invocation is not invocation
            or swe_runtime.policy is not policy
        ):
            _deny("SWE_RUNTIME_AUTHORITY_MISMATCH")
        self.principal = principal
        self._principal_digest = _digest(principal)
        self.provider = provider
        self._pinned_provider = provider
        self.request_factory = request_factory
        self.auth_enabled = auth_enabled
        self._auth_enabled_anchor = auth_enabled
        self.policy = policy
        self._pinned_policy = policy
        self.execution_live_checker = execution_live_checker
        self._liveness_anchor = execution_live_checker
        if (policy.fingerprint != resources.policy_fingerprint or
                not set(view.names).issubset(policy.allowed_business_tools)):
            _deny("TOOL_POLICY_IDENTITY_MISMATCH")
        self.closed = False
        self._call_lock = threading.RLock()
        self._pending_calls: set[str] = set()
        self._used_call_ids: set[str] = set()
        self._tool_receipts: list[dict[str, str]] = []
        self._dev_failed_checks = 0

    def close(self) -> None:
        """Revoke future calls. In-flight provider/native tool quiescence is 5E."""
        with self._call_lock:
            self.closed = True

    def _live(self) -> None:
        if self.execution_live_checker is not self._liveness_anchor:
            _deny("EXECUTION_LIVENESS_GUARD_MUTATED")
        try:
            running = self.execution_live_checker(self.invocation) is True
        except Exception:
            running = False
        if not running:
            _deny("EXECUTION_BINDING_NOT_ACTIVE")

    def _validate(self, *, tool: Any, tool_call_id: str, tool_input: Any) -> str:
        if self.closed:
            _deny("EXECUTION_BINDING_CLOSED")
        if self.swe_runtime is not self._swe_runtime_anchor:
            _deny("SWE_RUNTIME_BINDING_MUTATED")
        self._live()
        if (self.provider is not self._pinned_provider
                or self.policy is not self._pinned_policy
                or self.auth_enabled is not self._auth_enabled_anchor
                or _digest(self.principal) != self._principal_digest):
            _deny("RUN_AUTHORITY_MUTATED")
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            _deny("TOOL_CALL_ID_REQUIRED")
        if tool_call_id in self._used_call_ids:
            _deny("TOOL_CALL_REPLAY")
        self.resources.assert_intact()
        self.view.check_model_visible(self.view.objects)
        if tool is None or not any(t is tool for t in self.view.objects):
            _deny("UNBOUND_TOOL_OBJECT")
        name = tool.name
        if name not in self.view.names or name in self.policy.denied_tools:
            _deny("UNBOUND_TOOL_NAME")
        if (name in self.policy.prohibited_actions
                or "*" in self.policy.prohibited_actions):
            _deny("TOOL_ACTION_PROHIBITED")
        effect = STANDARD_EFFECTS.get("config:" + name, ToolEffect.UNKNOWN)
        # 5D has no authenticated Sandbox/Workspace argument policy hook.
        # Do not permit even authorized WRITE/Bash calls until 5E/5F bind the
        # canonical path/command verifier and mutation evidence lifecycle.
        if self.swe_runtime is None:
            if effect is not ToolEffect.READ_ONLY:
                _deny("MUTATING_TOOL_EXECUTION_NOT_ENABLED")
            if self.policy.allowed_paths is not None or self.policy.forbidden_paths:
                _deny("TOOL_PATH_POLICY_UNBOUND")
        else:
            if name not in ("read_file","write_file","str_replace","bash"):
                _deny("SWE_TOOL_UNSUPPORTED")
            if effect not in (ToolEffect.READ_ONLY,ToolEffect.WORKSPACE_MUTATING):
                _deny("SWE_TOOL_EFFECT_UNTRUSTED")
            if name == "bash" and self.swe_runtime.command_backend is None:
                _deny("SWE_BASH_ISOLATION_REQUIRED")
        if tool_call_id in self._pending_calls:
            _deny("TOOL_CALL_REPLAY")
        # Disallow malformed opaque arguments that native AuthorizationProvider
        # cannot assess as JSON-compatible values.
        if not isinstance(tool_input, (dict, str)):
            _deny("TOOL_INPUT_UNATTESTED")
        return name

    def _reserve(self, *, tool: Any, tool_call_id: str, tool_input: Any) -> str:
        # LangChain can invoke native sync tools from a worker thread while
        # async tools run on the event loop: the replay test/set must be atomic.
        with self._call_lock:
            name = self._validate(tool=tool, tool_call_id=tool_call_id,
                                  tool_input=tool_input)
            self._used_call_ids.add(tool_call_id)
            self._pending_calls.add(tool_call_id)
            return name

    def _record(self, *, name: str, call_id: str, argument: Any,
                status: str, result: Any = None, failure: str = "") -> None:
        # This is a bounded, host-observed ToolCallGuard *receipt*, not a
        # native shell/Workspace effect attestation. Never persist raw data.
        try:
            args_digest = _digest(argument)
        except Exception:
            args_digest = "unserializable"
        try:
            output_digest = _digest(result) if status == "completed" else ""
        except Exception:
            output_digest = "unserializable"
        receipt = {
            "tool_call_id": call_id,
            "tool_name": name,
            "arguments_digest": args_digest,
            "output_digest": output_digest,
            "status": status,
            "failure_code": failure,
            "execution_id": self.invocation.execution_id,
        }
        with self._call_lock:
            self._tool_receipts.append(receipt)
        if self.trace_sink is not None:
            common = {"execution_id":self.invocation.execution_id,
                      "attempt":self.invocation.attempt,
                      "run_id":self.invocation.run_id}
            self.trace_sink.emit("tool.call.finished",node_id=self.invocation.node_id,
                                 payload={**receipt, **common})
            # Model-controlled Bash is a development observation, not the
            # independently trusted Canonical Verification verdict.
            if name == "bash" and status == "completed" and isinstance(result,str):
                import re
                match = re.match(r"^exit_code=(-?\d+|None); timed_out=(True|False)\n", result)
                if match is not None:
                    exit_code = None if match.group(1) == "None" else int(match.group(1))
                    passed = exit_code == 0 and match.group(2) == "False"
                    self.trace_sink.emit("agent.test.observed", node_id=self.invocation.node_id,
                        payload={**common, "tool_call_id":call_id,
                                 "exit_code":exit_code, "passed":passed,
                                 "authority":"agent_observed_only"})
                    if not passed:
                        with self._call_lock:
                            self._dev_failed_checks += 1
                            failed_checks = self._dev_failed_checks
                        self.trace_sink.emit("repair.feedback.available",node_id=self.invocation.node_id,
                            payload={**common, "tool_call_id":call_id,
                                     "failed_check_count":failed_checks,
                                     "source":"agent_bash",
                                     "authority":"agent_observed_only"})

    def receipt_snapshot(self) -> tuple[dict[str, str], ...]:
        with self._call_lock:
            if self._pending_calls:
                _deny("TOOL_RECEIPTS_STILL_INFLIGHT")
            return tuple(dict(item) for item in sorted(
                self._tool_receipts, key=lambda x: x["tool_call_id"]
            ))

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
        """Authorize the real native tool handler, record effect-agnostic receipt."""
        name = self._reserve(tool=tool, tool_call_id=tool_call_id, tool_input=tool_input)
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
            if self.closed:
                _deny("EXECUTION_BINDING_CLOSED")
            self._live()
            if (_digest(self.principal) != self._principal_digest
                    or self.provider is not self._pinned_provider
                    or self.auth_enabled is not self._auth_enabled_anchor):
                _deny("RUN_AUTHORITY_MUTATED")
            self.resources.assert_intact()
            result = await handler()
        except BaseException as exc:
            self._record(name=name, call_id=tool_call_id, argument=tool_input,
                         status="cancelled" if isinstance(exc, asyncio.CancelledError)
                                else "denied" if isinstance(exc, ToolBindingError)
                                else "failed",
                         failure=(exc.code if isinstance(exc, ToolBindingError)
                                  else "TOOL_CANCELLED" if isinstance(exc, asyncio.CancelledError)
                                  else "NATIVE_TOOL_FAILED"))
            raise
        else:
            self._record(name=name, call_id=tool_call_id, argument=tool_input,
                         status="completed", result=result)
            return result
        finally:
            with self._call_lock:
                self._pending_calls.discard(tool_call_id)

    def invoke(self, *, tool: Any, tool_call_id: str,
               tool_input: dict | str, handler: Callable[[], Any]) -> Any:
        """Sync native tool call, atomic replay reservation across threads."""
        name = self._reserve(tool=tool, tool_call_id=tool_call_id, tool_input=tool_input)
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
            self._live()
            if (_digest(self.principal) != self._principal_digest
                    or self.provider is not self._pinned_provider
                    or self.auth_enabled is not self._auth_enabled_anchor):
                _deny("RUN_AUTHORITY_MUTATED")
            self.resources.assert_intact()
            result = handler()
        except BaseException as exc:
            self._record(name=name, call_id=tool_call_id, argument=tool_input,
                         status="denied" if isinstance(exc, ToolBindingError) else "failed",
                         failure=exc.code if isinstance(exc, ToolBindingError)
                                 else "NATIVE_TOOL_FAILED")
            raise
        else:
            self._record(name=name, call_id=tool_call_id, argument=tool_input,
                         status="completed", result=result)
            return result
        finally:
            with self._call_lock:
                self._pending_calls.discard(tool_call_id)


def make_langchain_tool_policy_middleware(binding: "NodeExecutionBinding") -> Any:
    """5D native shape: intercept LangChain ToolCallRequest before its handler.

    The factory imports the real LangChain middleware base only when the
    optional dependency is present. **Not automatically injected** into the
    frozen DeerFlow SubagentExecutor; 5E must install it and verify the
    compiled ToolNode registry, otherwise real execution remains disabled.
    """
    try:
        from langchain.agents.middleware import AgentMiddleware
    except ImportError as exc:
        raise ToolBindingError("LANGCHAIN_MIDDLEWARE_DEPENDENCY_UNAVAILABLE") from exc

    class PinnedToolPolicyMiddleware(AgentMiddleware):
        """Run-owned middleware, not an extension, skill or MCP capability."""

        def _incoming(self, request):
            call = getattr(request, "tool_call", None)
            if not isinstance(call, Mapping):
                _deny("TOOL_CALL_UNATTESTED")
            tool = getattr(request, "tool", None)
            name = call.get("name")
            if not isinstance(name, str) or tool is None or name != getattr(tool, "name", None):
                _deny("TOOL_CALL_NAME_OBJECT_MISMATCH")
            runtime = getattr(request, "runtime", None)
            context = getattr(runtime, "context", None) if runtime is not None else None
            if not isinstance(context, Mapping):
                _deny("TOOL_CALL_RUNTIME_CONTEXT_MISSING")
            if (context.get("run_id") != binding.invocation.run_id
                    or context.get("execution_id") != binding.invocation.execution_id):
                _deny("TOOL_CALL_RUNTIME_CONTEXT_MISMATCH")
            return tool, call.get("id"), call.get("args")

        def wrap_tool_call(self, request, handler):
            tool, call_id, args = self._incoming(request)
            return binding.guard.invoke(
                tool=tool, tool_call_id=call_id,
                tool_input=args, handler=lambda: handler(request),
            )

        async def awrap_tool_call(self, request, handler):
            tool, call_id, args = self._incoming(request)
            return await binding.guard.ainvoke(
                tool=tool, tool_call_id=call_id,
                tool_input=args, handler=lambda: handler(request),
            )

    return PinnedToolPolicyMiddleware()


@dataclass(frozen=True)
class NodeExecutionBinding:
    execution_id: str
    preparation_id: str
    invocation: NodeExecutionInvocation
    resources: PinnedNodeResources
    tool_view: BoundToolView
    guard: ToolCallGuard
    swe_runtime: ControlledSWEWorkspace | None = None


class NodeExecutionBindingStore:
    """Single-process, once-only bind after genuine Scheduler commit.

    The preparation backend itself checks Scheduler identity. This store does
    not allocate execution_id or commit attempts; it never invokes a model or
    a business tool. On any bind failure the 5C preparation is consumed and no
    binding is published.
    """

    def __init__(self, *, preparation_backend: DeerFlowPreparationBackend,
                 principal_supplier: Callable[[PinnedNodeResources], Any],
                 provider_supplier: Callable[[Any], Any],
                 auth_request_factory: Callable[..., Any],
                 execution_live_checker: Callable[[NodeExecutionInvocation], bool],
                 swe_workspace_factory: Callable[[NodeExecutionInvocation, PinnedNodeResources, Any], ControlledSWEWorkspace] | None = None,
                 expected_swe_workspace_root: Path | None = None,
                 trace_sink: LocalRuntimeEventSink | None = None):
        if swe_workspace_factory is not None and expected_swe_workspace_root is None:
            raise ValueError("trusted Scheduler Workspace root required for SWE profile")
        self.trace_sink = trace_sink
        self.preparation_backend = preparation_backend
        self.swe_workspace_factory = swe_workspace_factory
        self.expected_swe_workspace_root = (
            Path(expected_swe_workspace_root).resolve(strict=True)
            if expected_swe_workspace_root is not None else None
        )
        self.principal_supplier = principal_supplier
        self.provider_supplier = provider_supplier
        self.auth_request_factory = auth_request_factory
        if not callable(execution_live_checker):
            raise ValueError("trusted Scheduler execution-live checker required")
        self.execution_live_checker = execution_live_checker
        self._active: dict[str, NodeExecutionBinding] = {}
        self._used: set[str] = set()

    @classmethod
    def from_deerflow(cls, *, preparation_backend: DeerFlowPreparationBackend,
                      host_identity_supplier: Callable[[], Mapping[str, Any]],
                      execution_live_checker: Callable[[NodeExecutionInvocation], bool],
                      swe_workspace_factory: Callable[[NodeExecutionInvocation, PinnedNodeResources, Any], ControlledSWEWorkspace] | None = None,
                      expected_swe_workspace_root: Path | None = None):
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
        def principal_supplier(resources: PinnedNodeResources):
            context = host_identity_supplier()
            if not isinstance(context, Mapping):
                _deny("HOST_PRINCIPAL_UNTRUSTED")
            # Use the frozen AppConfig from 5C, NEVER get_app_config() again
            # after Scheduler commit or observe another authorization role.
            config = resources.app_config
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
            execution_live_checker=execution_live_checker,
            swe_workspace_factory=swe_workspace_factory,
            expected_swe_workspace_root=expected_swe_workspace_root,
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
            admitted = _static_surface(resources)
            restricted = tuple(name for name in admitted
                if STANDARD_EFFECTS.get("config:" + name) is not ToolEffect.READ_ONLY)
            required = self.preparation_backend.policy.required_business_tools
            swe_factory = self.swe_workspace_factory
            if swe_factory is None:
                if set(required).intersection(restricted):
                    _deny("MUTATING_TOOL_EXECUTION_NOT_ENABLED")
                names = tuple(name for name in admitted if name not in restricted)
            else:
                if any(name not in ("read_file", "write_file", "str_replace", "bash")
                       for name in admitted):
                    _deny("SWE_PROFILE_TOOL_SET_UNSUPPORTED")
                names = admitted
            principal = deepcopy(self.principal_supplier(resources))
            if not _principal_ok(principal):
                _deny("HOST_PRINCIPAL_UNTRUSTED")
            principal_digest = _digest(principal)
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
            source_tools = tuple(t for t in resources.tools if t.name in visible)
            if any(isinstance(t, RuntimeDockerBashSource) for t in source_tools):
                if (swe_factory is None or getattr(resources, "docker_bash_grant", None) is None
                        or self.preparation_backend.docker_bash_backend is None):
                    _deny("DOCKER_BASH_EXECUTION_NOT_PROVISIONED")
                try:
                    getattr(resources, "docker_bash_grant", None).assert_matches(
                        self.preparation_backend.docker_bash_backend)
                except Exception:
                    _deny("DOCKER_BASH_GRANT_DRIFT")
            swe_runtime = None
            if swe_factory is not None:
                swe_runtime = swe_factory(invocation, resources, self.preparation_backend.policy)
                if (not isinstance(swe_runtime, ControlledSWEWorkspace)
                        or swe_runtime.invocation is not invocation
                        or swe_runtime.policy is not self.preparation_backend.policy
                        or swe_runtime.root != self.expected_swe_workspace_root):
                    _deny("SWE_RUNTIME_AUTHORITY_MISMATCH")
                if getattr(resources, "docker_bash_grant", None) is not None:
                    if (swe_runtime.command_backend is not
                            self.preparation_backend.docker_bash_backend):
                        _deny("DOCKER_BASH_BACKEND_REBOUND")
                    try:
                        getattr(resources, "docker_bash_grant", None).assert_matches(swe_runtime.command_backend)
                    except Exception:
                        _deny("DOCKER_BASH_GRANT_DRIFT")
                view_tools = swe_runtime.make_tools(tuple(t.name for t in source_tools))
                if (len(view_tools) != len(source_tools)
                        or any(t.name != orig.name for t,orig in zip(view_tools, source_tools))):
                    _deny("SWE_RUNTIME_TOOL_IDENTITY_MISMATCH")
            else:
                view_tools = source_tools
            view = BoundToolView(
                names=tuple(t.name for t in view_tools),
                objects=view_tools,
                object_seals=tuple(_tool_seal(t) for t in view_tools),
            )
            # A provider must not rewrite identity between visibility and
            # use decisions (e.g. mutate role to administrator).
            if _digest(principal) != principal_digest:
                _deny("HOST_PRINCIPAL_MUTATED")
            # Authorization may await external systems. Fail closed if the
            # Scheduler already terminalized this committed attempt.
            try:
                still_running = self.execution_live_checker(invocation) is True
            except Exception:
                still_running = False
            if not still_running:
                _deny("EXECUTION_BINDING_NOT_ACTIVE")
            resources.assert_intact()
            guard = ToolCallGuard(
                invocation=invocation, resources=resources,
                view=view, principal=principal, provider=provider,
                request_factory=self.auth_request_factory, auth_enabled=enabled,
                policy=self.preparation_backend.policy,
                execution_live_checker=self.execution_live_checker,
                swe_runtime=swe_runtime,trace_sink=self.trace_sink,
            )
            record = NodeExecutionBinding(
                execution_id=invocation.execution_id,
                preparation_id=preparation.preparation_id,
                invocation=invocation, resources=resources,
                tool_view=view, guard=guard,
                swe_runtime=swe_runtime,
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
        binding.guard._live()
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
