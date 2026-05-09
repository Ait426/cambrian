# Cambrian Login Bug Demo

이 demo는 Cambrian의 strongest lane인 Python + pytest + auth/login narrow bug fix를 빠르게 체험하기 위한 샘플 프로젝트다.

Cambrian은 AI Worker Installer다. 이 프로젝트에 로컬 AI 일꾼과 작업반을 설치하고, source 변경 전 diagnosis와 validation evidence를 먼저 만든다.

## Start here

```bash
cambrian init --wizard --answers-file demo_answers.yaml
cambrian do "로그인 정규화 버그 수정해"
cambrian do --continue --use-suggestion 1 --execute
cambrian do --continue --old-choice old-1 --new-text "return username.strip().lower()" --validate
cambrian do --continue --apply --reason "normalize username before login"
cambrian status
```

실제 source 수정은 explicit apply 단계에서만 수행된다.

## What this proves

- local Cambrian runtime이 프로젝트 상태를 읽는다.
- AI bridge와 work loop가 source 변경 전 evidence를 만든다.
- `validated_proposal_rate`가 Cambrian의 north star metric인 이유를 체감할 수 있다.
- strongest lane 밖에서는 더 많은 evidence가 필요하다는 원칙을 유지한다.

## Advanced manual path

```bash
cambrian patch intent .cambrian/brain/runs/<run-id>/report.json
cambrian patch intent-fill .cambrian/patch_intents/<intent>.yaml --old-choice old-1 --new-text "return username.strip().lower()" --propose --execute
cambrian patch apply .cambrian/patches/<proposal>.yaml --reason "normalize username before login"
```

`<run-id>`, `<intent>.yaml`, `<proposal>.yaml`은 실행 중 생성된 실제 경로로 바꿔 넣으면 된다.
