# Cambrian 10-Year Architecture

## 0. 2026-05-10 고정 보정: Platform-first와 Runtime 분리

현재 방향은 옳다.
다만 앞으로 10년을 보려면 두 제품 축을 섞지 않아야 한다.

```text
Platform-first track:
  브라우저에서 AI 에이전트 계약을 만들고 다운로드 가능한 agent pack으로 내보낸다.

Local Cambrian Runtime:
  프로젝트 안에서 실행, 검증, evidence, proof, evolution을 담당한다.
```

이 둘은 경쟁하지 않는다.
Platform-first는 더 넓은 사용자가 에이전트 계약을 만들게 하는 진입면이고, Local Cambrian Runtime은 그 계약이 실제 프로젝트에서 안전하게 실행되고 증거로 진화하게 만드는 신뢰 엔진이다.

### 0.1 절대 경계

- Platform-first Defensible Alpha는 Cambrian Runtime 설치를 요구하지 않는다.
- Platform-first Defensible Alpha는 provider API를 호출하지 않는다.
- Platform-first Defensible Alpha는 사용자의 파일이나 프로젝트를 자동 수정하지 않는다.
- Platform-first Defensible Alpha는 proof 없는 성공률을 표시하지 않는다.
- 공개 marketplace와 결제는 `no_runtime_evidence` 상태가 해소된 뒤에만 연다.
- 한국 시장 선점은 단순 에이전트 쇼핑몰 UI가 아니라 agent contract, preflight, audit lineage, proof boundary 표준을 먼저 박는 것이다.

### 0.2 10년 관점의 올바른 순서

```text
agent contract
-> downloadable agent pack
-> preflight validation
-> private download and version history
-> optional Cambrian adapter
-> runtime execution evidence
-> proof
-> evolution history
-> trusted marketplace
```

지금 당장 만들어야 하는 것은 마켓 화면이 아니라 신뢰 가능한 계약과 preflight gate다.
마켓은 이 계약과 evidence가 쌓인 뒤에 열리는 유통 레이어다.

### 0.3 법률과 신뢰 원칙

Cambrian은 법률 판단을 자동화하지 않는다.
플랫폼은 위험 행동을 조기에 드러내고, Red 위험을 차단하며, 사용자가 책임 경계를 이해하게 만든다.

초기 법률 게이트의 최소 원칙:

- 의료 결정, 법률 결정, 투자·금융 결정, 채용·해고 판단은 Red로 차단한다.
- 비밀번호, 토큰, 개인 API 키 수집은 기본 금지다.
- 외부 전송과 파일 생성은 명시 승인 대상이다.
- 실제 실행 evidence가 없으면 proof, 성능, 성공률을 주장하지 않는다.
- 공개 판매 상태는 기본 false다.

## 1. 현재 방향 판정

판정:

```text
방향은 옳다.
단, 지금부터는 기능을 더 많이 만드는 게임이 아니라,
작은 승리 영역에서 증거를 압축하고 신뢰를 배포하는 게임으로 바뀌어야 한다.
```

Cambrian은 이미 단순 에이전트 묶음이 아니다. 현재 제품 중심은 `installable AI company runtime`이고, 이 방향은 장기적으로도 맞다. 이유는 세 가지다.

첫째, 모델 자체는 계속 강해지고 싸진다. Cambrian이 모델을 대체하려 하면 진다. 대신 Cambrian은 모델이 실제 프로젝트에서 일할 수 있도록 회사 구조, 권한, 검증, 증거, 진화 루프를 설치해야 한다.

둘째, 사용자가 진짜 원하는 것은 "더 많은 에이전트"가 아니라 "내 프로젝트를 안전하게 이해하고 끝까지 밀어주는 운영 체계"다. `project scan -> harness -> workforce -> authority -> auto -> validation -> evidence -> evolution` 흐름은 이 문제를 정확히 겨냥한다.

셋째, 장기 해자는 모델 호출이 아니라 누적된 작업 증거다. 어떤 하네스, 인력, 스킬, 템플릿, 권한, 검증 조합이 실제로 좋은 결과를 냈는지 쌓는 것이 Cambrian의 진짜 자산이다.

현재 위험도 명확하다.

- 모듈과 명령이 빠르게 늘어 제품 spine이 흐려질 수 있다.
- `AI company runtime`과 과거 `pack / worker installer` 언어가 섞이면 외부 메시지가 약해진다.
- 증거와 proof가 코드 안에는 있지만 사용자가 즉시 믿을 만큼 압축되어 보이지 않을 수 있다.
- Web control plane, registry, marketplace 같은 큰 말은 로컬 proof가 충분히 강해진 뒤에만 확장해야 한다.
- `template evolve`, `template fork`처럼 문서와 CLI가 어긋난 부분은 장기 신뢰를 갉아먹는다.

따라서 앞으로 10년의 방향은 다음 한 문장으로 고정한다.

```text
Cambrian은 모든 프로젝트 안에 검증 가능한 AI 회사를 설치하고,
그 회사가 안전하게 일하고, 증거로 배우고, 더 좋은 기본값으로 진화하게 만드는
로컬 우선 AI company operating system이 된다.
```

## 2. 사고 원칙

이 문서는 특정 인물을 흉내 내기 위한 문서가 아니다. 다만 장기 제품을 만든 사람들의 공개적으로 알려진 사고 원칙을 Cambrian에 맞게 번역한다.

### 2.1 제1원리

질문:

- 사용자가 정말 사는 것은 무엇인가?
- AI가 이미 잘하는 것과 Cambrian이 반드시 맡아야 하는 것은 무엇인가?
- 지금 만든 기능이 없어도 사용자가 원하는 결과를 얻을 수 있는가?
- 이 기능이 증거, 신뢰, 반복 사용 중 무엇을 개선하는가?

Cambrian의 제1원리 답:

```text
사용자는 에이전트가 아니라 검증된 결과를 산다.
사용자는 자동화가 아니라 신뢰할 수 있는 위임을 산다.
사용자는 도구가 아니라 자기 프로젝트 안에서 일하는 AI 회사를 산다.
```

### 2.2 고객에서 거꾸로 설계

2036년에 사용자가 Cambrian을 설명하는 말은 이래야 한다.

```text
새 프로젝트를 시작하면 먼저 Cambrian을 설치한다.
그러면 프로젝트 안에 작은 AI 회사가 생기고,
그 회사가 목표를 쪼개고, 일을 맡기고, 검증하고, 기록하고,
다음번에는 더 잘한다.
```

따라서 내부 설계는 항상 고객 경험에서 역산한다.

- 설치 첫 10분 안에 "AI 회사가 생겼다"는 감각을 줘야 한다.
- 첫 작업 안에 "이 시스템은 함부로 고치지 않는다"는 신뢰를 줘야 한다.
- 첫 검증 안에 "결과를 말로만 주장하지 않는다"는 증거를 보여줘야 한다.
- 첫 반복 안에 "지난 실패가 다음 기본값을 바꾼다"는 진화를 보여줘야 한다.

