"""Step 7D: compact observations and truthful budget telemetry.

No model is mocked into a successful native terminal; all summaries are
diagnostic. The physical pinned-Docker tail test is the integration witness.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aswe.integrations.deerflow.controlled_swe import (
    ControlledSWEWorkspace, ShellOutcome, SWEExecutionDenied,
)
from aswe.trace.reliability import summarize_execution_trace
from tests.unit.test_deerflow_controlled_swe_step5fc import env
from tests.unit.test_node_workspace_delta import repository as repository_fixture


@pytest.mark.asyncio
async def test_coder_bash_uses_smaller_output_budget_without_truncating_file_reads(
    repository_fixture,
):
    root=Path(repository_fixture.repository_root)
    (root/"big.py").write_text("A"*8800)
    workspace,sandbox=env(repository_fixture)
    assert len(await workspace.read_file(path="big.py"))==8800
    output=await workspace.bash(command="python -m unittest -q")
    assert sandbox.commands[0][2]==4000
    assert workspace.max_output_chars==12000
    assert "output_truncated=False" in output


@pytest.mark.asyncio
async def test_invalid_command_budget_refused_before_tool_execution(repository_fixture):
    workspace,sandbox=env(repository_fixture)
    with pytest.raises(SWEExecutionDenied,match="SWE_COMMAND_OUTPUT_BUDGET_INVALID"):
        ControlledSWEWorkspace(
            invocation=workspace.invocation,policy=workspace.policy,
            root=workspace.root,command_backend=sandbox,
            max_command_output_chars=12001,
        )
    assert sandbox.commands==[]


def ev(i,event,payload):
    return {
        "task_id":"task","seq":i,"event_type":event,
        "timestamp":f"2026-10-12T00:00:{i:02d}+00:00",
        "payload":payload,
    }


def test_model_growth_and_tool_mix_without_raw_context_or_false_token_estimates():
    secret="my_private_file_and_key-do-not-export"
    events=[
        ev(1,"workflow.started",{"prompt":secret}),
        ev(2,"model.turn.finished",{"usage":{
            "input_tokens":500,"output_tokens":15,"total_tokens":515,
            "raw_prompt":secret,
        }}),
        ev(3,"tool.call.finished",{
            "tool_name":"read_file","status":"completed",
            "arguments":secret,"tool_call_id":"tool1","execution_id":"e",
        }),
        ev(4,"model.turn.finished",{"usage":{
            "input_tokens":1900,"output_tokens":20,"total_tokens":1920,
        }}),
        ev(5,"tool.call.finished",{
            "tool_name":secret,"status":"completed",
            "tool_output":secret,"tool_call_id":"tool2","execution_id":"e",
        }),
        ev(6,"model.turn.finished",{"usage":{
            "input_tokens":False,"output_tokens":-1,"total_tokens":"bad",
        }}),
        ev(7,"workflow.stage.finished",{"native_status":"completed"}),
        ev(8,"workflow.finished",{"verification_status":"passed"}),
    ]
    result=summarize_execution_trace(events,round_reports=[{
        "native_status":"completed","verification_status":"passed",
    }])
    assert result["input_tokens_per_turn_tail"]==[500,1900]
    assert result["output_tokens_per_turn_tail"]==[15,20]
    assert result["first_last_input_tokens"]==[500,1900]
    assert result["peak_input_tokens_per_turn"]==1900
    assert result["tool_name_counts"]=={"other":1,"read_file":1}
    assert result["token_reported_turns"]==2
    assert result["token_usage_reported"]["total_tokens"]==2435
    assert secret not in json.dumps(result)


def test_no_provider_tokens_are_not_guessed():
    result=summarize_execution_trace([
        ev(1,"model.turn.finished",{"content":"raw secret"}),
        ev(2,"mvp.task.finished",{
            "native_status":"completed","verification_status":"passed",
        }),
    ])
    assert result["first_last_input_tokens"]==[]
    assert result["input_tokens_per_turn_tail"]==[]
    assert result["peak_input_tokens_per_turn"] is None
    assert result["token_usage_reported"]=={}
