# Product Thesis

## 166R Product Identity

Cambrian is an installable AI company runtime.
Every project becomes an AI company.

Cambrian은 인간의 외주를 받아 제품을 만드는 AI 회사다.
Cambrian을 설치하는 순간 매 프로젝트는 하나의 AI 회사가 된다.

사용자가 제품 목표를 맡기면 Cambrian은 그 프로젝트 안에 AI 회사를 세운다. 그 회사는 CEO, CTO, COO, PM, 엔지니어, QA, 릴리즈 매니저 역할을 만들고, 하네스·인력·스킬·권한·검증·진화 루프를 통해 제품을 끝까지 만든다.

`auth-bug-core` 같은 preset은 선택 가능한 참고 템플릿이다. Cambrian의 제품 중심은 preset 설치가 아니라 프로젝트별 AI company 설치다.

## 1. 한 문장 정의

**Cambrian은 각 프로젝트를 AI 회사로 바꾸는 설치형 AI 회사 런타임이다.**

사용자가 제품 목표를 맡기면 Cambrian은 프로젝트 안에 회사 구조, 역할, 스킬, 권한, 검증 루프, evidence, 진화 루프를 설치한다.

`AI Worker Installer`와 `evidence-based harness engineering runtime`은 과거 wedge/내부 구현 언어다. 현재 제품 정의에서는 legacy compatibility vocabulary로만 다룬다.

---

## 2. 왜 이 제품이 필요한가

AI는 이미 충분히 강하다.
문제는 대부분의 사용자가 **AI를 “일하게 만드는 법”** 을 모른다는 점이다.

대부분 사용자는 다음에서 막힌다.

- 어떤 프롬프트와 어떤 역할 분리가 좋은지 모른다.
- 여러 에이전트나 작업반을 어떻게 구성할지 모른다.
- 내 프로젝트 문맥을 AI에게 어떻게 입혀야 할지 모른다.
- 결과를 어떻게 검증하고 반복 개선할지 모른다.
- 한번 잘된 설정을 다음 프로젝트에 어떻게 재사용할지 모른다.

즉 사용자의 진짜 문제는
**“AI가 없어서”** 가 아니라
**“AI를 안정적인 일꾼으로 설치·배치·검증·진화시키기 너무 어렵다”** 는 데 있다.

Cambrian은 이 문제를 푼다.

---

## 3. 핵심 가설

### 3.1 시장은 에이전트를 더 만드는 도구보다, 프로젝트에 AI 회사를 세우는 경험을 원한다

대부분의 사람은 “에이전트를 설계”하고 싶어하지 않는다.
대부분의 사람은 그냥 이렇게 생각한다.

- 이 프로젝트 목표를 이해하는 AI 회사를 세워줘
- CEO/CTO/PM/엔지니어/QA 역할이 나눠진 상태로 일하게 해줘
- 검증과 evidence를 남기면서 제품 완성까지 밀어줘

Cambrian은 이 욕구를 직접 겨냥한다.

### 3.2 AI는 모델 하나로 끝나지 않고, 설치 가능한 회사 운영 단위가 되어야 한다

AI는 단순 채팅 모델이 아니라 다음 단위로 다뤄져야 한다.

- AI Company
- Harness
- Workforce
- Agent
- Skill
- Boardroom
- Authority Mode
- Auto Mode

즉 사용자는 모델을 직접 조립하는 것이 아니라,
**프로젝트별 AI company를 설치** 해야 한다.

`worker pack`, `team pack`, `template pack`, `lane pack`은 seed/preset 호환 용어로 남긴다.

### 3.3 진짜 차별점은 생성이 아니라 검증과 진화다

AI 에이전트를 만들게 해주는 제품은 많다.
하지만 실제로 중요한 것은 다음이다.

- 이 일꾼이 진짜 잘 일하는가
- raw AI보다 더 좋은 결과를 내는가
- validated proposal까지 더 자주 가는가
- 반복할수록 더 좋아지는가
- 안 좋으면 되돌릴 수 있는가

Cambrian은 “만들기”보다 **증거 기반 승격과 철회** 에 집중한다.

### 3.4 좋은 실험은 다음 프로젝트의 기본값이 되어야 한다

Cambrian은 한 프로젝트 안에서만 잘 도는 시스템이 아니다.
좋은 실험은 다음 순서로 승격되어야 한다.

- intervention
- keep / dismiss
- persistent overlay
- template evolution
- qualification
- canary
- promotion
- rollback

