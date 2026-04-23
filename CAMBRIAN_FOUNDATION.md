# CAMBRIAN_FOUNDATION.md

## 1. 한 줄 정의

Cambrian은 AI 위에 입히는 프로젝트용 진화형 신뢰 하네스다.

영문 정의:

> Cambrian is an evolutionary trust harness that turns inconsistent LLM work into a persistent, verifiable, and improving project execution system.

한국어 정의:

> Cambrian은 들쭉날쭉한 LLM 작업 결과를 지속 가능하고 검증 가능하며 점점 나아지는 프로젝트 실행 시스템으로 바꾸는 진화형 신뢰 하네스다.

## 2. Cambrian이 푸는 문제

Cambrian은 다음 문제를 해결하려고 한다.

- 같은 요청을 다시 실행하면 LLM 결과 품질과 방식이 흔들린다.
- 세션이 초기화되면 프로젝트 맥락과 이전 판단이 끊기기 쉽다.
- 프로젝트별 기억이 없어서 같은 실수를 반복하기 쉽다.
- 어떤 변경을 채택해도 되는지 기준이 불명확하다.
- 실패 패턴과 회귀 신호가 축적되지 않으면 같은 문제를 계속 밟는다.
- 승인 없는 자동 변경이 실제 프로젝트를 불안정하게 만든다.

Cambrian의 문제의식은 AI를 막는 것이 아니라, AI를 더 많이 쓰되 더 안전하고 일관되게 쓰도록 만드는 데 있다.

## 3. 제품 철학

- AI는 유용하지만 그대로는 프로젝트 실행 시스템이 되기 어렵다.
- Cambrian은 AI를 대체하지 않는다. AI 위에 프로젝트 기억, 실행 규칙, 검증, 채택 이력을 덧씌운다.
- 좋은 실행 방식은 파일 기반 기록으로 축적되어야 한다.
- 실패한 방식은 다음 실행에서 피할 수 있도록 남아야 한다.
- 사람의 명시 승인과 이유가 필요한 단계는 끝까지 유지한다.

Cambrian은 AI를 덜 쓰게 만드는 도구가 아니라, 더 믿을 수 있게 더 오래 쓰게 만드는 하네스다.

## 4. Cambrian은 무엇인가

Cambrian은 다음 레이어를 제공하는 프로젝트 실행 시스템이다.

- project memory layer
  - 프로젝트 설정, 보호 경로, 선호 모드, 최근 여정, 학습된 힌트
- execution harness
  - 자연어 요청을 프로젝트 맥락 안에서 준비하고 실행하는 흐름
- verification layer
  - diagnose, related tests, isolated validation, post-apply verification
- explicit adoption layer
  - 사람이 승인한 변경만 공식 adoption record로 남기는 체계
- feedback and evolution memory
  - 무엇이 통했고 무엇이 실패했는지 다음 실행에 반영하는 기록

## 5. Cambrian은 무엇이 아닌가

Cambrian은 아래를 목표로 하지 않는다.

- Product OS
- Jira, Amplitude, LaunchDarkly 대체재
- 일반 목적 AI 챗봇
- 모든 것을 자동으로 수정하는 코딩 에이전트
- 자동 merge bot
- 현 단계의 AI 인증 기관

Cambrian은 프로젝트 안에서 AI 작업을 더 신뢰할 수 있게 만드는 실행 하네스다.

## 6. 핵심 루프

사용자 친화적 루프:

```text
Request
→ project memory
→ context suggestion
→ diagnose
→ patch intent
→ patch proposal
→ validation
→ explicit apply/adoption
→ status/learning
```

내부 루프:

```text
run
→ evidence
→ decision
→ adoption
→ feedback
→ next generation
```

## 7. 안전 원칙

Cambrian은 다음 원칙을 유지한다.

- no automatic adoption
- explicit human reason for apply/adoption
- file-first artifacts
- source immutability before apply
- backup before apply
- post-apply verification before latest update
- project-aware context before execution

즉, Cambrian은 자동으로 멋대로 고치는 시스템이 아니라, 근거를 모으고 사람이 안전하게 결정하게 돕는 시스템이다.

## 8. 사용자 경험 원칙

- 첫 명령은 `cambrian init --wizard`로 프로젝트 하네스를 맞춘다.
- 사용자는 `cambrian run "<요청>"`으로 자연어 요청을 시작한다.
- Cambrian은 부족한 문맥이 있으면 context scan과 clarification으로 다음 선택지를 제안한다.
- diagnose 단계에서는 파일을 읽고 관련 테스트를 실행하지만 source를 수정하지 않는다.
- patch intent와 patch proposal은 사용자의 명시 입력을 기반으로만 만든다.
- 실제 프로젝트 source 수정은 `cambrian patch apply --reason "..."` 단계에서만 일어난다.
- 결과는 `.cambrian/` 아래에 file-first로 남고, `cambrian status`가 최근 여정과 다음 행동을 보여준다.

## 9. 앞으로의 방향

Cambrian의 다음 확장 방향은 다음과 같다.

- 더 나은 project-aware skill routing
- 더 나은 context finding
- guided patch workflow 개선
- multi-variant 비교
- generation learning 강화
- 프로젝트별 진화 품질 향상

핵심은 기능을 늘리는 것 자체가 아니라, 프로젝트별로 더 일관되고 검증 가능한 AI 실행 체계를 만드는 것이다.
