# AI Company Bootstrap

## Purpose

AI Company Bootstrap is the installation flow that turns a normal project into a local Cambrian AI company.

It does not install a preset directly.
It creates a project-specific harness, generated workforce, generated skills, authority profile, validation rules, and evidence-ready operating files under `.cambrian/`.

## Canonical Bootstrap Flow

```bash
cambrian project scan --json
cambrian harness interview start --json
cambrian harness interview answer --answers .cambrian/interview/answers.yaml --json
cambrian harness engineer design --json
cambrian harness engineer review --json
cambrian harness engineer dry-run "로그인 문제 봐줘" --json
cambrian workforce generate --json
cambrian skill generate --json
cambrian harness install --confirm --json
```

## Installed AI Company Files

After a valid install, the project should contain:

```text
.cambrian/profile.yaml
.cambrian/harness.yaml
.cambrian/workforce.yaml
.cambrian/agents/*.yaml
.cambrian/skills/*.yaml
.cambrian/validation.yaml
.cambrian/operating_rules.yaml
.cambrian/authority.yaml
.cambrian/interview/questions.yaml
.cambrian/interview/answers.yaml
.cambrian/engineering/design_candidate.yaml
.cambrian/engineering/review.yaml
.cambrian/engineering/dry_run.yaml
.cambrian/plan.yaml
```

## Authority Default

Bootstrap creates `.cambrian/authority.yaml` when it is missing.
The default mode is `proposal_only`.

If a project already has `full_authority`, bootstrap preserves it and does not downgrade it.

## Install Gate

`cambrian harness install --confirm` requires:

- a design candidate
- a successful engineering review
- at least one engineering dry-run
- quality score of at least 70
- explicit `--confirm`

If the gate is not passed, install returns `engineering_gate_not_passed`.

## Dispatch Boundary

Bootstrap does not dispatch agents.
Bootstrap does not create a job.
Bootstrap does not call an AI provider.
Bootstrap does not modify source code.

Work starts only when the user runs:

```bash
cambrian job start "원하는 작업"
```

## Preset Boundary

Presets such as `auth-bug-core` and `typescript-jest-auth-core` may be used as optional seeds.
They are not the installed company.
The installed result is always a custom project AI company.
