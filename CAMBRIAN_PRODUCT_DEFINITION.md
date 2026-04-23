# CAMBRIAN_PRODUCT_DEFINITION.md

## 1. 제품 한 줄 정의

Cambrian은 AI 위에 입히는 프로젝트용 진화형 신뢰 하네스다.

영문 정의:

> Cambrian is an evolutionary trust harness for AI work.

확장 정의:

> Cambrian wraps AI work with project memory, execution rules, verification, explicit adoption, and evolutionary feedback.

## 2. 현재 제품 정의

Cambrian은 코딩 에이전트를 대체하려는 제품이 아니다.
Cambrian은 코딩 에이전트와 LLM 위에 프로젝트별 기억, 실행 규칙, 검증, 명시적 채택, 학습 기록을 덧씌우는 제품이다.

지금의 사용자 경험은 아래 흐름으로 설명된다.

```text
init
→ run
→ context suggestion
→ clarify
→ diagnose
→ patch intent
→ patch proposal
→ validation
→ explicit apply/adoption
→ status
```

즉, Cambrian의 중심은 내부 엔진 용어가 아니라 프로젝트 안에서 AI 작업을 더 안전하고 더 일관되게 실행하는 사용자 여정이다.

## 3. Cambrian이 푸는 문제

Cambrian은 다음 문제를 다룬다.

- LLM 출력 편차
- 세션 초기화와 맥락 손실
- 프로젝트 기억 부재
- 채택 기준 불명확
- 반복 실패 패턴의 재발
- 승인 없는 자동 변경의 위험

Cambrian은 "한 번 잘 생성하기"보다 "프로젝트 안에서 계속 믿고 쓸 수 있는 실행 체계 만들기"에 초점을 둔다.

## 4. 제품 철학

### 4.1 AI를 막지 않고 더 안전하게 쓴다

Cambrian은 AI를 제한하기 위한 도구가 아니라, 더 많이 쓰되 더 안전하게 쓰기 위한 하네스다.

### 4.2 내부 복잡성은 UX 뒤로 숨긴다

사용자는 `init`, `run`, `clarify`, `status`, `patch` 흐름을 이해하면 된다.
handoff, candidate, cycle, ledger, pressure 같은 개념은 내부 혹은 고급 artifact로 남긴다.

### 4.3 파일 기반 기록을 우선한다

프로젝트 기억과 실행 흔적은 `.cambrian/` 아래 file-first artifact로 남는다.
그래야 세션이 끊겨도 복원 가능하고, 사람과 도구가 같은 기록을 볼 수 있다.

### 4.4 명시 승인 경계를 유지한다

Cambrian은 source를 자동으로 바꾸지 않는다.
명시적 apply/adoption과 사람의 이유 입력은 끝까지 유지한다.

## 5. Cambrian이 제공하는 것

- project memory
  - 프로젝트 설정, 규칙, 추천 스킬, 최근 여정
- project-aware execution harness
  - 자연어 요청을 실행 가능한 다음 단계로 정리
- context suggestion
  - 관련 source/test 후보 추천
- guided diagnose
  - source를 바꾸지 않고 inspect와 관련 테스트 실행
- guided patch workflow
  - patch intent, patch proposal, isolated validation
- explicit adoption
  - 검증된 proposal만 실제 프로젝트에 적용하고 기록
- feedback and evolution memory
  - 무엇이 통했고 무엇이 실패했는지 다음 실행에 반영

## 6. Cambrian이 아닌 것

Cambrian은 다음을 지향하지 않는다.

- Product OS
- Jira 대체재
- Amplitude 대체재
- 일반 목적 AI 챗봇
- 자동 merge bot
- 승인 없이 모든 소스를 자동 수정하는 시스템

특히 아래는 현재 제품 정의와 충돌한다.

- 기본 자동 채택
- 승인 없는 자동 source 변경
- 완전 자율형 제품 관리자

## 7. 안전 원칙

Cambrian은 다음 원칙을 제품 정의의 일부로 본다.

- no automatic adoption
- explicit apply/adoption only
- file-first artifacts
- source immutability before apply
- backup and post-apply verification
- human reason required for real apply

## 8. 프로젝트 모드 핵심 명령

사용자 중심 명령은 다음이다.

- `cambrian init`
- `cambrian run`
- `cambrian status`
- `cambrian context scan`
- `cambrian clarify`
- `cambrian patch intent`
- `cambrian patch intent-fill`
- `cambrian patch propose`
- `cambrian patch apply`

`brain`, `evolution` 같은 명령은 여전히 중요하지만 고급 내부/운영 명령으로 설명하는 편이 맞다.

## 9. 앞으로의 방향

앞으로 Cambrian은 다음 축을 강화한다.

- 더 나은 project-aware skill routing
- 더 나은 context finding
- guided patch workflow 개선
- multi-variant 비교
- generation learning
- 프로젝트별 진화 품질 향상

핵심은 새 용어를 늘리는 것이 아니라, 프로젝트별 AI 실행 체계를 더 일관되고 더 검증 가능하게 만드는 것이다.
