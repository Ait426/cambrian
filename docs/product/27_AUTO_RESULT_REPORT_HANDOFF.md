# Auto Result Report Handoff

## 목적

`cambrian auto report`는 auto mode의 단순 상태 출력이 아니다.

Codex/Claude 결과를 `auto step ingest`로 받아들인 뒤, Cambrian이 다음 결정을 어디로 넘겨야 하는지 요약하는 handoff 문서다.

## 입력

`auto report`는 아래 로컬 metadata를 읽는다.

```text
.cambrian/auto/state.yaml
.cambrian/auto/plan.yaml
.cambrian/auto/tasks/*.yaml
.cambrian/auto/execution_log.yaml
```

## 출력 계약

```json
{
  "ok": true,
  "report": {
    "task_statuses": {
      "waiting_for_result": 0,
      "validated": 1,
      "blocked": 0
    },
    "step_results": {
      "total": 1,
      "validated": 1,
      "blocked": 0,
      "open_blockers": []
    },
    "decision_handoff": {
      "status": "ready_for_release_or_next_plan",
      "next_command": "cambrian auto plan --json"
    },
    "source_code_modified": false
  }
}
```

## Handoff 상태

- `waiting_for_external_result`: 아직 result intake가 필요한 task가 있다.
- `needs_boardroom_review`: blocked step result가 있어 boardroom 판단이 필요하다.
- `ready_for_release_or_next_plan`: 검증 evidence가 있어 다음 계획 또는 release gate로 넘길 수 있다.
- `needs_validation`: 결과는 들어왔지만 검증 evidence가 부족하다.
- `ready_for_auto_run`: pending result가 없고 다음 auto run을 시작할 수 있다.
- `not_initialized`: auto mode가 아직 초기화되지 않았다.

## 안전 경계

- `auto report`는 source code를 수정하지 않는다.
- `auto report`는 provider API를 호출하지 않는다.
- `auto report`는 task를 자동 완료 처리하지 않는다.
- `auto report`는 다음 명령을 제안할 뿐 실행하지 않는다.

## 제품 루프 위치

```text
auto task directive
→ Codex/Claude execution
→ result intake
→ auto report
→ boardroom / next plan / validation / release gate
```

이 문서는 `auto report`가 결과 evidence를 다음 의사결정으로 넘기는 계약을 고정한다.
