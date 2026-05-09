# Five Minute Product Walkthrough Script

## 0:00 -- Problem

말할 문장:

AI는 강하지만, 대부분의 사용자는 AI를 일꾼처럼 설치하고 검증하는 법을 모릅니다. 매번 역할, 맥락, 테스트, 결과 확인을 직접 조립해야 합니다.

보여줄 화면:

- 웹 landing hero
- README quickstart

Expected output:

- Cambrian의 한 문장 메시지가 보입니다.

Recovery:

- 웹이 준비되지 않았으면 README quickstart로 시작합니다.

## 0:30 -- Product

말할 문장:

Cambrian installs AI worker packs into the AI you already use. 이미 쓰는 AI에 검증된 AI 일꾼을 설치하세요.

보여줄 명령:

```bash
cambrian pack show auth-bug-core
```

Expected output:

- Auth Bug Core pack 설명
- install command
- Python + pytest + auth/login lane fit

Recovery:

- pack이 보이지 않으면 `cambrian pack list`로 catalog를 확인합니다.

## 1:00 -- Show Auth Bug Core

말할 문장:

첫 데모는 Auth Bug Core입니다. Python + pytest + 좁은 로그인 버그 수정에 맞춘 작업반입니다.

보여줄 명령:

```bash
cambrian pack show auth-bug-core
```

Expected output:

- `bug-fix-agent`
- `regression-test-agent`
- `review-agent`
- `auth-bug-team`
- `auth-bug-template`

Recovery:

- detail 출력이 너무 길면 install command와 known limits만 짚고 넘어갑니다.

## 1:45 -- Install

말할 문장:

설치는 source code를 고치는 작업이 아닙니다. 로컬 Cambrian state에 worker pack을 설치합니다.

보여줄 명령:

```bash
cambrian install pack auth-bug-core
cambrian install doctor
```

Expected output:

- installed pack state
- doctor summary

Recovery:

- doctor가 warning을 내면 launch run의 핵심 흐름을 막는지 확인하고, 막지 않으면 그대로 설명합니다.

## 2:15 -- Activate

말할 문장:

활성화는 현재 프로젝트의 기본 작업 맥락을 Auth Bug Core로 고르는 단계입니다. template apply나 source 변경이 아닙니다.

보여줄 명령:

```bash
cambrian pack activate auth-bug-core
cambrian pack doctor auth-bug-core
```

Expected output:

- active pack: `auth-bug-core`
- next action: `cambrian pack start "로그인 에러 수정해"`

Recovery:

- active pack이 없다고 나오면 activate 명령을 다시 실행합니다.

## 2:45 -- Start Job

말할 문장:

이제 작업을 맡깁니다. Cambrian은 AI provider를 호출하지 않고, 이미 쓰는 AI에 붙여넣을 packet과 pack job artifact를 만듭니다.

보여줄 명령:

```bash
cambrian pack start "로그인 에러 수정해"
```

Expected output:

- job id
- bridge packet
- next command

Recovery:

- job id를 놓쳤으면 `cambrian pack job-next latest` 또는 dry-run transcript를 확인합니다.

## 3:30 -- Paste Canned AI Reply

말할 문장:

공개 데모는 재현성을 위해 실제 AI 호출 대신 canned AI reply fixture를 사용합니다.

보여줄 명령:

```bash
cambrian pack job-ingest <job-id> fixtures/ai_reply_patch_candidate.yaml
```

Expected output:

- `patch_candidate`
- validation-ready job state

Recovery:

- fixture 오류가 나면 `fixtures/ai_reply_patch_candidate.yaml`의 `old_text`가 `src/auth.py`에 있는지 확인합니다.

## 4:15 -- Validate

말할 문장:

검증은 source apply가 아닙니다. validated proposal로 이어지는 handoff를 확인합니다.

보여줄 명령:

```bash
cambrian pack job-validate <job-id>
```

Expected output:

- validation status
- proposal reference

Recovery:

- validation-ready가 아니면 ingest 단계가 성공했는지 다시 확인합니다.

## 4:45 -- Proof / Outcome

말할 문장:

Cambrian은 결과를 evidence로 남깁니다. 아직 실제 사용 결과가 적으면 없다고 말합니다. 숫자를 만들지 않습니다.

보여줄 명령:

```bash
cambrian pack proof auth-bug-core
```

Expected output:

- local proof card
- insufficient data 또는 local evidence summary

Recovery:

- proof가 비어 있으면 `cambrian pack outcomes auth-bug-core`나 dry-run report를 보여줍니다.

## 5:00 -- Closing

말할 문장:

이제 AI 작업반을 설치하고, 일을 맡기고, 결과를 검증할 수 있습니다. Cambrian은 새 챗봇이 아니라, 이미 쓰는 AI를 작업반처럼 쓰게 해주는 로컬 실행 엔진입니다.
