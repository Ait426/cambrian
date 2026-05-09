# Product Definition

## 166R Official Definition

Cambrian is an installable AI company runtime that turns each project into an AI company.

한국어:

Cambrian은 각 프로젝트를 AI 회사로 바꾸는 설치형 AI 회사 런타임이다.

사람이 제품 목표를 맡기면 Cambrian은 회사 구조, 역할, 스킬, 의사결정 방식, 권한 규칙, 검증 루프, 실행 체계를 프로젝트 안에 설치한다.

정의:

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

`auth-bug-core`는 첫 seed preset 중 하나일 뿐이며 Cambrian의 제품 정의가 아니다.

## 162R-REPLACE-V3 Conversational harness, workforce and skill builder

Cambrian의 기본 제품 정의는 `custom harness first`, `custom workforce first`, `custom skill first`, `dispatch on demand`입니다.

```text
project scan -> harness interview -> answer ingest -> harness design -> workforce generate -> skill generate -> install with approval
```

작업 실행은 설치와 분리합니다.

```text
job start -> generated agent and skill selection -> AI reply ingest -> job validate -> local evidence
```

개념:

- Harness: 프로젝트에서 AI가 일하는 운영 체계
- Workforce: 이 프로젝트를 위해 생성된 AI 인력 조직
- Agent: 특정 책임을 가진 AI 인력
- Skill: agent가 실제 작업에 사용하는 반복 가능한 작업 능력
- Dispatch: 사용자가 job을 요청했을 때 agent와 skill을 투입하는 행위
- Preset: optional seed/template

프리셋은 참고 템플릿입니다. 최종 설치물은 항상 프로젝트 답변 기반 custom harness, generated workforce, generated skills입니다.

## 162R-REPLACE-V2 Conversational harness and workforce builder

Cambrian의 기본 제품 정의는 `custom harness first`, `custom workforce first`, `dispatch on demand`입니다.

```text
project scan -> harness interview -> answer ingest -> harness design -> workforce generate -> install with approval
```

작업 실행은 설치와 분리합니다.

```text
job start -> generated agent selection -> AI reply ingest -> job validate -> local evidence
```

제품 원칙:

- custom harness first
- custom workforce first
- dispatch on demand
- preset optional seed
- user approval before install
- proposal-only by default
- no automatic patch apply

프리셋은 참고 템플릿입니다. 최종 설치물은 항상 프로젝트 답변 기반 custom harness와 generated workforce입니다.

## 162R Conversational custom harness builder

Cambrian의 기본 제품 흐름은 이제 `custom harness first`입니다.

```text
project scan -> harness interview -> answer ingest -> custom harness plan -> install with approval -> agent dispatch
```

Preset pack은 자동 설치 대상이 아닙니다. `auth-bug-core`와 `typescript-jest-auth-core`는 선택 가능한 seed/reference이며, 실제 설치물은 사용자 답변으로 만든 custom harness입니다.

고정 원칙:

- custom harness first
- preset optional
- user approval before install
- AI-mediated Q&A
- local-first evidence
- no automatic patch apply

## 161R TypeScript/Jest preset correction

Cambrian의 기본 제품 spine은 project-first입니다.

```text
project scan -> harness plan -> harness install -> agent dispatch -> job ingest / validate
```

`auth-bug-core`는 Python + pytest auth bug preset입니다.
`typescript-jest-auth-core`는 TypeScript + Jest auth/API preset입니다.

ONMI-STAY 같은 TypeScript + Jest 프로젝트에는 `auth-bug-core`를 설치하지 않고, `typescript-jest-auth-core`를 추천해야 합니다.

## 0. 160R 제품 축 정정

Cambrian의 본체는 `auth-bug-core` 전용 도구가 아니다.

정정된 제품 정의:

```text
Cambrian은 프로젝트별 맞춤 AI 하네스를 설치하고,
그 하네스 위에 적절한 AI 에이전트/작업반을 파견하는 local-first 실행 시스템이다.
```

기본 제품 spine:

```text
project scan
→ project profile
→ harness plan
→ harness install
→ agent dispatch
→ job ingest / validate
→ local evidence
```

역할 구분:

