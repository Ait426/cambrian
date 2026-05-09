# Evolution Rollback Contract

## 목적

`cambrian evolve rollback <proposal-id> --confirm`은 이전 `evolve apply`에서 남긴 backup을 사용해 로컬 `.cambrian/` metadata를 복원한다.

이 명령은 source code를 복구하지 않는다. Cambrian 진화 적용 대상인 하네스, 인력, 스킬, 검증 metadata만 복원한다.

## 명령 흐름

```bash
cambrian evolve apply <proposal-id> --confirm --json
cambrian evolve rollback <proposal-id> --confirm --json
```

`rollback`은 `--confirm` 없이는 실행되지 않는다.

## rollback 출력 계약

```json
{
  "ok": true,
  "status": "rolled_back",
  "proposal_id": "evolution-...",
  "rollback_ref": ".cambrian/evolution/rollback/evolution-....yaml",
  "rollback_applied_ref": ".cambrian/evolution/rollback/applied/evolution-....yaml",
  "history_ref": ".cambrian/evolution/history.yaml",
  "restored_files": [
    ".cambrian/harness.yaml",
    ".cambrian/workforce.yaml",
    ".cambrian/skills/trace-auth-token-flow.yaml"
  ]
}
```

## 입력 계약

Rollback은 아래 manifest를 읽는다.

```text
.cambrian/evolution/rollback/<proposal-id>.yaml
```

각 파일 항목은 최소 아래 정보를 가져야 한다.

```yaml
path: .cambrian/harness.yaml
backup_ref: .cambrian/evolution/backups/evolution-.../.cambrian/harness.yaml
```

## 저장 위치

Rollback 실행 기록은 아래 위치에 저장된다.

```text
.cambrian/evolution/rollback/applied/<proposal-id>.yaml
```

전체 이력은 아래에 누적된다.

```text
.cambrian/evolution/history.yaml
```

## 안전 경계

- `--confirm` 없이는 복원하지 않는다.
- `.cambrian/` 밖의 파일은 복원하지 않는다.
- `.cambrian/evolution/` 내부 proposal/audit/backup/rollback 기록 파일은 복원 대상이 아니다.
- source code를 수정하지 않는다.
- preset 원본을 수정하지 않는다.
- provider API를 호출하지 않는다.
- 자동 patch apply를 하지 않는다.

## 제품 판단

진화 적용은 되돌릴 수 있어야 한다. 단, V1 rollback은 제품 source rollback이 아니라 Cambrian 운영 metadata rollback이다.

```text
evolve apply
→ audit manifest
→ backup refs
→ evolve rollback --confirm
→ metadata restored
→ history updated
```
