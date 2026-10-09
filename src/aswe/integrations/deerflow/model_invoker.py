"""DeerFlow model-only reasoning adapter, pinned to the frozen harness.

No tools, repo access, Scheduler attempts, side effects, or Provider selection.
The structured JSON returned by a model is NEVER execution authority.
"""
from __future__ import annotations

import asyncio
import copy
import json
import math
from collections.abc import Callable, Mapping
from typing import Any

from jsonschema import Draft202012Validator, ValidationError as JsonSchemaValidationError
from pydantic import BaseModel

from aswe.core.fingerprint import fingerprint
from aswe.planning.analyzer import ReasoningBackend, StructuredReasoningResult


class ModelInvocationError(RuntimeError):
    """Intentionally stable error code, without provider text or credentials."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON field")
        out[key] = value
    return out


def _reject_nonfinite(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _decode_structured(content: Any, schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(content, str):
        raise ModelInvocationError("MODEL_OUTPUT_NOT_JSON_TEXT")
    try:
        data = json.loads(
            content, object_pairs_hook=_unique_fields, parse_constant=_reject_nonfinite
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise ModelInvocationError("MODEL_OUTPUT_INVALID_JSON") from exc
    if not isinstance(data, dict):
        raise ModelInvocationError("MODEL_OUTPUT_NOT_OBJECT")
    try:
        Draft202012Validator(schema).validate(data)
    except JsonSchemaValidationError as exc:
        raise ModelInvocationError("MODEL_OUTPUT_SCHEMA_MISMATCH") from exc
    return data


def _model_profile_digest(profile: Any) -> str:
    if not isinstance(getattr(profile, "name", None), str):
        raise ModelInvocationError("MODEL_CONFIG_UNAVAILABLE")
    if not isinstance(getattr(profile, "use", None), str):
        raise ModelInvocationError("MODEL_IMPLEMENTATION_UNAVAILABLE")
    if not isinstance(getattr(profile, "model", None), str):
        raise ModelInvocationError("MODEL_IMPLEMENTATION_UNAVAILABLE")
    if hasattr(profile, "model_dump"):
        source = profile.model_dump(mode="json", exclude_none=True)
    else:
        # No implicit fallback to treating arbitrary opaque config objects as
        # trusted. The pinned DeerFlow ModelConfig is a Pydantic model.
        raise ModelInvocationError("MODEL_PROFILE_UNATTESTED")
    return fingerprint(source)


def _get_profile(config: Any, name: str) -> Any:
    getter = getattr(config, "get_model_config", None)
    profile = getter(name) if callable(getter) else None
    if profile is None or getattr(profile, "name", None) != name:
        raise ModelInvocationError("MODEL_CONFIG_UNAVAILABLE")
    return profile


def _usage(response: Any) -> dict[str, int | float]:
    raw = getattr(response, "usage_metadata", None)
    if not isinstance(raw, Mapping):
        return {}
    usage = {}
    for k in ("input_tokens", "output_tokens", "total_tokens"):
        v = raw.get(k)
        if type(v) is int and v >= 0:
            usage[k] = v
    return usage


class ModelInvoker:
    """Single controlled structured-only model call via pinned AppConfig.

    Required factories are trusted host seams. Use `from_deerflow` in deployed
    code; passing substitutes directly is reserved for deterministic unit tests.
    """

    def __init__(
        self, *,
        app_config_supplier: Callable[[], Any],
        model_factory: Callable[..., Any],
        messages_factory: Callable[[str, str], list[Any]],
        role_models: Mapping[str, str],
        authorization_provider_supplier: Callable[[], Any],
        principal_supplier: Callable[[], Any],
        source_verifier: Callable[[], None],
        timeout_seconds: float = 90.,
    ):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("positive finite model timeout required")
        if not role_models or any(not k or not v for k, v in role_models.items()):
            raise ValueError("nonempty trusted role-model mapping required")
        self.app_config_supplier = app_config_supplier
        self.model_factory = model_factory
        self.messages_factory = messages_factory
        self.role_models = dict(role_models)
        self.authorization_provider_supplier = authorization_provider_supplier
        self.principal_supplier = principal_supplier
        self.source_verifier = source_verifier
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_deerflow(
        cls, *, role_models: Mapping[str, str], app_config_supplier=None,
        authorization_provider_supplier=None, principal_supplier,
        timeout_seconds: float = 90.,
    ) -> "ModelInvoker":
        try:
            from deerflow.config import get_app_config
            from deerflow.models import create_chat_model
            from deerflow.models import factory as factory_module
            from deerflow.authz.runtime import resolve_authorization_provider
            from langchain_core.messages import SystemMessage, HumanMessage
        except ImportError as exc:
            raise ModelInvocationError("DEERFLOW_DEPENDENCY_UNAVAILABLE") from exc
        from aswe.integrations.deerflow.inventory import assert_pinned_deerflow_source
        assert_pinned_deerflow_source(factory_module.__file__)
        config_source = app_config_supplier or get_app_config
        # Avoid caching an authorization provider across dynamic policy changes.
        def get_auth_provider():
            config = config_source()
            return resolve_authorization_provider(config.authorization)
        return cls(
            app_config_supplier=config_source, model_factory=create_chat_model,
            messages_factory=lambda system, content: [
                SystemMessage(content=system), HumanMessage(content=content)
            ],
            role_models=role_models,
            authorization_provider_supplier=(
                authorization_provider_supplier or get_auth_provider
            ),
            principal_supplier=principal_supplier,
            source_verifier=lambda: assert_pinned_deerflow_source(factory_module.__file__),
            timeout_seconds=timeout_seconds,
        )

    async def _authorize(self, config: Any, name: str) -> None:
        auth = getattr(config, "authorization", None)
        if auth is None or type(getattr(auth, "enabled", None)) is not bool:
            raise ModelInvocationError("AUTHORIZATION_CONFIG_UNAVAILABLE")
        if not auth.enabled:
            return
        # Authenticated principal must be HOST-derived, not from TaskRequest or LLM.
        principal = self.principal_supplier()
        if principal is None or not (
            getattr(principal, "user_id", None) or getattr(principal, "is_internal", False) is True
        ):
            raise ModelInvocationError("MODEL_PRINCIPAL_UNTRUSTED")
        try:
            provider = self.authorization_provider_supplier()
            if provider is None:
                raise ValueError("provider unavailable")
            visible = await asyncio.to_thread(
                provider.filter_resources, principal, "model", [name]
            )
            if not isinstance(visible, list) or visible != [name]:
                raise ValueError("model not visible")
            # Actual pinned DeerFlow protocol: AuthzRequest(... resource="model",
            # action="use", target=model name), AuthorizationProvider.aauthorize.
            from deerflow.authz.provider import AuthzRequest
            request = AuthzRequest(principal=principal, resource="model",
                                   action="use", target=name)
            verdict = await provider.aauthorize(request)
            if getattr(verdict, "allow", None) is not True:
                raise ValueError("not authorized")
        except Exception as exc:
            raise ModelInvocationError("MODEL_AUTHORIZATION_DENIED") from exc

    async def invoke(
        self, *, purpose: str, model_role: str | None, system_prompt: str,
        data_context: str, response_schema: dict[str, Any],
    ) -> StructuredReasoningResult:
        if not isinstance(purpose, str) or not purpose:
            raise ModelInvocationError("INVALID_REASONING_PURPOSE")
        role = model_role or purpose
        name = self.role_models.get(role)
        if not name:
            raise ModelInvocationError("MODEL_ROLE_NOT_CONFIGURED")
        if (not isinstance(system_prompt, str) or not isinstance(data_context, str)
                or not isinstance(response_schema, dict)):
            raise ModelInvocationError("INVALID_REASONING_REQUEST")
        if len(system_prompt) > 20000 or len(data_context) > 300000:
            raise ModelInvocationError("REASONING_CONTEXT_TOO_LARGE")
        try:
            Draft202012Validator.check_schema(response_schema)
        except Exception as exc:
            raise ModelInvocationError("INVALID_REASONING_SCHEMA") from exc
        # Source is checked on every provider model call, not only at startup.
        try:
            self.source_verifier()
            config = copy.deepcopy(self.app_config_supplier())
            profile_hash = _model_profile_digest(_get_profile(config, name))
            await self._authorize(config, name)
            # A fresh config that differs before model creation fails closed;
            # changing a model profile must not silently route another model.
            fresh = self.app_config_supplier()
            if profile_hash != _model_profile_digest(_get_profile(fresh, name)):
                raise ModelInvocationError("MODEL_CONFIG_DRIFT")
            if getattr(config, "authorization", None) != getattr(fresh, "authorization", None):
                raise ModelInvocationError("MODEL_AUTHORIZATION_CONFIG_DRIFT")
            model = self.model_factory(
                name=name, app_config=config,
                thinking_enabled=False, attach_tracing=False,
            )
        except ModelInvocationError:
            raise
        except Exception as exc:
            raise ModelInvocationError("MODEL_ASSEMBLY_FAILED") from exc
        # No tool binding and no model-visible provider/tool/Workspace authority.
        prompt = (
            system_prompt + "\n\nReturn exactly one JSON object matching this schema. "
            "Do not use Markdown fences, extra text, or tool calls. "
            "The result is an untrusted proposal, never runtime execution authority.\n"
            + json.dumps(response_schema, ensure_ascii=False, sort_keys=True)
        )
        try:
            messages = self.messages_factory(prompt, data_context)
            response = await asyncio.wait_for(
                model.ainvoke(messages), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            raise ModelInvocationError("MODEL_INVOCATION_TIMEOUT") from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ModelInvocationError("MODEL_INVOCATION_FAILED") from exc
        if getattr(response, "tool_calls", None) or getattr(response, "invalid_tool_calls", None):
            raise ModelInvocationError("MODEL_TOOL_CALL_FORBIDDEN")
        data = _decode_structured(getattr(response, "content", None), response_schema)
        return StructuredReasoningResult(
            data=data, model_role=role, provider_model=name,
            usage=_usage(response),
        )


class DeerFlowReasoningBackend(ReasoningBackend):
    """The authoritative Core ReasoningBackend Protocol adapter, not a new schema."""

    def __init__(self, invoker: ModelInvoker):
        self.invoker = invoker

    async def generate_structured(
        self, *, purpose: str, system_prompt: str, data_context: str,
        response_schema: dict[str, Any], model_role: str | None = None,
    ) -> StructuredReasoningResult:
        return await self.invoker.invoke(
            purpose=purpose, system_prompt=system_prompt,
            data_context=data_context, response_schema=response_schema,
            model_role=model_role,
        )