- `harness`: 프로젝트에 설치된 작업 시스템이다.
- `agent dispatch`: 사용자가 일을 맡기는 기본 행동이다.
- `pack`: built-in preset과 worker/team/template을 배포하는 내부 단위다.
- `auth-bug-core`: Cambrian의 본체가 아니라 첫 built-in harness preset이다.

## 1. 문서 목적

이 문서는 Cambrian이 **정확히 무엇이고 무엇이 아닌지**를 고정하기 위한 문서다.

이 문서는 다음 질문에 답해야 한다.

- Cambrian은 사용자에게 무엇을 제공하는가?
- Cambrian은 외부적으로 어떻게 설명되어야 하는가?
- Cambrian의 내부 정체성은 무엇인가?
- 어떤 문제를 지금 풀고 있고, 어떤 문제는 아직 풀지 않는가?
- 제품의 핵심 단위는 무엇인가?
- 현재 strongest lane은 무엇인가?
- 어떤 기능은 product promise에 포함되고, 어떤 기능은 아직 포함되지 않는가?

이 문서는 기능 문서가 아니라 **제품 경계 정의 문서**다.

---

## 2. Cambrian의 외부 정의

외부적으로 Cambrian은 이렇게 정의한다.

> **Cambrian은 사용자가 이미 쓰는 AI에 검증된 AI 일꾼과 작업반을 설치하고, 실제 결과를 바탕으로 더 좋은 작업 방식으로 계속 진화시키는 시스템이다.**

더 짧은 외부 문장으로는 아래가 좋다.

- **AI Worker Installer**
- **AI 인력 설치기**
- **AI Workforce Runtime**
- **검증된 AI 작업반 설치 시스템**

외부 메시지의 핵심은 “하네스”가 아니라 **설치와 고용**이다.

사용자는 보통 “하네스”를 사지 않는다.
사용자는 다음을 원한다.

- 필요한 AI 일꾼을 바로 쓰고 싶다
- 복잡한 에이전트 설계를 대신해주길 원한다
- 결과가 검증되길 원한다
- 잘된 구성을 반복해서 재사용하고 싶다

따라서 Cambrian은 외부에서
**“AI 위에 일꾼을 설치해주는 제품”** 으로 설명되어야 한다.

---

## 3. Cambrian의 내부 정의

내부적으로 Cambrian은 이렇게 정의한다.

> **Cambrian은 local-first, file-first, evidence-based harness engineering runtime이다.**

이 문장은 다음을 뜻한다.

- **local-first**
  핵심 실행과 상태는 로컬 프로젝트에서 관리된다.

- **file-first**
  중요한 상태는 `.cambrian/` 아래의 artifact로 남는다.

- **evidence-based**
  승격, 추천, canary, promotion, rollback은 증거를 바탕으로 한다.

- **harness engineering runtime**
  단순한 prompt 툴이 아니라, 프로젝트 맞춤 작업복을 설치하고 운영하는 런타임이다.

외부적으로는 “AI worker installer”지만,
내부적으로는 **설치 + 검증 + 진화 엔진**이다.

---

## 4. Cambrian이 제공하는 핵심 가치

Cambrian이 제공하는 가치는 네 가지다.

### 4.1 설치

사용자는 직접 복잡한 에이전트 구성을 설계하지 않아도 된다.
필요한 worker/team/template/lane pack을 고를 수 있다.

### 4.2 실행

설치된 일꾼과 작업반은 사용자의 실제 프로젝트 문맥 안에서 일한다.
Cambrian은 bridge, context, policy, team, template을 통해 작업 환경을 입힌다.

### 4.3 검증

결과는 benchmark, replay, canary, proof pack, metrics로 검증된다.
Cambrian은 “좋아 보이는 것”보다 **실제로 더 나은 것**을 선호한다.

### 4.4 진화

좋았던 실험은 keep, persistent overlay, template evolution, canary, promotion을 통해 다음 기본값이 된다.
나빴던 실험은 rollback, dismiss, retire로 정리된다.

즉 Cambrian은 단순 자동화 툴이 아니라:

> **설치된 AI 일꾼을 실제 성과 데이터로 더 나은 작업반으로 진화시키는 시스템**

이다.

---

## 5. Cambrian이 해결하는 사용자 문제

