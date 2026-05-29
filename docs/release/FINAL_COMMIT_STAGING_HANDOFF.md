# Final Commit Staging Handoff

## Purpose

This handoff is the final checkpoint after the seven commit slices have been validated.

The goal is not to add product behavior. The goal is to stage and review the current large Cambrian worktree without turning it into one opaque commit.

## Current Worktree Snapshot

Refresh these numbers before committing.

```text
Total git status entries: 188
Tracked modified files: 26
Untracked files/directories: 162
Slice candidate entries: 188
Excluded-by-default entries: 0
Manual review entries: 0
Final staging receipt body sha256: b7917cffb0416a2e2d84a7c3fc68e82ca7b53f80f6539fe7a53acd907706f2e2
Engine/runtime slice entries: 0
Harness/workforce/skill slice entries: 0
Launch/pilot/release docs slice entries: 173
Pack/template/benchmark slice entries: 0
Web area entries: 12
Runtime evidence archive entries: 3
Generated test/tool caches are ignored before staging. Runtime evidence/noisy generated entries still remain excluded by default if they appear in git status.
```

## Latest Slice Prestage Audit

Read-only slice prestage verification is complete for all seven active slices. No `git add`, commit, tag, push, deploy, publish, send, secret read, or private recipient entry occurred.

| Slice | Candidate Paths | Candidate Paths SHA256 | Worktree Status | Prestage Status |
|---|---:|---|---|---|
| `slice_1_packaging_rc_runtime` | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | `committed_locally` | `complete` |
| `slice_2_ai_company_auto_runtime` | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | `committed_locally` | `complete` |
| `slice_3_harness_workforce_skill` | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | `committed_locally` | `complete` |
| `slice_4_pack_template_benchmark` | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | `committed_locally` | `complete` |
| `slice_5_launch_pilot_release_docs` | 173 | `1239b3a69d9169fa85cb5f2ed8480902adff70a090d99d074c156e0bd48cb78f` | `slice_worktree_ready` | `slice_prestage_ready` |
| `slice_6_web_and_tools` | 12 | `d786f469da7364a023f124cd4b09d269ade6be883dbdecb949c30ca513fc99b5` | `slice_worktree_ready` | `slice_prestage_ready` |
| `slice_7_runtime_evidence_archive` | 3 | `aac9d033dd84aced11f5bf8cb2d40db2fa5b246dff57eb8b6d3e65db64e7f2bd` | `slice_worktree_ready` | `slice_prestage_ready` |

For each slice, `staged existing` was `0` during the receipt-backed prestage audit. This means the current index is still clean and the next operator action remains manual slice-by-slice staging.

## Completed Slice Gates

| Slice | Area | Readiness Document | Latest Gate |
|---:|---|---|---|
| 1 | Packaging RC Runtime | `docs/release/PACKAGING_SLICE_READY.md` | GO |
| 2 | AI Company Auto Runtime | `docs/release/AUTO_RUNTIME_SLICE_READY.md` | GO |
| 3 | Harness Workforce Skill | `docs/release/HARNESS_WORKFORCE_SKILL_SLICE_READY.md` | GO |
| 4 | Pack Template Benchmark | `docs/release/PACK_TEMPLATE_BENCHMARK_SLICE_READY.md` | GO |
| 5 | Launch Pilot Release Docs | `docs/release/LAUNCH_PILOT_RELEASE_DOCS_SLICE_READY.md` | GO |
| 6 | Web Tools | `docs/release/WEB_TOOLS_SLICE_READY.md` | GO |
| 7 | Runtime Evidence Archive | `docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md` | GO |

Latest active auto release gate:

```text
release-gate-20260513-142945
Verdict: GO
Goal: AI 응답 evidence compliance 검증을 job ingest와 validate에 연결
```

Latest release closure sweep:

