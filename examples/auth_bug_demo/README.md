# Auth Bug Demo

이 fixture는 Cambrian launch demo를 재현하기 위한 작은 Python + pytest 프로젝트입니다.

데모 목적은 실제 AI provider 호출 없이 `auth-bug-core` 작업반의 흐름을 보여주는 것입니다.

```text
pack start
→ canned AI reply ingest
→ validate
→ proof
```

## Bug Scenario

`src/auth.py`의 `normalize_username()`이 username의 앞뒤 공백과 대소문자를 정규화하지 않습니다.

데모 요청:

```text
로그인 에러 수정해
```

## Run

저장소 루트에서:

```bash
cd examples/auth_bug_demo
cambrian pack show auth-bug-core
cambrian install pack auth-bug-core
cambrian install doctor
cambrian pack activate auth-bug-core
cambrian pack doctor auth-bug-core
cambrian pack start "로그인 에러 수정해"
cambrian pack job-ingest latest fixtures/ai_reply_patch_candidate.yaml
cambrian pack job-validate latest
cambrian pack proof auth-bug-core
```

이 데모는 재현성을 위해 실제 AI 호출 대신 준비된 AI 답변 fixture를 사용합니다.

```text
fixtures/ai_reply_patch_candidate.yaml
```

## Safety

- provider API key가 필요 없습니다.
- Cambrian 본체 source file을 수정하지 않습니다.
- `pack job-ingest`와 `pack job-validate`는 source를 자동 apply하지 않습니다.
- 실제 source 변경은 별도 explicit apply 단계에서만 일어납니다.