### 2.3 장기주의와 플라이휠

Cambrian의 플라이휠:

```text
프로젝트 설치
-> 실제 작업
-> 검증 결과
-> evidence 축적
-> 더 좋은 하네스/인력/스킬/템플릿
-> 더 높은 성공률
-> 더 많은 설치와 반복 사용
-> 더 많은 evidence
```

이 플라이휠 밖의 기능은 보류한다.

### 2.4 되돌릴 수 있는 결정과 되돌리기 어려운 결정

되돌릴 수 있는 결정:

- 새 문서
- 새 local report
- 새 fixture
- 새 optional command
- 새 derived artifact

되돌리기 어려운 결정:

- artifact source-of-truth 변경
- 기본 설치 flow 변경
- authority 기본값 확대
- source apply 자동화
- public registry trust model
- marketplace 또는 payment 약속

되돌리기 어려운 결정은 proof gate 없이 진행하지 않는다.

### 2.5 메커니즘 우선

구호는 충분하지 않다. 모든 원칙은 메커니즘으로 바뀌어야 한다.

| 원칙 | 메커니즘 |
| --- | --- |
| 고객 집착 | pilot feedback, first-run friction log, validated outcome interview |
| 높은 기준 | release gate, proof pack, docs/CLI consistency test |
| 장기주의 | 10년 아키텍처, quarterly kill list, non-goal ledger |
| 제1원리 | feature intake checklist, loop/metric/source-of-truth gate |
| 신뢰 | explicit authority, no hidden apply, rollback hint, audit manifest |
| 진화 | evidence-backed adoption, canary, qualification, rollback |

## 3. 2036 목적지

2036년 Cambrian은 아래 상태를 목표로 한다.

### 3.1 제품 상태

Cambrian은 프로젝트 안에 설치되는 AI 회사 운영 체계다. 사용자는 CLI, IDE, 웹 control plane, 또는 다른 AI 도구에서 Cambrian을 부른다. Cambrian은 각 프로젝트의 목표, 제약, 테스트, 배포 경계, 팀 규칙, 과거 evidence를 알고 있다.

Cambrian이 직접 모델이 되지는 않는다. Claude, Codex, GPT, Cursor, local model은 실행 엔진이고 Cambrian은 그 위에 역할, 하네스, 권한, 검증, 증거, 진화 구조를 제공한다.

### 3.2 기술 상태

목표 아키텍처:

```text
Human / Team Goal
-> Project-local AI Company
-> Harness Operating System
-> Workforce / Role Graph
-> Skill and Tool Contracts
-> Authority and Risk Gates
-> Execution Engine Bridge
-> Validation and Release Gates
-> Evidence Lake
-> Evolution and Governance
-> Trusted Distribution
```

기본 실행 원칙:

- 로컬 프로젝트 상태가 제품의 중심이다.
- 모델 호출은 교체 가능한 adapter다.
- 모든 중요한 변경은 source-of-truth와 derived artifact가 분리된다.
- 모든 승격은 evidence-backed다.
- 모든 자동화는 authority와 rollback 경계를 가진다.
- Web control plane은 선택과 배포를 돕고, 로컬 runtime은 실행과 검증을 맡는다.

### 3.3 사업 상태

장기적으로 Cambrian이 파는 것은 "AI 회사 설치와 운영 신뢰"다.

가능한 제품 단위:

- 개인 개발자용 local AI company runtime
- 팀용 project AI company 운영 체계
- 조직용 private registry와 proof dashboard
- 검증된 lane, workforce, skill, harness 배포
- 산업별 AI company template
- enterprise local appliance

단, 이 모든 것은 strongest lane proof가 먼저 충분히 강해진 뒤 확장한다.

## 4. 유지해야 할 5개 아키텍처 층

기존 `04_SYSTEM_ARCHITECTURE.md`의 5-layer 구조는 유지한다. 앞으로 10년 동안 이름을 자주 바꾸지 않는다.

### Layer 1. Web Control Plane

역할:

- discovery
- hiring desk
- registry browsing
- proof-backed catalog
- install manifest 발급
- team/org visibility

하지 않는 것:

- 소스 코드 실행
- 로컬 프로젝트 직접 수정
- cloud patch/apply
- authority 우회

10년 목표:

```text
웹은 실행기가 아니라 신뢰 가능한 선택과 배포의 표면이다.
```

### Layer 2. Local Cambrian Runtime

역할:

- install
- project scan
- harness engineering
- workforce and skill generation
- authority profile
- auto mode
- job lifecycle
- validation
- local evidence

10년 목표:

```text
로컬 runtime은 Cambrian의 본체다.
웹, IDE, AI 도구는 모두 이 본체에 붙는 표면이다.
```

### Layer 3. AI Bridge

역할:

- model-agnostic request packet
- structured reply contract
- result intake
- review and handoff
- provider adapter
- human-in-the-loop boundary

10년 목표:

```text
AI Bridge는 모델 교체 비용을 낮추고,
프로젝트 운영 지식이 특정 provider 안에 갇히지 않게 한다.
```

### Layer 4. Evidence and Proof

역할:

- validated proposal rate
- benchmark
- replay
- proof pack
- release gate
- customer outcome evidence
- regression tracking

10년 목표:

```text
Evidence layer는 Cambrian의 해자다.
Cambrian은 "잘한다"를 주장하지 않고 증명한다.
```

### Layer 5. Evolution and Governance

역할:

- improvement loop
- bottleneck selection
- intervention
- qualification
- canary
- promotion
- rollback
- policy and authority governance

10년 목표:

```text
Evolution layer는 성공한 작업 방식을 다음 기본값으로 바꾼다.
진화는 자동 생성이 아니라 evidence-backed adoption이다.
```

## 5. 장기 해자

Cambrian의 해자는 하나가 아니라 복합 구조여야 한다.

### 5.1 Evidence 해자

가장 중요한 자산은 누적된 검증 결과다.

예:

- 어떤 프로젝트 유형에서 어떤 하네스가 성공했는가
- 어떤 역할 조합이 재작업을 줄였는가
- 어떤 validation gate가 실제 회귀를 막았는가
- 어떤 authority mode가 속도와 안전의 균형이 좋았는가
- 어떤 template 변화가 재사용 성과를 높였는가

### 5.2 Workflow 해자

Cambrian은 AI 답변 하나가 아니라 작업 전체 흐름을 가진다.

```text
goal -> plan -> work -> validation -> evidence -> decision -> evolution
```

이 흐름이 반복될수록 사용자는 Cambrian 없이 일하기 어려워져야 한다.

### 5.3 Trust 해자

AI 제품의 장기 승부는 신뢰다.

Cambrian의 신뢰 장치:

- explicit authority
- no hidden source mutation
- audit manifest
- rollback hint
- source-of-truth classification
- proof-backed promotion
- registry digest and trust metadata

