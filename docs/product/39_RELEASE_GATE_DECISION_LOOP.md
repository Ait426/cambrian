# Release Gate Decision Loop

## 목적

`cambrian auto release-gate`가 만든 verdict를 다음 auto loop 판단으로 연결한다.

이전 단계는 release gate package를 만들었다. 이번 계약은 그 package를 `auto report`, `auto boardroom`, `auto plan`이 읽고 다음 행동을 고르게 만든다.

## Verdict Handoff

release gate verdict는 다음 handoff 상태로 변환된다.

```text
GO -> release_gate_go
CONDITIONAL GO -> release_gate_conditional_go
NO-GO -> release_gate_no_go
```

## Next Command

```text
release_gate_go:
  cambrian auto next --goal "Next product iteration" --json

release_gate_conditional_go:
  cambrian auto boardroom --json

release_gate_no_go:
  cambrian auto boardroom --json
```

GO는 자동으로 다음 iteration을 열지 않는다. 사용자가 새 목표를 명시해야 한다.

## Plan Kind

`cambrian auto plan`은 release gate handoff에 따라 다음 plan kind를 만든다.

```text
release_gate_go -> next_iteration
release_gate_conditional_go -> conditional_release_review
release_gate_no_go -> release_gate_recovery
```

## Status / Run Consistency

`release_gate_go` 이후에는 `auto report`와 `auto status`가 모두 `cambrian auto next --goal "..." --json`을 다음 명령으로 보여줘야 한다.

`plan_kind: next_iteration`은 실행 plan이 아니라 반복 전환 plan이다. 따라서 `cambrian auto run`은 이 plan에서 새 task directive를 만들지 않고 차단한다. 다음 반복은 반드시 `cambrian auto next --goal "명시적 다음 목표" --json`으로만 시작한다.

## Safety

이 루프는 source code를 수정하지 않는다.

금지:

```text
자동 release
자동 git tag
자동 deploy
provider API 호출
secret 사용
```

release gate verdict는 `.cambrian/auto/release_gate/`와 `.cambrian/auto/report.yaml`의 local evidence를 다음 boardroom/plan 판단으로 넘기는 metadata다.
