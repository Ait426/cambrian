# Auto Plan From Handoff

## Stale Boardroom Guard

`auto plan` blocks stale boardroom summaries. If the active auto report changed after the latest boardroom decision, run this sequence again before planning:

```bash
cambrian auto report --json
cambrian auto boardroom --json
cambrian auto plan --json
```

This prevents a plan from using old boardroom evidence after task, result, quality, or release gate state changed.

## 목적

`cambrian auto plan`은 항상 같은 기본 step을 만들면 안 된다.

Boardroom이 `auto_report_summary`를 만들면, plan은 그 handoff 상태를 읽고 다음 Codex/Claude 작업지시서의 목적을 바꿔야 한다.

## 입력

```text
.cambrian/auto/boardroom/boardroom-*.yaml
```

최신 boardroom 파일의 `auto_report_summary.handoff_status`가 plan 종류를 결정한다.

## Plan Kind

```text
default
recovery
release_gate
next_product_step
validated_next
quality_review
result_intake
validation
```

## 분기 규칙

### needs_boardroom_review

`plan_kind: recovery`

Blocked auto result를 회복하기 위한 step을 만든다.

필수 성격:

- blocker 재현
- recovery scope 제한
- validation evidence 정의
- broad refactor 금지

### ready_for_release_or_next_plan

`quality_route: release_gate`이면 `plan_kind: release_gate`

`quality_route: next_product_step`이면 `plan_kind: next_product_step`

legacy result처럼 quality route가 없으면 `plan_kind: validated_next`

Validated evidence를 다음 plan 또는 release gate 판단으로 넘긴다.

필수 성격:

- validated result 참조
- release gate readiness 확인
- 다음 bounded product step 작성

### needs_result_quality_review

`plan_kind: quality_review`

Validated result라도 `result_quality`가 threshold보다 낮으면 release gate나 다음 product step으로 바로 넘기지 않는다.

필수 성격:

- quality weakness 분류
- 부족한 role output/evidence 명시
- 다음 result request 강화

### waiting_for_external_result

`plan_kind: result_intake`

새 구현 계획을 만들지 않고 Codex/Claude result file 수집을 우선한다.

### needs_validation

`plan_kind: validation`

결과는 들어왔지만 검증 evidence가 부족하므로 QA 중심 validation step을 만든다.

### 그 외

`plan_kind: default`

기본 boardroom plan step을 생성한다.

## 안전 경계

- `auto plan`은 source code를 수정하지 않는다.
- `auto plan`은 provider API를 호출하지 않는다.
- `auto plan`은 result를 자동 성공 처리하지 않는다.
- `auto plan`은 다음 Codex/Claude directive 후보만 만든다.

## 제품 루프 위치

```text
auto report
→ boardroom report review
→ auto plan from handoff
→ auto run
→ Codex/Claude directive
```

이 문서는 handoff evidence가 다음 plan step으로 변환되는 계약을 고정한다.