즉 Cambrian의 진짜 가치 중 하나는
**좋은 결과를 다음 기본 옷으로 바꾸는 것** 이다.

---

## 4. 외부 제품 언어와 내부 제품 언어

### 외부 제품 언어

사용자에게는 Cambrian을 이렇게 설명해야 한다.

- 프로젝트 안에 AI 회사를 설치하세요
- 제품 목표를 맡기면 AI 회사가 계획, 실행, 검증, 진화를 기록합니다
- Claude/Codex를 회사 역할과 절차를 가진 실행 엔진으로 사용하세요
- 필요한 때 job을 시작하면 적절한 agent와 skill이 투입됩니다

### 내부 제품 언어

내부적으로 Cambrian은 이렇게 정의한다.

- installable AI company runtime
- project-specific harness engineering system
- generated workforce and skill system
- authority and auto mode runtime
- evidence, validation, and evolution layer

이 둘은 충돌하지 않는다.
외부에는 쉬운 언어가 필요하고, 내부에는 정확한 구조가 필요하다.

Legacy compatibility vocabulary:

- AI Worker Installer
- AI 인력 설치기
- AI 작업반 설치 시스템
- worker pack
- team pack
- template pack
- lane pack

---

## 5. Cambrian이 해결하는 핵심 문제

### 문제 1. AI는 똑똑하지만, 프로젝트에 맞게 입혀져 있지 않다

모델은 일반 지능에 가깝지만,
실제 프로젝트에서 일하려면 다음이 필요하다.

- 프로젝트 문맥
- 팀/템플릿/정책
- 검증 습관
- safe defaults
- 반복 작업에 맞는 lane

Cambrian은 이걸 **하네스** 로 제공한다.

### 문제 2. 잘 된 AI 작업 방식이 재사용되지 않는다

대부분의 AI 사용은 휘발성이다.
오늘 잘된 프롬프트나 흐름이 내일 다시 재현되지 않는다.

Cambrian은 다음을 남긴다.

- template
- team
- qualification
- canary
- benchmark
- proof pack
- persistent overlay

즉 “잘됐다”를 시스템에 남긴다.

### 문제 3. AI 결과를 믿어도 되는지 증명하기 어렵다

Cambrian은 다음 질문에 답해야 한다.

- validated proposal까지 갔는가
- adoption 되었는가
- regression 없이 안전했는가
- human intervention이 줄었는가
- raw AI보다 나았는가

그래서 Cambrian은 운영체계인 동시에 **증명 시스템** 이어야 한다.

---

## 6. 대상 사용자

### 1차 사용자

- AI를 적극적으로 쓰지만 에이전트를 직접 설계하기 어려운 개발자
- 작은 팀의 builder / technical operator
- 이미 Claude, GPT, Cursor, local model 등을 쓰고 있는 사람
- 반복 작업이 있고, 그 작업을 더 안전하게 자동화하고 싶은 사람

### 2차 사용자

- 팀 단위로 검증된 AI 작업반을 배포하고 싶은 조직
- private template/team/worker catalog가 필요한 회사
- 결과 증거와 rollback이 중요한 엔지니어링 팀

### 지금 당장 가장 중요한 wedge

현재 Cambrian의 strongest lane은 다음이다.

- Python
- pytest
- narrow auth/login bug fix
- test-first
- narrow-scope
- review-support

즉 Cambrian은 지금 모든 분야를 다 이기겠다고 약속하지 않는다.
**세일즈는 넓게 가더라도, 증명은 이 좁은 lane에서 먼저 한다.**

---

## 7. 제품이 반드시 해야 하는 약속

Cambrian은 아래를 약속해야 한다.

### 7.1 설치

사용자는 직접 에이전트를 복잡하게 만들지 않아도 된다.
필요한 worker/team/template/lane pack을 골라 설치할 수 있어야 한다.

### 7.2 연결

사용자가 이미 쓰는 AI와 연결되어야 한다.
Cambrian은 AI를 대체하는 것이 아니라, AI 위에 입는 작업복이어야 한다.

### 7.3 검증

결과는 benchmark, replay, compare, proof, canary로 검증되어야 한다.

### 7.4 진화

좋은 실험은 승격되고, 안 좋은 실험은 철회되어야 한다.

### 7.5 가역성

승격, canary, lane default switch는 모두 rollback 가능해야 한다.

---

## 8. 제품이 하지 말아야 하는 것

Cambrian은 다음으로 보이면 안 된다.

### 8.1 단순 프롬프트 저장소

