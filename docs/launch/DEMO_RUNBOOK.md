# First Run Runbook

## 1. 데모 목적

Auth Bug Core 작업반을 설치하고, 로그인 버그 작업을 맡기고, 실제 AI 호출 없이 준비된 AI 답변 fixture로 reply ingest와 validation handoff를 시연한다.

This launch run uses a canned AI reply fixture so the product flow is reproducible without calling any AI provider.

이 출시 데모는 재현성을 위해 실제 AI 호출 대신 준비된 AI 답변 fixture를 사용합니다.

## 2. 데모 전 준비

- `cambrian` CLI가 실행 가능해야 한다.
- provider API key는 필요 없다.
- 네트워크 연결은 필요 없다.
- 첫 실행은 저장소의 `examples/auth_bug_demo/` fixture에서 실행한다.

## 3. 실행 디렉토리

```bash
cd examples/auth_bug_demo
```

## 4. 명령 순서

```bash
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

## 4.1 재현 가능한 dry run

출시 전에는 아래 runner로 같은 흐름을 자동 리허설한다.

```bash
python tools/run_launch_demo.py --out .launch_runs/latest
```

runner는 `examples/auth_bug_demo`를 `.launch_runs/latest/workdir`로 복사한 뒤 실제 Cambrian CLI 명령을 실행한다. 각 단계의 stdout, stderr, exit code, duration은 transcript와 summary로 저장된다.

생성되는 증거:

```text
.launch_runs/latest/transcript.md
.launch_runs/latest/summary.json
docs/launch/LAUNCH_RC_REPORT.md
```

이 dry run도 실제 AI provider를 호출하지 않는다. 준비된 canned AI reply fixture만 사용한다.

## 5. Expected Output

- `pack show auth-bug-core`: Auth Bug Core pack 설명과 install command가 보인다.
- `install pack auth-bug-core`: `.cambrian/` 아래 pack 설치 기록이 생긴다.
- `install doctor`: worker, team, template, workset 설치 상태를 확인한다.
- `pack activate auth-bug-core`: active pack이 `auth-bug-core`로 설정된다.
- `pack doctor auth-bug-core`: readiness 상태가 표시된다.
- `pack start "로그인 에러 수정해"`: pack job과 bridge packet이 생성된다.
- `pack job-ingest latest fixtures/ai_reply_patch_candidate.yaml`: `patch_candidate` reply가 validation-ready job으로 라우팅된다.
- `pack job-validate latest`: validated proposal까지 연결된다. source file은 자동 적용되지 않는다.
- `pack proof auth-bug-core`: local proof 상태를 보여준다. 아직 실제 채택 outcome이 없으면 없는 상태를 정직하게 보여준다.

## 6. AI Reply Fixture

준비된 답변 fixture:

```text
examples/auth_bug_demo/fixtures/ai_reply_patch_candidate.yaml
```

핵심 필드:

```yaml
response_kind: patch_candidate
target_path: src/auth.py
old_text: "return username"
new_text: "return username.strip().lower()"
```

`old_text`는 `examples/auth_bug_demo/src/auth.py`의 실제 내용과 맞아야 한다.

## 7. Validation 예상 결과

Cambrian validation은 patch candidate를 validated proposal로 연결한다. 이 단계는 source를 자동 수정하지 않는다.

데모 fixture의 pytest는 source가 그대로이면 실패할 수 있다. 제안된 patch를 명시적으로 적용하면 통과해야 한다.

## 8. Proof / Outcome 확인

```bash
cambrian pack proof auth-bug-core
```

이 명령은 local usage/outcome 기반 proof를 보여준다. launch run는 fake success rate나 public proof metric을 만들지 않는다.

## 9. 실패 시 Recovery

- job id를 잊었으면 `cambrian pack job-next latest`를 실행한다.
- 설치 상태가 이상하면 `cambrian install doctor`를 실행한다.
- active pack이 없으면 `cambrian pack activate auth-bug-core`를 다시 실행한다.
- reply ingest가 실패하면 `fixtures/ai_reply_patch_candidate.yaml`의 `old_text`가 `src/auth.py`에 그대로 있는지 확인한다.
- proof가 비어 있으면 아직 local outcome이 충분히 없는 것이다. 수치를 만들지 않는다.

## 10. 의도적으로 제외한 것

- remote registry
- web marketplace
- dependency resolver 확장
- rollout / vNext
- canary / challenger
- provider API 호출
- source auto apply
- cloud execution
- 결제 / 로그인
- public proof publishing