### 5.4 Distribution 해자

처음에는 local catalog다. 이후 static registry, private registry, verified registry로 확장한다.

중요한 순서:

```text
local proof
-> static catalog
-> signed registry
-> private/team registry
-> proof-backed public distribution
```

순서를 바꾸면 신뢰보다 유통을 먼저 만들게 된다. 그러면 제품이 약해진다.

### 5.5 Installed State 해자

Cambrian은 사용자의 프로젝트 안에 설치된다. 이 점이 중요하다.

로컬 `.cambrian/` 상태는 단순 cache가 아니라 프로젝트 AI 회사의 기억이다.

장기적으로 이 상태는 다음을 포함한다.

- company charter
- project goals
- authority history
- workforce graph
- skill registry
- validation history
- release decisions
- evidence and proof
- evolution lineage

### 5.6 Meta-Harness 흡수 원칙

GitHub의 Meta-Harness 계열 구현에서 가져올 핵심은 외부 프레임워크나 새 의존성이 아니다.
가져와야 할 것은 아래 세 가지 운영 원리다.

- 작업 영역을 하나의 domain spec으로 고정한다.
- 후보를 실행하고 evaluator가 같은 기준으로 판정한다.
- 결과가 좋은 후보만 lineage와 함께 다음 세대로 승격한다.

Cambrian은 이 원리를 그대로 복제하지 않고 로컬 우선 AI company runtime에 맞게 번역한다.

```text
Meta-Harness의 domain spec
-> Cambrian의 project-local harness contract

Meta-Harness의 evaluator
-> Cambrian의 validation, judge rubric, proof gate

Meta-Harness의 population / generation
-> Cambrian의 workforce, skill, template, harness candidate lineage

Meta-Harness의 selection
-> Cambrian의 evidence-backed promotion / rollback
```

따라서 10년 아키텍처에서 하네스는 단순 검증 파일이 아니다.
하네스는 특정 프로젝트에서 AI 회사가 어떤 문제를 풀고, 어디까지 쓸 수 있고, 어떤 검증을 통과해야 하며, 어떤 후보가 다음 기본값이 될 수 있는지를 고정하는 실행 계약이다.

초기 구현은 새 복잡도를 늘리지 않는다.
먼저 `.cambrian/harness/harness.yaml` 안에 domain spec에 해당하는 최소 필드를 흡수하고, evaluator는 기존 validation command와 judge rubric을 감싸는 표준 verdict 계약으로 정리한다.
population 기반 자동 탐색은 external alpha 안정화와 pilot evidence가 충분히 쌓인 뒤에만 좁은 strongest lane에서 켠다.

## 6. 10년 로드맵

### Horizon 1: 2026-2027, 신뢰 가능한 로컬 회사

목표:

```text
한 프로젝트 안에서 Cambrian AI company가 실제로 설치되고,
첫 작업을 안전하게 처리하고,
검증과 evidence를 남기고,
다음 반복에서 더 좋아지는 것을 증명한다.
```

집중 범위:

- Python + pytest + auth/login narrow bug fix strongest lane
- local install
- harness engineering
- workforce generation
- job start and validation
- auto mode bounded run
- proof pack
- docs/CLI drift 제거

필수 작업:

- `template evolve`, `template fork` 문서/CLI 불일치 해결
- `.cambrian/` artifact source-of-truth doctor 추가
- `.cambrian/harness/harness.yaml`에 domain spec 최소 계약 고정
- evaluator verdict 계약을 validation, judge rubric, proof gate와 연결
- 후보 lineage에 parent, mutation, evaluator result, promotion decision 기록
- representative `.cambrian/` fixture 추가
- first-run demo를 10분 안에 통과하도록 압축
- pilot feedback을 evidence로 저장
- full test와 launch smoke를 release gate로 정착

측정:

- `validated_proposal_rate`
- `median_time_to_validated_proposal`
- `human_intervention_rate`
- `validation_autonomy_rate`
- first-run completion rate
- docs/CLI drift count

금지:

- broad marketplace
- cloud execution
- 자동 source apply 기본값
- 다중 lane 확장
- provider-specific deep integration 우선 개발

### Horizon 2: 2028-2029, 신뢰 가능한 배포와 registry

목표:

```text
검증된 workforce, skill, harness, lane을 안전하게 찾고 설치할 수 있다.
```

집중 범위:

- signed static registry
- private registry
- manifest digest and trust model
- proof-backed catalog
- pack dependency graph hardening
- registry sync and verification
- provider adapter contract

필수 작업:

- registry trust policy 도입
- proof 없는 pack의 노출 제한
- local/team registry 분리
- install graph rollback 강화
- organization-level policy profile
- proof dashboard alpha

측정:

- trusted install success rate
- broken manifest catch rate
- proof-backed install ratio
- rollback success rate
- registry drift count

금지:

- payment를 먼저 붙이는 것
- public marketplace를 proof보다 먼저 여는 것
- source upload를 기본 요구로 만드는 것
- remote runtime을 local runtime보다 앞세우는 것

### Horizon 3: 2030-2031, multi-lane AI company

목표:

```text
Cambrian은 auth/login bug fix를 넘어 여러 검증된 lane에서 작동한다.
단, lane마다 proof와 gate가 따로 있어야 한다.
```

가능한 lane:

- auth/login bug fix
- test stabilization
- dependency upgrade
- API contract change
- frontend regression repair
- documentation-to-tests alignment
- release readiness
- incident reproduction

필수 작업:

- lane qualification framework
- lane-specific benchmark worksets
- cross-lane risk router
- workforce graph specialization
- shared evidence schema
- team memory and role continuity

측정:

- lane-specific validated proposal rate
- lane expansion failure rate
- cross-lane regression rate
- reuse lift by lane
- time-to-first-trusted-lane

금지:

- "모든 일을 잘한다"는 broad claim
- proof 없는 lane default
- 하나의 template을 모든 lane에 강제
- canary 없이 default 전환

### Horizon 4: 2032-2033, 자율 제품 팀

목표:

```text
Cambrian AI company는 제품 목표를 받고,
역할별로 계획하고,
작업을 배치하고,
검증하고,
릴리즈 판단까지 준비한다.
사람은 권한, 방향, 최종 승인에 집중한다.
```

집중 범위:

- boardroom decision quality
- multi-agent accountability
- release simulation
- cost and risk budget
- bounded source apply under explicit authority
- incident and rollback playbooks
- enterprise audit integration

필수 작업:

- role decision ledger
- authority escalation protocol
- release gate with customer impact model
- automatic validation planning
- failed-run autopsy and learning loop
- cost-aware execution planner

측정:

- plan-to-validated-release rate
- release gate false positive/negative rate
- cost per validated outcome
- rollback readiness score
- human approval latency

금지:

- 사람 승인 없는 production deploy
- secret 자동 사용
- organization policy 우회
- 책임 소재 없는 multi-agent 실행

