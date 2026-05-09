# Final Commit Staging Handoff

## Purpose

This handoff is the final checkpoint after the seven commit slices have been validated.

The goal is not to add product behavior. The goal is to stage and review the current large Cambrian worktree without turning it into one opaque commit.

## Current Worktree Snapshot

Refresh these numbers before committing.

```text
Total git status entries: 266
Tracked modified files: 21
Untracked files/directories: 245
Engine/runtime area entries: 106
Test area entries: 140
Docs area entries: 7
Script area entries: 3
Tools area entries: 1
Web area entries: 1
Runtime evidence entry: .cambrian/
```

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
release-gate-20260509-180519
Verdict: GO
Goal: Validate runtime evidence archive commit slice readiness
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
- launch/pilot/release docs tests
- `docs/release/LAUNCH_PILOT_RELEASE_DOCS_SLICE_READY.md`

Gate:

```bash
python -m pytest -q tests/test_public_demo_kit.py tests/test_launch_assets.py tests/test_pilot_outreach_kit.py tests/test_pilot_learning_board.py tests/test_launch_go_no_go.py tests/test_product_docs.py tests/test_split_run_regression_gate.py tests/test_worktree_release_handoff.py tests/test_commit_slicing_plan.py tests/test_launch_pilot_release_docs_slice_ready.py
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

Run before each commit:

```bash
git diff --cached --stat
git diff --cached --name-only
```

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
