# Auto Boardroom Report Review

## 목적

`cambrian auto boardroom`은 고정된 회의 문구를 반복하면 안 된다.

Boardroom은 최근 `auto report`와 `execution_log.yaml`의 step result evidence를 읽고, 다음 결정을 위한 agenda와 role decision을 만들어야 한다.

## 입력

Boardroom은 실행 시점에 아래 정보를 요약한다.

```text
.cambrian/auto/report.yaml
.cambrian/auto/tasks/*.yaml
.cambrian/auto/execution_log.yaml
```

`report.yaml`이 없더라도 boardroom은 현재 task 상태와 execution log를 직접 요약해 report를 갱신한다.

## Boardroom Summary

Boardroom meeting에는 아래 필드가 포함된다.

```yaml
source_auto_report: .cambrian/auto/report.yaml
auto_report_summary:
  handoff_status: needs_boardroom_review
  waiting_for_result: 0
  validated_results: 0
  blocked_results: 1
  open_blockers:
    - task_id: auto-plan-...-step-001
      blockers:
        - validation failed
```

## Agenda 규칙

- `needs_boardroom_review`: blocked auto step 결과를 검토하고 recovery plan을 결정한다.
- `ready_for_release_or_next_plan`: validated evidence를 보고 다음 plan 또는 release gate를 결정한다.
- `waiting_for_external_result`: 새 plan을 만들지 말고 result intake를 기다린다.
- `needs_validation`: 검증 evidence 보강을 다음 판단으로 둔다.
- 기본 상태: 제품 목표의 다음 단계를 결정한다.

## Decision 규칙

Blocked result가 있으면:

- CEO는 forward planning을 멈추고 blocker review를 우선한다.
- CTO는 대규모 리팩토링 대신 원인 분류를 요구한다.
- PM은 blocker와 검증 기준을 다음 plan에 넣는다.
- QA는 blocker를 release-blocking으로 유지한다.

Validated result가 있으면:

- CEO는 다음 plan 또는 release gate로 진행한다.
- PM은 validated evidence를 다음 bounded step으로 변환한다.
- Release Manager는 release gate 가능 여부를 확인한다.

Waiting result가 있으면:

- COO는 새 plan 생성을 막는다.
- PM은 Codex/Claude result file 수집을 먼저 요구한다.

## 안전 경계

- boardroom은 source code를 수정하지 않는다.
- boardroom은 provider API를 호출하지 않는다.
- boardroom은 blocked 결과를 자동으로 해결하지 않는다.
- boardroom은 다음 계획 생성을 위한 decision evidence만 기록한다.

## 제품 루프 위치

```text
auto report
→ boardroom report review
→ boardroom decisions
→ auto plan
→ auto run
```

이 문서는 result evidence가 boardroom 의사결정으로 들어가는 계약을 고정한다.