### Horizon 5: 2034-2036, AI company network

목표:

```text
Cambrian은 프로젝트별 AI 회사를 설치하는 표준 runtime이 되고,
검증된 회사 운영 방식이 프로젝트와 조직 사이에서 안전하게 이동한다.
```

집중 범위:

- verified company templates
- cross-project learning with privacy boundaries
- enterprise/private network
- industry-specific company profiles
- regulatory audit packs
- long-lived project memory
- interoperability with AI tools and IDEs

필수 작업:

- company snapshot format
- privacy-preserving evidence export
- organization trust graph
- verified template marketplace only after proof maturity
- multi-year evolution lineage
- standard integration protocol

측정:

- trusted company bootstrap time
- cross-project reuse lift
- enterprise audit pass rate
- template survival rate
- long-term regression reduction

금지:

- privacy boundary 없는 cross-project learning
- proof 없는 public ranking
- cloud lock-in
- model-provider lock-in

## 7. 90일 실행 계획

다음 90일은 10년 전략의 기초를 닦는 시간이다. 새로운 큰 기능보다 신뢰 압축이 우선이다.

### 7.1 제품 spine 고정

해야 할 일:

- README, launch docs, product docs에서 `AI company runtime`을 중심 언어로 유지한다.
- `AI Worker Installer`, `pack`, `worker` 언어는 compatibility 또는 distribution vocabulary로 낮춘다.
- 첫 사용자 경험을 `project scan -> harness interview -> engineer review -> workforce/skill -> authority -> auto -> job -> validation` 흐름으로 정리한다.

완료 기준:

- 새 사용자가 README만 보고 첫 흐름을 따라갈 수 있다.
- 문서에 나온 주요 명령이 실제 CLI와 어긋나지 않는다.
- `docs/product/00_INDEX.md`가 현재 source-of-truth 순서를 반영한다.

### 7.2 drift 제거

해야 할 일:

- `template evolve`, `template fork`를 구현하거나 문서/next-action에서 제거한다.
- `.cambrian/proposals/`와 `.cambrian/patches/` 표현을 감사한다.
- planned, partial, implemented 상태 표기를 정확히 유지한다.

완료 기준:

- product docs와 CLI help 사이의 알려진 drift가 0개다.
- architecture inventory의 critical gaps가 최신이다.

### 7.3 proof를 사용자 눈앞으로 가져오기

해야 할 일:

- `validated_proposal_rate`를 first-run proof surface에 노출한다.
- proof pack을 사람이 읽기 쉬운 한 장으로 만든다.
- 실패한 작업도 evidence로 남겨 다음 개선 입력이 되게 한다.

완료 기준:

- demo run 후 사용자가 "무엇이 검증됐고 무엇이 아직 위험한지" 한 화면에서 알 수 있다.
- proof 없는 성공 주장은 launch docs에 남지 않는다.

### 7.4 pilot reality loop

해야 할 일:

- 좁은 strongest lane에서 실제 사용자 pilot을 반복한다.
- pilot마다 friction log, outcome, validation result, missing skill을 기록한다.
- 5개 이상 반복된 friction만 제품 작업으로 승격한다.

완료 기준:

- pilot evidence가 `.cambrian/` 또는 docs/release artifact로 남는다.
- 개선 작업은 pilot evidence에 연결된다.

## 8. 12개월 운영 계획

### Q1: 신뢰성

- docs/CLI drift 제거
- artifact doctor 추가
- representative `.cambrian/` fixture 작성
- docs consistency 테스트 보강
- launch demo 안정화

### Q2: proof 압축

- proof pack 읽기 개선
- benchmark workset 품질 향상
- pilot outcome evidence 저장
- release gate를 문서와 CLI 양쪽에 고정

### Q3: local distribution

- local catalog hardening
- manifest trust metadata 강화
- install/update/uninstall rollback story 정리
- static web catalog를 local catalog의 파생물로 유지

### Q4: controlled registry 준비

- registry trust policy 초안
- signed manifest 설계
- private registry workflow 설계
- public marketplace는 보류하고 proof-backed distribution만 준비

## 9. 개발 게이트

앞으로 큰 기능은 아래 질문을 통과해야 한다.

### 9.1 어느 loop에 속하는가?

하나 이상에 속해야 한다.

- Install Loop
- Work Loop
- Proof Loop
- Evolution Loop

속하지 않으면 보류한다.

### 9.2 어떤 지표를 움직이는가?

최소 하나를 직접 개선하거나 측정 가능하게 해야 한다.

- `validated_proposal_rate`
- `median_time_to_validated_proposal`
- `human_intervention_rate`
- `validation_autonomy_rate`
- `team_template_recommendation_hit_rate`
- `reuse_lift`
- `repeat_task_improvement_rate`
- `regression_free_apply_rate`

### 9.3 어떤 상태를 바꾸는가?

명확히 분류해야 한다.

- source-of-truth
- current runtime
- future default
- derived artifact
- cache

source-of-truth를 바꾸면 explicit command와 rollback path가 있어야 한다.

### 9.4 strongest lane에 도움이 되는가?

초기에는 `Python + pytest + auth/login narrow bug fix`에서 먼저 증명한다. 이 lane과 무관한 기능은 다음 중 하나를 만족해야 한다.

- release safety를 높인다.
- proof quality를 높인다.
- install trust를 높인다.
- docs/CLI drift를 줄인다.
- pilot learning을 수집한다.

### 9.5 신뢰를 늘리는가, 표면적만 늘리는가?

새 화면, 새 명령, 새 파일이 신뢰를 늘리지 않으면 보류한다.

## 10. 아키텍처 금지 목록

다음은 10년 방향과 충돌한다.

- 모델 provider에 제품 정체성을 종속시키는 것
- cloud execution을 local runtime보다 앞세우는 것
- source change를 기본 자동 동작으로 만드는 것
- proof 없는 template, lane, workforce를 default로 승격하는 것
- public marketplace를 trust model보다 먼저 여는 것
- pack 수를 늘리는 것을 제품 진전으로 착각하는 것
- broad AI OS라는 문구로 strongest lane proof 부족을 가리는 것
- `.cambrian/` 상태를 source-of-truth와 derived artifact 구분 없이 키우는 것
- CLI와 docs drift를 방치하는 것
- 실패 evidence를 숨기는 것

## 11. 조직 운영 리듬

Cambrian 자체도 AI 회사처럼 운영한다.

### 매주

- proof review
- failed-run autopsy
- docs/CLI drift check
- pilot friction triage
- one bottleneck selection

### 매월

- architecture inventory update
- non-goal ledger review
- strongest lane benchmark replay
- release gate dry-run
- local catalog trust check

### 분기마다

- kill list 작성
- roadmap 재정렬
- lane expansion 여부 판단
- registry readiness 판단
- pilot evidence 기반 product thesis 수정

## 12. 현실적인 성공 순서

