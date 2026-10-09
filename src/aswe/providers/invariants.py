"""FakeBackend-compatible physical Git post-node semantic READ invariant.

A Verifier may require an exclusive WRITE lock for bash, but that does not
grant it *business* repository mutation authority. Only real pinned physical
Git before/after state establishes source mutation, never a model statement.
"""
from __future__ import annotations
from aswe.core.contracts.backend import BackendTerminalStatus
from aswe.repository import capture_repository_state

class PostNodeGitInvariantBackend:
    def __init__(self,backend,repository_binding,*,semantic_read_only:bool):
        self.backend=backend
        self.binding=repository_binding
        self.semantic_read_only=semantic_read_only

    async def prepare_node(self,node):
        return await self.backend.prepare_node(node)

    async def cancel_node(self,execution_id):
        return await self.backend.cancel_node(execution_id)

    async def execute_prepared(self,preparation,invocation):
        before=capture_repository_state(self.binding) if self.semantic_read_only else None
        result=await self.backend.execute_prepared(preparation,invocation)
        if self.semantic_read_only and result.quiescent:
            after=capture_repository_state(self.binding)
            if after.fingerprint!=before.fingerprint:
                mutation_type=type(result.mutation_evidence)
                return result.model_copy(update={
                    "terminal_status":BackendTerminalStatus.FAILED,
                    "mutation_evidence":mutation_type("observed"),
                    "failure_kind":"POST_NODE_INVARIANT_GIT_MUTATION",
                })
        return result
