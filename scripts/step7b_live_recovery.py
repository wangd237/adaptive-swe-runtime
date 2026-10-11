"""Paid Step 7B live-model recovery acceptance with one controlled fault.

Only the FIRST model turn is harness-injected to make an unauthorized
str_replace call. This runs through the ACTUAL native LangGraph ToolNode and
ControlledSWEWorkspace (no write). Every subsequent action is decided by the
real external LLM, without mocked tool results, reference patch, or scripted
read/repair. This is a recovery benchmark, not a natural Issue solve rate.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, PrivateAttr

from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend
from aswe.integrations.deerflow.developer_entry import execute_swe_task
from aswe.integrations.deerflow.live_smoke_config import LiveModelSettings
from aswe.integrations.deerflow.native_execution import NativeSubagentAssembler
from aswe.llm_config import load_llm_settings, vendor_model_key
from scripts.live_adaptive_acceptance import (
    AcceptanceFailed, python_image_digest, require,
)

TEST_PATH = "tests/test_answer.py"
CHECK = ("python", "-B", "-m", "unittest", "tests.test_answer", "-q")
TASK = (
    "Repair the existing bug in calc.py: answer() returns 0 instead of 42. "
    "The independent tests/test_answer.py checks for 42. A preceding tool "
    "operation may have failed; inspect the exact tool feedback, read the "
    "current file via read_file to satisfy the Runtime precondition, make "
    "the correct production change, and verify it. Do not modify tests, "
    "Git metadata, or configuration."
)
SOURCE = "def answer():\n    return 0\n"
TEST = (
    "import unittest\nfrom calc import answer\n"
    "class AnswerTest(unittest.TestCase):\n"
    "    def test_answer(self): self.assertEqual(answer(), 42)\n"
)


class InjectFirstWriteThenRealLLM(BaseChatModel):
    """One replayable injected tool request, then the genuine bound model."""

    provider: Any = Field(exclude=True, repr=False)
    fault_issued: bool = False
    live_model_calls: int = 0
    observed_denial: bool = False
    _bound_provider: Any = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "aswe-one-shot-real-llm-recovery"

    def bind_tools(self, tools, **kwargs):
        self._bound_provider = self.provider.bind_tools(tools, **kwargs)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("ASWE_LIVE_RECOVERY_ASYNC_REQUIRED")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.fault_issued:
            self.fault_issued = True
            # First ask the *real* provider for its initial assistant turn.
            # Preserve its reasoning metadata when replacing only the first
            # tool request. Thinking-mode providers reject a fabricated
            # assistant turn that does not return required reasoning_content.
            self.live_model_calls += 1
            genuine_first = await self._bound_provider.ainvoke(messages)
            # Fresh AIMessage follows the same LangGraph contract as the
            # tested deterministic first-turn injection. Only carry the
            # upstream protocol reasoning field, not the real call's ID or
            # any incompatible original tool_calls arguments.
            protocol_metadata = {
                k: v for k, v in
                dict(getattr(genuine_first, "additional_kwargs", {}) or {}).items()
                if k == "reasoning_content"
            }
            injected = AIMessage(
                content="",
                additional_kwargs=protocol_metadata,
                tool_calls=[{
                    "name": "str_replace",
                    "args": {"path": "calc.py", "old_str": "return 0",
                             "new_str": "return 42"},
                    "id": "aswe-step7b-injected-write-001",
                }],
            )
            return ChatResult(generations=[ChatGeneration(message=injected)])
        self.observed_denial = self.observed_denial or any(
            getattr(msg, "status", None) == "error"
            and "SWE_READ_BEFORE_WRITE_REQUIRED" in str(getattr(msg, "content", ""))
            for msg in messages
        )
        if not self.observed_denial:
            raise RuntimeError("ASWE_LIVE_RECOVERY_DENIAL_NOT_DELIVERED")
        self.live_model_calls += 1
        message = await self._bound_provider.ainvoke(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, timeout=30)


def seed(repo: Path) -> None:
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "ASWE Recovery")
    git(repo, "config", "user.email", "aswe-recovery@example.invalid")
    (repo / "calc.py").write_text(SOURCE)
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    (repo / "tests").mkdir()
    (repo / "tests/__init__.py").write_text("")
    (repo / TEST_PATH).write_text(TEST)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "Independent failing recovery fixture")


async def execute(summary: dict) -> None:
    require(
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("ASWE_LIVE_SMOKE") == "1"
        and os.environ.get("ASWE_STEP7B_RECOVERY_ONCE") == "1",
        "STEP7B_RECOVERY_NOT_AUTHORIZED",
    )
    LiveModelSettings.from_environment()
    llm = load_llm_settings()
    image = python_image_digest()
    vendor_factory = NativeSubagentAssembler.from_deerflow().seams.create_chat_model
    models: list[InjectFirstWriteThenRealLLM] = []

    def model_factory(**kwargs):
        with vendor_model_key(llm.api_key):
            provider = vendor_factory(**kwargs)
        instance = InjectFirstWriteThenRealLLM(provider=provider)
        models.append(instance)
        return instance

    with tempfile.TemporaryDirectory(prefix="aswe-step7b-recovery-") as td:
        root = Path(td)
        repository = root / "repo"
        seed(repository)
        baseline = await DockerCommandBackend(
            workspace_root=repository, image=image).run(
                " ".join(CHECK), timeout=45, max_output=900)
        require(baseline.exit_code not in (None, 0) and not baseline.timed_out,
                "RECOVERY_BASELINE_NOT_FAILING")
        runtime = root / "runtime"
        path, report, trace = await asyncio.wait_for(execute_swe_task(
            repository=repository, task=TASK, runtime_dir=runtime,
            check_argv=CHECK, image=image, model_factory=model_factory,
        ), timeout=420)
        events = [json.loads(line) for line in trace.read_text().splitlines() if line]
        tools = [e["payload"] for e in events
                 if e["event_type"] == "tool.call.finished"]
        # The first request is intentionally a hosted fault; after this
        # controlled injection, only provider model turns select actions.
        denied = [i for i, event in enumerate(tools)
                  if event.get("tool_name") == "str_replace"
                  and event.get("status") == "denied"
                  and event.get("failure_code") == "SWE_READ_BEFORE_WRITE_REQUIRED"]
        reads = [i for i, event in enumerate(tools)
                 if event.get("tool_name") == "read_file"
                 and event.get("status") == "completed"]
        successful_edits = [i for i, event in enumerate(tools)
                            if event.get("tool_name") == "str_replace"
                            and event.get("status") == "completed"]
        final = path.parent / "workspace"
        summary.update(
            injected_first_tool_call=True,
            genuine_llm_calls=sum(m.live_model_calls for m in models),
            model_observed_denial=any(m.observed_denial for m in models),
            denial_count=len(denied),
            successful_read_count=len(reads),
            successful_edit_count=len(successful_edits),
            recoverable_sequence=bool(denied and any(i > denied[0] for i in reads)
                and any(i > min((j for j in reads if j > denied[0]), default=10**10)
                        for i in successful_edits)),
            native_status=report.native_status,
            native_stop_reason=report.native_stop_reason,
            canonical_status=report.verification_status,
            verified_returncode=report.verified_returncode,
            changed_files=list(report.changed_files),
            source_fixed=(final / "calc.py").read_text() != SOURCE,
            test_unchanged=((final / TEST_PATH).read_text() == TEST),
            native_model_turn_events=Counter(
                e["event_type"] for e in events)["model.turn.finished"],
        )
        require(denied and tools[0].get("failure_code") == "SWE_READ_BEFORE_WRITE_REQUIRED",
                "REAL_NATIVE_TOOL_REJECTION_MISSING")
        require(summary["recoverable_sequence"], "REAL_RECOVERY_SEQUENCE_MISSING")
        require(summary["model_observed_denial"] and summary["genuine_llm_calls"] >= 1,
                "REAL_LLM_RECOVERY_NOT_PROVEN")
        require(report.native_status == "completed"
                and report.native_stop_reason is None
                and report.verification_status == "passed",
                "RECOVERY_FINAL_VERIFICATION_FAILED")
        require(summary["source_fixed"] and summary["test_unchanged"],
                "RECOVERY_PATCH_INTEGRITY_FAILED")


def persist(summary: dict) -> None:
    path = Path(os.environ["ASWE_STEP7B_RECOVERY_REPORT_PATH"]).resolve()
    require(path.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve()),
            "RECOVERY_REPORT_PATH_FORBIDDEN")
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(
                "## Step 7B controlled first-write rejection, real LLM recovery\n\n"
                f"Outcome: {summary.get('outcome', 'unknown')}\n\n"
                f"Failure: {summary.get('failure_code', 'none')}\n\n"
                f"Genuine model calls: {summary.get('genuine_llm_calls', 0)}\n\n"
                f"Recovery sequence: {summary.get('recoverable_sequence', False)}\n"
            )


def main() -> int:
    summary = {
        "case": "controlled_first_native_write_then_unscripted_real_model",
        "first_tool_call_injected": True,
        "subsequent_model_mocked": False,
        "outcome": "not_started",
    }
    try:
        asyncio.run(execute(summary))
        summary["outcome"] = "passed"
        status = 0
    except Exception as exc:
        summary["outcome"] = "failed"
        summary["failure_code"] = (
            exc.args[0] if isinstance(exc, AcceptanceFailed)
            else type(exc).__name__)
        status = 1
    persist(summary)
    print("STEP7B_RECOVERY_RESULT=" + summary["outcome"])
    print("STEP7B_RECOVERY_FAILURE=" + str(summary.get("failure_code", "none")))
    return status


if __name__ == "__main__":
    sys.exit(main())
