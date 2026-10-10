"""5F-D: live smoke is explicit, credentials never enter AppConfig or logs."""
from __future__ import annotations

import pytest

from aswe.integrations.deerflow.live_smoke_config import (
    LiveModelSettings, LiveSmokeConfigError,
)


def baseline(**updates):
    values = {
        "ASWE_LIVE_SMOKE": "1",
        "GITHUB_ACTIONS": "true",
        "SWE_LLM_API_KEY": "test-key-NEVER-SEND",
        "SWE_LLM_MODEL": "provider/example-model-01",
        "SWE_LLM_BASE_URL": "https://example.provider.invalid/v1",
    }
    values.update(updates)
    return values


def test_missing_opt_in_and_runner_denied_before_any_network():
    for updates, error in [
        ({"ASWE_LIVE_SMOKE": ""}, "LIVE_SMOKE_EXPLICIT_OPT_IN_REQUIRED"),
        ({"GITHUB_ACTIONS": ""}, "LIVE_SMOKE_MANUAL_ACTIONS_ONLY"),
        ({"SWE_LLM_API_KEY": ""}, "LIVE_LLM_API_KEY_MISSING"),
        ({"SWE_LLM_API_KEY": "x\ny"}, "LIVE_LLM_API_KEY_MISSING"),
        ({"SWE_LLM_MODEL": ""}, "LIVE_LLM_MODEL_INVALID"),
        ({"SWE_LLM_MODEL": "x;echo hello"}, "LIVE_LLM_MODEL_INVALID"),
    ]:
        with pytest.raises(LiveSmokeConfigError, match=error):
            LiveModelSettings.from_environment(baseline(**updates))


@pytest.mark.parametrize("url", [
    "http://provider.example/v1",
    "https://localhost:443/v1",
    "https://127.0.0.1/v1",
    "https://192.168.10.11/v1",
    "https://provider.example.local/v1",
    "https://user:secret@provider.example/v1",
    "https://provider.example/v1?token=abc",
    "https://provider.example/v1#fragment",
    "https://provider.example:8080/v1",
    "https://provider.example/v1\nextra",
])
def test_unsafe_api_endpoints_denied(url):
    with pytest.raises(LiveSmokeConfigError, match="LIVE_LLM_BASE_URL_INVALID"):
        LiveModelSettings.from_environment(baseline(SWE_LLM_BASE_URL=url))


def test_valid_settings_do_not_retain_raw_api_key_or_expose_it():
    config=LiveModelSettings.from_environment(baseline())
    assert config.model=="provider/example-model-01"
    assert config.base_url=="https://example.provider.invalid/v1"
    assert "test-key-NEVER-SEND" not in repr(config)
    assert "test-key-NEVER-SEND" not in str(config)
    assert not hasattr(config,"api_key")


def test_official_provider_uses_default_url():
    config=LiveModelSettings.from_environment(baseline(SWE_LLM_BASE_URL=""))
    assert config.base_url is None


def test_no_mutation_of_host_environment_during_validation(monkeypatch):
    before=dict(baseline())
    settings=LiveModelSettings.from_environment(before)
    assert before==baseline()
    assert settings.profile_name=="aswe-real-swe-smoke"