Cambrian은 아래 순서로 이겨야 한다.

```text
1. 한 lane에서 진짜로 더 잘한다.
2. 그 증거를 사람이 믿을 수 있게 보여준다.
3. 그 성공 방식을 설치 가능한 기본값으로 만든다.
4. 그 기본값을 안전하게 배포한다.
5. 여러 lane으로 확장한다.
6. 팀과 조직의 운영 체계가 된다.
7. 검증된 AI 회사 네트워크가 된다.
```

순서를 건너뛰면 제품은 커 보이지만 약해진다.

## 13. 최종 아키텍처 문장

```text
Cambrian의 10년 아키텍처는 모델 경쟁이 아니라 신뢰 경쟁이다.
로컬 프로젝트 안에 AI 회사를 설치하고,
그 회사가 일한 증거를 축적하고,
증거로 좋은 운영 방식을 승격하며,
검증된 운영 방식을 안전하게 배포하는 시스템이 된다.
```

따라서 지금부터의 판단 기준은 단순하다.

```text
더 많은 기능인가?
아니면 더 신뢰할 수 있는 AI 회사인가?
```

Cambrian은 항상 두 번째를 선택한다.
## 14. 24-Hour Product Completion Agent

Cambrian should eventually let a user install a project-local agent that keeps working for the product around the clock.

This must not mean an unlimited autonomous coder.

The product should be:

```text
24-hour product completion agent
= a governed AI company loop that repeatedly plans, proposes, validates, records evidence, and asks for approval at risk boundaries.
```

The core promise:

```text
The user does not have to restart the thinking loop every day.
Cambrian keeps the product goal, architecture, open blockers, validation commands, and proof history alive.
```

The forbidden promise:

```text
Cambrian will autonomously finish any product without supervision.
```

### 14.1 Runtime Shape

The 24-hour agent is a loop, not one giant agent.

```text
mission state
-> boardroom decision
-> bounded work plan
-> worker directive
-> AI reply ingest
-> evidence envelope
-> validation
-> verdict
-> next mission state
```

### 14.2 Required Gates

The loop may continue automatically only through low-risk planning and evidence work.

It must stop for explicit approval before:

```text
source code apply
git push
deploy
secret/API-key handling
payment/outbound send
database migration
public release
long-running paid cloud execution
```

### 14.3 Installed Capabilities

An installed 24-hour agent needs these local components:

```text
.cambrian/mission.yaml
.cambrian/harness.yaml
.cambrian/workforce.yaml
.cambrian/skills/
.cambrian/auto/agenda.yaml
.cambrian/auto/tasks/
.cambrian/evidence/
.cambrian/reports/latest_verdict.json
```

The user-facing command should be simple:

```text
cambrian mission install --goal "Finish this product"
cambrian mission status
cambrian mission run --max-steps 1
cambrian mission resume
```

Later, a scheduler may call bounded steps repeatedly:

```text
cambrian mission run --max-steps 1 --write-evidence
```

### 14.4 Product Standard

A 24-hour completion loop is allowed to claim progress only when it can show:

```text
what changed
why it mattered
which files or docs were used
which validation commands ran
which risks remain
what the next safest action is
```

If evidence is missing, the agent must say:

```text
hold
```

not:

```text
done
```

### 14.5 First Build Target

Do not start with cloud autonomy.

Start with local bounded continuity:

```text
One Good Harness
-> One Good Mission
-> One Bounded 24-Hour Loop
```

The first implementation target is:

```text
Cambrian can wake up, read the mission state, select one next task, produce an evidence-bound directive or result, validate it, and update mission state without losing the product goal.
```

### 14.6 First CLI Slice, 2026-05-21

Implemented local bounded mission commands:

```text
cambrian mission install --goal "Finish this product" --json
cambrian mission status --json
cambrian mission run --max-steps 1 --json
cambrian mission run --max-steps 1 --start-job --json
cambrian mission sync --json
cambrian mission resume --json
```

The installed state lives at:

```text
.cambrian/mission.yaml
.cambrian/mission/events.yaml
.cambrian/mission/tasks/
```

When a project-specific harness is not installed yet, the mission layer falls back to basic project evidence such as `pyproject.toml`, `package.json`, `README.md`, `tests`, `engine`, `src`, and release/product docs. That fallback is intentionally modest: it gives the company loop a first validation command and evidence surface without pretending that a real custom harness already exists.

The first version intentionally does not run forever by itself. It creates a repeatable operating loop that Codex, Claude, or another AI worker can execute one bounded step at a time. This keeps the product honest: Cambrian is not claiming autonomous completion until it can prove every step with evidence.

Hard gates remain explicit-human-confirmation only:

```text
source_apply
git_push
public_release
deploy
secrets
payment_or_external_spend
database_migration
```

The correct next product step is not to add a daemon yet. The correct next step is to connect each mission directive to the existing job ingest, validation, completion, and company memory loop so the mission can learn from verified outcomes without becoming an unsafe background coder.

### 14.7 Mission To Job Bridge, 2026-05-21

The mission loop now has a first bridge into the existing Cambrian job runtime:

```text
cambrian mission run --max-steps 1 --start-job --json
```

Behavior:

```text
if custom harness is installed:
  create mission task directive
  create linked Cambrian job with entry_mode=mission
  create bridge packet
  set mission last_job_ref and last_bridge_packet_ref
  wait for AI reply evidence

if custom harness is missing:
  create mission task directive
  block job start
  point next_command to harness engineering
```

This is still not a background daemon. It is the first honest company installation loop: mission state can now open real work packets, but execution, source mutation, validation, and promotion remain gated by the existing evidence contracts.

### 14.8 Mission Outcome Sync, 2026-05-21

The mission loop now absorbs the latest job outcome:

```text
cambrian mission sync --json
```

It reads:

```text
.cambrian/evidence/outcomes.yaml
```

and updates:

```text
.cambrian/mission.yaml#last_outcome
.cambrian/mission/events.yaml
```

If the synced outcome has a `pass` verdict and no unchecked items, the next mission action becomes:

```text
cambrian mission run --max-steps 1 --start-job --json
```

Important boundary:

```text
mission sync only absorbs the outcome of the job opened by the mission itself.
older unrelated outcomes are ignored.
stale last_outcome is cleared when no linked mission job outcome exists.
```

This gives the local company its first closed control loop:

```text
mission install
-> mission run --start-job
-> job ingest
-> job validate
-> job complete
-> mission sync
-> next mission run
```

### 14.9 Cambrian Self Company Install, 2026-05-21

Cambrian itself now has a project-local AI company installed against the mission-company identity:

```text
harness_id: custom-cambrian-mission-company
workforce_id: workforce-cambrian-mission-company
authority_mode: proposal_only
```

Installed worker contracts:

```text
mission-control-architect
evidence-gate-reviewer
release-loop-qa
safety-boundary-reviewer
pytest-regression-guardian
```

Installed skills:

