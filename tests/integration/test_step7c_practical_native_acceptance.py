"""Physical native Step 7C-C execution: real pinned DeerFlow + real Docker.

The model is deliberately offline/deterministic; the graph, ToolNode,
ToolCallGuard, worktree, Docker canonical verification, evidence store and
Scheduler acceptance are real. This is NOT a live paid LLM benchmark.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from aswe.integrations.deerflow.developer_entry import execute_swe_task


class OfflineCodingModel(BaseChatModel):
    turns: int = 0

    @property
    def _llm_type(self):
        return "aswe-step7c-practical-offline"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.turns += 1
        if self.turns == 1:
            msg = AIMessage(content="", tool_calls=[{
                "name": "read_file", "args": {"path": "calc.py"},
                "id": "physical-step7c-read",
            }])
        elif self.turns == 2:
            msg = AIMessage(content="", tool_calls=[{
                "name": "str_replace",
                "args": {
                    "path": "calc.py", "old_str": "return 1",
                    "new_str": "return 42",
                },
                "id": "physical-step7c-write",
            }])
        else:
            msg = AIMessage(content="The source change is ready for host verification.")
        return ChatResult(generations=[ChatGeneration(message=msg)])


def git(repo: Path, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, timeout=20,
    )


@pytest.mark.asyncio
async def test_native_coder_actual_scheduler_accepts_sealed_practical_handoff(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("LLM_API_KEY", "offline-only-not-a-real-secret")
    monkeypatch.setenv("LLM_MODEL", "offline-frozen")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    source=tmp_path/"source"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "Practical")
    git(source, "config", "user.email", "practical@example.invalid")
    (source/"calc.py").write_text("def answer():\n    return 1\n")
    (source/".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    (source/"tests").mkdir()
    (source/"tests/__init__.py").write_text("")
    (source/"tests/test_calc.py").write_text(
        "import unittest\nfrom calc import answer\n"
        "class TestCalc(unittest.TestCase):\n"
        "    def test_answer(self): self.assertEqual(answer(),42)\n"
    )
    git(source, "add", "-A")
    git(source, "commit", "-m", "baseline failing fixture")
    image=subprocess.run(
        ["docker","image","inspect","--format",
         "{{index .RepoDigests 0}}","python:3.12-slim"],
        check=True, capture_output=True, text=True, timeout=15,
    ).stdout.strip()
    assert image.startswith("python@sha256:")
    factory_calls = []

    def offline_factory(**kwargs):
        factory_calls.append(kwargs.get("name"))
        return OfflineCodingModel()

    report_path,report,trace_path=await execute_swe_task(
        repository=source,
        task="Fix calc.answer so it returns 42; inspect file first.",
        runtime_dir=tmp_path/"private-runtime",
        check_argv=("python","-B","-m","unittest","tests.test_calc","-q"),
        image=image, model_factory=offline_factory,
        acceptance_profile="practical",
    )
    assert factory_calls
    assert report_path.exists() and trace_path.exists()
    assert report.native_status == "completed"
    assert report.native_stop_reason is None
    assert report.verification_status == "passed"
    assert report.acceptance_profile == "practical"
    assert report.quiescence_proven
    assert report.scheduler_node_status == "succeeded"
    assert not report.scheduler_failed
    assert report.accepted_handoff_fingerprint is not None
    assert report.delivery_status == "tests_passed_practical_handoff"
    assert (source/"calc.py").read_text() == "def answer():\n    return 1\n"
    assert (
        report_path.parent/"workspace"/"calc.py"
    ).read_text() == "def answer():\n    return 42\n"
    trace=[
        json.loads(line) for line in trace_path.read_text().splitlines() if line
    ]
    assert [
        e["payload"]["status"] for e in trace
        if e["event_type"] == "tool.call.finished"
    ] == ["completed", "completed"]
    assert any(
        e["event_type"] == "mvp.task.finished"
        and e["payload"].get("accepted_handoff_fingerprint")
            == report.accepted_handoff_fingerprint
        for e in trace
    )
