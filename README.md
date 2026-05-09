# Cambrian

Cambrian is an installable AI company runtime.
Every project becomes an AI company.

It turns each project into an AI company that can plan, build, validate, and evolve a product using Claude, Codex, or other AI execution engines.

Cambrian은 인간의 외주를 받아 제품을 만드는 AI 회사다.
Cambrian을 설치하는 순간 매 프로젝트는 하나의 AI 회사가 된다.

사용자가 제품 목표를 맡기면 Cambrian은 그 프로젝트 안에 AI 회사를 세웁니다. 그 회사는 CEO, CTO, COO, PM, 엔지니어, QA, 릴리즈 매니저 역할을 만들고, 하네스·인력·스킬·권한·검증·진화 루프를 통해 제품을 끝까지 만듭니다.

## Install from local wheel

PyPI 배포 전 RC는 로컬 wheel로 설치합니다.

```bash
python -m pip install build
python -m build
python -m pip install dist/*.whl
```

## Quickstart

Core flow:

```bash
cambrian doctor
cambrian project scan
cambrian harness interview start
cambrian harness interview answer --answers .cambrian/interview/answers.yaml
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
```

`project scan`과 `harness interview`는 프로젝트의 목적, 구조, 금지 범위, 검증 기준을 모읍니다. `harness engineer design/review/dry-run`은 설치 전 하네스·인력·스킬 설계를 검수합니다. `authority`는 AI 회사에 부여할 실행 권한을 정의하고, `auto`는 boardroom decision, plan, bounded run, evidence를 기록합니다.

설치 직후에는 어떤 agent도 자동 파견하지 않습니다. 오토 모드도 V1에서는 source code를 자동 수정하지 않고 실행 계획과 evidence를 남깁니다.

AI company bootstrap details are documented in [AI Company Bootstrap](docs/product/15_AI_COMPANY_BOOTSTRAP.md).

## Manual Job Mode

```bash
cambrian job start "로그인 세션 만료 문제 확인해" --json
```

`job start`는 설치된 AI 회사의 `.cambrian/workforce.yaml`과 `.cambrian/skills/*.yaml`을 읽고 필요한 agent와 skill을 선택합니다. 이 단계는 AI provider를 호출하지 않고 source code를 수정하지 않습니다. 대신 request packet과 job record를 만들고, AI 답변을 저장한 뒤 실행할 `job ingest` / `job validate` 명령을 보여줍니다.

런타임 계약은 [Job Start Runtime Contract](docs/product/16_JOB_START_RUNTIME_CONTRACT.md)에 고정되어 있습니다.
Codex/Claude에 넘기는 request packet 계약은 [Codex / Claude Request Packet Contract](docs/product/17_CODEX_CLAUDE_REQUEST_PACKET.md)에 고정되어 있습니다.
AI 응답을 다시 받아들이는 계약은 [AI Reply Ingest Contract](docs/product/18_AI_REPLY_INGEST_CONTRACT.md)에 고정되어 있습니다.
AI 응답 검증과 evidence/trust gate 계약은 [Job Validate Trust Gate](docs/product/19_JOB_VALIDATE_TRUST_GATE.md)에 고정되어 있습니다.
사람이 검증 결과를 기록하고 evolution 입력으로 넘기는 계약은 [Job Complete Outcome Contract](docs/product/20_JOB_COMPLETE_OUTCOME_CONTRACT.md)에 고정되어 있습니다.
outcome evidence를 진화 신호로 요약하는 계약은 [Evolution Review Signal Contract](docs/product/21_EVOLUTION_REVIEW_SIGNAL_CONTRACT.md)에 고정되어 있습니다.
진화 제안을 적용 전에 검토하는 계약은 [Evolution Proposal Preview Contract](docs/product/22_EVOLUTION_PROPOSAL_PREVIEW_CONTRACT.md)에 고정되어 있습니다.
진화 적용의 감사 manifest와 rollback hint 계약은 [Evolution Apply Audit Contract](docs/product/23_EVOLUTION_APPLY_AUDIT_CONTRACT.md)에 고정되어 있습니다.
진화 적용을 되돌리는 metadata rollback 계약은 [Evolution Rollback Contract](docs/product/24_EVOLUTION_ROLLBACK_CONTRACT.md)에 고정되어 있습니다.

## AI Company Pieces

- A project-specific harness is the operating system inside the installed AI company.
- AI Company: Cambrian이 프로젝트 안에 설치하는 실행 조직
- Harness: AI 회사가 일하는 운영 체계
- Workforce: 프로젝트를 위해 생성된 AI 인력 조직
- Agent: 회사 내 역할을 가진 AI 인력
- Skill: 인력이 사용하는 반복 가능한 작업 능력
- Boardroom: CEO/CTO/COO/PM 등 의사결정 회의 구조
- Authority Mode: 사용자가 AI 회사에 부여한 실행 권한 범위
- Auto Mode: AI 회사가 제품 제작 전 과정을 자동 운영하는 모드
- Claude / Codex: Cambrian이 사용하는 실행 엔진
- Preset: 선택 가능한 참고 템플릿. 기본 설치물이 아님.

