"""5F-D manually opted-in REAL LLM coding smoke.

This test deliberately has no pytest auto-run path. It is only eligible for
the manual Actions workflow, never regular push/PR CI or local pytest.
It calls a paid external model using the frozen DeerFlow create_chat_model;
the installed vendor graph, 5D tool guard, Docker execution and canonical
Runtime test are real. This integration fixture still provides a *test-only*
5C preparation source and does not attest production 5C inventory/Authz.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess

import pytest

from aswe.llm_config import load_llm_settings, vendor_model_key
from aswe.integrations.deerflow.live_smoke_config import (
    LiveModelSettings, LiveSmokeConfigError,
)
from aswe.integrations.deerflow.native_execution import (
    NativeSubagentAssembler, NativeDeerFlowExecutionBackend,
)
from aswe.integrations.deerflow.mvp_task import MVPTaskRunner
from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend
from aswe.runtime.canonical_verifier import make_command_policy
from tests.integration.test_deerflow_mvp_e2e_step5fcb import physical_binding_store
from tests.unit.test_deerflow_controlled_swe_step5fc import policy as coding_policy
from tests.unit.test_deerflow_mvp_task_step5fcb import prepared_mvp

# Importing the module alone must never read secrets or call a provider.
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("ASWE_LIVE_SMOKE") != "1"
        or os.environ.get("GITHUB_ACTIONS") != "true",
        reason="5F-D is manual Actions opt-in only",
    ),
]


def _python_image_digest() -> str:
    # The workflow pre-pulls this image before accepting paid model calls.
    proc = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}",
         "python:3.12-slim"],
        check=True, capture_output=True, text=True, timeout=15,
    )
    image = proc.stdout.strip()
    if not image.startswith("python@sha256:"):
        raise RuntimeError("LIVE_SWE_DOCKER_DIGEST_UNAVAILABLE")
    return image


def _report_summary(report, *, tool_calls: int, failed_calls: int) -> None:
    # Never print/configure the key, endpoint, model ID or raw provider error.
    document = report.to_dict()
    path = os.environ.get("ASWE_LIVE_REPORT_PATH")
    if path:
        destination = Path(path).resolve()
        runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
        if not destination.is_relative_to(runner_temp):
            raise RuntimeError("LIVE_REPORT_PATH_OUTSIDE_RUNNER_TEMP")
        destination.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## 5F-D: Real Model SWE Smoke",
            "",
            "| Check | Observed |",
            "|---|---|",
            f"| Native terminal | `{report.native_status}` |",
            f"| Runtime canonical unittest | `{report.verification_status}` |",
            f"| Actual modified paths | `{', '.join(report.changed_files) or 'none'}` |",
            f"| Executed tool calls | `{tool_calls}` |",
            f"| Noncompleted tool calls | `{failed_calls}` |",
            f"| Docker dynamic command count | `{report.agent_dynamic_command_count}` |",
            f"| Workspace | `{report.workspace_status}` |",
            f"| Core acceptance | `{report.delivery_status}` |",
            "",
            "Strict Scheduler quarantine is expected: production quiescence "
            "is deferred, not fabricated.",
        ]
        with open(summary_path, "a", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")


async def test_live_model_autonomously_fixes_python_bug(prepared_mvp):
    settings = LiveModelSettings.from_environment()
    credentials = load_llm_settings()

    repo, core, store, verifier, canonical_policy = prepared_mvp
    root = Path(repo.repository_root)
    baseline_tests = (root / "tests" / "test_calc.py").read_bytes()

    # No proposed command sequence or repair patch is injected into the model.
    # The model must independently read, reason, call tools, and correct code.
    compiled_policy = coding_policy(tools=("read_file", "str_replace", "bash"))
    image = _python_image_digest()
    # The model's token lives in the host process. Never import Agent-written
    # calc.py in a host subprocess with inherited credentials. Both dynamic
    # Agent Bash and the independent canonical regression run inside Docker,
    # without any model environment/secret mounts.
    canonical_policy = make_command_policy(
        "mvp-python-regression-container",
        ("python", "-B", "-m", "unittest", "discover", "-s", "tests", "-q"),
        timeout_seconds=45,
    )
    isolated_verifier = DockerCommandBackend(
        workspace_root=root, image=image,
    )
    binding_store = physical_binding_store(
        core=core, repository=repo, image=image,
        compiled_policy=compiled_policy,
    )
    resources = binding_store.preparation_backend.resources
    resources.app_config = settings.build_vendor_app_config(resources.app_config)
    resources.model_name = settings.profile_name
    resources.subagent_config.system_prompt = (
        "You are a software-engineering repair agent in an isolated worktree. "
        "You may use the provided read_file, str_replace and bash tools. "
        "First inspect tests/test_calc.py and calc.py. Determine the bug from "
        "the test, without assuming a fix. Modify ONLY calc.py using "
        "str_replace after reading it. Do not modify tests or .git. "
        "The bash tool runs inside a network-disabled Python 3.12 Docker "
        "container. To test, use: "
        "python -B -m unittest discover -s tests -q. "
        "When Bash returns an exit_code that is not zero, inspect and repair "
        "instead of claiming success. Finish only after a passing test."
    )
    resources.subagent_config.max_turns = 30
    resources.subagent_config.timeout_seconds = 250
    resources.effective_max_turns = 50
    resources.effective_timeout_seconds = 250

    # Source-pinned vendor model factory, not a mock or direct SDK override.
    assembler = NativeSubagentAssembler.from_deerflow()
    vendor_factory = assembler.seams.create_chat_model
    def configured_vendor_factory(**kwargs):
        with vendor_model_key(credentials.api_key):
            return vendor_factory(**kwargs)
    assembler = NativeSubagentAssembler(replace(
        assembler.seams, create_chat_model=configured_vendor_factory))
    backend = NativeDeerFlowExecutionBackend(
        binding_store=binding_store, assembler=assembler,
        task_renderer=lambda _: (
            "Fix the broken behavior in this Python repository. "
            "Run the regression tests. The required behavior is encoded in "
            "tests/test_calc.py. Inspect the repository and find a minimal "
            "fix in calc.py; do not edit tests or configuration."
        ),
        enable_native_execution=True,
        evidence_collector=None,  # full physical quiescence deferred
    )
    runner = MVPTaskRunner(
        scheduler=core, backend=backend, repository=repo,
        verifier=verifier, policy=canonical_policy,
        isolated_canonical_container=isolated_verifier,
    )

    # The normal Native/Subagent timeout applies; this is just an outer
    # budget against a hung provider, not a quiescence assertion.
    report = await asyncio.wait_for(runner.run_node("writer"), timeout=300)

    binding = getattr(binding_store, "_captured_for_e2e", None)
    receipts = binding.guard.receipt_snapshot() if binding is not None else ()
    failed_tools = sum(x["status"] != "completed" for x in receipts)
    _report_summary(report, tool_calls=len(receipts), failed_calls=failed_tools)

    assert report.native_status == "completed", "LIVE_NATIVE_EXECUTION_INCOMPLETE"
    assert report.verification_status == "passed", "LIVE_CANONICAL_REGRESSION_NOT_PASSED"
    assert report.verified_returncode == 0, "LIVE_CANONICAL_NONZERO"
    assert (root / "tests" / "test_calc.py").read_bytes() == baseline_tests, (
        "LIVE_REGRESSION_TESTS_MUTATED"
    )
    assert report.changed_files == ("calc.py",), "LIVE_UNEXPECTED_WORKSPACE_MUTATION"
    assert report.canonical_receipt_ref is not None
    assert store.get(report.canonical_receipt_ref)["status"] == "holds"
    assert binding is not None and binding.guard.closed
    assert any(x["tool_name"] == "read_file" for x in receipts), (
        "LIVE_NO_CODE_INSPECTION"
    )
    assert any(x["tool_name"] == "str_replace" for x in receipts), (
        "LIVE_NO_TOOL_MEDIATED_CODE_EDIT"
    )
    assert report.agent_dynamic_command_count >= 1, (
        "LIVE_NO_ISOLATED_BASH_EXECUTION"
    )
    assert report.workspace_status == "quarantined"
    assert report.delivery_status == "tests_passed_scheduler_quarantined"
