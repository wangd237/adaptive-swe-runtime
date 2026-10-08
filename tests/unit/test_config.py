import pytest
from pydantic import ValidationError
from aswe.core.config import RuntimeBudgetConfig

def test_frozen_budget_defaults_match_design()->None:
    cfg=RuntimeBudgetConfig()
    assert cfg.max_work_items==8
    assert cfg.planning_attempts==2
    assert cfg.execution_replans==1
    assert cfg.max_retries_per_node==1
    assert cfg.max_repairs_per_write==1

def test_read_parallelism_cannot_exceed_backend_capacity()->None:
    with pytest.raises(ValidationError):
        RuntimeBudgetConfig(max_inflight_node_executions=2,max_parallel_read_nodes=3)
