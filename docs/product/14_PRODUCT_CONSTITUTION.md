# Cambrian Product Constitution

## Current Product Identity

Cambrian is an installable AI company runtime.
Every project becomes an AI company.

Cambrian은 각 프로젝트를 AI 회사로 바꾸는 설치형 AI 회사 런타임이다.
Cambrian은 인간의 외주를 받아 제품을 만드는 AI 회사다.

## Constitution

1. Cambrian installs an AI company inside each project.
2. The installed AI company contains a harness, workforce, agents, skills, authority rules, evidence, validation, boardroom decisions, and evolution history.
3. Claude, Codex, Cursor, GPT, and local models are execution engines. They are not the product identity.
4. Presets are optional seeds. They are not the default installation unit.
5. `auth-bug-core` is a seed preset for a narrow Python + pytest auth/login lane. It is not Cambrian's product center.
6. `typescript-jest-auth-core` is a seed preset for TypeScript + Jest auth/API projects. It is not Cambrian's product center.
7. The default install flow is custom AI company creation, not direct pack installation.
8. Installation does not dispatch agents automatically.
9. Work starts only when the user creates a job.
10. Source changes, git operations, deployment, secret access, payment, and external network use require explicit authority and safety gates.

## Canonical Flow

```text
project scan
-> harness interview
-> harness engineering
-> workforce generation
-> skill generation
-> authority profile
-> auto mode
-> boardroom decision
-> execution plan
-> job start
-> validation
-> evidence
-> evolution
```

## Public CLI Spine

```bash
cambrian project scan
cambrian harness interview start
cambrian harness engineer design
cambrian harness engineer review
cambrian harness engineer dry-run "로그인 문제 봐줘"
cambrian workforce generate
cambrian skill generate
cambrian harness install --confirm
cambrian authority grant --mode full-authority
cambrian auto init --goal "Build this product"
cambrian auto boardroom
cambrian auto plan
cambrian auto run --max-steps 5
cambrian job start "Fix the login issue"
```

## Legacy Compatibility Vocabulary

Older documents and tests may still mention these terms:

- AI Worker Installer
- AI 인력 설치기
- AI 작업반 설치 시스템
- worker pack
- team pack
- template pack
- lane pack
- auth-bug-core

These terms are compatibility vocabulary. They may remain in historical docs, pack compatibility docs, and seed preset docs, but they must not define the product center.

Current interpretation:

- worker pack: old distribution language for a seed/preset bundle
- team pack: old compatibility language for a reusable team template
- template pack: old compatibility language for a reusable harness template
- lane pack: old compatibility language for a validated narrow lane
- AI Worker Installer: old public wedge, superseded by installable AI company runtime

## Non-Goals For V1

- no automatic provider API call
- no automatic patch apply
- no automatic git commit or push
- no production deployment automation
- no secret auto-use
- no payment or marketplace promise
- no remote registry dependency for the core local runtime

## Product Test

If a feature does not help a project create, operate, validate, or evolve its local AI company, it is not part of the core product spine.
