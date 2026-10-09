"""Live precommit provider revalidation; mismatch fails without allocating attempt."""
from aswe.core.fingerprint import fingerprint
from aswe.capabilities.effects import trusted_effect,ToolEffect,access_for
from aswe.providers.policy import NodeExecutionPolicy,OperatorSurface,AdmissionError

class LivePreflightError(AdmissionError):pass

def revalidate_live(*,policy,planning,live,operator):
    if (policy.planning_inventory_fingerprint!=planning.fingerprint
            or policy.provider_id!=operator.provider_id):
        raise LivePreflightError("PREPARED_POLICY_IDENTITY_MISMATCH")
    drift=live.fingerprint!=planning.fingerprint
    allowed=set(operator.allowed_tools) if operator.allowed_tools is not None else set(policy.allowed_business_tools)
    narrowed=tuple(k for k in policy.allowed_business_tools if k in allowed and k not in operator.denied_tools)
    if not set(policy.required_business_tools).issubset(narrowed):
        raise LivePreflightError("BACKEND_PREFLIGHT_STALE")
    for contract_id in policy.required_business_tools:
        old=planning.candidate_tools.get(contract_id)
        current=live.candidate_tools.get(contract_id)
        if old is None or current is None:
            raise LivePreflightError("BACKEND_PREFLIGHT_STALE")
        if (
            old.implementation_id,old.resolved_exposed_name,old.delivery,
        )!=(current.implementation_id,current.resolved_exposed_name,current.delivery):
            raise LivePreflightError("PROVIDER_TOOL_IDENTITY_MISMATCH")
    infos=tuple(live.candidate_tools.get(k) for k in narrowed)
    if any(t is None or trusted_effect(t) in (ToolEffect.UNKNOWN,ToolEffect.EXTERNAL_SIDE_EFFECT) for t in infos):
        raise LivePreflightError("BACKEND_PREFLIGHT_STALE")
    if (policy.model_name not in live.configured_model_names
            or policy.backend_agent_type not in live.candidate_agent_types
            or not set(policy.required_sandbox_features).issubset(live.sandbox_features)):
        raise LivePreflightError("BACKEND_PREFLIGHT_STALE")
    if operator.auth_enabled and (
        not set(policy.required_business_tools).issubset(operator.authorized_tools)
        or policy.model_name not in operator.authorized_models):
        raise LivePreflightError("PROVIDER_AUTHORIZATION_DENIED")
    if (policy.workspace_access.value=="read"
            and access_for((),infos).value!="read"):
        raise LivePreflightError("BACKEND_PREFLIGHT_STALE")
    if (set(policy.required_infrastructure_tools).intersection(operator.denied_tools)
            or operator.allowed_tools is not None
            and not set(policy.required_infrastructure_tools).issubset(operator.allowed_tools)):
        raise LivePreflightError("REQUIRED_INFRASTRUCTURE_TOOL_DENIED")
    if operator.max_turns<1 or operator.timeout_seconds<=0:
        raise LivePreflightError("INVALID_LIVE_CEILING")
    effective=fingerprint((
        policy.fingerprint,live.fingerprint,narrowed,
        min(policy.max_turns,operator.max_turns),
        min(policy.timeout_seconds,operator.timeout_seconds),
    ))
    return effective,("BACKEND_DRIFT_OBSERVED",) if drift else (),narrowed

class LivePreflightBackend:
    """FakeBackend-compatible adapter; execute only a pinned prepared binding."""
    def __init__(self,backend,*,policy,planning_inventory,live_inventory,live_operator):
        self.backend=backend
        self.policy=policy
        self.planning=planning_inventory
        self.live_inventory=live_inventory
        self.live_operator=live_operator
        self.prepared={}

    async def prepare_node(self,node):
        if (node.id!=self.policy.node_id or node.provider_id!=self.policy.provider_id
            or node.workspace_access!=self.policy.workspace_access):
            raise LivePreflightError("PREPARATION_NODE_POLICY_MISMATCH")
        live=self.live_inventory()
        operator=self.live_operator()
        effective,diagnostics,allowed=revalidate_live(
            policy=self.policy,planning=self.planning,live=live,operator=operator)
        # Original backend owns the opaque pinned resources.
        raw=await self.backend.prepare_node(node)
        prep=raw.model_copy(update={
            "compiled_policy_fingerprint":self.policy.fingerprint,
            "planning_inventory_fingerprint":self.planning.fingerprint,
            "live_inventory_fingerprint":live.fingerprint,
            "effective_policy_fingerprint":effective,
            "drift_observed":live.fingerprint!=self.planning.fingerprint,
            "drift_diagnostics":diagnostics})
        self.prepared[prep.preparation_id]=(raw,prep,live.fingerprint,allowed)
        return prep

    async def execute_prepared(self,preparation,invocation):
        entry=self.prepared.pop(preparation.preparation_id,None)
        if entry is None or entry[1]!=preparation or invocation.node_id!=self.policy.node_id:
            raise LivePreflightError("PREPARED_EXECUTION_BINDING_MISMATCH")
        # No second inventory lookup. Underlying provider reuses prepared
        # resources from the same execution snapshot.
        return await self.backend.execute_prepared(entry[0],invocation)

    async def cancel_node(self,execution_id):
        return await self.backend.cancel_node(execution_id)
