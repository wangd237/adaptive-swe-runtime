from pydantic import BaseModel, ConfigDict, Field, model_validator

class RuntimeBudgetConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    max_work_items: int = Field(default=8, ge=1)
    max_inflight_node_executions: int = Field(default=3, ge=1)
    max_parallel_read_nodes: int = Field(default=3, ge=1)
    planning_attempts: int = Field(default=2, ge=1)
    execution_replans: int = Field(default=1, ge=0)
    max_retries_per_node: int = Field(default=1, ge=0)
    max_repairs_per_write: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def _parallelism_must_fit_backend_capacity(self) -> "RuntimeBudgetConfig":
        if self.max_parallel_read_nodes > self.max_inflight_node_executions:
            raise ValueError("max_parallel_read_nodes cannot exceed max_inflight_node_executions")
        return self
