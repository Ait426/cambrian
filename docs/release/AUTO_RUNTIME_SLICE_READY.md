# AI Company Auto Runtime Slice Readiness

## Purpose

This document records the readiness of the second recommended commit slice from `COMMIT_SLICING_PLAN.md`.

Slice 2 covers Cambrian authority mode and the AI company auto runtime: state, boardroom, planning, bounded run cycles, result ingestion, quality-aware planning, reporting, and release gate behavior.

## Slice

Suggested commit:

```text
feat(auto): authority and AI company auto runtime
```

## Include

- `engine/project_authority.py`
- `engine/project_auto_mode.py`
- auto state, boardroom, plan, run, report, and release gate tests
- authority mode tests
- role-specific directive and result contract tests
- quality-aware plan selection tests
- auto loop dogfood tests

## Do Not Include

- installed wheel pack catalog fixes
- harness/workforce/skill builder source files
- pack/template/benchmark advanced surfaces
- launch or pilot copy unrelated to auto runtime
- `.cambrian/` runtime evidence unless intentionally committing evidence
- private local project files
- `.env` or secret files

## Validation

### Auto Runtime Test Gate

```bash
python -m pytest -q tests/test_authority_mode.py tests/test_auto_mode_state.py tests/test_auto_boardroom.py tests/test_auto_plan.py tests/test_auto_run_limits.py tests/test_auto_cycle.py tests/test_auto_input_required_gate.py tests/test_auto_release_gate.py tests/test_auto_result_quality_scoring.py tests/test_auto_done_gate.py tests/test_auto_next_iteration.py tests/test_role_specific_auto_directives.py tests/test_role_specific_result_compliance.py tests/test_quality_aware_auto_plan_selection.py tests/test_auto_loop_dogfood.py
```

Result:

```text
83 passed in 167.47s
```

## Review Notes

- `proposal_only` remains the safe default authority mode.
- `full_authority` is explicit and must be granted.
- proposal_only remains the safe default, and full_authority is explicit only.
- Auto mode uses bounded cycles and respects `--max-steps`.
- Auto result ingestion uses explicit external result files.
- Quality-aware planning can avoid stale or low-quality evidence.
- Release gate uses current evidence and does not let stale blockers dominate newer passing results.
- Auto runtime does not call provider APIs, deploy, access secrets, or apply source patches by itself.

## Slice Verdict

GO for review/staging as Slice 2, provided the staged diff matches only the intended auto runtime files.
