# Cambrian 10-Year Architecture

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
- proof dashboard MVP

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
