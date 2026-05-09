# Quality-Aware Auto Plan Selection

## 목적

`cambrian auto step ingest`가 결과 품질을 계산한 뒤, Cambrian은 그 결과를 같은 방식으로 다음 계획에 넘기지 않는다.

V1의 목표는 품질 점수에 따라 다음 auto plan을 다르게 선택하는 것이다.

## 입력

입력은 `auto report`가 만든 `decision_handoff`와 `step_results.latest.result_quality`다.

핵심 필드:

```text
result_quality.score
result_quality.status
decision_handoff.quality_route
```

## 품질 상태

품질 상태는 다음처럼 해석한다.

```text
strong: 90점 이상
usable: 80점 이상
weak: 50점 이상
poor: 50점 미만
```

80점 미만의 validated 결과는 release나 다음 product step으로 바로 가지 않고 `quality_review`로 돌아간다.

## quality_route

Cambrian은 validated 결과에 대해 다음 `quality_route`를 만든다.

```text
release_gate
next_product_step
quality_review
validated_next
```

라우팅 규칙:

```text
strong -> release_gate
usable -> next_product_step
weak / poor -> quality_review
legacy result without quality -> validated_next
```

## Plan Selection

`cambrian auto plan`은 `quality_route`에 따라 `plan_kind`를 선택한다.

```text
release_gate -> release-manager-agent가 release gate 검토를 시작
next_product_step -> pm-agent가 다음 bounded product step을 작성
quality_review -> qa-agent가 결과 품질 약점을 먼저 분류
validated_next -> 예전 validated handoff 호환 경로
```

## 안전 경계

이 기능은 source code를 수정하지 않는다.

품질 점수와 route는 `.cambrian/auto/` evidence를 다음 boardroom/plan 판단으로 넘기는 metadata다. provider API 호출, 자동 patch apply, 자동 release는 하지 않는다.
