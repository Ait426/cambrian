# Cambrian Commit Slicing Plan

## Purpose

The current Cambrian worktree should not be committed as one large opaque change.

This plan defines the recommended commit order, validation gate, and review focus for turning the current worktree into reviewable commits.

## Current Worktree Size

- Total git status entries: 258
- Tracked modified files: 21
- Untracked files/directories: 237
- Engine/runtime area entries: 106
- Test area entries: 132
- Docs area entries: 7
- Script area entries: 3
- Runtime evidence entry: `.cambrian/`

Refresh these counts before actually committing.

## Commit Rules

- Do not mix product runtime changes with launch copy in the same commit.
- Do not mix `.cambrian/` local evidence with source code commits unless the commit is explicitly an evidence artifact commit.
- Do not include `.env`, secrets, private user data, or private project data.
- Run the slice-specific test gate before each commit.
- Keep commit messages in the project format: `{feat|fix|refactor|docs|test}(scope): 한국어 설명`.

## Recommended Commit Slices

### Slice 1 — Packaging RC Runtime

Suggested commit:

```text
fix(packaging): 설치형 wheel pack catalog 경로 안정화
```

Include:

- `pyproject.toml`
- `engine/_data_path.py`
- `engine/_data/packs/`
- `engine/project_pack_catalog.py`
- `engine/project_pack_dependencies.py`
- `engine/project_pack_readiness.py`
- `engine/project_pack_install.py`
- `engine/demo_project.py`
- `scripts/smoke_installed_wheel.py`
- packaging/readiness/install tests

Gate:

```bash
python scripts/smoke_installed_wheel.py
python -m pytest -q tests/test_installed_wheel_pack_rc.py tests/test_alpha_packaging.py tests/test_pack_catalog.py tests/test_pack_install.py tests/test_pack_readiness.py tests/test_launch_golden_path.py tests/test_launch_surface.py
```

### Slice 2 — AI Company Auto Runtime

Suggested commit:

```text
feat(auto): 권한 모드와 AI 회사 auto loop 추가
```

Include:

- `engine/project_authority.py`
- `engine/project_auto_mode.py`
- auto state, boardroom, plan, run, report, release gate tests
- role-specific result contract tests

Gate:

```bash
python -m pytest -q tests/test_authority_mode.py tests/test_auto_mode_state.py tests/test_auto_boardroom.py tests/test_auto_plan.py tests/test_auto_run_limits.py tests/test_auto_cycle.py tests/test_auto_input_required_gate.py tests/test_auto_release_gate.py tests/test_auto_result_quality_scoring.py tests/test_auto_done_gate.py tests/test_auto_next_iteration.py tests/test_role_specific_auto_directives.py tests/test_role_specific_result_compliance.py tests/test_quality_aware_auto_plan_selection.py tests/test_auto_loop_dogfood.py
```

### Slice 3 — Conversational Harness, Workforce, Skill System

Suggested commit:

```text
feat(harness): 대화형 하네스 인력 스킬 생성 흐름 추가
```

Include:

- `engine/project_harness_profile.py`
- `engine/project_harness_interview.py`
- `engine/project_harness_plan.py`
- `engine/project_harness_engineering.py`
- `engine/project_custom_harness.py`
- `engine/project_workforce_builder.py`
- `engine/project_skill_builder.py`
- `engine/project_agent_dispatch.py`
- job start, dispatch, evolution, and harness tests

Gate:

```bash
python -m pytest -q tests/test_project_harness_profile.py tests/test_project_harness_plan.py tests/test_project_agent_dispatch.py tests/test_pack_compatibility.py tests/test_typescript_jest_auth_harness.py tests/test_harness_interview.py tests/test_custom_harness_from_answers.py tests/test_harness_install_requires_approval.py tests/test_harness_engineer_design.py tests/test_harness_engineer_review.py tests/test_harness_engineer_dry_run.py tests/test_harness_install_requires_engineering_gate.py tests/test_workforce_builder.py tests/test_agent_generation.py tests/test_skill_generation.py tests/test_job_start_selects_agents_and_skills.py tests/test_job_start_runtime_contract.py tests/test_dispatch_on_demand.py tests/test_preset_as_optional_seed.py tests/test_job_complete_evidence.py tests/test_evolution_review.py tests/test_evolution_proposal.py tests/test_evolution_apply_requires_confirm.py tests/test_skill_evolution.py tests/test_ai_company_bootstrap.py
```

### Slice 4 — Pack, Template, Benchmark Advanced Surfaces

Suggested commit:

```text
feat(pack): pack template qualification surfaces 추가
```

Include:

- pack lifecycle, proof, release, registry, rollout, trust modules
- template bootstrap, canary, challenge, qualification modules
- benchmark/proof modules
- related tests

Gate:

```bash
python -m pytest -q tests/test_pack_*.py
python -m pytest -q tests/test_template_*.py
python -m pytest -q tests/test_benchmark*.py
```

If the broad template group times out, apply the split-run policy in `docs/release/SPLIT_RUN_REGRESSION_GATE.md`.

### Slice 5 — Launch, Pilot, Release Docs

Suggested commit:

```text
docs(launch): launch pilot release 운영 문서 정리
```

Include:

- `docs/launch/`
- `docs/release/`
- launch, pilot, RC, split-run, handoff docs
- docs tests

Gate:

```bash
python -m pytest -q tests/test_public_demo_kit.py tests/test_launch_assets.py tests/test_pilot_outreach_kit.py tests/test_pilot_learning_board.py tests/test_launch_go_no_go.py tests/test_product_docs.py tests/test_split_run_regression_gate.py tests/test_worktree_release_handoff.py tests/test_commit_slicing_plan.py
```

### Slice 6 — Web And Tools

Suggested commit:

```text
feat(web): launch surface and local tooling 정리
```

Include only if intentionally part of this RC:

- `web/`
- `tools/`
- web catalog tests

Gate:

```bash
python -m pytest -q tests/test_web_catalog.py
```

### Slice 7 — Runtime Evidence Archive

Suggested commit:

```text
docs(evidence): Cambrian auto loop evidence archive 추가
```

Include only if the repo intentionally tracks local evidence:

- `.cambrian/auto/iterations/`
- selected `.cambrian/auto/release_gate/`
- selected `.cambrian/auto/report.yaml`

Default recommendation:

- Do not commit all `.cambrian/` evidence by default.
- Prefer copying final summaries into `docs/release/`.

## Pre-Commit Checklist

- [ ] Confirm no `.env` or secret file is staged.
- [ ] Confirm no private project source is staged.
- [ ] Confirm slice-specific tests pass.
- [ ] Confirm `git diff --cached --stat` matches the intended slice.
- [ ] Confirm commit message follows project format.
- [ ] Confirm release docs still point to current validation evidence.

## Stop Conditions

Stop slicing and fix first if any of these occur:

- installed wheel smoke fails,
- auto release gate latest verdict is not GO,
- split-run gate has a failed chunk,
- staged diff contains secrets or private project files,
- staged diff mixes unrelated slices.