```text
trace-failure-flow
inspect-pytest-regression
propose-safe-patch
review-regression-risk
```

Important correction:

```text
mission-company identity outranks incidental auth scan evidence.
mission-company skill generation uses generic regression validation, not auth-specific test skills.
fixtures, .pytest_tmp, archive, errors, and dropzones are scan-noise boundaries, not product identity.
```

Verified local loop:

```text
cambrian harness bootstrap --confirm --json
-> custom-cambrian-mission-company installed
cambrian mission install --goal "Ship Cambrian so external users can install it, use One Good Harness, and follow a verified release path" --json
-> contract_source: installed_harness
cambrian mission run --max-steps 1 --start-job --json
-> linked job created with entry_mode=mission
-> source_code_modified_by_cambrian: false
-> provider_api_called_by_cambrian: false
job ingest latest ai_reply_patch_candidate.yaml --json
-> reply evidence envelope satisfied
job validate latest --run --json
-> validation_status: passed
-> trust_gate_status: verified
job complete latest --outcome success --json
-> verdict: pass
mission sync --json
-> last_outcome synced
-> next_command: cambrian mission run --max-steps 1 --start-job --json
```

Second-cycle proof, same day:

```text
cambrian mission run --max-steps 1 --start-job --json
-> run_count: 2
-> linked job: job-custom-cambrian-mission-company-20260521_123525_483321
job ingest latest ai_reply_patch_candidate.yaml --json
-> reply_evidence_compliance: satisfied
job validate latest --run --json
-> validation_status: passed
-> trust_gate_status: verified
-> pytest mission/job contract slice: 25 passed
-> py_compile mission/bridge slice: passed
job complete latest --outcome success --json
-> verdict: pass
mission sync --json
-> synced last_outcome: success/pass/verified
-> unchecked_count: 0
-> next_command: cambrian mission run --max-steps 1 --start-job --json
```

Third-cycle proof, same day:

```text
cambrian mission run --max-steps 1 --start-job --json
-> run_count: 3
-> linked job: job-custom-cambrian-mission-company-20260521_124123_126932
job ingest latest ai_reply_patch_candidate.yaml --json
-> reply_evidence_compliance: satisfied
job validate latest --run --json
-> validation_status: passed
-> trust_gate_status: verified
-> pytest mission/job contract slice: 25 passed
-> py_compile mission/bridge slice: passed
job complete latest --outcome success --json
-> verdict: pass
mission sync --json
-> synced last_outcome: success/pass/verified
-> unchecked_count: 0
-> next_command: cambrian mission run --max-steps 1 --start-job --json
```

Operator surface installed, same day:

```text
cambrian mission operator --save --json
-> status: operator_ready
-> operator_mode: supervised_24h_company
-> scheduler_readiness.safe_to_schedule: true
-> current_run_count: 3
-> last_outcome_verified: true
-> operator_ref: .cambrian/mission/operator.yaml
```

The external scheduler entry is `Cambrian 24h Company Operator` (`cambrian-24h-company-operator`). Its contract is intentionally narrow: every tick must read `mission operator` first, open at most one mission-linked job only when `safe_to_schedule` is true, then stop at the evidence-envelope boundary.

Product-level scheduler tick installed, same day:

```text
cambrian mission tick --json
-> calls mission operator first
-> skips when a job is waiting for AI evidence
-> opens at most one mission-linked job when operator_ready
-> stops at: cambrian job ingest latest ai_reply_patch_candidate.yaml --json
```

The scheduler no longer has to compose multiple Cambrian commands by prompt. It calls one product contract, `mission tick`, and Cambrian itself decides whether to skip or open exactly one bounded job.

Fourth-cycle proof through `mission tick`, same day:

```text
cambrian mission tick --json
-> status: tick_started_job
-> run_count: 4
-> opened job: job-custom-cambrian-mission-company-20260521_125621_788260
-> packet: .cambrian/bridge/packets/packet_20260521_125621_f030.yaml
job ingest latest ai_reply_patch_candidate.yaml --json
-> reply_evidence_compliance: satisfied
job validate latest --run --json
-> validation_status: passed
-> trust_gate_status: verified
-> pytest mission/job/operator slice: 29 passed
-> py_compile mission/bridge slice: passed
job complete latest --outcome success --json
-> verdict: pass
mission sync --json
-> synced last_outcome: success/pass/verified
mission operator --save --json
-> run_count: 4
-> status: operator_ready
-> scheduler_readiness.safe_to_schedule: true
```

Bounded worker-cycle automation installed, same day:

```text
automation_id: cambrian-24h-company-operator
old contract: mission tick only
new contract: operator -> tick -> evidence envelope -> ingest -> validate -> complete success only if verified -> mission sync -> operator_ready
hard gates: no git push, no deploy, no publish, no secrets, no spend, no migrations, no source patch apply
```

Fifth-cycle proof through the bounded worker cycle:

```text
cambrian mission tick --json
-> status: tick_started_job
-> run_count: 5
-> opened job: job-custom-cambrian-mission-company-20260521_130102_987724
-> packet: .cambrian/bridge/packets/packet_20260521_130103_f6e1.yaml
job ingest latest ai_reply_patch_candidate.yaml --json
-> reply_evidence_compliance: satisfied
job validate latest --run --json
-> validation_status: passed
-> trust_gate_status: verified
-> pytest mission/job/operator slice: 29 passed
-> py_compile mission/bridge slice: passed
job complete latest --outcome success --json
-> verdict: pass
mission sync --json
-> synced last_outcome: success/pass/verified
mission operator --save --json
-> run_count: 5
-> status: operator_ready
-> scheduler_readiness.safe_to_schedule: true
```

This is still a governed company loop, not an ungated autonomous daemon. The company can keep the release goal alive, open bounded jobs, demand evidence envelopes, and sync only linked outcomes; applying source changes, pushing git, deploying, publishing, touching secrets, spending money, or migrating a database still requires explicit human approval.

### CEO/CTO/COO Product Boardroom Gate

Added on 2026-05-22 KST / 2026-05-21 UTC.

The 24h company loop now has a product boardroom gate before repeated mission work:

```text
cambrian company boardroom install --goal "Keep Cambrian product direction sharp for the 24h company loop" --json
-> agents_ref: .cambrian/company/product_boardroom/agents.yaml
-> agent_ids: ceo-agent, cto-agent, coo-agent
-> agent_prompt_refs:
   .cambrian/company/product_boardroom/agent_prompts/ceo-agent.md
   .cambrian/company/product_boardroom/agent_prompts/cto-agent.md
   .cambrian/company/product_boardroom/agent_prompts/coo-agent.md
-> meeting_protocol_ref: .cambrian/company/product_boardroom/meeting_protocol.md
-> agenda_ref: .cambrian/company/product_boardroom/agenda.yaml
-> decision_history_ref: .cambrian/company/product_boardroom/decision_history.yaml

cambrian company boardroom convene --topic "24h company product boardroom with durable agenda and decision history" --json
-> conversation_ref: .cambrian/company/product_boardroom/conversations/24h-company-product-boardroom-with-durable-agenda-and-decision-history-20260521_163506_210843.yaml
-> decision_packet_ref: .cambrian/company/product_boardroom/decision_packet.yaml
-> open_questions_ref: .cambrian/company/product_boardroom/open_questions.yaml
-> mission_gate.ready_for_mission: true
```

