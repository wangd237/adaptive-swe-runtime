# Step 5F-D — Credentialed Real Model SWE Smoke: Preflight and Live-Run Audit

**Date:** 2026-10-10
**Branch:** `coding/step5-deerflow-adapter`, PR #7 Draft / Open
**Frozen DeerFlow:** `bytedance/deer-flow@c0895d295bba34f6e95188fca380f555dabed891`
**Stage disposition:** **Scoped GO: offline CI plus one real credentialed model smoke completed successfully.** Strict Core acceptance and full release integration remain NO-GO.

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

## Actual manual workflow registration and execution

- Manual workflow registered on default `main` in commit `a57b80291f4c61245dd38c8d8b5bd6f016a0d120`, *without* merging PR #7.
- User launched the manual workflow with explicit consent on `coding/step5-deerflow-adapter`; successful run #38018937188 on developer HEAD `1cc3567eeed4550254b0cff35f9f2183bcbefe59`.
- Credentials were loaded by the runner and the test completed. Secret values were never queried or printed by the audit.
- The full evidence-based outcome is recorded in the dated run verification section below.

## Trust limits / live acceptance

- The true external LLM API must demonstrate at least one genuine model-driven read, guarded edit, Docker command, correct Git diff and independent canonical unittest `holds`. Any model-only report, model refusal, auth 401, provider tool-call schema mismatch, timeout or test failure is **NO-GO**, not success.
- `tests/integration/test_deerflow_live_swe_step5fd.py` uses a **test-fixed precommit 5C resource fixture**, albeit genuine runtime `NodeExecutionBindingStore.bind()` and source-pinned Native executor after actual Scheduler Commit. It is not a complete production 5C immutable-source/Inventory live verification or real deployed AuthorizationProvider test.
- Full native Sandbox/worker quiescence remains deferred by user direction; strict Scheduler still reports quarantine / failed for unknown quiescence. `tests_passed_scheduler_quarantined` describes independent tests and does not declare accepted TaskResult or dispatch downstream DAG work.
- The isolation backend is a development Docker boundary with Workspace writable mount and best-effort cleanup; host Git operations and the trusted Python runner still own model credentials. The repaired code only runs via model Bash and isolated canonical Python Docker, not by the host Python regression path. Formal host privilege isolation remains future work.
- Model compatibility and budget/cost remain provider-dependent. The specific configured provider completed one paid model invocation; actual Secret values and token usage remain inaccessible to this audit.
- No raw provider Secret values have been accessed. The real-model run did produce a verified source patch; detailed reasoning trajectory, token/cost and complete tool-by-tool outputs were not retained in the artifact.

## Next gate

- 5F-D real-model *smoke* is evidenced and Scoped GO. Do not automatically rerun a paid API test.
- PR #7 remains Draft/Open. Full production 5C inventory/AuthorizationProvider composition and complete native Quiescence are still not attested.
- If needed, a separate, user-approved extended smoke should persist secret-redacted per-tool traces and model token/cost metrics, and run a nontrivial multi-step repair before claiming stronger SWE capabilities.

## 5F-D Live Model Run #38018937188 — Verified (2026-10-10)

- **Real live result: Scoped GO** for *one actual paid-model autonomous coding smoke*, on commit `1cc3567eeed4550254b0cff35f9f2183bcbefe59`; GitHub Actions run: https://github.com/wangd237/adaptive-swe-runtime/actions/runs/38018937188. This was a `workflow_dispatch` on `coding/step5-deerflow-adapter`. Workflow conclusion `success`; no retries recorded.
- Actual model stage `One real LLM autonomous repair and canonical verification` succeeded. GitHub Actions credentials preflight succeeded; the run uploaded artifact `swe-live-mvp-report` (ID `11657392376`), retrieved and parsed independently.
- Report: `native_status=completed`, `verification_status=passed`, `verified_returncode=0`, `tests_passed=true`, canonical check `mvp-python-regression-container`, nonempty canonical EvidenceRef bound to this execution, `agent_dynamic_command_count=2`, `agent_last_dynamic_command_exit_code=0`, `agent_tool_changed_paths=["calc.py"]`, `changed_files=["calc.py"]`, `git_diff_truncated=false`. Exact observed patch: `calc.py` `return 1` → `return 42`; regression test file was not modified.
- **Not strict ACCEPTED**: report honestly states `scheduler_failed=true`, `scheduler_node_status=failed`, `workspace_status=quarantined`, `quiescence_proven=false`, `delivery_status=tests_passed_scheduler_quarantined`. Full Sandbox Quiescence remains deferred and no strict NodeHandoff/TaskResult was signed.
- Limits: script includes instructions to inspect specified files and run unittest, but **model tool calls were not hardcoded**. Only aggregated command counts and patch are stored; no full per-tool/model transcript, so **the real-model run does not independently prove a failing-test→repair retry or reasoning trajectory**. No repeatability study, unknown token/cost, no provider stress/benchmark, no production 5C inventory/Authz single physical composition. The test fixed only a trivial Python regression; do not claim general SWE-bench capability.
- Decision: **5F-D minimal real-model smoke accepted, within expressly limited scope**. PR #7 remains Draft/Open/unmerged. Before full Step 5 Design Freeze consider optional per-tool structured trace without secrets, reliable provider cost counters, and a harder multi-step bug. Do NOT replay paid API calls automatically.
