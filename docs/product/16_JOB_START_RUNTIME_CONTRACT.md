# Job Start Runtime Contract

## 목적

`cambrian job start "..."`는 설치된 AI 회사에 첫 작업을 시작시키는 공식 런타임 계약이다.

이 명령은 AI provider를 호출하지 않는다.
이 명령은 source code를 수정하지 않는다.
이 명령은 자동 patch apply를 하지 않는다.

대신 설치된 `.cambrian/` 회사 상태를 읽고, 이번 작업에 투입할 agent와 skill을 고른 뒤, 사람이 기존 AI 도구에 전달할 request packet과 Cambrian job record를 생성한다.

## 명령

```bash
cambrian job start "로그인 세션 만료 문제 확인해" --json
```

Installed pack 또는 Studio-generated agent pack을 직접 고를 때는 `--pack`을 쓴다.

```bash
cambrian job start --pack document-organizer-agent "문서 폴더를 주제별로 정리해줘" --json
```

이 경로도 AI provider를 호출하지 않고, source code를 수정하지 않는다.
차이는 `request_packet`의 active pack context와 execution contract에 선택된 pack worker가 `selected_agents`로 들어간다는 점이다.

## 필수 JSON 계약

`--json` 출력은 상위 레벨에 아래 필드를 포함해야 한다.

```json
{
  "ok": true,
  "status": "created",
  "job_id": "...",
  "job_status": "waiting_for_ai_reply",
  "harness_id": "...",
  "workforce_id": "...",
  "selected_agents": [],
  "selected_skills": [],
  "dispatch_reason": "...",
  "change_policy": "proposal_only",
  "validation_commands": [],
  "validation_criteria": [],
  "forbidden_actions": [],
  "approval_required_actions": [],
  "request_packet": ".cambrian/bridge/packets/....yaml",
  "request_packet_ref": ".cambrian/bridge/packets/....yaml",
  "job_ref": ".cambrian/packs/jobs/....yaml",
  "ai_provider_called": false,
  "source_code_modified": false,
  "next_commands": [
    "cambrian job ingest latest ai_reply_patch_candidate.yaml",
    "cambrian job validate latest"
  ]
}
```

`pack_job` 필드는 기존 pack job 호환성을 위해 유지한다.
새 제품 spine에서는 상위 필드를 우선 사용한다.

Studio-generated agent pack은 agent contract의 `validation_criteria`, `forbidden_actions`, `approval_required_actions`를 request packet의 execution contract와 이후 validation evidence에 남긴다.
사람이 기준 충족 여부를 검토한 뒤 `cambrian pack job-validate latest --criteria-status satisfied` 또는 `--criteria-status failed`로 판정을 남기면, validation evidence와 proof card가 같은 상태로 갱신된다.

## 생성 파일

`job start`는 최소 아래 파일을 생성한다.

```text
.cambrian/bridge/packets/<packet-id>.yaml
.cambrian/packs/jobs/<job-id>.yaml
.cambrian/packs/jobs/latest.yaml
```

`request_packet_ref`는 AI 실행 엔진에 넘길 요청 패킷 경로다.
`job_ref`는 Cambrian이 추적하는 로컬 작업 레코드 경로다.

## 상태 의미

`job_status = waiting_for_ai_reply`는 정상 상태다.

이 상태는 Cambrian이 작업 요청을 만들었고, 사용자가 Claude, Codex, Cursor, GPT, local model 같은 외부 실행 엔진에 request packet을 전달할 차례라는 뜻이다.

## 안전 계약

`job start` 단계에서는 아래 값이 반드시 고정된다.

```json
{
  "ai_provider_called": false,
  "source_code_modified": false
}
```

이 값이 `true`가 되려면 별도 권한 모드와 별도 실행 명령이 필요하다.
V1의 `job start`는 실행 권한 위임이 아니라 작업 패킷 생성 계약이다.

## 다음 단계

사용자는 request packet을 기존 AI 도구에 붙여넣고, AI 응답을 파일로 저장한 뒤 아래 명령을 실행한다.

```bash
cambrian job ingest latest ai_reply_patch_candidate.yaml
cambrian job validate latest
```

## 제품 내 위치

`job start`는 설치 이후 on-demand dispatch 단계다.

설치 단계:

```text
project scan
→ harness interview
→ harness engineer design/review/dry-run
→ workforce generate
→ skill generate
→ harness install --confirm
```

작업 단계:

```text
job start
→ request packet 전달
→ job ingest
→ job validate
→ job complete
→ evolve review/propose/apply
```
