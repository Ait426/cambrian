# Conversational Harness, Workforce & Skill Builder

## 166R Position In The AI Company Runtime

This builder is the installation workshop for Cambrian's AI company runtime.

It does not merely install a preset. It asks questions, designs a harness, generates workforce and skills, prepares authority boundaries, and creates the local operating system that the project AI company will use.

The output of this phase becomes the company structure that auto mode can later operate.

## Product Principle

Cambrian is custom harness first, custom workforce first, and custom skill first.

Preset packs are optional seeds. They are not the default installed product surface.

## Default Flow

```bash
cambrian project scan
cambrian harness interview start
cambrian harness interview answer --answers .cambrian/interview/answers.yaml
cambrian harness engineer design
cambrian harness engineer review
cambrian harness engineer dry-run "로그인 문제 봐줘"
cambrian harness install --confirm
```

The engineer step creates a candidate harness, generated workforce, and generated skills, then reviews quality and simulates dispatch before install. No agent is dispatched during install.

Work starts on demand:

```bash
cambrian job start "로그인 세션 만료 문제 확인해"
```

## How It Works

1. `project scan` detects stack signals such as language, test framework, and domain hints.
2. `harness interview start` creates a small question set for the AI to ask the user.
3. The user answers project-specific questions about goals, test commands, forbidden scope, validation rules, agent roles, and change policy.
4. `harness engineer design` converts those answers into a candidate harness/workforce/skill design.
5. `harness engineer review` checks missing information, quality score, agent-skill coverage, and validation readiness.
6. `harness engineer dry-run` simulates which agents and skills would be selected for a real request without creating a job.
7. `harness install --confirm` writes the harness, workforce, agent, and skill files to `.cambrian/` only after the engineering gate passes.
8. `job start` dispatches generated agents and skills only when the user asks for work.

## Installed Files

```text
.cambrian/profile.yaml
.cambrian/harness.yaml
.cambrian/workforce.yaml
.cambrian/agents/<agent-id>.yaml
.cambrian/skills/<skill-id>.yaml
.cambrian/validation.yaml
.cambrian/operating_rules.yaml
.cambrian/interview/answers.yaml
.cambrian/interview/questions.yaml
.cambrian/plan.yaml
```

## Workforce Boundary

```yaml
dispatch_policy:
  mode: on_demand
  auto_dispatch_on_install: false
```

Generated agents are draft local artifacts until a user starts a job.

Generated skills are draft local artifacts until selected by `job start`.

## Preset Boundary

Presets can appear in `preset_options` during the interview.

They can also be used as a seed:

```bash
cambrian harness design --seed-preset typescript-jest-auth-core
```

This does not install the preset as-is. It only records the preset as reference material for the custom harness and workforce plan.

## Safety Boundary

- No AI provider API call is made.
- No automatic patch apply is performed.
- No git commit is created.
- `harness install` requires `--confirm`.
- `harness install --confirm` also requires an engineering review, dry-run, and quality score of at least 70.
- No agent is dispatched during install.
- Source changes remain a separate human decision.

## Authority And Auto Mode Boundary

After a harness, workforce, and skill set exists, Cambrian can enter auto product organization mode.

```bash
cambrian authority status
cambrian authority grant --mode full-authority
cambrian auto init --goal "제품을 설치형 RC로 완성"
cambrian auto boardroom
cambrian auto plan
cambrian auto run --max-steps 5
```

Authority mode is explicit. The default is `proposal_only`, and `full_authority` is never assumed. Auto mode V1 records organization decisions, plans, blocked steps, and execution proposals; it does not mutate source code, deploy, use secrets, or run an infinite loop.

## Evidence-Based Evolution

Generated harness, workforce, and skills can evolve only after real job evidence exists.

```bash
cambrian job complete latest --outcome partial --notes "refresh token path was missed"
cambrian evolve review --recent 5
cambrian evolve propose
cambrian evolve apply <proposal-id> --confirm
```

Evolution proposals may update local metadata such as:

- `.cambrian/harness.yaml`
- `.cambrian/workforce.yaml`
- `.cambrian/agents/*.yaml`
- `.cambrian/skills/*.yaml`
- `.cambrian/validation.yaml`

Evolution never mutates project source, never edits preset source files, and never applies without `--confirm`.
