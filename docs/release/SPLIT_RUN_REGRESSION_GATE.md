# Cambrian Split-Run Regression Gate

## Purpose

Cambrian's full pytest suite is now large enough that a single local `python -m pytest -q` run can exceed the interactive timeout even when individual test groups pass.

For RC and auto-loop validation, the official regression gate is a split-run gate with recorded evidence, not a single long-running pytest command.

## Gate Rule

- Use split-run as the release-blocking regression gate for the broad suite.
- Treat a single-command full pytest timeout as a runtime-capacity signal unless a split chunk fails.
- Treat any failed split chunk as release-blocking until reproduced, fixed, or explicitly classified.
- Keep the installed wheel smoke as a separate required gate.
- Record commands, pass/fail status, duration, and any timeout classification in `.cambrian/auto/external_results/`.

## Required Smoke Gate

```bash
python scripts/smoke_installed_wheel.py
```

This gate must remain PASS for installable RC confidence.

## Required Focus Gates

```bash
python -m pytest -q tests/test_installed_wheel_pack_rc.py tests/test_alpha_packaging.py tests/test_pack_catalog.py tests/test_pack_install.py tests/test_pack_readiness.py tests/test_launch_golden_path.py tests/test_launch_surface.py
python -m pytest -q tests/test_authority_mode.py tests/test_auto_mode_state.py tests/test_auto_boardroom.py tests/test_auto_plan.py tests/test_auto_run_limits.py tests/test_auto_cycle.py tests/test_auto_input_required_gate.py tests/test_auto_release_gate.py tests/test_auto_result_quality_scoring.py tests/test_auto_done_gate.py tests/test_auto_next_iteration.py tests/test_role_specific_auto_directives.py tests/test_role_specific_result_compliance.py tests/test_quality_aware_auto_plan_selection.py tests/test_auto_loop_dogfood.py
python -m pytest -q tests/test_project_harness_profile.py tests/test_project_harness_plan.py tests/test_project_agent_dispatch.py tests/test_pack_compatibility.py tests/test_typescript_jest_auth_harness.py tests/test_harness_interview.py tests/test_custom_harness_from_answers.py tests/test_harness_install_requires_approval.py tests/test_harness_engineer_design.py tests/test_harness_engineer_review.py tests/test_harness_engineer_dry_run.py tests/test_harness_install_requires_engineering_gate.py tests/test_workforce_builder.py tests/test_agent_generation.py tests/test_skill_generation.py tests/test_job_start_selects_agents_and_skills.py tests/test_job_start_runtime_contract.py tests/test_dispatch_on_demand.py tests/test_preset_as_optional_seed.py tests/test_job_complete_evidence.py tests/test_evolution_review.py tests/test_evolution_proposal.py tests/test_evolution_apply_requires_confirm.py tests/test_skill_evolution.py tests/test_ai_company_bootstrap.py
```

## Broad Suite Split Policy

When the full test suite is needed, split it into bounded chunks instead of relying on one long command.

Recommended chunk policy:

- Keep each chunk under the local command timeout.
- Prefer domain groups: packaging, auto mode, harness/company runtime, packs, templates, web/docs.
- If a chunk times out, isolate the files inside that chunk before classifying it as a product failure.
- If every isolated file passes and only the combined chunk times out, classify the issue as `SPLIT_RUN_REQUIRED`.

## Current RC Focused Re-Run

Latest release-finishing re-run:

- Installed wheel smoke: `PASS`
- Packaging/launch focused gate: `61 passed`
- Auto runtime focused gate: initial 120s interactive run timed out; same focused gate passed with extended timeout as `93 passed`
- Harness/company focused gate: combined command timed out; split groups passed as `40 passed`, `29 passed`, `23 passed`, `7 passed`, `9 passed`, `16 passed`, and `4 passed`
- Harness/company focused split total: `128 passed`

The auto and harness timeouts above are classified as `SPLIT_RUN_REQUIRED`, not release-blocking product failures, because the bounded split or extended gate runs passed.

## Current Evidence Baseline

The latest broad validation evidence recorded:

- Chunk 1: `281 passed`
- Chunk 2: `261 passed, 2 skipped`
- Chunk 3: `292 passed, 3 skipped`
- Chunk 4: `272 passed, 9 skipped`
- Chunk 5: `344 passed`
- Chunk 6a: `86 passed`
- Chunk 6b: `77 passed`
- Chunk 6c isolated files: `73 passed`
- Chunk 7: `62 passed`
- Auto/release regression subset: `48 passed`
- Installed wheel smoke: `PASS`

## Timeout Classification

Use these labels in auto evidence:

- `PASS`: split chunk or isolated file group completed successfully.
- `FAIL`: a test failed.
- `TIMEOUT_REPRODUCED`: the same bounded command times out repeatedly.
- `SPLIT_RUN_REQUIRED`: the full or combined command times out, but isolated chunks pass.
- `BLOCKED`: missing dependency, environment issue, or unreadable evidence.

## Release Decision

GO is allowed when:

- installed wheel smoke passes,
- release-blocking focused gates pass,
- split-run evidence has no failed chunk,
- timeouts are classified as `SPLIT_RUN_REQUIRED` rather than hidden failures,
- `.cambrian/auto/report.yaml` has no open blockers.

NO-GO is required when:

- installed wheel smoke fails,
- any release-blocking focused gate fails,
- a split chunk fails and is not fixed,
- timeout evidence cannot be reproduced or classified,
- auto report has open blockers.
