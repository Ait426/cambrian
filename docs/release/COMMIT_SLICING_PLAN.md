# Cambrian Commit Slicing Plan

## Purpose

The current Cambrian worktree should not be committed as one large opaque change.

This plan defines the recommended commit order, validation gate, and review focus for turning the current worktree into reviewable commits.

## Current Handoff Snapshot

Authoritative staging counts come from:

```bash
python scripts/check_final_commit_staging_handoff.py --worktree --all-slices --json
```

Current snapshot:

- File-level git status entries: 188
- Active candidate paths: 188
- Excluded by default: 0
- Manual review paths: 0
- Blockers: 0
- Active slices: 5, 6, 7

The count uses `git status --porcelain=v1 -z --untracked-files=all`, so untracked directories are expanded to file-level paths before slice digests are calculated. Generated pytest/tool caches are ignored at source by `.gitignore`, and regular `git status --short` is not the source of truth for commit slicing.

## Receipt-Locked Slice Snapshot

| Slice | Candidate paths | Candidate paths SHA-256 | Staging status |
| --- | ---: | --- | --- |
| Slice 1 — Packaging RC Runtime | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | Committed locally |
| Slice 2 — AI Company Auto Runtime | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | Committed locally |
| Slice 3 — Conversational Harness, Workforce, Skill System | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | Committed locally |
| Slice 4 — Pack, Template, Benchmark Advanced Surfaces | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | Committed locally |
| Slice 5 — Launch, Pilot, Release Docs | 173 | `1239b3a69d9169fa85cb5f2ed8480902adff70a090d99d074c156e0bd48cb78f` | Ready for manual slice staging |
| Slice 6 — Web And Tools | 12 | `d786f469da7364a023f124cd4b09d269ade6be883dbdecb949c30ca513fc99b5` | Ready for manual slice staging |
| Slice 7 — Runtime Evidence Archive | 3 | `aac9d033dd84aced11f5bf8cb2d40db2fa5b246dff57eb8b6d3e65db64e7f2bd` | Ready for manual slice staging |

Before staging a slice, regenerate `dist/final-commit-staging-receipt.json`, `dist/final-commit-staging-runbook.md`, the per-slice pathspec files, and `dist/final-commit-test-gate-evidence/*.template.json`. Run `python scripts/check_final_commit_staging_handoff.py --verify-all-artifacts dist/final-commit-staging-receipt.json` and require `receipt_all_artifacts_current`; this single preflight covers the receipt, current worktree, pathspec files, runbook, and test gate evidence templates. Then run `python scripts/check_final_commit_staging_handoff.py --verify-prestage-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id>` to confirm the selected slice is current and the index is empty. Stage only paths listed in that receipt for the selected slice, preferably through `git add --pathspec-from-file=dist/final-commit-staging-pathspecs/<slice_id>.pathspec`, then run the receipt-backed staged verifier and `python scripts/check_final_commit_staging_handoff.py --verify-commit-ready-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id>` before committing. After the slice test evidence returns `test_gate_evidence_ready`, run `python scripts/check_final_commit_staging_handoff.py --verify-final-commit-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id> --test-gate-evidence dist/final-commit-test-gate-evidence/<slice_id>.json` and require `slice_final_commit_gate_ready`; this final command also requires `receipt_all_artifacts_current`, empty `blocking_reasons`, empty `blocking_details`, empty `recovery_commands`, empty `recovery_command_plan`, `recovery_command_summary.total_count` equal to `0`, and `recovery_execution_policy.script_executes_recovery_commands` equal to `false`. If blocked, review `recovery_execution_policy`, `recovery_command_plan`, and `recovery_command_summary` first; returned `recovery_commands` are suggestions only and the script does not execute `git add`, `git commit`, or `git push`. `dist/final-commit-staging-runbook.md` mirrors this sequence for every active slice and includes the receipt-locked suggested commit message plus the slice-specific `test_gate_commands`; the commit-ready command also echoes those commands so the final terminal output names the required test gate before `git commit`.

## Commit Rules

- Do not mix product runtime changes with launch copy in the same commit.
- Do not mix `.cambrian/` local evidence with source code commits unless the commit is explicitly an evidence artifact commit.
- Do not include `.env`, secrets, private user data, or private project data.
- Run the receipt-locked slice-specific `test_gate_commands` before each commit.
- Verify the completed slice evidence JSON returns `test_gate_evidence_ready` before each commit; it must be saved at the receipt-designated `test_gate_evidence_file`, and every PASS command result must include a unique non-empty portable local `evidence_ref` under `dist/final-commit-test-gate-logs/` plus matching `evidence_sha256`; each referenced evidence file must contain the exact expected command string.
- Verify the integrated final commit gate returns `slice_final_commit_gate_ready`, includes `receipt_all_artifacts_current`, has empty `blocking_reasons`, empty `blocking_details`, empty `recovery_commands`, empty `recovery_command_plan`, `recovery_command_summary.total_count` of `0`, and `recovery_execution_policy.script_executes_git_add` set to `false` before each commit.
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
- `HARNESS_ARTIFACT_SYSTEM.md`
- harness/evolution product contracts
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
- agent platform schemas, validators, candidate promotion tools, and platform tests
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
- external alpha root launcher/support files
- demo fixture files used by the external alpha install surface
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
