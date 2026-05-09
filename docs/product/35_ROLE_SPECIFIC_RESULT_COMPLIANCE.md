# 역할별 결과 Compliance Gate

## 목적

`cambrian auto step ingest`는 이제 공통 결과 계약뿐 아니라 역할별 산출물 계약도 확인한다.

이 gate는 Codex 또는 Claude가 `success`, `partial`, `done` 결과를 주장할 때, 담당 역할에 맞는 산출물을 실제로 남겼는지 검사한다.

## 공통 계약

모든 결과 파일은 기존 필드를 유지해야 한다.

- `status`
- `summary`
- `changed_files`
- `tests`
- `blockers`
- `next_action`
- `evidence`

## 역할별 계약

역할별 task는 `role_outputs`를 포함해야 한다.

예시:

```yaml
status: success
summary: "PM 결과 제출"
changed_files: []
tests: []
blockers: []
next_action: "cambrian auto report --json"
evidence:
  notes: []
  artifacts: []
role_outputs:
  scope: "이번 작업 범위"
  acceptance_criteria:
    - "완료 기준"
  test_plan:
    - "검증 명령"
```

## 역할별 필수 키

`pm-agent`:

- `scope`
- `acceptance_criteria`
- `test_plan`

`cto-agent`:

- `architecture_notes`
- `risks`
- `minimal_change_plan`

`coo-agent`:

- `execution_order`
- `blocker_handling`
- `evidence_map`

`engineering-agent`:

- `implementation_plan`
- `changed_files`
- `rollback_hint`

`qa-agent`:

- `test_matrix`
- `failure_classification`
- `release_risk`

`release-manager-agent`:

- `verdict`
- `artifact_checklist`
- `post_release_backlog`

## Blocking Rule

아래 status는 역할별 산출물 검사를 통과해야 한다.

- `success`
- `partial`
- `done`

아래 status는 실패 수집 자체가 목적이므로 `role_outputs` 없이도 ingest할 수 있다.

- `failed`
- `blocked`
- `needs_more_info`

## Error

역할별 산출물이 부족하면 `auto step ingest`는 다음 오류를 반환한다.

```json
{
  "ok": false,
  "error": "invalid_result_contract",
  "errors": ["role_outputs.scope is required for pm-agent"]
}
```

이 gate는 source code를 수정하지 않는다. 결과 파일의 품질만 검사한다.
