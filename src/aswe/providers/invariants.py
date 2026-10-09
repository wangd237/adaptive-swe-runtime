"""Real Git-backed Step-4 post-node invariant for business read-only nodes.

The semantic read-only decision is bound to a compiled TaskDAG. Callers
cannot supply a boolean to disable or enable the guard for a given node.
"""
from aswe.core.contracts.backend import BackendTerminalStatus
from aswe.core.contracts.task import TaskDAG,WorkKind
from aswe.repository import capture_repository_state

class PostNodeGitInvariantBackend:
    def __init__(self,backend,repository_binding,*,dag:TaskDAG,node_id:str):
        self.backend=backend
        self.binding=repository_binding
        if not isinstance(dag,TaskDAG):
            raise ValueError("compiled TaskDAG is required")
        nodes={n.id:n for n in dag.nodes}
        if node_id not in nodes:raise ValueError("unknown guarded TaskDAG node")
        self.node=nodes[node_id]
        self.semantic_read_only=self.node.work_kind is not WorkKind.IMPLEMENTATION

    async def prepare_node(self,node):
        if node!=self.node:raise ValueError("guard/Node identity mismatch")
        return await self.backend.prepare_node(node)

    async def cancel_node(self,execution_id):
        return await self.backend.cancel_node(execution_id)

    async def execute_prepared(self,preparation,invocation):
        if invocation.node_id!=self.node.id:
            raise ValueError("guard/Invocation identity mismatch")
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