Cambrian이 해결하는 핵심 문제는 “AI가 약하다”가 아니다.

AI는 이미 강하다.
문제는 사용자가 AI를 **일하게 만드는 설치·배치·검증·개선 구조**를 만들기 어렵다는 점이다.

Cambrian은 다음 문제를 푼다.

### 문제 1. 직접 에이전트를 설계하기 어렵다

대부분 사용자는 아래를 하기 어렵다.

- 어떤 프롬프트와 역할이 좋은지
- 어떤 팀 구성이 좋은지
- 어떤 검증 루프를 붙여야 하는지
- 어떤 기본값을 반복 사용해야 하는지

Cambrian은 이걸 설치 가능한 단위로 바꾼다.

### 문제 2. 잘된 작업 방식이 재사용되지 않는다

오늘 잘된 AI 사용 방식이 내일 다시 재현되지 않는 경우가 많다.
Cambrian은 그것을 template, team, lane, proof, canary, qualification으로 남긴다.

### 문제 3. 실제로 더 좋은지 증명하기 어렵다

Cambrian은 다음을 증명 대상으로 삼는다.

- validated proposal까지 가는가
- adoption되는가
- regression 없이 안전한가
- intervention이 줄어드는가
- 반복할수록 더 좋아지는가

즉 Cambrian은 “AI를 쓰는 법”을 돕는 것이 아니라,
**AI가 실제로 더 잘 일한다는 증거를 만드는 시스템**이다.

---

## 6. 사용자가 실제로 “사는 것”

사용자가 Cambrian에서 실제로 사거나 선택하는 단위는 agent 하나가 아닐 수 있다.
제품 단위는 더 큰 묶음이어야 한다.

### Worker Pack

하나 또는 소수의 agent 묶음.
예: bug-fix-agent + regression-test-agent

### Team Pack

실제 협업을 전제로 한 작업반.
예: auth-bug-team, safe-patch-team

### Template Pack

안전한 기본값과 bias가 담긴 템플릿.
예: auth-bug-template

### Lane Pack

team + template + policy + benchmark까지 포함된 strongest lane 단위 설치 묶음.
초기 제품 단위로는 lane pack이 가장 강하다.

즉 Cambrian은 “에이전트 빌더”보다는 다음에 가깝다.

> **검증된 AI 일꾼과 작업반을 설치 가능한 팩으로 제공하는 시스템**

---

## 7. 핵심 제품 표면

Cambrian의 핵심 제품 표면은 아래 다섯 개다.

### 7.1 Install surface

- pack install
- list installed
- doctor
- current defaults 확인

### 7.2 Work surface

- do / continue
- bridge prepare / ingest / handoff
- validate before apply
- exact next command

### 7.3 Proof surface

- metrics week
- benchmark report
- compare
- replay
- autonomy board
- proof pack

### 7.4 Evolution surface

- bottlenecks
- intervention
- improvement cycle
- keep / dismiss
- persistent overlay
- template evolution

### 7.5 Lane governance surface

- qualification
- canary
- promotion
- rollback
- challenger queue
- lane playbook

이 다섯 surface가 합쳐져 Cambrian을 제품으로 만든다.

---

## 8. Web과 Local Runtime의 관계

Cambrian은 웹 제품처럼 보여야 하지만, 실제 본체는 로컬 runtime이다.

### Web Control Plane

역할:

- catalog
- hiring surface
- install manifest
- recommendation
- future private registry

웹은 **고용과 선택**을 다룬다.

### Local Runtime

역할:

- 실제 설치
- bridge
- do / continue / validate
- benchmark
- canary
- rollback
- persistent learning

로컬 runtime이 진짜 본체다.

즉:

> **웹은 control plane이고, Cambrian 로컬 런타임은 execution engine이다.**

이 경계는 제품 전체에서 절대 흐려지면 안 된다.

---

## 9. AI와 Cambrian의 관계

Cambrian은 AI를 대체하지 않는다.
Cambrian은 AI 위에 입는 작업복이다.

AI는 다음을 한다.

- reasoning
- generation
- analysis
- patch candidate
- plan

Cambrian은 다음을 한다.

