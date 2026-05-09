# Harness Workforce Skill Slice Readiness

## Purpose

This document records the readiness of the third recommended commit slice from `COMMIT_SLICING_PLAN.md`.

Slice 3 covers Cambrian's conversational harness builder, harness engineering gate, generated workforce, generated skills, on-demand job start, and evidence-based local evolution loop.

## Slice

Suggested commit:

```text
feat(harness): conversational harness workforce skill system
```

## Include

- `engine/project_harness_profile.py`
- `engine/project_harness_interview.py`
- `engine/project_harness_plan.py`
- `engine/project_harness_engineering.py`
- `engine/project_custom_harness.py`
- `engine/project_workforce_builder.py`
- `engine/project_skill_builder.py`
- `engine/project_agent_dispatch.py`
- `engine/project_evidence.py`
- `engine/project_evolution.py`
- project scan, interview, design, review, dry-run, install, workforce, skill, dispatch, job start, and evolution tests

## Do Not Include

- installed wheel pack catalog fixes
- authority and auto runtime source files
- pack/template/benchmark advanced surfaces
- launch or pilot copy unrelated to harness creation
- `.cambrian/` runtime evidence unless intentionally committing evidence
- private local project files
- `.env` or secret files

## Validation

### Harness Workforce Skill Test Gate

```bash
python -m pytest -q tests/test_project_harness_profile.py tests/test_project_harness_plan.py tests/test_project_agent_dispatch.py tests/test_pack_compatibility.py tests/test_typescript_jest_auth_harness.py tests/test_harness_interview.py tests/test_custom_harness_from_answers.py tests/test_harness_install_requires_approval.py tests/test_harness_engineer_design.py tests/test_harness_engineer_review.py tests/test_harness_engineer_dry_run.py tests/test_harness_install_requires_engineering_gate.py tests/test_workforce_builder.py tests/test_agent_generation.py tests/test_skill_generation.py tests/test_job_start_selects_agents_and_skills.py tests/test_job_start_runtime_contract.py tests/test_dispatch_on_demand.py tests/test_preset_as_optional_seed.py tests/test_job_complete_evidence.py tests/test_evolution_review.py tests/test_evolution_proposal.py tests/test_evolution_apply_requires_confirm.py tests/test_skill_evolution.py tests/test_ai_company_bootstrap.py
```

Result:

```text
59 passed in 138.72s
```

## Review Notes

- Custom harness creation is the primary user-facing path.
- Presets remain optional seeds, not the default installation unit.
- Harness install requires approval and engineering gate evidence.
- Install creates harness, workforce, agents, skills, validation, and operating rules.
- Install does not dispatch agents.
- `job start` dispatches on demand and returns selected agents and selected skills.
- Evolution proposals require evidence and confirmation before metadata changes.
- This slice does not call provider APIs, deploy, access secrets, or apply source patches by itself.

## Slice Verdict

GO for review/staging as Slice 3, provided the staged diff matches only the intended harness, workforce, skill, job, and evolution files.