```text
python scripts/prepare_cambrian_install_kit_release.py --verify-release-bundle dist/cambrian-install-kit-release-bundle.zip -> PASS
python scripts/check_cambrian_install_kit_send_ready.py --verify-send-ready dist/cambrian-install-kit-send-ready.json -> GO
python scripts/prepare_cambrian_install_kit_release.py --verify-release-receipt dist/cambrian-install-kit-release-receipt.json -> PASS
python scripts/smoke_cambrian_install_kit_release_bundle.py --verify-receipt dist/cambrian-install-kit-release-bundle-smoke-receipt.json -> PASS
python -m pytest --collect-only -q tests -> 2705 tests collected
python -m pytest -q tests/test_cambrian_install_kit.py tests/test_ai_company_os_task_backlog.py tests/test_final_commit_staging_handoff.py tests/test_installed_wheel_pack_rc.py -> 138 passed
python scripts/smoke_installed_wheel.py -> PASS
python -m engine.cli auto status --json -> release_gate_go, GO
all seven receipt-backed slice prestage checks -> PASS, staged existing 0
```

## Stage Order

Stage and commit in this order:

1. Slice 1: Packaging RC Runtime
2. Slice 2: AI Company Auto Runtime
3. Slice 3: Conversational Harness, Workforce, Skill System
4. Slice 4: Pack, Template, Benchmark Advanced Surfaces
5. Slice 5: Launch, Pilot, Release Docs
6. Slice 6: Web And Tools
7. Slice 7: Runtime Evidence Archive summary

Do not stage all files at once.

## Slice 1 Stage Scope

Commit type:

```text
fix(packaging): 설치형 wheel pack catalog 경로 안정화
```

Stage only:

- `pyproject.toml`
- `engine/_data_path.py`
- `engine/_data/packs/`
- `engine/project_pack_catalog.py`
- `engine/project_pack_dependencies.py`
- `engine/project_pack_readiness.py`
- `engine/project_pack_install.py`
- `engine/demo_project.py`
- `scripts/smoke_installed_wheel.py`
- packaging and pack install/readiness tests
- `docs/release/PACKAGING_SLICE_READY.md`

Gate:

```bash
python scripts/smoke_installed_wheel.py
python -m pytest -q tests/test_installed_wheel_pack_rc.py tests/test_alpha_packaging.py tests/test_pack_catalog.py tests/test_pack_install.py tests/test_pack_readiness.py tests/test_launch_golden_path.py tests/test_launch_surface.py tests/test_packaging_slice_ready.py
```

## Slice 2 Stage Scope

Commit type:

```text
feat(auto): 권한 모드와 AI 회사 auto runtime 추가
```

Stage only:

- `engine/project_authority.py`
- `engine/project_auto_mode.py`
- auto runtime tests
- role-specific auto directive/result tests
- quality-aware auto plan tests
- `docs/release/AUTO_RUNTIME_SLICE_READY.md`

Gate:

```bash
python -m pytest -q tests/test_authority_mode.py tests/test_auto_mode_state.py tests/test_auto_boardroom.py tests/test_auto_plan.py tests/test_auto_run_limits.py tests/test_auto_cycle.py tests/test_auto_input_required_gate.py tests/test_auto_release_gate.py tests/test_auto_result_quality_scoring.py tests/test_auto_done_gate.py tests/test_auto_next_iteration.py tests/test_role_specific_auto_directives.py tests/test_role_specific_result_compliance.py tests/test_quality_aware_auto_plan_selection.py tests/test_auto_loop_dogfood.py tests/test_auto_runtime_slice_ready.py
```

## Slice 3 Stage Scope

Commit type:

```text
feat(harness): 대화형 하네스 인력 스킬 생성 흐름 추가
```

Stage only:

- harness profile/interview/plan/engineering/custom harness modules
- workforce, skill, dispatch, evidence, evolution modules
- `HARNESS_ARTIFACT_SYSTEM.md` and harness/evolution product contracts
- harness/workforce/skill tests
- TypeScript/Jest harness fixture and compatibility tests
- `docs/release/HARNESS_WORKFORCE_SKILL_SLICE_READY.md`

Gate:

