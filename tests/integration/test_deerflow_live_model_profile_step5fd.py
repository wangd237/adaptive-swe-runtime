"""Installed frozen DeerFlow real model FACTORY test, with NO HTTP calls.

Executed by normal pinned-native CI using a fake key that never leaves
memory. Not evidence of a successful external live model request.
"""
from __future__ import annotations

from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model
from langchain_openai.chat_models.base import BaseChatOpenAI

from aswe.integrations.deerflow.live_smoke_config import LiveModelSettings
from aswe.llm_config import vendor_model_key


def test_live_profile_builds_real_frozen_chatopenai_without_api_request(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "offline-test-key-no-network")
    settings=LiveModelSettings.from_environment({
        "ASWE_LIVE_SMOKE": "1",
        "GITHUB_ACTIONS": "true",
        "LLM_API_KEY": "offline-test-key-no-network",
        "LLM_MODEL": "offline-test-model",
        "LLM_BASE_URL": "https://unused.provider.invalid/v1",
    })
    config=AppConfig.model_validate({
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider",
                    "allow_host_bash": False},
    })
    config=settings.build_vendor_app_config(config)
    profile=config.get_model_config(settings.profile_name)
    assert profile is not None
    assert profile.model=="offline-test-model"
    assert profile.use=="langchain_openai:ChatOpenAI"
    assert "api_key" not in profile.model_dump()
    assert "offline-test-key-no-network" not in str(profile.model_dump())
    # Provider-specific key exists only during frozen factory construction.
    with vendor_model_key("offline-test-key-no-network"):
        model=create_chat_model(
            name=settings.profile_name,app_config=config,
            thinking_enabled=False,attach_tracing=False,
        )
    assert isinstance(model,BaseChatOpenAI)
    assert model.model_name=="offline-test-model"
    assert "unused.provider.invalid" in str(model.openai_api_base)
    # Note: no .ainvoke(); this only tests exact vendor factory construction.


def test_live_profile_official_base_url_omitted(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "offline-test-key-no-network")
    settings=LiveModelSettings.from_environment({
        "ASWE_LIVE_SMOKE": "1",
        "GITHUB_ACTIONS": "true",
        "LLM_API_KEY": "offline-test-key-no-network",
        "LLM_MODEL": "offline-test-model",
        "LLM_BASE_URL": "",
    })
    config=AppConfig.model_validate({
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider",
                    "allow_host_bash": False},
    })
    config=settings.build_vendor_app_config(config)
    assert "base_url" not in config.models[0].model_dump()
