# 역할별 Auto 지시서

## 목적

`cambrian auto run`은 하나의 일반 작업지를 만들지 않고, 역할별 Codex 또는 Claude 작업지시서를 만든다.

auto loop가 실제 제품 완성력으로 이어지려면 AI 회사의 각 역할이 서로 다른 일을 받아야 한다.

- `pm-agent`는 작업 범위와 완료 기준을 좁힌다.
- `cto-agent`는 아키텍처와 기술 리스크를 검토한다.
- `coo-agent`는 실행 순서와 blocker 처리를 정리한다.
- `engineering-agent`는 구현 작업을 준비한다.
- `qa-agent`는 검증과 실패 분류를 정의한다.
- `release-manager-agent`는 release gate와 산출물을 점검한다.

## 계약

생성되는 task YAML은 다음 항목을 포함한다.

- `directive_type: role_specific_auto_task`
- `role_profile`
- `result_contract`
- `expected_result`

생성되는 Markdown 지시서는 다음 항목을 포함한다.

- 역할 임무
- 역할별 초점
- 역할별 작업 지시
- 기대 산출물
- 금지 사항
- 결과 계약

## 결과 계약

`result_contract`는 다음 필드를 요구한다.

- `status`
- `summary`
- `changed_files`
- `tests`
- `blockers`
- `next_action`
- `evidence`

허용 상태:

- `success`
- `partial`
- `failed`
- `blocked`
- `done`
- `needs_more_info`

## 안전성

Auto run은 여전히 source code를 직접 수정하지 않는다.

Auto run은 작업지시서를 쓰고, 아래 명령으로 Codex 또는 Claude 결과가 들어오기를 기다린다.

```bash
cambrian auto step ingest <task-ref> --result <result-file> --json
```

역할별 지시서는 외부 작업 요청의 품질만 높인다. 이 문서 자체가 새 권한을 부여하지는 않는다.
