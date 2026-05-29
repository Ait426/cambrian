# Evolution Apply Audit Contract

## 목적

`cambrian evolve apply <proposal-id> --confirm`은 로컬 `.cambrian/` metadata를 실제로 바꾸는 단계다.

이 단계는 반드시 무엇을 바꿨는지, 어떤 evidence 제안에서 왔는지, 되돌리려면 어떤 백업을 봐야 하는지 기록해야 한다.

## 명령 흐름

```bash
cambrian evolve review --recent 5 --json
cambrian evolve propose --json
cambrian evolve preview <proposal-id> --json
cambrian evolve apply <proposal-id> --confirm --json
```

`apply`는 `--confirm` 없이는 실행되지 않는다.
`apply --confirm`은 같은 proposal에 대한 preview 산출물이 없거나 proposal과 맞지 않으면 실행되지 않는다.
승격 검토가 필요한 proposal은 `--confirm`이 있어도 `.cambrian/evolution/review_decisions/latest_promotion_review.yaml`가 유효해야 한다.
또한 proposal에 고정된 `promotion_review_decision_sha256`과 현재 decision 파일 digest가 같아야 한다.

## apply 출력 계약

`cambrian evolve apply <proposal-id> --confirm --json`은 최소 아래 필드를 포함한다.

```json
{
  "ok": true,
  "status": "applied",
  "proposal_id": "evolution-...",
  "changed_files": [
    ".cambrian/harness.yaml",
    ".cambrian/workforce.yaml",
    ".cambrian/skills/trace-auth-token-flow.yaml"
  ],
  "preview_ref": ".cambrian/evolution/previews/evolution-....yaml",
  "preview_digest_ref": ".cambrian/evolution/previews/evolution-....digest.yaml",
  "proposal_sha256": "sha256...",
  "preview_sha256": "sha256...",
  "applied_ref": ".cambrian/evolution/applied/evolution-....yaml",
  "history_ref": ".cambrian/evolution/history.yaml",
  "audit_ref": ".cambrian/evolution/audit/evolution-....yaml",
  "rollback_ref": ".cambrian/evolution/rollback/evolution-....yaml",
  "promotion_review_decision_ref": ".cambrian/evolution/review_decisions/latest_promotion_review.yaml",
  "promotion_review_decision_sha256": "sha256...",
  "rollback_manifest_sha256": "sha256...",
  "backup_refs": [
    ".cambrian/evolution/backups/evolution-.../.cambrian/harness.yaml"
  ]
}
```

## audit manifest

Audit manifest는 아래 위치에 저장된다.

```text
.cambrian/evolution/audit/<proposal-id>.yaml
```

필수 내용:

- proposal id
- 적용 시각
- proposal ref
- preview ref
- preview digest ref
- proposal sha256
- preview sha256
- summary
- risk / quality score
- changed files
- 파일별 before / after sha256
- 파일별 backup ref
- 파일별 backup sha256
- promotion review decision ref / sha256 / gate status
- safety 경계
- rollback ref
- rollback manifest sha256

## rollback manifest

Rollback manifest는 아래 위치에 저장된다.

```text
.cambrian/evolution/rollback/<proposal-id>.yaml
```

V1은 자동 rollback 명령을 제공하지 않는다. 대신 각 변경 파일에 대해 `backup_ref`와 수동 복원 힌트를 남긴다.
Rollback manifest도 적용 당시 사용된 `promotion_review_decision_ref`와 `promotion_review_decision_sha256`을 함께 남겨야 한다.
Rollback manifest는 적용 당시 proposal sha256과 preview sha256도 함께 남겨야 한다.
Rollback manifest는 각 `backup_ref`의 `backup_sha256`을 함께 남겨야 한다.
적용 결과와 history는 rollback manifest의 sha256을 함께 남기며, 이후 rollback 실행 시 현재 manifest digest와 비교한다.

```text
필요하면 <backup_ref> 내용을 <path>로 복원한다.
```

## backup

적용 전 metadata 백업은 아래에 저장된다.

```text
.cambrian/evolution/backups/<proposal-id>/
```

백업 대상은 실제로 변경될 수 있는 로컬 `.cambrian/` metadata 파일이다.

## 안전 경계

- source code를 수정하지 않는다.
- preset 원본을 수정하지 않는다.
- provider API를 호출하지 않는다.
- 자동 patch apply를 하지 않는다.
- preview 산출물이 없거나 proposal과 맞지 않으면 적용하지 않는다.
- preview digest lock이 없거나 현재 preview 파일 digest와 맞지 않으면 적용하지 않는다.
- evaluator `pass`를 자동 promotion으로 해석하지 않는다.
- 승격 검토 decision artifact가 없거나 안전 경계가 깨진 proposal은 적용하지 않는다.
- proposal 생성 후 승격 검토 decision artifact가 바뀌면 적용하지 않는다.
- 적용 결과, audit manifest, rollback manifest, history는 동일한 promotion review decision ref와 sha256을 남긴다.
- 적용 결과, audit manifest, rollback manifest, history는 동일한 preview digest ref, proposal sha256, preview sha256을 남긴다.
- 적용 결과와 history는 rollback manifest sha256을 남긴다.
- rollback manifest는 각 backup file의 sha256을 남긴다.
- rollback은 자동 실행하지 않고 수동 힌트와 백업만 제공한다.
- 적용 이력은 `.cambrian/evolution/history.yaml`에 남긴다.

## 제품 판단

진화 적용은 아래 조건을 만족해야 한다.

```text
evidence 기반 proposal
→ promotion review decision 확인
→ preview
→ preview 산출물 확인
→ 사용자 confirm
→ metadata apply
→ audit manifest
→ rollback hint
→ history
```

Cambrian의 진화 루프는 “자동으로 좋아지는 설정”이 아니라, evidence와 승인과 감사 기록을 가진 운영 루프다.
