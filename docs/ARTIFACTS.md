# Cambrian Artifacts

Cambrian은 `.cambrian/` 아래에 file-first artifact를 남깁니다.
이 기록은 세션이 끝나도 남아 프로젝트 기억과 실행 근거를 복원하는 기준이 됩니다.

## 원칙

- source of truth는 가능한 한 개별 artifact 파일입니다.
- `_latest.json`, `_ledger.json` 같은 파일은 derived index일 수 있습니다.
- user-facing artifact와 internal artifact를 구분해 설명합니다.
- 삭제 가능 여부는 "복구 가능성" 기준으로 봅니다.

## 아티팩트 안내

| 경로 | 목적 | source of truth 여부 | 성격 | 삭제 안전성 | 재생성 가능 |
|---|---|---|---|---|---|
| `.cambrian/project.yaml` | 프로젝트 이름, 타입, 테스트 명령, onboarding 정보 | 예 | user-facing | 권장하지 않음 | 일부 가능 |
| `.cambrian/rules.yaml` | 보호 경로, adoption 안전 규칙 | 예 | user-facing | 권장하지 않음 | 일부 가능 |
| `.cambrian/skills.yaml` | 추천 스킬과 기본 선택 | 예 | user-facing | 권장하지 않음 | 가능 |
| `.cambrian/profile.yaml` | mode, variants, 기본 UX/운영 옵션 | 예 | user-facing | 권장하지 않음 | 가능 |
| `.cambrian/init_report.yaml` | init wizard 결과 요약 | 예 | user-facing | 삭제 가능 | 제한적 |
| `.cambrian/requests/` | 자연어 요청과 실행 준비 상태 | 예 | user-facing | 권장하지 않음 | 일부 가능 |
| `.cambrian/context/` | context scan 추천 결과 | 예 | user-facing | 삭제 가능 | 가능 |
| `.cambrian/clarifications/` | 부족한 문맥 질문과 사용자 선택 | 예 | user-facing | 삭제 가능 | 일부 가능 |
| `.cambrian/brain/runs/` | diagnose/brain run 결과와 report | 예 | mixed | 권장하지 않음 | 재실행 필요 |
| `.cambrian/patch_intents/` | patch intent form과 사용자 입력 결과 | 예 | user-facing | 삭제 가능 | 일부 가능 |
| `.cambrian/patches/` | patch proposal, task spec, isolated validation 결과 | 예 | user-facing | 권장하지 않음 | 일부 가능 |
| `.cambrian/adoptions/` | 공식 adoption record와 backup | 예 | user-facing | 권장하지 않음 | 일부는 불가 |
| `.cambrian/adoptions/_latest.json` | 최신 adoption 빠른 포인터 | 아니오, derived | user-facing | 삭제 가능 | 가능 |
| `.cambrian/feedback/` | 사람이 남긴 피드백과 autopsy 결과 | 예 | mixed | 삭제 가능 | 일부 가능 |
| `.cambrian/evolution/` | generation/evolution 관련 derived view와 일부 source artifact | mixed | internal | 주의 필요 | 일부 가능 |

## 사용자에게 중요한 경로

### `.cambrian/project.yaml`

프로젝트 하네스의 기본 정의입니다.
`cambrian status`와 `run` 흐름이 이 파일을 기준으로 프로젝트 타입과 기본 테스트 명령을 해석합니다.

### `.cambrian/requests/`

자연어 요청이 어떻게 해석되었는지 남깁니다.
needs_context, selected skills, next action 같은 정보가 들어갑니다.

### `.cambrian/context/`

관련 source/test 후보 추천 결과입니다.
실행이 아니라 추천 단계의 근거를 저장합니다.

### `.cambrian/clarifications/`

무엇이 부족했고, 어떤 후보를 보여줬고, 사용자가 무엇을 골랐는지 남깁니다.

### `.cambrian/brain/runs/`

diagnose-only run이나 고급 brain run의 report가 들어갑니다.
inspect 결과, related tests, diagnostics summary를 확인할 수 있습니다.

### `.cambrian/patch_intents/`

diagnosis 결과에서 patch intent form을 만든 뒤, 사용자가 old/new text를 채운 결과를 남깁니다.

### `.cambrian/patches/`

patch proposal과 validation 결과가 남습니다.
이 단계까지는 실제 프로젝트 source를 수정하지 않습니다.

### `.cambrian/adoptions/`

실제 apply 이후의 공식 기록입니다.
adoption record, backup, latest pointer가 여기에 있습니다.

## derived artifact와 source of truth 구분

다음 파일은 빠른 조회를 위한 derived index일 수 있습니다.

- `.cambrian/adoptions/_latest.json`
- `.cambrian/evolution/_ledger.json`

이런 파일은 다시 만들 수 있지만, 원본 source artifact가 사라지면 의미가 줄어듭니다.

## 삭제 정책 가이드

- `project.yaml`, `rules.yaml`, `skills.yaml`, `profile.yaml`은 유지하는 편이 맞습니다.
- `requests`, `context`, `clarifications`, `patch_intents`는 필요 시 정리할 수 있지만 이력 손실이 있습니다.
- `adoptions`와 `brain/runs`는 나중에 왜 그런 결정을 했는지 추적하는 핵심 기록이라 보존 권장입니다.
- `patches/workspaces` 같은 isolated validation 산출물은 상황에 따라 정리할 수 있습니다.

## 왜 file-first인가

Cambrian은 세션 메모리보다 파일 기록을 우선합니다.
그래야 다음이 가능해집니다.

- 세션이 끊겨도 실행 맥락 복원
- 사람이 결과와 근거를 직접 검토
- derived index 재구성
- apply/adoption 이력 추적
- 프로젝트별 학습 축적