```bash
python -m pytest -q tests/test_project_harness_profile.py tests/test_project_harness_plan.py tests/test_project_agent_dispatch.py tests/test_pack_compatibility.py tests/test_typescript_jest_auth_harness.py tests/test_harness_interview.py tests/test_custom_harness_from_answers.py tests/test_harness_install_requires_approval.py tests/test_harness_engineer_design.py tests/test_harness_engineer_review.py tests/test_harness_engineer_dry_run.py tests/test_harness_install_requires_engineering_gate.py tests/test_workforce_builder.py tests/test_agent_generation.py tests/test_skill_generation.py tests/test_job_start_selects_agents_and_skills.py tests/test_job_start_runtime_contract.py tests/test_dispatch_on_demand.py tests/test_preset_as_optional_seed.py tests/test_job_complete_evidence.py tests/test_evolution_review.py tests/test_evolution_proposal.py tests/test_evolution_apply_requires_confirm.py tests/test_skill_evolution.py tests/test_ai_company_bootstrap.py tests/test_harness_workforce_skill_slice_ready.py
```

## Slice 4 Stage Scope

Commit type:

```text
feat(pack): pack template benchmark 고급 검증 표면 추가
```

Stage only:

- advanced pack lifecycle/proof/release/registry/rollout/trust modules
- template bootstrap/canary/challenge/qualification/library modules
- benchmark/proof modules
- agent platform schemas, validators, promotion/proof tools, and platform tests
- pack/template/benchmark tests
- `docs/release/PACK_TEMPLATE_BENCHMARK_SLICE_READY.md`

Gate:

```bash
python -m pytest -q tests/test_pack_*.py
python -m pytest -q tests/test_template_*.py
python -m pytest -q tests/test_benchmark*.py
python -m pytest -q tests/test_pack_template_benchmark_slice_ready.py
```

If the broad template group times out, use `docs/release/SPLIT_RUN_REGRESSION_GATE.md`.

## Slice 5 Stage Scope

Commit type:

```text
docs(launch): launch pilot release 운영 문서 정리
```

Stage only:

- `docs/launch/`
- release and product docs tied to launch, pilot, RC, split-run, and worktree handoff
- external alpha root launcher/support files and demo fixture files
- launch/pilot/release docs tests
- `docs/release/LAUNCH_PILOT_RELEASE_DOCS_SLICE_READY.md`

Gate:

```bash
python -m pytest -q tests/test_public_demo_kit.py tests/test_launch_assets.py tests/test_pilot_outreach_kit.py tests/test_launch_go_no_go.py tests/test_product_docs.py tests/test_split_run_regression_gate.py tests/test_worktree_release_handoff.py tests/test_commit_slicing_plan.py tests/test_dogfood_runbook.py tests/test_launch_pilot_release_docs_slice_ready.py
```

## Slice 6 Stage Scope

Commit type:

```text
feat(web): launch surface and local tooling 정리
```

Stage only:

- `web/`
- `tools/generate_web_catalog.py`
- `tools/run_launch_demo.py`
- `tests/test_web_catalog.py`
- `docs/release/WEB_TOOLS_SLICE_READY.md`
- `tests/test_web_tools_slice_ready.py`

Gate:

```bash
python tools/generate_web_catalog.py
python -m pytest -q tests/test_web_catalog.py tests/test_web_tools_slice_ready.py
```

Do not stage:

- `tools/__pycache__/`

## Slice 7 Stage Scope

Commit type:

```text
docs(evidence): Cambrian auto loop evidence archive 요약 추가
```

Default stage only:

- `docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md`
- `tests/test_runtime_evidence_archive_slice_ready.py`
- `docs/release/RC_CHECKLIST.md`

Do not stage by default:

- full `.cambrian/` runtime tree
- raw external AI replies
- private project paths
- user data
- `.env` or secret files
- `.env or secret files` must stay excluded from every staging scope
- pycache directories

Gate:

```bash
python -m pytest -q tests/test_runtime_evidence_archive_slice_ready.py tests/test_web_tools_slice_ready.py tests/test_launch_pilot_release_docs_slice_ready.py tests/test_pack_template_benchmark_slice_ready.py tests/test_harness_workforce_skill_slice_ready.py tests/test_auto_runtime_slice_ready.py tests/test_packaging_slice_ready.py tests/test_commit_slicing_plan.py tests/test_worktree_release_handoff.py tests/test_split_run_regression_gate.py
```

## Final Pre-Commit Commands

Run before any manual staging attempt:

```bash
python scripts/check_final_commit_staging_handoff.py --json
```

Expected result:

```text
verdict: GO
status: ready_for_manual_slice_staging
safe_to_stage_all: false
```

