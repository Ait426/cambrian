# AI Reply Ingest Contract

## 목적

`cambrian job ingest`는 Codex, Claude, Cursor, GPT, local model 같은 실행 엔진이 만든 응답을 Cambrian 작업 기록에 연결하는 계약이다.

이 단계는 source code를 수정하지 않는다.
이 단계는 patch를 적용하지 않는다.
이 단계는 AI provider를 호출하지 않는다.

대신 응답 구조를 검증하고, reply artifact와 patch intent draft를 만들고, 다음 `job validate` 명령으로 넘긴다.

## 명령

```bash
cambrian job ingest latest ai_reply_patch_candidate.yaml --json
```

## 허용 응답 종류

```text
analysis
patch_candidate
review
plan
```

`patch_candidate`는 자동 적용 후보가 아니다.
`patch_candidate`는 사람이 검토하고 Cambrian이 validate할 수 있는 구조화된 제안이다.

## Patch Candidate 계약

권장 YAML:

```yaml
response_kind: patch_candidate
summary: "Bearer token parsing fix proposal"
target_path: backend/src/middleware/authMiddleware.ts
old_text: |
  export function auth() {}
new_text: |
  export function auth() { return true; }
reason: "Authorization 헤더에서 Bearer 접두사를 제거해야 한다."
related_tests:
  - backend/tests/auth.test.ts
warnings:
  - "JWT_SECRET 설정은 별도 검토 필요"
```

아래 nested 형태도 허용한다.

```yaml
response_kind: patch_candidate
summary: "Bearer token parsing fix proposal"
patch:
  target_path: backend/src/middleware/authMiddleware.ts
  old_text: |
    export function auth() {}
  new_text: |
    export function auth() { return true; }
  reason: "Authorization 헤더에서 Bearer 접두사를 제거해야 한다."
  related_tests:
    - backend/tests/auth.test.ts
```

Cambrian은 nested `patch` 값을 top-level patch candidate 계약으로 정규화한다.

## 필수 필드

`patch_candidate`에는 아래 필드가 필요하다.

```text
summary
target_path
old_text
new_text
reason
```

필수 필드가 없으면 `job ingest`는 blocked 상태로 끝난다.

## JSON 결과 계약

성공 시:

```json
{
  "ok": true,
  "status": "validation_ready",
  "reply_kind": "patch_candidate",
  "reply_contract_status": "accepted_patch_candidate",
  "reply_file_ref": ".cambrian/bridge/replies/...",
  "request_packet_ref": ".cambrian/bridge/packets/...",
  "patch_candidate_accepted": true,
  "patch_intent_ref": ".cambrian/patch_intents/...",
  "patch_applied": false,
  "source_code_modified": false,
  "ai_provider_called": false,
  "next_commands": [
    "cambrian job validate latest"
  ]
}
```

실패 시:

```json
{
  "ok": false,
  "status": "blocked",
  "reply_contract_status": "blocked",
  "patch_candidate_accepted": false,
  "patch_applied": false,
  "source_code_modified": false,
  "ai_provider_called": false,
  "errors": [
    "new_text is required for patch_candidate"
  ]
}
```

## 생성 파일

성공한 patch candidate ingest는 최소 아래 파일을 만든다.

```text
.cambrian/bridge/replies/<reply-id>.yaml
.cambrian/bridge/reviews/<review-id>.yaml
.cambrian/bridge/handoffs/<handoff-id>.yaml
.cambrian/patch_intents/<patch-intent-id>.yaml
.cambrian/packs/jobs/latest.yaml
```

이 파일들은 적용 결과가 아니라 evidence와 handoff artifact다.

## 안전 계약

`job ingest`는 항상 아래 값을 유지한다.

```json
{
  "patch_applied": false,
  "source_code_modified": false,
  "ai_provider_called": false
}
```

source code 변경은 별도 명령과 명시 승인 없이는 발생하지 않는다.

## 다음 단계

```bash
cambrian job validate latest --json
```

`job validate`는 patch candidate가 현재 하네스, 검증 명령, evidence 규칙 기준으로 사용 가능한지 판단한다.
## Evidence Envelope V2

Every serious AI reply should now include the evidence envelope below.
Without it, `job validate` may run commands but must keep the verdict on hold.

```yaml
response_kind: review
summary: Short answer.
codebase_evidence_paths:
  - path/to/file.py
risk_boundary_check:
  checked: true
  summary: Forbidden paths and external side effects were checked.
validation_command_selection:
  commands:
    - python -m pytest tests/ -v
  reason: Why these commands prove the claim.
patch_application_state:
  patch_applied: false
  source_code_modified: false
  summary: Proposal-only; Cambrian did not auto-apply source mutations.
verdict_rationale: Why the evidence supports pass, hold, or rollback.
context_intent_resolution:
  resolved: true
  reason: Why this answer matches the current user intent.
project_discussion_role_check:
  checked: true
  reason: Which role owns this judgment.
```

`patch_application_state` records the reply's claim about the target work.
The top-level Cambrian safety flags still describe Cambrian's own behavior:

```json
{
  "patch_applied": false,
  "source_code_modified": false,
  "ai_provider_called": false
}
```

Cambrian must not turn a missing evidence envelope into a pass verdict.