Compatibility aliases remain available but are not the default AI company runtime flow:

```bash
cambrian harness plan
cambrian agent dispatch "로그인 에러 수정해"
```

## Validate a canned AI reply

```bash
cambrian demo create login-bug --out ./auth-bug-demo
cd ./auth-bug-demo
cambrian job ingest latest fixtures/ai_reply_patch_candidate.yaml
cambrian job validate latest
```

이 검증은 실제 AI provider를 호출하지 않고 준비된 AI 답변 fixture를 사용합니다. `job validate`는 검증 handoff를 확인하지만 source code를 자동 적용하지 않습니다.

## Evidence-based evolution

작업 결과는 사람이 명시적으로 기록하고, Cambrian은 그 evidence를 바탕으로 하네스/인력/스킬 진화 제안만 만듭니다. 적용은 항상 사용자 승인 후 로컬 `.cambrian/` metadata에만 반영됩니다.

```bash
cambrian job complete latest --outcome partial --notes "test command가 틀렸고 refresh token 경로를 놓쳤음"
cambrian evolve review --recent 5
cambrian evolve propose
cambrian evolve apply <proposal-id> --confirm
```

`evolve apply`는 source code, preset 원본, provider API를 건드리지 않습니다.

## Authority and auto mode

Cambrian은 기본적으로 `proposal_only` 권한으로 동작합니다. 오토 제품 제작 모드는 명시 권한 프로파일 안에서만 상태, 회의, 계획, 실행 제안을 기록합니다.

```bash
cambrian authority status
cambrian authority grant --mode full-authority
cambrian auto init --goal "제품을 설치형 RC로 완성"
cambrian auto boardroom
cambrian auto plan
cambrian auto run --max-steps 5
```

V1 auto mode는 무한 자동 실행기가 아닙니다. CEO/CTO/COO/PM/Engineering/QA/Release 역할의 boardroom decision, bounded plan, execution log를 `.cambrian/auto/`와 `.cambrian/evidence/`에 남기며 source code, secret, deploy, payment는 자동 처리하지 않습니다.
`auto run`이 Codex/Claude 작업지시서를 만들고 결과 대기 상태로 남기는 계약은 [Auto Task Directive Bridge](docs/product/25_AUTO_TASK_DIRECTIVE_BRIDGE.md)에 고정되어 있습니다.
Codex/Claude 결과 파일을 다시 받아 auto task와 execution log에 반영하는 계약은 [Auto Step Result Intake](docs/product/26_AUTO_STEP_RESULT_INTAKE.md)에 고정되어 있습니다.
수집된 결과를 다음 boardroom/plan/release 판단으로 넘기는 보고 계약은 [Auto Result Report Handoff](docs/product/27_AUTO_RESULT_REPORT_HANDOFF.md)에 고정되어 있습니다.
boardroom이 auto report evidence를 읽고 다음 회의 agenda와 role decision을 만드는 계약은 [Auto Boardroom Report Review](docs/product/28_AUTO_BOARDROOM_REPORT_REVIEW.md)에 고정되어 있습니다.
boardroom handoff를 recovery/validation/release/next plan step으로 바꾸는 계약은 [Auto Plan From Handoff](docs/product/29_AUTO_PLAN_FROM_HANDOFF.md)에 고정되어 있습니다.
`report → boardroom → plan → run`을 안전한 한 사이클로 묶는 계약은 [Auto Cycle Command](docs/product/30_AUTO_CYCLE_COMMAND.md)에 고정되어 있습니다.
Codex/Claude result 파일의 필수 필드와 타입 검증 계약은 [Codex Result Contract Hardening](docs/product/31_CODEX_RESULT_CONTRACT_HARDENING.md)에 고정되어 있습니다.