`safe_to_stage_all: false` is intentional. This handoff authorizes manual slice-by-slice staging only.

Run before staging a specific slice to list its current worktree candidates:

```bash
python scripts/check_final_commit_staging_handoff.py --worktree --all-slices --json
python scripts/check_final_commit_staging_handoff.py --write-receipt-dir dist
python scripts/check_final_commit_staging_handoff.py --verify-all-artifacts dist/final-commit-staging-receipt.json
python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json
python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json --verify-pathspec-files
python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json --verify-runbook
python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json --against-current-worktree
python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json --against-current-worktree --verify-pathspec-files --verify-runbook
python scripts/check_final_commit_staging_handoff.py --worktree --slice <slice_id> --json
```

Use `slice_plans.<slice_id>.candidate_paths` or the single-slice `candidate_paths` as the proposed stage list. Both commands are read-only; they do not run `git add`.
Record the matching `candidate_paths_sha256` before staging.
The receipt command writes `dist/final-commit-staging-receipt.json`, `dist/final-commit-staging-receipt.md`, `dist/final-commit-staging-runbook.md`, and `dist/final-commit-test-gate-evidence/*.template.json`; keep those out of source commits unless an explicit release artifact scope is chosen.
The one-command preflight must return `receipt_all_artifacts_current`. The receipt verifier checks `receipt_body_sha256`, `candidate_paths_sha256`, `test_gate_commands_sha256`, policy flags, slice verify commands, and slice test gate commands before the receipt is used for staging. The pathspec verifier must return `receipt_pathspec_files_current`, the runbook verifier must return `receipt_runbook_current`, the evidence template verifier must return `receipt_test_gate_evidence_templates_current`, and the current-worktree verifier must return `receipt_current`; otherwise regenerate the receipt before staging.
Receipt generation uses `git status --porcelain=v1 -z --untracked-files=all`, so untracked directories are expanded into file-level paths before path digests are calculated.
Receipt files keep every slice `candidate_paths` entry in full because those paths are part of the commit digest lock. `excluded_by_default` is intentionally compacted into `excluded_by_default_count`, `excluded_by_default_summary`, `excluded_by_default_truncated`, and a bounded sample so large `.cambrian/` runtime trees do not create unreadable review artifacts.
Receipt generation also writes one line-delimited pathspec file per active slice under `dist/final-commit-staging-pathspecs/`, a pending test gate evidence template under `dist/final-commit-test-gate-evidence/`, and a command-only runbook at `dist/final-commit-staging-runbook.md`. Prefer the runbook sequence and `git add --pathspec-from-file=dist/final-commit-staging-pathspecs/<slice_id>.pathspec` over copying long path lists by hand, then verify the staged diff with the receipt-backed command. The runbook includes the selected slice's receipt-locked `test_gate_commands`; run those after staged verification and before `git commit`.

Run before each commit:

```bash
python scripts/check_final_commit_staging_handoff.py --verify-prestage-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id>
git add --pathspec-from-file=dist/final-commit-staging-pathspecs/<slice_id>.pathspec
python scripts/check_final_commit_staging_handoff.py --staged --slice <slice_id>
python scripts/check_final_commit_staging_handoff.py --staged --slice <slice_id> --expect-paths-sha256 <candidate_paths_sha256>
python scripts/check_final_commit_staging_handoff.py --verify-staged-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id>
python scripts/check_final_commit_staging_handoff.py --verify-commit-ready-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id>
git diff --cached --stat
git diff --cached --name-only
```

Then run the selected slice's `test_gate_commands` from `dist/final-commit-staging-receipt.json` or `dist/final-commit-staging-runbook.md`. The gate must pass before `git commit`.
Record the passing command results in the receipt-designated file `dist/final-commit-test-gate-evidence/<slice_id>.json`, including a unique non-empty portable local `evidence_ref` under `dist/final-commit-test-gate-logs/` and matching `evidence_sha256` for every command result. The `evidence_ref` should point to the terminal log, CI output saved as a local file, or captured verification note used to prove that command ran, and that local evidence file must contain the exact expected command string. Then verify it:

