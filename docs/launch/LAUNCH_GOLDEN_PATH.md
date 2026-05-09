# Launch Golden Path

## 제품 한 문장

Cambrian installs AI worker packs into the AI you already use.

이미 쓰는 AI에 검증된 AI 일꾼을 설치하세요.

## 데모 대상

출시 데모는 `auth-bug-core` 하나만 사용한다. 이 pack은 Python + pytest + auth/login narrow bug fix에 맞춘 lane pack이다.

데모에서 보여주는 이야기는 다음 하나다.

```text
AI 작업반 설치
→ 작업 맡기기
→ 준비된 AI 답변 fixture ingest
→ 검증
→ 성과 확인
```

## 데모 전제

- 로컬에서 `cambrian` CLI를 실행할 수 있다.
- 첫 실행 프로젝트는 `examples/auth_bug_demo/`의 Python + pytest auth/login bug fixture다.
- 웹 catalog는 작업반을 고르는 hiring desk다.
- 실제 설치, 검증, proof는 로컬 Cambrian runtime에서 실행한다.
- AI provider API는 호출하지 않는다.
- 재현성을 위해 준비된 AI 답변 fixture를 사용한다.

## 실제 명령 순서

```bash
cd examples/auth_bug_demo
cambrian pack list
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

## Expected Output 요약

- `pack list`: `auth-bug-core`가 catalog에 보인다.
- `pack show auth-bug-core`: install command와 lane fit 정보가 보인다.
- `install pack auth-bug-core`: `.cambrian/` 아래 pack 설치 기록이 생긴다.
- `install doctor`: worker, team, template, workset 설치 상태를 확인한다.
- `pack activate auth-bug-core`: active pack context가 설정된다.
- `pack doctor auth-bug-core`: readiness가 `ready`, `partial`, `blocked` 중 하나로 표시된다.
- `pack start "로그인 에러 수정해"`: pack job과 bridge packet을 만들고 다음 명령을 안내한다.
- `pack job-ingest latest fixtures/ai_reply_patch_candidate.yaml`: canned `patch_candidate` reply를 bridge fast path로 라우팅한다.
- `pack job-validate latest`: validation-ready job을 validated proposal 흐름으로 연결한다.
- `pack proof auth-bug-core`: local usage/outcome 기반 proof card를 보여준다.

## Canned AI Reply

이 출시 데모는 재현성을 위해 실제 AI 호출 대신 준비된 AI 답변 fixture를 사용합니다.

```text
examples/auth_bug_demo/fixtures/ai_reply_patch_candidate.yaml
```

이 fixture의 `old_text`는 `examples/auth_bug_demo/src/auth.py`의 실제 내용과 맞아야 한다.

## 실패 시 Recovery

- active pack이 없으면 `cambrian pack activate auth-bug-core`를 실행한다.
- 설치 상태가 깨졌으면 `cambrian install doctor`를 먼저 본다.
- readiness가 blocked면 `cambrian pack setup auth-bug-core`로 안전한 setup checklist를 확인한다.
- job id를 잊었으면 `cambrian pack job-next latest`로 다음 명령을 다시 확인한다.
- canned reply가 실패하면 `fixtures/ai_reply_patch_candidate.yaml`의 `old_text`가 `src/auth.py`에 그대로 있는지 확인한다.
- proof가 비어 있으면 아직 local outcome이 없는 상태다. fake proof를 만들지 말고 실제 job 결과를 누적한다.

## 제외 범위

이번 launch run에는 아래를 넣지 않는다.

- remote registry
- dependency resolver
- pack rollout
- vNext release
- proof export
- public registry bundle
- canary/challenger board
- marketplace
- payment
- login
- cloud execution
- provider API 직접 호출

## Launch 판단 기준

처음 보는 사람이 1분 안에 제품을 이해하고, 5분 안에 `auth-bug-core`를 설치하고, 10분 안에 첫 job을 시작할 수 있으면 launch path는 성공이다.