The boardroom is not an extra decorative office. It is a pre-mission product decision contract:

- `ceo-agent` keeps external-user value, market priority, release trust, and scope discipline fixed.
- `cto-agent` protects architecture, reliability gates, testability, and long-term maintainability.
- `coo-agent` turns the discussion into one bounded operating step, stop condition, and validation handoff.

Each agent now has a standalone prompt contract. `meeting_protocol.md` defines the required meeting order: CEO product outcome and scope cut, CTO architecture constraint and validation proof, COO next bounded mission job and stop condition, then exactly one decision packet.

The boardroom also has durable continuity:

- `agenda.yaml` carries the next product discussion topic, standing order, input refs, and open questions.
- `latest_ai_request.yaml` is the request packet for real CEO/CTO/COO AI agent turns.
- `decision_history.yaml` appends each ingested AI-authored boardroom decision so the 24h company can continue the product conversation instead of restarting from a blank prompt.

The boardroom may write only product discussion artifacts under `.cambrian/company/product_boardroom/`. It cannot apply source patches, push git, deploy, publish, touch secrets, spend money, migrate databases, or call a provider API. `convene` is not allowed to fabricate CEO/CTO/COO turns. It creates an AI-agent request, and only `boardroom ingest` with verified AI-authored CEO/CTO/COO turns may create a `ready_for_mission` decision packet.

As of the same build, this is enforced inside the mission operator itself:

```text
cambrian mission operator --save --json
-> scheduler_readiness.product_boardroom_ready: true
-> tick_contract.requires_product_boardroom_ready: true
-> product_boardroom_gate.ready: true
-> product_boardroom_gate.latest_decision_ai_agent_turns_verified: true
-> product_boardroom_gate.latest_decision_generated_at >= product_boardroom_gate.mission_direction_updated_at
-> product_boardroom_gate.freshness_basis: mission_direction_updated_at
```

If the boardroom is missing, lacks CEO/CTO/COO prompt refs, lacks AI-agent contracts, lacks protocol/agenda/history, has no `ready_for_mission` decision packet, has no verified AI-authored CEO/CTO/COO turns, or the latest boardroom decision is older than the current mission direction, the operator reports `boardroom_required` and will not schedule the next mission tick.

This distinction is intentional. `mission_updated_at` is an operational ledger timestamp and can change when validation evidence is synced. `mission_direction_updated_at` changes only when the mission direction changes, so clean validation syncs do not force a new CEO/CTO/COO meeting by themselves.

Verification:

```text
python -m py_compile engine\project_company_layer.py engine\cli.py engine\project_mission.py
python -m pytest -q tests\test_company_layer.py tests\test_mission_company.py
-> 32 passed
```

### 14.10 Generated Agent Runtime Classification

Added on 2026-05-22 KST.

Cambrian must not use the word `agent` as a vague bucket. Generated workers are now classified by runtime kind:

```text
general_agent
= deterministic local workflow, routing, file inspection, validation, or artifact bookkeeping.

ai_agent
= thinking work: planning, diagnosis, review, product discussion, architecture judgment, risk judgment, or synthesis.
```

The rule is strict:

```text
If an agent has to think, it is an ai_agent.
If it is an ai_agent, it must require an LLM call.
If it requires an LLM call, job replies must include llm_invocation_evidence.
```

This prevents Cambrian from pretending that YAML, templates, or deterministic local code performed real reasoning.
Install and generation remain provider-free, but runtime thinking must be attributed to an external AI worker, provider
API, or local model adapter.

The generated workforce now carries:

```text
agent_kind_summary
agent_runtime_contracts
agent_runtime_policy
```

Each generated thinking agent carries:

```text
agent_kind: ai_agent
requires_llm_call: true
runtime_contract.llm_invocation.required: true
runtime_contract.llm_invocation.evidence_key: llm_invocation_evidence
```

The job bridge now includes selected agent runtime contracts in the execution packet. If any selected agent requires an
LLM call, the response contract adds `llm invocation evidence` to required evidence. `job ingest` then rejects or holds
the reply unless `llm_invocation_evidence` proves that the thinking work was actually performed by an AI worker/provider.

AVE proof cycle:

```text
workforce installed in AVE:
  ddmq-debugger
  anthropic-api-error-analyst
  stage-schema-validator
  pytest-regression-guardian
  risk-boundary-reviewer

agent_kind_summary:
  ai_agent: 5
  general_agent: 0

job ingest latest ai_reply_patch_candidate.yaml --json
-> required evidence included llm_invocation_evidence
-> reply_evidence_compliance: satisfied

job validate latest --run --json
-> validation_status: passed
-> trust_gate_status: verified
-> pytest: 27 passed
-> py_compile: passed

job complete latest --outcome success --json
-> verdict: pass

mission sync --json
-> synced

company boardroom convene + ingest
-> fresh CEO/CTO/COO ai_agent decision ingested
-> mission operator safe_to_schedule: true
```

Focused Cambrian regression checks:

```text
python -m py_compile engine\project_workforce_builder.py engine\project_custom_harness.py engine\project_bridge.py
python -m pytest -q tests\test_workforce_builder.py tests\test_agent_generation.py tests\test_job_start_runtime_contract.py
-> 16 passed

python -m pytest -q tests\test_job_complete_evidence.py tests\test_job_start_selects_agents_and_skills.py tests\test_project_agent_dispatch.py tests\test_dispatch_on_demand.py tests\test_custom_harness_from_answers.py tests\test_company_layer.py tests\test_mission_company.py
-> 48 passed
```

This is a product boundary, not only a schema addition. Cambrian can orchestrate ordinary deterministic agents locally,
but it cannot claim CEO/CTO/COO discussion, code diagnosis, review, planning, or synthesis happened unless an AI agent
turn or LLM invocation evidence exists.

### 14.11 Cambrian As LLM Clothing

Added on 2026-05-22 KST.

Cambrian is not a replacement for an LLM. Cambrian is the operating layer worn by an LLM:

```text
LLM = intelligence engine
Cambrian = clothes, harness, memory, evidence, authority, skills, agents, validation, and evolution around that engine
```

Therefore agent, skill, harness, and evolution generation must be LLM-first whenever the work needs judgment.
Only trivial routing, file bookkeeping, and validation command execution may stay purely deterministic.

Generation stages now carry an LLM assist contract:

```text
harness_generation
workforce_generation
agent_generation
skill_generation
skill_fusion
evolution_review
evolution_proposal
```