Auto loop completion gate is fixed in [Auto Loop Done Gate](docs/product/32_AUTO_LOOP_DONE_GATE.md).
Next iteration startup after `DONE` is fixed in [Auto Next Iteration Gate](docs/product/33_AUTO_NEXT_ITERATION_GATE.md).
Role-specific auto task directives are fixed in [Role-Specific Auto Directives](docs/product/34_ROLE_SPECIFIC_AUTO_DIRECTIVES.md).
Role-specific result compliance is fixed in [Role-Specific Result Compliance](docs/product/35_ROLE_SPECIFIC_RESULT_COMPLIANCE.md).
Auto result quality scoring is fixed in [Auto Result Quality Scoring](docs/product/36_AUTO_RESULT_QUALITY_SCORING.md).
Quality-aware auto plan selection is fixed in [Quality-Aware Auto Plan Selection](docs/product/37_QUALITY_AWARE_AUTO_PLAN_SELECTION.md).
Release gate evidence packaging is fixed in [Release Gate Evidence Package](docs/product/38_RELEASE_GATE_EVIDENCE_PACKAGE.md).
Release gate verdict routing is fixed in [Release Gate Decision Loop](docs/product/39_RELEASE_GATE_DECISION_LOOP.md).
Auto iteration archive and fresh-start boundaries are fixed in [Auto Iteration Archive Fresh Start Contract](docs/product/40_AUTO_ITERATION_ARCHIVE_FRESH_START.md).
Explicit next goal selection is fixed in [Explicit Next Goal Contract](docs/product/41_EXPLICIT_NEXT_GOAL_CONTRACT.md).

## Fresh install RC verification

```bash
python scripts/smoke_installed_wheel.py
```

이 smoke는 fresh venv에 wheel을 설치한 뒤 built-in harness preset 경로를 실행합니다. 자세한 설치 가이드는 [RC Install Guide](docs/release/RC_INSTALL_GUIDE.md)를 보세요.

## Built-in preset seeds

## Built-in preset compatibility

Cambrian shows compatible preset options during the interview, but it does not install a preset automatically.
For Python + pytest auth projects, `auth-bug-core` can be used as a seed.
For TypeScript + Jest auth/API projects, `typescript-jest-auth-core` can be used as a seed.

`auth-bug-core`는 Cambrian의 제품 중심이 아니라 Python + pytest auth/login 계열을 위한 built-in seed preset입니다.

기존 pack 명령은 계속 지원됩니다. 단, 기본 제품 흐름은 pack 설치가 아니라 `project scan → harness interview → harness engineering → workforce/skill generation → authority → auto mode`입니다.

```bash
cambrian pack list
cambrian pack show auth-bug-core
cambrian install pack auth-bug-core
cambrian pack activate auth-bug-core
cambrian pack start "로그인 에러 수정해"
```

이 경로는 호환/내부 distribution 경로입니다. 새 제품 spine은 `AI company runtime, custom harness first, preset optional seed`입니다.

## Product run docs

- First run runbook: [docs/launch/DEMO_RUNBOOK.md](docs/launch/DEMO_RUNBOOK.md)
- Public demo kit: [docs/launch/PUBLIC_DEMO_KIT.md](docs/launch/PUBLIC_DEMO_KIT.md)
- Public product assets: [docs/launch/DEMO_ASSETS.md](docs/launch/DEMO_ASSETS.md)
- RC checklist: [docs/release/RC_CHECKLIST.md](docs/release/RC_CHECKLIST.md)
- RC verification: [docs/release/RC_VERIFICATION.md](docs/release/RC_VERIFICATION.md)
- Dogfood runbook: [docs/release/DOGFOOD_RUNBOOK.md](docs/release/DOGFOOD_RUNBOOK.md)
- Pilot outreach kit: [docs/launch/PILOT_OUTREACH_KIT.md](docs/launch/PILOT_OUTREACH_KIT.md)
- Pilot learning board: [docs/launch/PILOT_LEARNING_BOARD.md](docs/launch/PILOT_LEARNING_BOARD.md)

Reproducible product run:

```bash
python tools/run_launch_demo.py
```

### Private pilot

For invite messages, interview guide, and feedback templates, see [Pilot Outreach Kit](docs/launch/PILOT_OUTREACH_KIT.md).

## What The Product Run Shows

- `project scan`: 현재 프로젝트를 AI company 설치 대상으로 분석
- `harness interview start`: AI-mediated Q&A용 질문 세트 생성
- `harness engineer design`: AI 회사의 하네스/인력/스킬 설계 후보 생성
- `harness engineer review`: 초기 회사 설계 품질 검수
- `harness engineer dry-run`: 실제 job 생성 없이 투입 인력과 스킬 시뮬레이션
- `workforce generate`: 프로젝트별 AI 인력 조직 생성
- `skill generate`: 인력이 사용할 프로젝트별 스킬 생성
- `authority grant`: AI 회사의 실행 권한 범위 정의
- `auto boardroom`: CEO/CTO/COO/PM 등 의사결정 회의 기록
- `auto plan`: 의사결정을 실행 계획으로 변환
- `auto run`: 제한된 step 안에서 실행 제안과 evidence 기록

Compatibility/history terms:

