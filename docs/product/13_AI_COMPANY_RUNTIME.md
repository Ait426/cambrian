# AI Company Runtime

## One-Line Definition

Cambrian is an installable AI company runtime that turns each project into an AI company.

한국어:

Cambrian은 각 프로젝트를 AI 회사로 바꾸는 설치형 AI 회사 런타임이다.

## User-Facing Explanation

A human outsources a product goal to Cambrian.
Cambrian creates the company structure, roles, skills, decision process, authority rules, validation loop, and execution system needed to build that product.

한국어:

사용자가 제품 목표를 맡기면 Cambrian은 그 프로젝트 안에 AI 회사를 세운다.
그 회사는 CEO, CTO, COO, PM, 엔지니어, QA, 릴리즈 매니저 역할을 만들고, 하네스·인력·스킬·권한·검증·진화 루프를 통해 제품을 끝까지 만든다.

## Core Model

```text
project scan
-> harness interview
-> harness engineering
-> workforce generation
-> skill generation
-> authority mode
-> auto mode
-> boardroom decision
-> execution
-> validation
-> release gate
-> evolution
```

## Concepts

- AI Company: Cambrian이 프로젝트 안에 설치하는 실행 조직
- Harness: AI 회사가 일하는 운영 체계
- Workforce: 프로젝트를 위해 생성된 AI 인력 조직
- Agent: 회사 내 역할을 가진 AI 인력
- Skill: 인력이 사용하는 반복 가능한 작업 능력
- Boardroom: CEO/CTO/COO/PM 등 의사결정 회의 구조
- Authority Mode: 사용자가 AI 회사에 부여한 실행 권한 범위
- Auto Mode: AI 회사가 제품 제작 전 과정을 자동 운영하는 모드
- Claude / Codex: Cambrian이 사용하는 실행 엔진
- Preset: 선택 가능한 참고 템플릿. 기본 설치물이 아님

## Execution Engines

Claude, Codex, Cursor, GPT, or local models are execution engines.
They are not the product identity.

Cambrian installs the project-specific AI company that tells those engines what roles exist, what rules apply, what skills are available, what authority is granted, what evidence must be recorded, and what release gates must pass.

## Preset Boundary

Preset packs such as `auth-bug-core` and `typescript-jest-auth-core` are optional seeds.
They are not the default installation unit and they are not the product center.

The default product experience is AI company installation:

```bash
cambrian project scan
cambrian harness interview start
cambrian harness engineer design
cambrian workforce generate
cambrian skill generate
cambrian authority grant --mode full-authority
cambrian auto init --goal "Build this product"
cambrian auto boardroom
cambrian auto plan
cambrian auto run --max-steps 5
```

## Safety Boundary

- no provider API call by default
- no automatic patch apply
- no automatic git commit
- no production deploy automation in V1
- no secret auto-use
- no marketplace, payment, or remote registry promise in the core identity
- full authority is explicit, never assumed

## Product Identity

Before Cambrian:

```text
a project is just a project
```

After Cambrian:

```text
the project has an AI company inside it
```

Auto mode:

```text
that AI company plans, executes, validates, records evidence, and evolves
```
