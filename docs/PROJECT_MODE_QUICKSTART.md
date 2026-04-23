# Cambrian Project Mode Quickstart

이 문서는 Cambrian을 프로젝트에 맞추고, `do`와 `do --continue` 중심으로 작업을 이어가는 가장 짧은 기본 흐름을 설명합니다.

Cambrian이 해주는 일:

- 프로젝트 규칙과 test command를 file-first artifact로 기록합니다.
- 자연어 요청에서 관련 source/test 후보를 찾습니다.
- source를 바로 바꾸지 않고 먼저 diagnose와 validation을 수행합니다.
- explicit apply 이유가 있을 때만 실제 source를 수정합니다.
- 작업 결과와 project memory를 status에 남깁니다.

중요한 안전 원칙:

- Cambrian은 automatic adoption을 하지 않습니다.
- project source 수정은 explicit apply 단계에서만 일어납니다.
- apply 이전에는 diagnose, intent, proposal, validation artifact만 쌓입니다.

## 기본 흐름

```bash
cambrian init --wizard
cambrian do "fix the login bug"
cambrian do --continue
cambrian status
```

## 1. 프로젝트 초기화

```bash
cambrian init --wizard
```

생성되는 주요 파일:

- `.cambrian/project.yaml`
- `.cambrian/rules.yaml`
- `.cambrian/skills.yaml`
- `.cambrian/profile.yaml`

다음 기본 명령:

```bash
cambrian do "fix the login bug"
```

## 2. 자연어 요청 시작

```bash
cambrian do "로그인 정규화 버그 수정해"
```

여기서 Cambrian은:

- project memory를 읽고
- 관련 source/test 후보를 찾고
- 필요하면 clarification을 만들고
- 다음 명령을 제안합니다

예상되는 다음 명령:

```bash
cambrian do --continue --use-suggestion 1 --execute
```

## 3. 추천 context로 진단

```bash
cambrian do --continue --use-suggestion 1 --execute
```

여기서 Cambrian은:

- source를 inspect하고
- 관련 test를 실행하고
- diagnosis report를 남깁니다

이 단계에서는 source를 수정하지 않습니다.

## 4. 한 줄로 validation까지 진행

```bash
cambrian do --continue --old-choice old-1 --new-text "return username.strip().lower()" --validate
```

여기서 Cambrian은:

- patch intent를 만들고
- intent를 채우고
- patch proposal을 만들고
- isolated validation까지 수행합니다

이 단계에서도 source를 수정하지 않습니다.

## 5. 명시적으로 apply

```bash
cambrian do --continue --apply --reason "normalize username before login"
```

여기서 Cambrian은:

- validated proposal만 적용하고
- post-apply tests를 다시 돌리고
- adoption record와 latest pointer를 남깁니다

이 단계에서만 source가 수정됩니다.

## 6. 현재 상태 확인

```bash
cambrian status
```

status에서 볼 수 있는 것:

- active work 또는 latest completed work
- recent journey
- latest adoption
- project memory
- next action

## Advanced / Manual Path

아래 명령은 수동 제어가 필요할 때 쓰는 고급 경로입니다.

```bash
cambrian run "fix the login bug"
cambrian patch intent ...
cambrian patch intent-fill ...
cambrian patch propose ...
cambrian patch apply ...
```

처음에는 이 문서보다 [FIRST_RUN_DEMO](C:/Users/user/Desktop/cambrain/cambrian/docs/FIRST_RUN_DEMO.md) 흐름을 그대로 따라가는 편이 가장 빠릅니다.
