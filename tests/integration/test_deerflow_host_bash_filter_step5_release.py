"""Release Closure P0-01: installed frozen DeerFlow must not leak host Bash.

This is a negative physical integration gate, NOT a substitute for positive
5C -> 5D -> Native Docker authorization. Keep it after the latter is built.
"""
from __future__ import annotations

from deerflow.config.app_config import AppConfig
from deerflow.tools.tools import get_available_tools
from deerflow.tools import tools as tools_module
from deerflow.sandbox.security import is_host_bash_allowed

from aswe.integrations.deerflow.inventory import assert_pinned_deerflow_source


def test_frozen_native_filters_host_bash_even_when_configured():
    assert_pinned_deerflow_source(tools_module.__file__)
    config = AppConfig.model_validate({
        "sandbox": {
            "use": "deerflow.sandbox.local:LocalSandboxProvider",
            "allow_host_bash": False,
        },
        "tools": [
            {"name": "read_file", "group": "file:read",
             "use": "deerflow.sandbox.tools:read_file_tool"},
            {"name": "bash", "group": "bash",
             "use": "deerflow.sandbox.tools:bash_tool"},
        ],
    })
    assert is_host_bash_allowed(config) is False
    observed = get_available_tools(
        app_config=config, include_mcp=False, subagent_enabled=False,
        include_upload_tool=False,
    )
    names = {tool.name for tool in observed}
    assert "read_file" in names
    assert "bash" not in names
