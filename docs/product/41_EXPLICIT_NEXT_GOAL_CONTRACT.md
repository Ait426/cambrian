# Explicit Next Goal Contract

## Purpose

`cambrian auto next` starts a fresh AI-company iteration only when the user provides an explicit next product goal.

The command must not accept placeholder goals such as `Next product iteration`. A `release_gate_go` verdict proves that the previous loop can be closed, not that Cambrian already knows what the next product loop should build.

## Contract

Allowed handoff states stay narrow:

- `auto_done`
- `release_gate_go`

The goal must also be specific enough to become the next `PRODUCT_CHARTER`. Generic labels are blocked:

- `Next product iteration`
- `next iteration`
- `ship next iteration`
- `start the next release iteration`
- `명시적 다음 제품 목표`
- `다음 목표`
- `다음 단계`

If the goal is blocked, Cambrian returns:

```json
{
  "ok": false,
  "status": "blocked",
  "errors": ["explicit next product goal is required"],
  "next_command": "cambrian auto next --goal \"명시적 다음 제품 목표\" --json"
}
```

The placeholder next command is only a shape hint. The user must replace the goal with a concrete product objective.

## Good Examples

```bash
cambrian auto next --goal "ONMI-STAY 예약 취소 플로우 검증 강화" --json
cambrian auto next --goal "auto loop stale boardroom guard 보강" --json
```

## Why This Exists

Without this contract, Cambrian can archive a valid `release_gate_go` loop and accidentally open a new loop named `Next product iteration`. That creates clean-looking state but weak product direction.

The next iteration must begin with a human-chosen product objective. Boardroom, plan, run, release gate, and evidence generation then proceed from that explicit goal.

## Safety

- no source code is modified
- no provider API is called
- no auto dispatch happens during `auto next`
- stale release gate evidence is archived, not reused
- placeholder goals are blocked before a new active loop is created
