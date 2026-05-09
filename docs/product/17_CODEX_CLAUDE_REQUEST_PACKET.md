# Codex / Claude Request Packet Contract

## 목적

Cambrian request packet은 Codex, Claude, Cursor, GPT, local model 같은 실행 엔진에 넘기는 작업지시서다.

이 packet은 AI 회사의 현재 상태를 담는다.
실행 엔진은 이 packet만 보고 어떤 역할로 일해야 하는지, 어떤 agent와 skill이 투입됐는지, 어떤 검증 명령을 고려해야 하는지, 무엇을 하면 안 되는지 이해해야 한다.

## 생성 시점

```bash
cambrian job start "로그인 세션 만료 문제 확인해" --json
```

`job start`는 request packet을 생성하고 `request_packet_ref`로 경로를 돌려준다.

```text
.cambrian/bridge/packets/<packet-id>.yaml
```

## 필수 상위 필드

request packet은 최소 아래 필드를 포함한다.

```yaml
packet_id: packet_...
request: "로그인 세션 만료 문제 확인해"
harness_id: custom-...
harness_summary: {}
agent_summary: {}
policy_summary: {}
memory_summary: {}
active_pack_context: {}
response_contract: {}
execution_contract: {}
codex_claude_instruction: |
  너는 Cambrian이 이 프로젝트 안에 설치한 AI 회사의 실행 엔진이다.
```

## Execution Contract

`execution_contract`는 다른 AI가 바로 읽는 핵심 계약이다.

필수 의미:

```yaml
execution_contract:
  contract_version: "1.0"
  execution_engines:
    - Codex
    - Claude
  role: "Cambrian 프로젝트 AI 회사의 실행 엔진"
  task: "사용자 요청"
  request_intent: bug_fix
  harness_id: custom-...
  workforce_id: workforce-...
  selected_agents:
    - auth-flow-investigator
  selected_skills:
    - trace-auth-token-flow
  change_policy: proposal_only
  validation_commands:
    - npm test
  must_do:
    - response_contract에 맞는 YAML 또는 JSON으로 답한다.
  must_not_do:
    - 프로젝트 파일을 직접 수정했다고 주장하지 않는다.
    - 패치를 적용했다고 말하지 않는다.
    - 검증하지 않은 성공을 성공처럼 말하지 않는다.
  handoff_back:
    - cambrian job ingest latest ai_reply_patch_candidate.yaml
    - cambrian job validate latest
```

## Codex / Claude Instruction

`codex_claude_instruction`은 packet을 사람이 복사해 Codex나 Claude에 붙여넣을 때 바로 보이는 짧은 작업지시서다.

필수 내용:

- Cambrian AI 회사의 실행 엔진 역할
- 사용자 작업 요청
- 투입 agent
- 투입 skill
- 변경 정책
- 검증 명령 후보
- source code 직접 수정 주장 금지
- YAML 또는 JSON 응답 요구

## 응답 계약

AI는 `response_contract`에 맞는 YAML 또는 JSON을 반환해야 한다.

허용 `response_kind`:

```text
analysis
patch_candidate
review
plan
```

`patch_candidate`는 자동 적용이 아니다.
Cambrian은 응답을 ingest하고 validate할 뿐, source code를 자동 수정하지 않는다.

## 안전 경계

Request packet은 아래를 허용하지 않는다.

- provider API 자동 호출
- source code 자동 수정
- secret 출력
- 검증 없는 성공 주장
- packet 밖의 사실 확정
- 자동 git commit

## 다음 명령

AI 응답을 `ai_reply_patch_candidate.yaml`로 저장한 뒤:

```bash
cambrian job ingest latest ai_reply_patch_candidate.yaml
cambrian job validate latest
```
