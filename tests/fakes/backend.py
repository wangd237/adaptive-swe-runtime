from __future__ import annotations
import asyncio
from collections import deque
from enum import Enum
from pydantic import BaseModel, ConfigDict
from aswe.core.contracts.backend import BackendExecutionPhase, BackendTerminalStatus, NodeExecutionInvocation, NodeExecutionPreparation
from aswe.core.contracts.task import TaskNode
from aswe.core.ids import new_preparation_id, new_safe_id

class MutationEvidence(str,Enum):
    PROVEN_NONE="proven_none"
    OBSERVED="observed"
    UNKNOWN="unknown"

class FakeExecutionScenario(BaseModel):
    model_config=ConfigDict(frozen=True,extra="forbid",arbitrary_types_allowed=True)
    terminal_status: BackendTerminalStatus=BackendTerminalStatus.COMPLETED
    execution_phase: BackendExecutionPhase=BackendExecutionPhase.STARTED
    mutation_evidence: MutationEvidence=MutationEvidence.PROVEN_NONE
    result: str|None="ok"
    error: str|None=None
    quiescent: bool=True
    release_event: asyncio.Event|None=None

class FakeExecutionRecord(BaseModel):
    model_config=ConfigDict(frozen=True,extra="forbid")
    execution_id:str
    node_id:str
    attempt:int
    terminal_status:BackendTerminalStatus
    execution_phase:BackendExecutionPhase
    mutation_evidence:MutationEvidence
    result:str|None
    error:str|None
    quiescent:bool

class FakeExecutionBackend:
    """Deterministic lifecycle harness used before DeerFlow integration."""
    def __init__(self,scenarios:list[FakeExecutionScenario]|None=None)->None:
        self._scenarios=deque(scenarios or [])
        self.preparations:list[NodeExecutionPreparation]=[]
        self.records:list[FakeExecutionRecord]=[]
        self.cancelled_execution_ids:set[str]=set()
        self._cancel_events:dict[str,asyncio.Event]={}
        self._claimed_preparations:set[str]=set()
        self._claimed_executions:set[str]=set()

    def push(self,scenario:FakeExecutionScenario)->None:
        self._scenarios.append(scenario)

    async def prepare_node(self,node:TaskNode)->NodeExecutionPreparation:
        prep=NodeExecutionPreparation(
            preparation_id=new_preparation_id(),
            node_id=node.id,
            provider_id=node.provider_id,
            compiled_policy_fingerprint="fake-policy",
            planning_inventory_fingerprint="fake-inventory-planning",
            live_inventory_fingerprint="fake-inventory-live",
            effective_policy_fingerprint="fake-policy",
            backend_snapshot_id=new_safe_id("fake-snapshot"),
            drift_observed=False,
            drift_diagnostics=(),
        )
        self.preparations.append(prep)
        return prep

    async def execute_prepared(
        self, preparation: NodeExecutionPreparation, invocation: NodeExecutionInvocation
    ) -> FakeExecutionRecord:
        if preparation.node_id != invocation.node_id:
            raise ValueError("preparation/invocation node mismatch")
        if preparation not in self.preparations:
            raise ValueError("preparation identity is not owned by this fake backend")
        if preparation.preparation_id in self._claimed_preparations:
            raise ValueError("preparation has already been used")
        if invocation.execution_id in self._claimed_executions:
            raise ValueError("execution identity has already been used")
        if not self._scenarios:
            raise RuntimeError("no FakeExecutionScenario queued")
        self._claimed_preparations.add(preparation.preparation_id)
        self._claimed_executions.add(invocation.execution_id)
        scenario = self._scenarios.popleft()
        cancel_event = self._cancel_events.setdefault(invocation.execution_id, asyncio.Event())
        try:
            if invocation.execution_id in self.cancelled_execution_ids:
                cancel_event.set()
            if scenario.release_event is not None and not cancel_event.is_set():
                release_wait = asyncio.create_task(scenario.release_event.wait())
                cancel_wait = asyncio.create_task(cancel_event.wait())
                try:
                    await asyncio.wait(
                        {release_wait, cancel_wait}, return_when=asyncio.FIRST_COMPLETED
                    )
                finally:
                    for pending in (release_wait, cancel_wait):
                        if not pending.done():
                            pending.cancel()
                    await asyncio.gather(release_wait, cancel_wait, return_exceptions=True)
            status = (
                BackendTerminalStatus.CANCELLED
                if invocation.execution_id in self.cancelled_execution_ids
                else scenario.terminal_status
            )
            record = FakeExecutionRecord(
                execution_id=invocation.execution_id,
                node_id=invocation.node_id,
                attempt=invocation.attempt,
                terminal_status=status,
                execution_phase=scenario.execution_phase,
                mutation_evidence=scenario.mutation_evidence,
                result=scenario.result,
                error=scenario.error,
                quiescent=scenario.quiescent,
            )
            self.records.append(record)
            return record
        finally:
            # Both normal completion and external asyncio.Task.cancel() clean up.
            # External cancellation propagates; never synthesize quiescence proof.
            self._cancel_events.pop(invocation.execution_id, None)
            self.cancelled_execution_ids.discard(invocation.execution_id)

    async def cancel_node(self, execution_id: str) -> None:
        self.cancelled_execution_ids.add(execution_id)
        event = self._cancel_events.get(execution_id)
        if event is not None:
            event.set()