- `project scan`: 현재 프로젝트 profile 생성
- `harness interview start`: AI-mediated Q&A용 질문 세트 생성
- `harness interview answer`: 사용자 답변 검증
- `harness plan`: 답변 기반 custom harness draft 생성
- `harness install --confirm`: 승인 후 `.cambrian/`에 custom harness 설치
- `agent dispatch`: 설치된 custom harness에 에이전트/작업반 파견
- `auth-bug-core`: Python + pytest + auth/login narrow bug fix에 맞춘 첫 built-in harness preset
- 포함 worker: `bug-fix-agent`, `regression-test-agent`, `review-agent`
- 포함 team/template/workset: `auth-bug-team`, `auth-bug-template`, `auth-bug-workset`
- 로컬 runtime: scan, plan, install, dispatch, ingest, validate 실행

## Safety Boundary

- AI provider API를 직접 호출하지 않습니다.
- source code execution이나 cloud patch/apply를 하지 않습니다.
- `pack start`와 `pack job-paste`는 source code를 mutate하지 않습니다.
- source 변경은 explicit apply/adoption 흐름에서만 다룹니다.
- `cambrian pack job-apply <job-id>`는 preview이고, 실제 apply는 `cambrian pack job-apply <job-id> --confirm`이 필요합니다.
- adoption은 `cambrian pack job-adopt <job-id> --accepted|--rejected|--skipped`로 명시적으로 기록합니다.

## Web Pack Catalog MVP

정적 웹 catalog는 Cambrian의 첫 control plane입니다.

- `web/`
- `web/assets/catalog.json`
- `web/assets/auth-bug-core.cambrian-pack.yaml`
- `python tools/generate_web_catalog.py`
- `packs/catalog.yaml`

The web catalog is the hiring desk. Your local Cambrian runtime does the actual install, job handoff, validation, and proof. This page does not execute code or mutate `.cambrian/` state.

## Product Docs

긴 제품 정의와 고급 lifecycle은 launch run 밖으로 뺐습니다.

- [Alpha install](docs/ALPHA_INSTALL.md)
- [Product index](docs/product/00_INDEX.md)
- [AI company runtime](docs/product/13_AI_COMPANY_RUNTIME.md)
- [Packs and install](docs/product/06_PACKS_AND_INSTALL.md)
- [Execution loops](docs/product/07_EXECUTION_LOOPS.md)
- [Metrics and proof](docs/product/08_METRICS_AND_PROOF.md)
- [Harness engineering system](docs/product/12_HARNESS_ENGINEERING_SYSTEM.md)
- [Launch golden path](docs/launch/LAUNCH_GOLDEN_PATH.md)
- [Product walkthrough script](docs/launch/DEMO_SCRIPT.md)
- [First run runbook](docs/launch/DEMO_RUNBOOK.md)
- [Launch checklist](docs/launch/LAUNCH_CHECKLIST.md)

## Current strongest lane

Current strongest lane:

```text
Python + pytest + auth/login narrow bug fix
```

- Default team: `auth-bug-team`
- Default template: `auth-bug-template`
- Default workset: `auth-bug-workset`
- Outside this lane, Cambrian should warn instead of pretending confidence.

## Compatibility Reference

Cambrian is also described in the product docs as an AI workforce runtime, harness engineering runtime, and evidence-based evolution engine. The launch surface keeps those terms below the fold because the first message is simpler: install AI workers into the AI you already use.

The Web control plane is the hiring desk. The Local Cambrian runtime performs local install, job handoff, validation, and proof. Broader lifecycle commands stay below the launch path.

Security note: Mode B skill execution can use an optional Docker container sandbox. The container sandbox disables network access by default, mounts the skill read-only, applies memory/CPU/PID limits, and uses a read-only root filesystem when enabled. The launch run does not require the sandbox path, but the safety boundary remains documented for local execution.

## Implemented Reference Commands Outside The Launch Path

아래 명령은 제품 문서와 호환되는 구현 참고입니다. 출시 데모의 첫 화면에서는 사용하지 않습니다.

```bash
cambrian pack next
cambrian install diff auth-bug-core
cambrian install update auth-bug-core
cambrian uninstall pack auth-bug-core
cambrian pack verify auth-bug-core
cambrian install verify
cambrian install verify auth-bug-core
cambrian pack draft auth-bug-core-local
cambrian pack build
cambrian pack publish-local
cambrian pack release-check --require-proof
cambrian pack web-sync
cambrian registry add local-web web/assets/catalog.json
cambrian registry sync local-web
cambrian pack search auth --registry local-web
cambrian install pack auth-bug-core --registry local-web
cambrian install plan cambrian/auth-bug-core@0.2.0 --registry official
cambrian install pack cambrian/auth-bug-core@0.2.0 --registry official --confirm-deps
```

Remote/web registry update is still planned for broader distribution. Static pull, manifest digest checks, no login, no payment, no cloud execution, and no source upload are the current boundary. Namespace, version, dependencies, `.cambrian/install/pack_lock.yaml`, `.cambrian/install/graphs/`, complex npm-style semver, dependency auto-update cascade, SHA-256, `--require-trusted`, and cryptographic signing are tracked in product docs.