- packet 생성
- structured reply contract
- project 문맥 주입
- validation 경계 설정
- benchmark / proof / canary
- 승격 / 철회 / rollback

즉:

> **AI는 노동력이고, Cambrian은 그 노동력을 프로젝트에 안전하게 투입하고 관리하는 운영체계다.**

---

## 10. 현재 strongest lane

Cambrian은 지금 모든 문제를 똑같이 잘 푸는 제품이 아니다.
현재 strongest lane은 명시적으로 좁다.

### Current strongest lane

- Python
- pytest
- narrow auth/login bug fix
- test-first
- narrow-scope
- review-support

이 lane 안에서는:

- 자동화율을 높이기 쉽고
- benchmark를 반복하기 쉽고
- template/team 추천이 선명하며
- canary/promote/rollback 판단도 정교해질 수 있다

외부 메시지는 넓게 가져갈 수 있어도,
실제 제품 증명은 이 lane에서 먼저 해야 한다.

---

## 11. Cambrian이 지금 약속하는 것

현재 Cambrian이 약속하는 것은 아래 정도다.

### 약속 1. AI entry가 가능하다

사용자는 Cambrian packet을 AI에 붙여넣고, structured reply를 다시 Cambrian에 넣을 수 있다.

### 약속 2. patch_candidate는 no-retype path로 이어질 수 있다

AI reply가 usable하면 patch intent draft와 continue validate path로 연결될 수 있다.

### 약속 3. non-patch reply도 운영 문서로 저장할 수 있다

analysis, review, plan은 brief, note, checklist 등으로 materialize될 수 있다.

### 약속 4. 결과는 증명된다

metrics, benchmark, replay, compare, proof pack으로 성과를 검증할 수 있다.

### 약속 5. 좋은 실험은 승격되고, 안 좋은 것은 철회될 수 있다

persistent overlay, template evolution, qualification, canary, rollback이 있다.

---

## 12. Cambrian이 지금 약속하지 않는 것

아직 약속하지 않는 것도 분명히 적어야 한다.

Cambrian은 아직 다음을 약속하지 않는다.

- 모든 분야에서 높은 자동화
- broad multi-language general dominance
- provider-native deep integration
- cloud execution orchestration
- auto apply
- auto adoption
- source code 무인 수정
- 모든 종류의 agent를 자동 생성
- 팀 협업 SaaS 전체 대체

즉 Cambrian은 지금 **강한 설치·검증·진화 시스템**이지,
모든 걸 대신하는 범용 autonomous super-agent가 아니다.

---

## 13. 핵심 성공 기준

Cambrian의 북극성은 다음이다.

**Validated Proposal Rate**

조금 더 풀어쓰면:

> **사용자가 이미 쓰는 AI에 검증된 작업복을 입혔을 때, 사람의 추가 재작성 없이 validated proposal까지 도달하는 비율을 높인다.**

그리고 같이 봐야 하는 핵심 지표는 다음이다.

- human_intervention_rate
- validation_autonomy_rate
- median_time_to_validated_proposal
- team_template_recommendation_hit_rate
- reuse_lift
- repeat_task_improvement_rate

즉 Cambrian의 성공은 “기능 수”가 아니라
**더 안전하고 덜 손가고 더 자주 검증 가능한 결과를 내는가**로 판단해야 한다.

---

## 14. Cambrian이 아닌 것

이 문장이 중요하다.

Cambrian은:

- prompt 저장소가 아니다
- generic no-code agent builder가 아니다
- 그냥 AI 직원 수를 늘려주는 도구가 아니다
- 클라우드 orchestration SaaS가 아니다
- 무인 코드 수정 엔진이 아니다

Cambrian은:

> **AI를 프로젝트에 설치 가능한 일꾼 단위로 바꾸고, 그 일꾼의 실제 성과를 증거 기반으로 계속 개선하는 로컬 runtime**

이다.

---

## 15. 제품 정의의 최종 문장

한 문장으로 가장 압축하면 이렇게 정의한다.

> **Cambrian은 사용자가 이미 쓰는 AI에 검증된 AI 일꾼과 작업반을 설치하고, benchmark·canary·rollback을 통해 더 좋은 기본값으로 계속 진화시키는 evidence-based local runtime이다.**
