"""Single .env-based LLM config and provider adapter regression tests."""
from pathlib import Path
import os

import pytest

from aswe.llm_config import load_llm_settings, vendor_model_key


def test_reads_llm_keys_from_current_directory_dotenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        "LLM_API_KEY=test-secret-do-not-print\n"
        "LLM_MODEL=provider/test-model\n"
        "LLM_BASE_URL=https://llm.provider.example/v1\n"
    )
    config = load_llm_settings()
    assert config.api_key == "test-secret-do-not-print"
    assert config.model == "provider/test-model"
    assert config.base_url == "https://llm.provider.example/v1"
    assert "test-secret-do-not-print" not in repr(config)
    assert "test-secret-do-not-print" not in str(config)
    assert os.environ.get("OPENAI_API_KEY") != "test-secret-do-not-print"


def test_environment_override_is_used_for_actions(monkeypatch, tmp_path):
    dotenv = tmp_path / "config.env"
    dotenv.write_text("LLM_API_KEY=file-key\nLLM_MODEL=file-model\n"
                      "LLM_BASE_URL=https://file.example/v1\n")
    config = load_llm_settings(env_file=dotenv, environ={
        "LLM_API_KEY": "actions-key", "LLM_MODEL": "actions-model"})
    assert config.api_key == "actions-key"
    assert config.model == "actions-model"
    assert config.base_url == "https://file.example/v1"


def test_missing_required_fields_never_echo_secret(tmp_path):
    dot = tmp_path / ".env"
    dot.write_text("LLM_API_KEY=test-secret\n")
    with pytest.raises(ValueError, match="LLM_MODEL_MISSING_OR_INVALID") as error:
        load_llm_settings(env_file=dot, environ={})
    assert "test-secret" not in str(error.value)
    with pytest.raises(ValueError, match="LLM_ENV_FILE_NOT_FOUND"):
        load_llm_settings(env_file=tmp_path / "absent", environ={})


@pytest.mark.parametrize("bad_url", ["file:///etc/passwd", "http://x/v1?token=abc",
                                     "https://user:password@host/v1"])
def test_rejects_credentials_and_invalid_url(tmp_path, bad_url):
    config = tmp_path / ".env"
    config.write_text(f"LLM_API_KEY=x\nLLM_MODEL=test\nLLM_BASE_URL={bad_url}\n")
    with pytest.raises(ValueError, match="LLM_BASE_URL_INVALID"):
        load_llm_settings(env_file=config, environ={})


def test_vendor_key_is_internal_and_scoped(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "old-provider-key")
    with vendor_model_key("llm-key"):
        assert os.environ["OPENAI_API_KEY"] == "llm-key"
    assert os.environ["OPENAI_API_KEY"] == "old-provider-key"
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(RuntimeError, match="synthetic"):
        with vendor_model_key("llm-key"):
            raise RuntimeError("synthetic")
    assert "OPENAI_API_KEY" not in os.environ
