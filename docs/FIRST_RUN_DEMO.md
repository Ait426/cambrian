# Cambrian First-Run Demo

Cambrian?멸? ?꾩쟾?섍쾶 怨꾩냽?섏? 紐삵븷 ???곷떒?쒕? 蹂댁뿬二쇨퀬, `Problem / Why / Try` ?뺤떇?쇰줈 ?ㅼ쓬 紐낅졊??안내?⑸땲??.

이 문서는 Cambrian을 처음 쓰는 사람이 10분 안에 핵심 흐름을 직접 따라가 보도록 만든 데모 안내서입니다.

이 데모에서 확인할 수 있는 것:

- Cambrian이 프로젝트에 맞는 문맥을 찾는 방식
- source를 바로 바꾸지 않고 먼저 진단하는 방식
- `cambrian do --continue`만으로 patch validation까지 이어지는 방식
- explicit apply 이유를 받은 뒤에만 실제 source를 바꾸는 방식
- 작업 결과와 project memory가 `cambrian status`에 남는 방식

길을 잃으면 언제든 아래 명령부터 다시 보면 됩니다.

```bash
cambrian status
```

설치나 환경 상태부터 다시 확인하고 싶다면 [ALPHA_INSTALL](C:/Users/user/Desktop/cambrain/cambrian/docs/ALPHA_INSTALL.md) 문서와 아래 명령을 먼저 보세요.

```bash
cambrian doctor
```

## 1. Demo 프로젝트 만들기

```bash
cambrian demo create login-bug --out ./cambrian-login-demo
cd ./cambrian-login-demo
```

What you should see:

- `src/auth.py`
- `tests/test_auth.py`
- `demo_answers.yaml`
- `README_DEMO.md`

초기 상태에서는 테스트가 실패합니다.

```bash
pytest -q
```

## 2. Cambrian을 프로젝트에 입히기

```bash
cambrian init --wizard --answers-file demo_answers.yaml
cambrian status
```

What you should see:

- `.cambrian/project.yaml`
- `.cambrian/rules.yaml`
- `.cambrian/skills.yaml`
- `.cambrian/profile.yaml`
- 다음 명령으로 `cambrian do ...` 제안

## 3. 자연어 요청으로 시작하기

```bash
cambrian do "로그인 정규화 버그 수정해"
```

What you should see:

- 관련 source/test 후보
- clarification artifact
- 다음 명령으로 `cambrian do --continue --use-suggestion 1 --execute`

## 4. 추천 context로 진단 실행하기

```bash
cambrian do --continue --use-suggestion 1 --execute
```

What you should see:

- source inspect
- related test 실행
- diagnosis report 생성
- source는 아직 수정되지 않음

## 5. 한 줄로 patch proposal validation까지 진행하기

```bash
cambrian do --continue --old-choice old-1 --new-text "return username.strip().lower()" --validate
```

What you should see:

- patch intent 생성
- patch proposal 생성
- isolated validation 수행
- source는 아직 수정되지 않음
- 다음 명령으로 `cambrian do --continue --apply --reason "..."`

## 6. 명시적으로 apply / adoption 하기

```bash
cambrian do --continue --apply --reason "normalize username before login"
```

What you should see:

- 실제 project source 수정
- post-apply tests 실행
- adoption record 생성
- `_latest.json` 갱신

이 단계에서만 source가 바뀝니다.

## 7. 결과와 기억 확인하기

```bash
pytest -q
cambrian status
cambrian summary
cambrian memory rebuild
cambrian memory list
```

What you should see:

- 최근 작업 여정
- latest adoption
- local-only usage summary
- project memory
- 다음 작업을 위한 next action

`cambrian summary`는 `.cambrian/` 아래 로컬 artifact만 읽어 session, diagnosis, adopted change, lessons remembered, safety summary를 보여줍니다.
외부 telemetry는 보내지 않습니다.

알파 사용 중 헷갈리거나 좋았던 점을 남기고 싶다면 아래처럼 로컬 note를 저장하면 됩니다.

```bash
cambrian notes add "clarify step was confusing" --kind confusion
```

## Advanced / Manual Path

아래 명령은 여전히 유지되는 고급 수동 경로입니다. 첫 사용자 흐름에서는 `do`와 `do --continue`를 먼저 쓰는 편이 좋습니다.

```bash
cambrian patch intent .cambrian/brain/runs/<run-id>/report.json
cambrian patch intent-fill .cambrian/patch_intents/<intent>.yaml --old-choice old-1 --new-text "return username.strip().lower()"
cambrian patch propose --from-intent .cambrian/patch_intents/<intent>.yaml --execute
cambrian patch apply .cambrian/patches/<proposal>.yaml --reason "normalize username before login"
```

`<run-id>`, `<intent>`, `<proposal>`은 실제 생성된 경로로 바꿔 넣으면 됩니다.
