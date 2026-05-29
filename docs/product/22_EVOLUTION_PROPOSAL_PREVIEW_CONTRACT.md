# Evolution Proposal Preview Contract

## 목적

`cambrian evolve propose`는 하네스, 인력, 스킬을 실제로 바꾸기 전에 사람이 검토할 수 있는 진화 제안을 만든다.

`cambrian evolve preview <proposal-id>`는 그 제안이 어떤 로컬 `.cambrian/` metadata 파일을 바꿀지 미리 보여준다. 이 명령은 source code, preset 원본, 설치된 하네스 metadata를 수정하지 않는다.

## 명령 흐름

```bash
cambrian evolve review --recent 5 --json
cambrian evolve propose --json
cambrian evolve preview <proposal-id> --json
cambrian evolve apply <proposal-id> --confirm --json
```

`preview`는 적용 전 필수 검토 단계다. 실제 적용은 여전히 `apply --confirm`에서만 일어나며, preview 산출물이 없거나 proposal과 맞지 않으면 apply는 차단된다.

## propose 출력 계약

`cambrian evolve propose --json`은 최소 아래 필드를 포함한다.

```json
{
  "ok": true,
  "proposal_id": "evolution-...",
  "quality_score": 80,
  "risk_score": 25,
  "risk": "low",
  "evidence_refs": [
    ".cambrian/evidence/outcomes.yaml"
  ],
  "changed_files_preview": [
    ".cambrian/harness.yaml",
    ".cambrian/skills/trace-auth-token-flow.yaml"
  ],
  "change_preview": {
    ".cambrian/harness.yaml": [
      "important_paths 추가",
      "success_criteria 강화"
    ]
  },
  "next_command": "cambrian evolve preview evolution-... --json"
}
```

## preview 출력 계약

`cambrian evolve preview <proposal-id> --json`은 최소 아래 필드를 포함한다.

```json
{
  "ok": true,
  "status": "previewed",
  "proposal_id": "evolution-...",
  "preview_ref": ".cambrian/evolution/previews/evolution-....yaml",
  "preview_digest_ref": ".cambrian/evolution/previews/evolution-....digest.yaml",
  "proposal_sha256": "sha256...",
  "preview_sha256": "sha256...",
  "quality_score": 80,
  "risk_score": 25,
  "changed_files_preview": [
    ".cambrian/harness.yaml",
    ".cambrian/agents/auth-flow-investigator.yaml",
    ".cambrian/skills/trace-auth-token-flow.yaml"
  ],
  "change_preview": {
    ".cambrian/skills/trace-auth-token-flow.yaml": [
      "procedure 보강",
      "known_failure_patterns 보강"
    ]
  },
  "safety": {
    "requires_confirm": true,
    "source_code_modified": false,
    "preset_modified": false,
    "auto_apply": false,
    "auto_promote": false,
    "promotion_review_required": true,
    "promotion_review_gate_status": "review_required",
    "maturity_gate_status": "review_required",
    "evolution_apply_allowed": true
  },
  "next_command": "cambrian evolve apply evolution-... --confirm --json"
}
```

## Evolution Maturity Gate

Every proposal and preview carries an evolution maturity gate.

```text
insufficient_data
→ fewer than 3 jobs
→ proposal can be recorded, but apply is blocked

signal_candidate
→ 3 to 9 jobs
→ signals can be inspected, but metadata evolution is blocked

review_required
→ 10 to 19 jobs
→ apply can proceed only after preview, digest checks, human review, and --confirm

trusted_pattern
→ 20 or more jobs
→ stronger evidence, but auto_apply and auto_promote remain false
```

If `safety.evolution_apply_allowed` is false, `apply --confirm` must return `blocked` even when preview and digest checks pass.

## Promotion Review Gate

`evolve review`가 `pass` evaluator verdict를 발견하면 `evolve propose`는 아래 decision ref를 proposal evidence에 포함해야 한다.

```text
.cambrian/evolution/review_decisions/latest_promotion_review.yaml
```

Proposal evidence는 같은 decision artifact의 `promotion_review_decision_sha256`도 함께 고정해야 한다.

`preview`는 승격 검토가 필요한 proposal에서 이 decision artifact를 확인한다.
파일이 없거나, decision이 `needs_human_review`가 아니거나, `auto_promote`가 true면 `preview`는 `blocked`가 된다.
파일 내용이 proposal 생성 이후 바뀌어 sha256 digest가 달라져도 `preview`는 `blocked`가 된다.
이 검사는 적용이 아니라 검토 단계에서 잘못된 승격 경로를 조기에 드러내기 위한 것이다.

## 저장 위치

Preview 결과는 아래에 저장된다.

```text
.cambrian/evolution/previews/<proposal-id>.yaml
```

이 파일은 검토용 산출물이다. 적용 이력은 아니다.
Preview 결과는 preview 생성 시점의 proposal sha256을 함께 저장한다.
Preview 파일 자체의 digest lock은 아래에 저장된다.

```text
.cambrian/evolution/previews/<proposal-id>.digest.yaml
```

이 lock은 `lock_kind: evolution_preview_digest_lock`, preview ref, proposal sha256, preview sha256을 함께 담는다.

## 안전 경계

- `preview`는 source code를 수정하지 않는다.
- `preview`는 preset 원본을 수정하지 않는다.
- `preview`는 `.cambrian/harness.yaml`, `.cambrian/workforce.yaml`, `.cambrian/agents/*.yaml`, `.cambrian/skills/*.yaml`, `.cambrian/validation.yaml`을 수정하지 않는다.
- `preview`는 job을 생성하지 않는다.
- `preview`는 승격 검토 decision artifact 없이 promotion 성격의 proposal을 통과시키지 않는다.
- `apply --confirm`은 `maturity_gate`가 apply를 허용하지 않으면 실행되지 않는다.
- `apply --confirm`은 같은 proposal의 `.cambrian/evolution/previews/<proposal-id>.yaml`가 없으면 실행되지 않는다.
- `apply --confirm`은 `.cambrian/evolution/previews/<proposal-id>.digest.yaml`가 없거나 현재 preview 파일 digest와 맞지 않으면 실행되지 않는다.
- `apply --confirm`은 preview digest lock의 `lock_kind`, preview ref, proposal sha256이 맞지 않으면 실행되지 않는다.
- `apply --confirm`은 preview에 고정된 `proposal_sha256`과 현재 proposal 파일 digest가 다르면 실행되지 않는다.
- `apply --confirm`은 preview의 proposal ref, 변경 미리보기, safety 경계가 proposal과 맞지 않으면 실행되지 않는다.
- 실제 metadata 변경은 `cambrian evolve apply <proposal-id> --confirm --json`에서만 가능하다.

## 제품 판단

진화 루프의 순서는 아래로 고정한다.

```text
job evidence
→ evolve review
→ evolve propose
→ evolve preview
→ user approval
→ evolve apply
```

Cambrian은 evidence 없는 진화를 적용하지 않고, preview 없는 변경도 적용하지 않는다. V1에서는 preview를 적용 전 필수 산출물로 고정하고, 최종 변경 권한은 `--confirm`에 둔다.
