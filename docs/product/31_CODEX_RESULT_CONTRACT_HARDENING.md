# Codex Result Contract Hardening

## 목적

Codex/Claude가 반환하는 step result가 애매하면 auto loop가 잘못된 다음 결정을 만들 수 있다.

그래서 `cambrian auto step ingest`는 결과 파일의 필수 필드와 타입을 먼저 검증한다.

## 필수 필드

```yaml
status: success
summary: "작업 결과 요약"
changed_files: []
tests:
  - command: "python -m pytest"
    status: passed
blockers: []
next_action: "cambrian auto report --json"
evidence:
  notes:
    - "검증 근거"
  artifacts: []
```

필수 필드:

```text
status
summary
changed_files
tests
blockers
next_action
evidence
```

## 타입 규칙

- `status`: `success`, `partial`, `failed`, `blocked`, `done`, `completed`, `needs_more_info` 중 하나
- `summary`: 비어 있지 않은 문자열
- `changed_files`: list
- `tests`: list
- `tests[].command`: 비어 있지 않은 문자열
- `tests[].status`: 비어 있지 않은 문자열
- `blockers`: list
- `next_action`: 비어 있지 않은 문자열
- `evidence`: mapping

## 실패 계약

계약이 깨진 result는 ingest하지 않는다.

```json
{
  "ok": false,
  "error": "invalid_result_contract",
  "errors": [
    "missing required field: evidence"
  ],
  "source_code_modified": false
}
```

이 경우 기존 task는 `waiting_for_result` 상태를 유지한다.

## 안전 경계

- invalid result는 task 상태를 바꾸지 않는다.
- invalid result는 execution log에 step result로 기록하지 않는다.
- source code를 수정하지 않는다.
- provider API를 호출하지 않는다.
- git commit/push를 하지 않는다.

## 제품 루프 위치

```text
Codex/Claude execution
→ result contract validation
→ result intake
→ auto report
```

이 문서는 외부 실행 결과가 Cambrian auto loop에 들어오기 위한 최소 계약을 고정한다.
