# Cambrian First-Run Demo

160R 기준 제품 메시지:

```text
Cambrian installs a custom AI harness for each project and dispatches AI agents into that harness.
```

기본 흐름:

```bash
cambrian project scan
cambrian harness plan
cambrian harness install
cambrian agent dispatch "로그인 에러 수정해"
```

`auth-bug-core`는 첫 built-in harness preset이며, Cambrian 자체가 아니다.

이 문서는 Cambrian을 처음 쓰는 사람이 "AI 일꾼 설치 → 안전한 작업 → 검증 → 명시적 적용" 흐름을 10분 안에 따라가도록 만든다.

Cambrian은 AI Worker Installer다. 데모에서는 Python + pytest + auth/login narrow bug fix lane에 맞는 로컬 하네스를 입힌다.

## Current strongest lane

```text
Python + pytest + auth/login narrow bug fix
test-first
narrow-scope
review-support
```

기본값:

- Default team: `auth-bug-team`
- Default template: `auth-bug-template`
- Default workset: `auth-bug-workset`

## What you will see

- 프로젝트에 맞는 local Cambrian runtime 초기화
- worker/team/template/lane pack 기반 추천
- source 변경 전 context scan, diagnose, validation
- explicit apply/adoption 뒤에만 source 변경
- `.cambrian/` artifact와 `cambrian status`로 evidence 확인

## 1. Demo project 만들기

```bash
cambrian demo create login-bug --out ./cambrian-login-demo
cd ./cambrian-login-demo
```

환경을 먼저 확인하고 싶다면 다음 명령을 사용한다.

```bash
cambrian doctor
```

생성 파일:

- `src/auth.py`
- `tests/test_auth.py`
- `demo_answers.yaml`
- `README_DEMO.md`

초기 상태에서는 test가 실패한다.

```bash
pytest -q
```

## 2. Cambrian 설치하기

```bash
cambrian init --wizard --answers-file demo_answers.yaml
cambrian status
```

원하면 template 선택을 명시할 수 있다.

```bash
cambrian init --wizard --use-recommended-template
cambrian init --wizard --skip-template
```

## 3. 자연어 요청 시작

```bash
cambrian do "로그인 정규화 버그 수정해"
```

Cambrian은 관련 source/test 후보를 찾고, 필요한 경우 clarification과 다음 명령을 제안한다.

## 4. 진단 실행

```bash
cambrian do --continue --use-suggestion 1 --execute
```

이 단계에서는 source를 바꾸지 않는다. source inspect, related test, diagnosis report를 만든다.

## 5. proposal validation까지 진행

```bash
cambrian do --continue --old-choice old-1 --new-text "return username.strip().lower()" --validate
```

이 단계에서는 patch intent, patch proposal, isolated validation을 만든다. 아직 source는 바뀌지 않는다.

## 6. 명시적으로 apply/adoption

```bash
cambrian do --continue --apply --reason "normalize username before login"
```

이 단계에서만 source가 바뀐다. Cambrian은 post-apply test와 adoption record를 남긴다.

## 7. 결과 확인

```bash
pytest -q
cambrian status
cambrian summary
```

`summary`는 local `.cambrian/` artifact만 읽는다. cloud telemetry를 보내지 않는다.

## Advanced manual path

처음에는 `do` / `do --continue` 흐름을 권장한다. artifact를 직접 제어해야 하면 다음 명령을 사용할 수 있다.

```bash
cambrian patch intent .cambrian/brain/runs/<run-id>/report.json
cambrian patch intent-fill .cambrian/patch_intents/<intent>.yaml --old-choice old-1 --new-text "return username.strip().lower()"
cambrian patch propose --from-intent .cambrian/patch_intents/<intent>.yaml --execute
cambrian patch apply .cambrian/patches/<proposal>.yaml --reason "normalize username before login"
```