```bash
python scripts/check_final_commit_staging_handoff.py --verify-test-gate-evidence-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id> --test-gate-evidence dist/final-commit-test-gate-evidence/<slice_id>.json
```

This verifier must return `test_gate_evidence_ready` before `git commit`; a PASS entry without `evidence_ref`, without `evidence_sha256`, outside `dist/final-commit-test-gate-logs/`, with a reused `evidence_ref`, with a local evidence file that does not contain the expected command, with a missing local evidence file, with a mismatched hash, or saved under a path other than the receipt-designated `test_gate_evidence_file` is blocked.

Run the integrated final commit gate after the staged slice verifier and test gate evidence verifier both pass:

```bash
python scripts/check_final_commit_staging_handoff.py --verify-final-commit-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id> --test-gate-evidence dist/final-commit-test-gate-evidence/<slice_id>.json
```

This command must return `slice_final_commit_gate_ready` before `git commit`; it reruns the full receipt artifact check and blocks when the receipt, pathspec files, runbook, evidence templates, staged slice digest, or test gate evidence are no longer aligned.
When it blocks, inspect `blocking_reasons` first; it names the stale artifact, staged slice, or test evidence condition that must be fixed before rerunning the final gate. Use `blocking_details` for the exact failed check names under `receipt_artifacts`, `commit_ready`, `test_gate_evidence`, or `integrated`, and treat `recovery_commands` as suggestions only. The script never executes those recovery commands, never runs `git add`, never runs `git commit`, and never runs `git push`; this is recorded under `recovery_execution_policy` with `script_executes_recovery_commands`, `script_executes_git_add`, `script_executes_git_commit`, and `script_executes_git_push` all set to `false`. Check `recovery_command_plan` before copying commands; it labels `git add` as `mutates_git_index`, and `index_mutation_requires_manual_user_confirmation` must remain `true`. Use `recovery_command_summary` to confirm whether any recovery step mutates the git index, writes `dist/`, or runs tests.

Use one of these slice ids:

```text
slice_1_packaging_rc_runtime
slice_2_ai_company_auto_runtime
slice_3_harness_workforce_skill
slice_4_pack_template_benchmark
slice_5_launch_pilot_release_docs
slice_6_web_and_tools
slice_7_runtime_evidence_archive
```

The prestage audit must return `slice_prestage_ready` before running `git add`; it blocks if the current index already contains staged paths, if the receipt is stale, or if the selected slice pathspec file no longer matches the receipt. The staged slice audit must return `slice_stage_ready` before committing. The digest-locked command must also pass so the staged path set matches the planned `candidate_paths` exactly. Prefer the receipt-backed staged verifier because it reads the expected digest from the verified receipt. The final commit-ready audit must return `slice_commit_ready` and prints the receipt-locked suggested commit message plus the selected slice's `test_gate_commands`. The final integrated gate must return `slice_final_commit_gate_ready` with `receipt_all_artifacts_current`, empty `blocking_reasons`, empty `blocking_details`, empty `recovery_commands`, empty `recovery_command_plan`, `recovery_command_summary.total_count` equal to `0`, and `recovery_execution_policy.script_executes_recovery_commands` set to `false`. If any command returns `slice_stage_blocked`, `receipt_staged_slice_blocked`, `slice_commit_blocked`, `test_gate_evidence_blocked`, `slice_final_commit_gate_blocked`, or a slice-specific test gate failure, unstage the wrong-slice, excluded, manual-review, sensitive, missing, or extra paths and rerun it.

Run before the final tag or RC packaging step:

```bash
python scripts/smoke_installed_wheel.py
python -m engine.cli auto status --json
```

Expected auto status:

```text
release_gate_go
```

## Stop Conditions

Stop before committing if any condition is true:

- staged diff mixes multiple slices
- staged diff includes `.env`, secrets, private user data, raw external AI replies, or private project source
- staged diff includes full `.cambrian/` without explicit evidence archive scope
- latest auto release gate is not GO
- installed wheel smoke fails
- slice-specific test gate fails
- broad test timeout is treated as failure without checking split-run evidence

## Final Verdict

Ready for manual slice-by-slice staging, review, and commit.

Do not create a tag from this handoff alone. Tagging should happen only after the selected staged commits are created and the RC smoke gate is rerun.
