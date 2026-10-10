"""5F-D live-model configuration: env-only secrets, frozen DeerFlow model profile.

This module has NO network calls and does not import pinned DeerFlow.
Only manually triggered live smoke may instantiate a real provider. The API
key never enters an AppConfig snapshot, logging payload, task prompt, Git
workspace or model-visible tool context; ChatOpenAI reads OPENAI_API_KEY from
the trusted runner process environment.
"""
from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


class LiveSmokeConfigError(ValueError):
    """Deliberately opaque error code: do not leak tokens or endpoint URLs."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class LiveModelSettings:
    model: str
    base_url: str | None
    profile_name: str = "aswe-real-swe-smoke"
    request_timeout: int = 60

    @classmethod
    def from_environment(cls, environ=None) -> "LiveModelSettings":
        source = environ if environ is not None else os.environ
        if source.get("ASWE_LIVE_SMOKE") != "1":
            raise LiveSmokeConfigError("LIVE_SMOKE_EXPLICIT_OPT_IN_REQUIRED")
        if not source.get("GITHUB_ACTIONS") == "true":
            raise LiveSmokeConfigError("LIVE_SMOKE_MANUAL_ACTIONS_ONLY")
        key = source.get("SWE_LLM_API_KEY", "")
        if not isinstance(key, str) or not key.strip() or any(
            ch in key for ch in ("\n", "\r")
        ):
            raise LiveSmokeConfigError("LIVE_LLM_API_KEY_MISSING")
        model = source.get("SWE_LLM_MODEL", "")
        if not isinstance(model, str) or not re.fullmatch(r"[a-zA-Z0-9_.:/+-]{1,160}", model):
            raise LiveSmokeConfigError("LIVE_LLM_MODEL_INVALID")
        raw_url = source.get("SWE_LLM_BASE_URL", "")
        url = raw_url.strip() if isinstance(raw_url, str) else ""
        if url:
            try:
                parsed = urlsplit(url)
                hostname = parsed.hostname
                valid = (
                    parsed.scheme == "https"
                    and hostname is not None
                    and len(url) <= 1024
                    and not parsed.username and not parsed.password
                    and not parsed.query and not parsed.fragment
                    and not any(ch.isspace() for ch in url)
                    and parsed.port in (None, 443)
                    and hostname.lower() not in ("localhost", "localhost.localdomain")
                    and not hostname.lower().endswith((".localhost", ".local", ".internal"))
                )
                if hostname:
                    try:
                        addr = ipaddress.ip_address(hostname)
                    except ValueError:
                        addr = None
                    if addr is not None and not addr.is_global:
                        valid = False
            except (ValueError, TypeError):
                valid = False
            if not valid:
                raise LiveSmokeConfigError("LIVE_LLM_BASE_URL_INVALID")
        return cls(model=model, base_url=url or None)

    def apply_to_vendor_app_config(self, config, *, api_key_env: str = "OPENAI_API_KEY") -> None:
        """Assemble real frozen DeerFlow ChatOpenAI profile without raw keys."""
        if not os.environ.get(api_key_env):
            raise LiveSmokeConfigError("LIVE_OPENAI_CLIENT_KEY_UNAVAILABLE")
        from deerflow.config.model_config import ModelConfig
        from aswe.integrations.deerflow.inventory import assert_pinned_deerflow_source
        from deerflow.config import model_config as model_config_module
        assert_pinned_deerflow_source(model_config_module.__file__)
        kwargs = {
            "name": self.profile_name,
            "use": "langchain_openai:ChatOpenAI",
            "model": self.model,
            "timeout": self.request_timeout,
            "max_retries": 0,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        profile = ModelConfig(**kwargs)
        # Only one explicitly chosen provider may be visible in this run.
        config.models = [profile]
        if config.get_model_config(self.profile_name) is not profile:
            raise LiveSmokeConfigError("LIVE_MODEL_PROFILE_NOT_SELECTED")