If an LLM provider is supplied, Cambrian calls it and records:

```text
llm_generation_evidence.called: true
mode: provider_api
provider: <provider>
quality_status: llm_assisted
```

If no provider is supplied, Cambrian may still create structure, but the quality status is downgraded:

```text
quality_status: bootstrap_draft
llm_enrichment_required: true
```

This is the honest boundary. Bootstrap drafts can help the user start, but they are not final intelligent generation.
Cambrian must not sell or present deterministic template output as if an LLM reasoned through the project.

### 14.12 Docs-To-Interview Inference

The harness interview is not the product. The product is Cambrian understanding the project well enough to build a useful operating layer.

Therefore the default install flow should be:

```text
project docs + scanner evidence
-> LLM-assisted interview inference
-> answers.yaml
-> ask only for missing or low-confidence fields
-> harness plan
```

For an existing project, Cambrian should read `README.md`, `CLAUDE.md`, `AGENTS.md`, architecture docs, release handoff docs, and other local Markdown before asking the user what the project is. If those documents already describe the domain, validation commands, safety policy, and key paths, the interview should collapse into a generated `answers.yaml`.

For a greenfield project, a deeper interview still matters because there may be no project evidence yet. Even there, strong project docs should reduce or replace manual questions.

Current implementation:

```text
cambrian harness interview infer --json
```

This command writes `.cambrian/interview/answers.yaml` from project documents and scanner evidence. If a provider is supplied, Cambrian records `llm_generation_evidence.called: true`. If no provider is supplied, the result is marked `project_docs_bootstrap` and keeps the honest `bootstrap_draft` quality boundary.

If the LLM returns structured interview answers, Cambrian may fill missing fields from that reply, but it must not blindly overwrite stronger local evidence. The practical rule is simple: local evidence drafts first, LLM fills gaps, human interview remains the fallback for unresolved or low-confidence fields.

### 14.13 Local MCP Adapter For AI Tool Operability

Added on 2026-05-22 KST.

The recent product decision is now fixed:

```text
CLI = human/operator entry
MCP = AI-tool entry
Web/download = distribution and understanding entry
```

For another person's Claude, Codex, Cursor, GPT, or local agent to use Cambrian naturally, a local MCP adapter is required. Without it, the user or AI must copy terminal commands by hand. That is acceptable for an internal smoke test, but weak for external-user adoption.

The correct first version is not a broad MCP platform. It is a thin local adapter:

```text
cambrian-mcp
```

Equivalent module form:

```text
python -m engine.project_mcp_server
```

The adapter exposes allowlisted Cambrian control-plane tools:

```text
cambrian_doctor
cambrian_project_scan
cambrian_harness_interview_infer
cambrian_harness_engineer_design
cambrian_harness_engineer_review
cambrian_harness_engineer_dry_run
cambrian_workforce_generate
cambrian_skill_generate
cambrian_harness_install
cambrian_job_start
cambrian_job_ingest
cambrian_job_validate
cambrian_job_complete
cambrian_company_snapshot
```

This is deliberately close to the CLI spine. MCP is not allowed to become a bypass around the harness.

MCP safety contract:

```text
explicit cwd required
allowlisted Cambrian CLI only
no arbitrary shell
no git push
no deploy
no publish
no secret reading
no source patch apply by default
harness install requires confirm=true
tool results return structuredContent and readable content
```

Product interpretation:

```text
MCP is the handle that lets an external AI operate Cambrian.
Cambrian remains the local AI company runtime.
Codex/Claude/Cursor/GPT remain execution engines.
```

Therefore MCP is now part of the external-user proof surface for OS-11, but not a replacement for One Good Harness.

The first proof question becomes:

```text
Can an external user's AI operate Cambrian's One Good Harness path through MCP without arbitrary shell access or private-data leakage?
```

If yes, MCP becomes the preferred entry path for external AI tools.

The local proof artifact is:

```text
python scripts/verify_mcp_operability.py --receipt dist/mcp_operability_receipt.json
```

That receipt must show initialize, tools/list, safe project scan with explicit `cwd`, missing-`cwd` blocking, harness install confirmation blocking, and no arbitrary shell exposure.

This proof belongs in the external-user release gate and AI Company Golden Path.
It should not run on every ordinary mission tick unless the mission is specifically about MCP or release readiness.

### 14.14 Supervised 24-Hour Company Operating Model

The 24-hour company is not a single autonomous agent.
It is a governed operating loop.

The correct architecture is:

```text
Cambrian
  = mission, boardroom, harness, authority, evidence, validation, memory, next task

Codex / Claude / Cursor / GPT / local model
  = thinking and execution worker

MCP
  = tool connection so the worker can operate Cambrian safely

Automation / heartbeat / scheduler
  = wake-up mechanism that starts the next bounded cycle
```

This matters because "24 hours" can easily become a fake autonomy claim.
Cambrian must not claim it can finish a product by itself unless each step is evidenced.

The allowed loop is:

```text
mission operator
-> product boardroom gate
-> mission tick or mission run --start-job
-> job packet
-> AI worker reply with evidence envelope
-> job ingest
-> job validate
-> job complete
-> mission sync
-> next bounded cycle
```

The loop must stop at any of these boundaries:

```text
missing boardroom decision
missing AI reply evidence
missing validation command
failed validation
authority-required action
source patch apply
git operation
deployment
publishing
secret access
payment or external spend
database migration
```

The practical local development mode in Codex is:

```text
Cambrian decides the next bounded job.
Codex performs the implementation work.
Cambrian validates, records, and selects the next job.
```

This is the right near-term product mode because it aligns with the architecture:

```text
AI company runtime first
AI execution engine second
MCP connection surface third
automation last
```

The next implementation priority is not to make Cambrian mutate code endlessly.
The priority is to make the supervised loop reliable enough that the user does not have to manually choose every task.

That means OS-11 remains the next task:

```text
First External Recipient Proof
```

But OS-11 now includes the local MCP path as a required operability proof, not merely CLI bundle proof.

### 14.15 Company Ready Status Must Be Proof-Derived

`cambrian company status --json` is a product trust surface, not a decorative dashboard.
It must never report the 24-hour company as ready from file presence alone, and it must never stay blocked when valid proof already exists.

The ready state is now derived from four conditions:

```text
company base initialized
context promotion proof exists
.cambrian/mission.yaml#last_outcome is success/pass/verified with unchecked_count = 0
.cambrian/company/verification/ledger.yaml has a pass/verified entry for the same job_id with unchecked_risk_count = 0
```

This makes the status board evidence-backed:

```text
company_loop_proof_exists: true
verification_ledger_proof_exists: true
project_company_ready: true
current_capability: verified_company_loop
readiness_blockers: []
```

Important boundary:

```text
auto_leadership_enabled remains false.
company_ready means the supervised loop has proof.
It does not mean Cambrian may mutate source, deploy, publish, spend money, use secrets, or run unattended without explicit scheduling authority.
```
