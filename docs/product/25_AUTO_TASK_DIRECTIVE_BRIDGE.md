# Auto Task Directive Bridge

## 목적

`cambrian auto run --max-steps N`은 V1에서 source code를 직접 수정하지 않는다.

대신 `auto plan`의 step을 Codex 또는 Claude가 실행할 수 있는 작업지시서로 변환하고, 각 step을 `waiting_for_result` 상태로 기록한다.

## 명령 흐름

```bash
cambrian auto init --goal "Build this product" --json
cambrian auto boardroom --json
cambrian auto plan --json
cambrian auto run --max-steps 5 --json
```

## 생성 파일

`auto run`은 실행 가능한 step마다 아래 파일을 생성한다.

```text
.cambrian/auto/tasks/<plan-id>-<step-id>.yaml
.cambrian/auto/tasks/<plan-id>-<step-id>.md
```

YAML 파일은 machine-readable task 상태다.

Markdown 파일은 Codex/Claude에 전달할 수 있는 작업지시서다.

## task 상태 계약

```yaml
status: waiting_for_result
execution_engine: Codex or Claude
safety:
  source_code_modified_by_auto_run: false
  provider_api_called_by_auto_run: false
  requires_result_ingest: true
```

## auto run 출력 계약

```json
{
  "ok": true,
  "mode": "auto",
  "executed_steps": 1,
  "waiting_for_result": 1,
  "task_refs": [
    ".cambrian/auto/tasks/auto-plan-...-step-001.yaml"
  ],
  "directive_refs": [
    ".cambrian/auto/tasks/auto-plan-...-step-001.md"
  ],
  "source_code_modified": false
}
```

`executed_steps`는 V1에서 실제 구현 완료가 아니라 “작업지시서 발행 완료”를 뜻한다.

## 실행 로그

`auto run`은 아래 파일에 실행 기록을 남긴다.

```text
.cambrian/auto/execution_log.yaml
```

각 run은 최소 아래 정보를 포함한다.

- task refs
- directive refs
- waiting_for_result count
- blocked steps
- next state
- changed_files: []
- commands_executed: []
- source code 변경 없음

## 안전 경계

- auto run은 source code를 수정하지 않는다.
- auto run은 provider API를 호출하지 않는다.
- auto run은 git commit/push를 하지 않는다.
- auto run은 deploy/payment/secret 작업을 하지 않는다.
- 실제 구현 결과는 다음 단계의 result intake에서 별도로 받아야 한다.

## 제품 판단

AI 회사의 실행 루프는 다음 순서로 닫힌다.

```text
boardroom decision
→ auto plan
→ auto task directive
→ Codex/Claude execution
→ result intake
→ validation
→ next plan or evolution
```

이번 V1은 `auto task directive`까지를 구현한다.
