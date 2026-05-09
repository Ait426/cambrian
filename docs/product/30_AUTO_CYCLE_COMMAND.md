# Auto Cycle Command

## 목적

`cambrian auto cycle`은 안전한 1-cycle 오케스트레이션 명령이다.

사람이 매번 네 명령을 직접 실행하지 않아도 아래 흐름을 한 번 묶어서 실행한다.

```text
auto report
→ auto boardroom
→ auto plan
→ auto run
```

## 명령

```bash
cambrian auto cycle --max-steps 1 --json
```

기본값은 `--max-steps 1`이다.

## 출력 계약

```json
{
  "ok": true,
  "cycle_id": "auto-cycle-...",
  "plan_kind": "recovery",
  "handoff_status": "needs_boardroom_review",
  "executed_steps": 1,
  "waiting_for_result": 1,
  "task_refs": [
    ".cambrian/auto/tasks/auto-plan-...-step-001.yaml"
  ],
  "source_code_modified": false,
  "provider_api_called": false,
  "next_command": "cambrian auto step ingest ..."
}
```

## 생성 파일

```text
.cambrian/auto/report.yaml
.cambrian/auto/boardroom/boardroom-*.yaml
.cambrian/auto/decisions/boardroom-*.yaml
.cambrian/auto/plan.yaml
.cambrian/auto/tasks/*.yaml
.cambrian/auto/tasks/*.md
.cambrian/auto/cycles/auto-cycle-*.yaml
```

## 안전 경계

- `auto cycle`은 source code를 수정하지 않는다.
- `auto cycle`은 provider API를 호출하지 않는다.
- `auto cycle`은 git commit/push를 하지 않는다.
- `auto cycle`은 deploy, payment, secret 작업을 하지 않는다.
- `auto cycle`은 Codex/Claude task directive 생성까지만 수행한다.

## 실패 처리

중간 단계가 실패하면 `failed_step`을 반환한다.

```json
{
  "ok": false,
  "failed_step": "boardroom",
  "source_code_modified": false
}
```

## 제품 루프 위치

```text
result intake
→ auto cycle
→ task directive
→ Codex/Claude execution
→ result intake
```

이 명령은 Cambrian AI company runtime의 첫 bounded automation loop다.
