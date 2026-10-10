# Step 5F-D — Credentialed Real Model SWE Smoke: Preflight Audit

**Date:** 2026-10-10
**Branch:** `coding/step5-deerflow-adapter`, PR #7 Draft / Open
**Frozen DeerFlow:** `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891`
**Stage disposition:** **Offline adapter / isolation checks GO subject to latest HEAD CI. Actual real-model invocation NOT EXECUTED / pending deliberate manual workflow registration and dispatch.**

## User-supplied GitHub Actions Secrets

- `SWE_LLM_API_KEY` — credential; required.
- `SWE_LLM_MODEL` — selected provider model ID; required.
- `SWE_LLM_BASE_URL` — HTTPS OpenAI-compatible `/v1` endpoint; optional for official OpenAI service.

The secret **values** were not inspected or exposed via GitHub tools. GitHub's repository secrets API is not available through this GitHub integration, and merely adding the values does not prove a real provider call succeeds.

## Implementation

1. `src/aswe/integrations/deerflow/live_smoke_config.py`: `LiveModelSettings.from_environment` rejects absent/manual opt-in, invalid model IDs, missing keys, HTTP, local/private-IP, credential-bearing, nonstandard-port and query/fragment endpoints. No raw key is stored in the settings dataclass or frozen `AppConfig`.
2. Model profile uses frozen `deerflow.config.model_config.ModelConfig`, `langchain_openai:ChatOpenAI`, selected model, optional approved HTTPS `base_url`, bounded timeout and no automatic retries. `OPENAI_API_KEY` is provided to ChatOpenAI via the trusted runner environment, not into model configuration or graph/tool prompts.
3. Pinned upstream `AppConfig` builds `_models_by_name` at validation time. Naively assigning `config.models` does not update this index. `build_vendor_app_config()` **revalidates the entire AppConfig snapshot**, pins one model profile, and confirms lookup matches. The defect was detected by an installed Python 3.12 native factory test, not by an API failure.
4. `tests/integration/test_deerflow_live_swe_step5fd.py` uses an actual frozen vendor `NativeSubagentAssembler.from_deerflow()` without the former scripted `BaseChatModel`. It composes an actual Scheduler claim/commit, real 5D `NodeExecutionBindingStore`, Tools/Guard, no-network Python Docker (model calls `read_file/str_replace/bash`) and separate Runtime canonical regression. The model receives the repair **objective and fixed tests**, but not a preselected edit or scripted tool-call trajectory.
5. `CanonicalVerifier.run_isolated_python()`: the canonical Python regression also executes inside a distinct no-network Docker run, with exact Runtime-owned `CanonicalCommandPolicy.argv` and repository mount, not as a host Python child. This is important because the model can modify `calc.py`; executing untrusted code in host `subprocess.run` while `OPENAI_API_KEY` exists on the parent GitHub runner would expose the credential to tests. Full merged output SHA-256 (not only model preview) is captured before HMAC signing. Host Git pre/post validation, HMAC and independent Receipt validation are retained. This does not claim formal Docker escape resistance or full native quiescence.
6. `.github/workflows/swe-real-model-smoke.yml` has **only `workflow_dispatch`**, with required operator input `authorization=RUN`. No `push` or `pull_request` event can access the real-model Secrets. Workflow privileges limited to `contents: read`; the key only enters the preflight and live-model steps, not Checkout/vendor download or Docker run. The job disables LangSmith/chain tracing. A JSON MVP report and GitHub Step Summary omit raw API Key/endpoint/model profile.
7. Guard tests `tests/unit/test_deerflow_live_workflow_step5fd.py` ensure core/normal PR workflows do not reference Secrets, and manual workflow contains the explicit gate.
8. Offline installed-vendor factory test `tests/integration/test_deerflow_live_model_profile_step5fd.py` instantiates the real `ChatOpenAI` class with a fake key but **never calls `ainvoke`**. Physical Docker canonical secret-canary test `tests/integration/test_deerflow_docker_canonical_step5fd.py` verifies a fake API Key from the parent runner is absent inside the container and tests positive, nonzero, foreign worktree and forbidden command cases. Core units cover invalid URL/model/key and no opt-in.

## Real-model execution gate: NOT RUN

**IMPORTANT:** GitHub only exposes a manually dispatchable workflow when its YAML file exists on the repository's **default branch**, currently `main`. The full 5F-D workflow only exists on the Draft PR branch, and default `main` does not yet register that file. This session does not possess a GitHub Actions workflow-dispatch API action and does **not** force an unrelated main branch change or merge PR #7 merely to run a credential-bearing smoke.

Once the user authorizes **workflow-only bootstrap** into default `main` (NOT merging whole PR #7), they can launch from GitHub Actions → `SWE Real Model Smoke (Manual)` → `Run workflow` → select `coding/step5-deerflow-adapter` → enter `RUN`. That selected branch contains the tested source and workflow; Secrets remain in repository settings. If GitHub refuses manual dispatch until registration, do not try to circumvent the gate via automatic push/PR secret execution.

## Trust limits / live acceptance

- The true external LLM API must demonstrate at least one genuine model-driven read, guarded edit, Docker command, correct Git diff and independent canonical unittest `holds`. Any model-only report, model refusal, auth 401, provider tool-call schema mismatch, timeout or test failure is **NO-GO**, not success.
- `tests/integration/test_deerflow_live_swe_step5fd.py` uses a **test-fixed precommit 5C resource fixture**, albeit genuine runtime `NodeExecutionBindingStore.bind()` and source-pinned Native executor after actual Scheduler Commit. It is not a complete production 5C immutable-source/Inventory live verification or real deployed AuthorizationProvider test.
- Full native Sandbox/worker quiescence remains deferred by user direction; strict Scheduler still reports quarantine / failed for unknown quiescence. `tests_passed_scheduler_quarantined` describes independent tests and does not declare accepted TaskResult or dispatch downstream DAG work.
- The isolation backend is a development Docker boundary with Workspace writable mount and best-effort cleanup; host Git operations and the trusted Python runner still own model credentials. The repaired code only runs via model Bash and isolated canonical Python Docker, not by the host Python regression path. Formal host privilege isolation remains future work.
- Model compatibility and budget/cost are provider-dependent. API/URL Secret content is unverified until the explicit manual paid call.
- No real provider secret values, human debugging logs with endpoint/key, or code patches from a real model have been observed yet.

## Next gate

1. Verify final HEAD Python 3.11/3.13 Core CI and pinned Python 3.12 native+Docker CI.
2. After review, register **only** manual smoke workflow on default `main` or follow the organization's approved manual workflow registration policy. **Do not merge PR #7 as a side effect.**
3. The user explicitly launches `workflow_dispatch` on the tested coding branch with `authorization=RUN`.
4. Audit run logs, inspect redacted report artifact, and classify `Real Model GO` / `Tool Calling NO-GO` / `Provider Configuration NO-GO` / `Independent Verification NO-GO` with exact evidence.

**Do not claim 5F-D is complete before step 3 passes with real HTTP requests.**
