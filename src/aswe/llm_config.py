"""Single user-facing LLM configuration: LLM_* from .env or process env.

The external model provider uses an OpenAI-compatible SDK convention
internally, but no provider-specific key is required in the user's .env.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
from threading import RLock
from typing import Iterator, Mapping
from urllib.parse import urlsplit

from dotenv import dotenv_values


@dataclass(frozen=True)
class LLMSettings:
    api_key: str = field(repr=False)
    model: str
    base_url: str | None = None


def load_llm_settings(*, env_file: Path | None = None,
                      environ: Mapping[str, str] | None = None) -> LLMSettings:
    """Read only LLM_* settings from the cwd .env, overridden by process env.

    An absent implicit .env is fine for GitHub Actions; a missing explicitly
    selected file is an error. Neither exception messages nor repr contain keys.
    """
    path = Path(env_file).expanduser() if env_file is not None else Path.cwd() / ".env"
    if env_file is not None and not path.is_file():
        raise ValueError("LLM_ENV_FILE_NOT_FOUND")
    values = dotenv_values(path, interpolate=False) if path.is_file() else {}
    source = environ if environ is not None else os.environ

    def read(key: str) -> str:
        value = source.get(key)
        if value is None:
            value = values.get(key)
        return value.strip() if isinstance(value, str) else ""

    key = read("LLM_API_KEY")
    model = read("LLM_MODEL")
    url = read("LLM_BASE_URL")
    if not key or any(c in key for c in "\r\n"):
        raise ValueError("LLM_API_KEY_MISSING_OR_INVALID")
    if not model or len(model) > 160 or any(c in model for c in "\r\n"):
        raise ValueError("LLM_MODEL_MISSING_OR_INVALID")
    if url:
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme in ("http", "https")
                     and bool(parsed.hostname)
                     and not parsed.username and not parsed.password
                     and not parsed.query and not parsed.fragment
                     and len(url) <= 1024
                     and not any(c.isspace() for c in url))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("LLM_BASE_URL_INVALID")
    return LLMSettings(api_key=key, model=model, base_url=url or None)


_VENDOR_KEY_LOCK = RLock()


@contextmanager
def vendor_model_key(api_key: str) -> Iterator[None]:
    """Give the frozen ChatOpenAI factory its expected key during construction.

    The variable is restored immediately; it is not a user configuration key,
    and the secret never enters AppConfig, command arguments or the task trace.
    """
    with _VENDOR_KEY_LOCK:
        name = "OPENAI_API_KEY"  # provider adapter detail only
        previous = os.environ.get(name)
        os.environ[name] = api_key
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