Cambrian의 핵심은 prompt library가 아니다.
검증 가능한 설치와 운영이다.

### 8.2 단순 agent builder

Cambrian의 핵심은 “에이전트를 만들어보세요”가 아니다.
**검증된 일꾼을 설치하세요** 여야 한다.

### 8.3 무조건 자동화 툴

Cambrian은 auto-apply, auto-adoption 중심 제품이 아니다.
validated proposal까지 안전하게 가는 것이 우선이다.

### 8.4 broad generic AI OS

지금 단계에서 “모든 일 다 잘합니다”라고 말하면 안 된다.
현재 strongest lane 바깥은 정직하게 약하다고 말해야 한다.

---

## 9. Cambrian의 moat

Cambrian의 moat는 단순한 agent 개수나 template 개수가 아니다.

진짜 moat는 다음이다.

### 9.1 evidence

- benchmark
- replay
- compare
- proof
- canary ledger
- canary outcomes
- qualification

### 9.2 reusable learning

- persistent overlay
- template evolution
- lane playbook
- qualification adoption
- rollback

### 9.3 local trust

- local-first
- file-first
- provenance
- current runtime / future defaults 분리
- source mutation과 proof layer 분리

즉 Cambrian은 **일꾼을 설치하는 것** 뿐 아니라
**그 일꾼이 진짜 괜찮다는 증거를 축적하는 것** 이 핵심이다.

---

## 10. 세일즈 원칙

### 세일즈는 넓게

외부 메시지는 쉽게 가야 한다.

- AI 일꾼 설치
- AI 작업반 고용
- AI를 바로 일하게 만들기
- 검증된 작업복 설치

### 증명은 좁게

내부 제품 증명은 strongest lane에서 먼저 한다.

이 원칙은 매우 중요하다.
넓게 팔 수는 있어도, 넓게 과장하면 안 된다.

---

## 11. 왜 웹이 필요한가

Cambrian은 궁극적으로 CLI만으로 끝나지 않는다.
웹은 꼭 필요하다.

하지만 웹은 runtime이 아니다.
웹은 **control plane** 이어야 한다.

웹의 역할:

- catalog
- hiring surface
- recommendation
- install manifest
- future private registry

로컬 Cambrian의 역할:

- 실제 설치
- runtime execution
- benchmark / proof / canary / rollback
- evidence accumulation

즉:

> **웹은 고용판, 로컬 Cambrian은 현장 엔진이다.**

---

## 12. 현재 단계에서의 제품 전략

Cambrian은 지금 모든 걸 다 하려는 제품이 아니다.
현재 단계의 핵심 전략은 아래와 같다.

### 1. strongest lane에서 먼저 이긴다

auth-bug core에서 실제로 결과가 좋아야 한다.

### 2. AI entry를 매끈하게 만든다

prepare → ingest/paste → handoff → continue까지 매일 쓸 수 있어야 한다.

### 3. validated proposal rate를 높인다

결과를 다시 사람 손으로 크게 고치지 않아도 되는 비율이 올라가야 한다.

### 4. benchmark로 증명한다

raw AI / bridge_only / guided / full을 비교해서 이겨야 한다.

### 5. improvement loop를 돈다

한 번에 병목 하나만 잡고, 개선하고, 다시 증명한다.

---

## 13. 북극성

Cambrian의 북극성은 이것이다.

**Validated Proposal Rate**

더 정확히 말하면:

> **사용자가 이미 쓰는 AI에 일꾼을 설치했을 때,
> 사람의 추가 재작성 없이 validated proposal까지 가는 비율을 높인다.**

그리고 더 큰 장기 목표는 이것이다.

> **반복 작업일수록, 시간이 갈수록, 더 적은 사람 개입으로 더 안전한 결과를 낸다.**

---

## 14. 최종 요약

Cambrian은 단순히 에이전트를 만드는 툴이 아니다.
Cambrian은 단순히 AI 직원을 많이 띄우는 툴도 아니다.

Cambrian은:

- AI 위에 일꾼을 설치하고
- 그 일꾼을 실제 프로젝트에서 일하게 하고
- 결과를 benchmark와 proof로 검증하고
- 더 좋은 실험을 다음 기본값으로 승격하며
- 안 좋으면 canary와 rollback으로 통제하는

**evidence-based AI workforce runtime** 이다.

한 문장으로 다시 쓰면:

> **Cambrian은 AI를 더 똑똑하게 만드는 제품이 아니라, AI를 더 믿고 더 자주 일하게 만드는 설치·검증·진화 시스템이다.**
