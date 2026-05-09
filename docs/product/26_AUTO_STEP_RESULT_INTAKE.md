# Auto Step Result Intake

## 목적

`cambrian auto run`이 만든 Codex/Claude 작업지시서는 Cambrian 내부에서 바로 완료 처리되지 않는다.

외부 실행 엔진이 실제 작업을 수행한 뒤, 그 결과를 파일로 남기고 Cambrian이 다시 받아들여 auto task 상태와 evidence를 갱신한다.

이 문서는 그 결과 수집 계약을 고정한다.

## 명령 흐름

```bash
cambrian auto run --max-steps 1 --json
cambrian auto step ingest .cambrian/auto/tasks/<task-id>.yaml --result step_result.yaml --json
```

`task-ref`는 task id, `.cambrian/auto/tasks/*.yaml` 경로, 또는 task yaml 파일명을 받을 수 있다.

## 결과 파일 형식

Codex/Claude는 최소 아래 형태의 YAML 또는 JSON을 남긴다.

```yaml
status: success
summary: "작업 결과 요약"
changed_files:
  - docs/product/example.md
tests:
  - command: "python -m pytest tests/test_example.py"
    status: passed
blockers: []
next_action: "auto report로 상태를 확인한다."
evidence:
  notes:
    - "검증 근거를 적는다."
  artifacts: []
```

필수 필드:

```text
status
summary
changed_files
tests
blockers
next_action
evidence
```

필수 필드가 없거나 타입이 맞지 않으면 `auto step ingest`는 task 상태를 바꾸지 않고 `invalid_result_contract`로 실패한다.

## 상태 판정

Cambrian은 결과 파일을 읽고 task 상태를 다음처럼 판정한다.

- `blocked`: 결과 status가 실패 계열이거나 `blockers`가 비어 있지 않다.
- `validated`: validation 또는 tests가 성공 계열이다.
- `done`: 명시적 성공 결과는 있지만 검증 evidence가 없다.
- `result_ingested`: 결과 파일은 수집됐지만 검증/차단 정보가 부족하다.

## 생성 및 갱신 파일

결과 수집은 아래 metadata만 갱신한다.

```text
.cambrian/auto/tasks/<task-id>.yaml
.cambrian/auto/results/<task-id>.yaml
.cambrian/auto/execution_log.yaml
.cambrian/auto/state.yaml
.cambrian/evidence/authority_log.yaml
```

`execution_log.yaml`에는 `step_results` 항목이 추가된다.

## 다음 상태

- 정상 수집 또는 검증 성공: `VALIDATION`
- blocker 존재: `REVIEW`

## 안전 경계

- result intake는 source code를 수정하지 않는다.
- result intake는 provider API를 호출하지 않는다.
- result intake는 git commit/push를 하지 않는다.
- result intake는 deploy, payment, secret 작업을 하지 않는다.
- 실제 변경 내용은 Codex/Claude 결과 파일의 evidence로만 기록된다.

## 제품 루프 위치

```text
boardroom decision
→ auto plan
→ auto task directive
→ Codex/Claude execution
→ result intake
→ validation / review
→ next plan or evolution
```

이번 계약은 `result intake` 구간을 담당한다.
