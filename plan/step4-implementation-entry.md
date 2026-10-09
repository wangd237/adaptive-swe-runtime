# Coding Step 4 — Capability / Provider / DAG Compiler Entry Contract

**Status: ENTRY APPROVED AFTER SCOPED STEP-3 PR MERGE.** Step-3-owned P0-A..D have direct negative tests (see `audits/step3-freeze-closure.md`). Wait for accepted PR #5 on main; no DeerFlow calls in this stage.

## Architecture handoff contract

Inputs are ONLY immutable compiler outputs, not original model proposals:

```text
CompiledTaskContract + TaskExecutionAuthority
            +
ValidatedWorkPlan (contract fingerprint verified)
            +
CompiledAcceptancePlan / VerificationCommand
            +
ExecutionContractBinding
            +
Trusted backend inventory + AgentProvider registry
            |
            v
Capability Resolver / ExecutionPlanValidator
            |
            v
NodeResourceRequirements + ProviderAssignment + TeamSpec
            |
            v
ToolEffect / WorkspaceAccess / NodeExecutionPolicy compiler
            |
            v
Deterministic TaskDAG + VerificationRepairBinding
            |
            v
CompiledPlanDescriptor + pinned Runtime execution policy identity
```

Hard rules: Step 4 may not read `WorkPlanProposal`, LLM arbitrary effect hints or unvalidated `TaskContractDraft` for executable authority. Recompute `TaskExecutionAuthority` from CompiledTaskContract. No provider rebinding after mutation. Accepted final policies/commands must be tied to exactly the same `ExecutionContractBinding`.

## Coding sequence (separate from Step 5)

| Step | Source owner | First deterministic evidence / regression |
|---|---|---|
| 4.0 Freeze import boundary + schema ownership | `src/aswe/capabilities/`, `src/aswe/providers/` | Single-source types; replace temporary `planning.validator.ALL_CAPABILITIES` ID set with canonical registry. Core no DeerFlow imports |
| 4.1 Capability / Provider contracts | `capabilities/registry.py`, `providers/contracts.py` | `CapabilitySpec`, `CapabilityAuthorityClass`, `CapabilityBinding`, `AgentProvider`; required_tool identity not derived from mere exposed name |
| 4.2 Provider-neutral inventory / feasibility | `providers/inventory.py`, `providers/resolver.py` | static FakeBackendInventory, frozen fingerprint, required eager tools; POC-28, 28A/B/C contract-level, 39, 41, 50, 53 |
| 4.3 Policy/effect projection | `capabilities/effects.py`, `providers/policy.py` | READ only when every final allowed tool is provably read-only; optional bash not selected → READ, selected or required bash → WRITE; POC-39/40, P3-11 semantic/physical split |
| 4.4 ExecutionPlanValidator + TeamSpec | `providers/validation.py`, `providers/team.py` | required tools, skills, sandbox features, exact acceptance command identity, no provider rebind or semantic work-item merge; POC-27/28/53 and R73 |
| 4.5 Deterministic DAG materializer | `planning/dag.py` | preserve WorkKind vs WorkspaceAccess, phase edges and stable ordinal WRITE serialization; P3-01/02/03/04/06; repeated compilation same structure + TaskDAG fingerprint |
| 4.6 Runtime handoff / descriptor | `planning/descriptor.py`, NodeExecutionPolicy | VerificationRepairBinding, CompiledPlanDescriptor, binding provenance and FakeBackend dispatch; fail on stale policy/WorkspaceRevision/contract drift; P3-11 Git invariant, C10 runtime-observed binding |
| 4.7 Integration audit | `audits/step4-poc-coverage.json` | End-to-end deterministic FakeBackend tests + dual Python CI before Go/No-Go for Step 5 |

## Four mandatory edge cases

1. **Coder WRITE → Tester bash WRITE:** ordering follows IMPLEMENTATION→VERIFICATION, not WorkspaceAccess; cannot open two WRITEs concurrently. Tester is **semantically READ_ONLY** and a business-code Git mutation is an invariant failure (P3-01/P3-11).
2. **Tester bash WRITE → Reviewer READ:** the REVIEW gate follows VERIFIED Tester even though WorkspaceAccess is READ (P3-02).
3. **Explorer READ → Coder WRITE:** explicit or materialized DISCOVERY→IMPLEMENTATION dependency, unless a bounded semantic coalescing rule already kept them in a single work item (P3-03).
4. **Same-phase two WRITEs without edges:** add a reproducible stable planner-ordinal-derived serialization edge; do not call provider ID or last writer a semantic dependency (P3-04).

## Runtime-owned policy and evidence boundaries

- BackendInventory is a trusted **snapshot**, not a permanent live authorization. Live auth/preflight gates must still revalidate at preparation/admission.
- `CapabilitySpec.authority_class` controls business intent; `ToolEffect` / effective Node allowed tools control physical WorkspaceAccess. Unknown implementation ⇒ WRITE or hard preflight failure, never READ.
- Tool implementation identity `config:<ToolConfig.use>` (resolved adapter inventory) is distinct from config label, exposed name and schema hash.
- `BashCommandPolicy` for load-bearing tests must EXACT match the compiled `VerificationCommand`, and Provider sandbox features must include `deerflow_tests_passed_evidence` before model/tool execution.
- Runtime observed `ExecutionContractBinding` cannot be an Agent-provided string. A pinned dispatch/admission source must supply it to the terminal evaluator.
- Do not implement actual DeerFlow models, extensions, tool-surface middleware or Bash evidence collection in Step 4. Those remain Step 5 and its explicit PoC Go/No-Go.

## Step 4 release gate

Pass P3-01/02/03/04/11 plus applicable P0-5 contract/static FakeBackend tests. Prove deterministic TaskDAG and rejection of provider/tool/fingerprint drift with adversarial fixtures. Preserve Step-2 cancellation, quiescence and business-mutation invariants. Neither a demo nor a successful LLM response closes the gate.

**Branching decision:** create `coding/step4-capability-provider-dag` from accepted `main` only after PR #5's scoped Step-3 baseline is merged. Until then, Step-4 work must be an isolated spike without pretending it is authoritative `main` implementation.
