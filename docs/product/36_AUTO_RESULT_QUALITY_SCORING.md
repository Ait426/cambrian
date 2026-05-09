# Auto 결과 품질 점수

## 목적

`cambrian auto step ingest`는 결과 파일을 구조적으로 통과시키는 데서 끝나지 않는다.

이제 각 결과에는 `result_quality`가 기록된다. 이 점수는 Codex 또는 Claude 결과가 다음 boardroom/plan으로 넘길 만큼 쓸만한지 판단하는 신호다.

## 기록 위치

품질 점수는 다음 위치에 저장된다.

- `.cambrian/auto/tasks/*.yaml`
- `.cambrian/auto/results/*.yaml`
- `.cambrian/auto/execution_log.yaml`
- `cambrian auto report --json`

## 점수 기준

V1 점수는 100점 만점이다.

- 역할별 compliance 통과
- `role_outputs` 필수 키 충족
- evidence notes 또는 artifacts 존재
- tests command/status 존재
- summary 존재
- next_action 존재
- blockers 없음

품질 threshold는 80점이다.

품질 상태:

```text
strong: 90점 이상
usable: 80점 이상
weak: 50점 이상
poor: 50점 미만
```

## Handoff

`validated` 결과라도 품질 점수가 threshold보다 낮으면 바로 release/next plan으로 가지 않는다.

`auto report`는 `step_results.quality_average`, `step_results.quality_threshold`, `step_results.low_quality`를 함께 반환한다.

대신 handoff는 다음 상태가 된다.

```text
needs_result_quality_review
```

이 경우 다음 boardroom은 낮은 품질의 결과를 검토하고, plan은 `quality_review` 단계로 전환된다.

## Safety

품질 점수는 metadata와 evidence만 평가한다.

이 기능은 source code를 수정하지 않고, provider API를 호출하지 않으며, 결과를 fake PASS로 바꾸지 않는다.
