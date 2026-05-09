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

`preview`는 적용 전 검토 단계다. 실제 적용은 여전히 `apply --confirm`에서만 일어난다.

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
    "auto_apply": false
  },
  "next_command": "cambrian evolve apply evolution-... --confirm --json"
}
```

## 저장 위치

Preview 결과는 아래에 저장된다.

```text
.cambrian/evolution/previews/<proposal-id>.yaml
```

이 파일은 검토용 산출물이다. 적용 이력은 아니다.

## 안전 경계

- `preview`는 source code를 수정하지 않는다.
- `preview`는 preset 원본을 수정하지 않는다.
- `preview`는 `.cambrian/harness.yaml`, `.cambrian/workforce.yaml`, `.cambrian/agents/*.yaml`, `.cambrian/skills/*.yaml`, `.cambrian/validation.yaml`을 수정하지 않는다.
- `preview`는 job을 생성하지 않는다.
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

Cambrian은 evidence 없는 진화를 적용하지 않고, preview 없는 변경도 사람이 검토하기 어렵다. V1에서는 preview를 적용 전 권장 단계로 제공하되, 최종 변경 권한은 `--confirm`에 둔다.
