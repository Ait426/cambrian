# Evolution Rollback Contract

## 목적

`cambrian evolve rollback <proposal-id> --confirm`은 이전 `evolve apply`에서 남긴 backup을 사용해 로컬 `.cambrian/` metadata를 복원한다.

이 명령은 source code를 복구하지 않는다. Cambrian 진화 적용 대상인 하네스, 인력, 스킬, 검증 metadata만 복원한다.

## 명령 흐름

```bash
cambrian evolve apply <proposal-id> --confirm --json
cambrian evolve rollback <proposal-id> --confirm --json
cambrian evolve rollback latest --confirm --json
```

`latest` means the most recent applied evolution entry in `.cambrian/evolution/history.yaml`.

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
  "audit_ref": ".cambrian/evolution/audit/evolution-....yaml",
  "preview_ref": ".cambrian/evolution/previews/evolution-....yaml",
  "preview_digest_ref": ".cambrian/evolution/previews/evolution-....digest.yaml",
  "proposal_sha256": "sha256...",
  "preview_sha256": "sha256...",
  "promotion_review_decision_ref": ".cambrian/evolution/review_decisions/latest_promotion_review.yaml",
  "promotion_review_decision_sha256": "sha256...",
  "rollback_manifest_sha256": "sha256...",
  "next_command": "cambrian evolve review --recent 5 --json",
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

Apply output and rollback manifest include an executable rollback command:

```yaml
rollback_command: cambrian evolve rollback <proposal-id> --confirm --json
```

각 파일 항목은 최소 아래 정보를 가져야 한다.

```yaml
path: .cambrian/harness.yaml
backup_ref: .cambrian/evolution/backups/evolution-.../.cambrian/harness.yaml
backup_sha256: sha256...
```

Rollback manifest는 적용 당시 audit ref, preview ref, preview digest ref, proposal sha256, preview sha256, promotion review decision snapshot, 그리고 apply 결과에 저장된 `rollback_manifest_sha256`과 일치해야 한다.
현재 rollback manifest digest가 apply 당시 digest와 다르면 복원하지 않는다.
각 backup 파일은 manifest에 저장된 `backup_sha256`과 일치해야 복원된다. 불일치하면 해당 파일은 복원하지 않고 rollback 실행 기록의 warnings에 남긴다.

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
- rollback manifest digest가 apply 당시 기록과 다르면 복원하지 않는다.
- backup 파일 sha256이 rollback manifest와 다르면 해당 파일은 복원하지 않는다.
- rollback 실행 기록과 history는 audit ref, preview ref, preview digest ref, proposal sha256, preview sha256, promotion review decision ref/sha256, rollback manifest sha256을 남긴다.

## 제품 판단

진화 적용은 되돌릴 수 있어야 한다. 단, V1 rollback은 제품 source rollback이 아니라 Cambrian 운영 metadata rollback이다.

```text
evolve apply
→ audit manifest
→ backup refs
→ rollback manifest digest check
→ backup sha256 check
→ evolve rollback --confirm
→ metadata restored
→ history updated
```
