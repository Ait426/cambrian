# Cambrian Commands

Cambrian?멸? ?꾩쟾?섍쾶 怨꾩냽?섏? 紐삵븷 ???곷떒?쒕? 蹂댁뿬二쇨퀬, `Problem / Why / Try` ?뺤떇?쇰줈 ?ㅼ쓬 紐낅졊??안내?⑸땲??.

이 문서는 현재 사용자 중심 CLI와 고급 내부 CLI를 함께 정리합니다.

## 사용자 중심 명령

### `cambrian init`

프로젝트 하네스를 초기화합니다.

자주 쓰는 예:

```bash
cambrian init --wizard
cambrian init --wizard --answers-file answers.yaml
cambrian init --non-interactive --name demo --type python --test-cmd "pytest -q"
```

만드는 것:

- `.cambrian/project.yaml`
- `.cambrian/rules.yaml`
- `.cambrian/skills.yaml`
- `.cambrian/profile.yaml`
- `.cambrian/init_report.yaml`

실제 source 수정: 아니오
자동 adoption: 아니오

### `cambrian run`

프로젝트 문맥 안에서 자연어 요청을 준비하거나 실행합니다.

자주 쓰는 예:

```bash
cambrian run "로그인 에러 수정해"
cambrian run "로그인 에러 수정해" --use-top-context --execute
```

만드는 것:

- request artifact
- 필요 시 context artifact
- 필요 시 clarification artifact
- 필요 시 diagnose task / brain run

실제 source 수정: 아니오
자동 adoption: 아니오

### `cambrian status`

프로젝트 기억, 최근 여정, 최신 adoption, 다음 행동을 보여줍니다.

자주 쓰는 예:

```bash
cambrian status
```

만드는 것: 없음
실제 source 수정: 아니오
자동 adoption: 아니오

### `cambrian summary`

`.cambrian/` 아래 로컬 artifact만 읽어서 지금까지 Cambrian이 이 프로젝트에서 무엇을 도왔는지 요약합니다.

자주 쓰는 예:

```bash
cambrian summary
cambrian summary --save
cambrian summary --json
```

보여주는 것:

- work session / diagnosis / patch proposal / adoption 개수
- project memory / hygiene 요약
- active work / recent journey / 다음 행동
- safety summary

만드는 것:

- `--save`일 때만 `.cambrian/summary/usage_summary.yaml`

실제 source 수정: 아니오
외부 telemetry 전송: 아니오
자동 adoption: 아니오

### `cambrian doctor`

설치와 project mode 환경이 기본적으로 준비되어 있는지 빠르게 점검합니다.

자주 쓰는 예:

```bash
cambrian doctor
cambrian doctor --workspace ./demo
cambrian doctor --json
```

보여주는 것:

- Python 3.11+
- CLI import 가능 여부
- 필수 의존성
- pytest 사용 가능 여부
- workspace 쓰기 가능 여부
- project mode 초기화 상태
- demo create 사용 가능 여부

실제 source 수정: 아니오
외부 telemetry 전송: 아니오
자동 adoption: 아니오

### `cambrian notes`

알파 사용 중 느낀 confusion / bug / idea / success를 로컬 note로 남기고 다시 볼 수 있습니다.

```bash
cambrian notes add "clarify step was confusing" --kind confusion --severity medium --tag clarification
cambrian notes list
cambrian notes show <note-id>
cambrian notes resolve <note-id> --resolution "Added better recovery hints for clarify"
```

- 저장 위치: `.cambrian/notes/note_*.yaml`
- 실제 source 수정: 아니오
- 외부 telemetry 전송: 아니오
- 자동 behavior 변경: 아니오

### `cambrian context scan`

요청과 관련된 source/test 후보를 추천합니다.

자주 쓰는 예:

```bash
cambrian context scan "로그인 에러 수정해"
```

만드는 것:

- `.cambrian/context/context_*.yaml`

실제 source 수정: 아니오
자동 adoption: 아니오

### `cambrian clarify`

needs_context 요청에 필요한 source/test 선택을 채우고, 준비가 되면 diagnose-only run으로 이어집니다.

자주 쓰는 예:

```bash
cambrian clarify <request-id>
cambrian clarify <request-id> --use-suggestion 1
cambrian clarify <request-id> --source src/auth.py --test tests/test_auth.py --execute
```

만드는 것:

- `.cambrian/clarifications/clarification_*.yaml`
- 준비되면 diagnose task
- `--execute` 시 brain run report

실제 source 수정: 아니오
자동 adoption: 아니오

### `cambrian patch intent`

diagnosis report를 바탕으로 patch intent form을 만듭니다.

자주 쓰는 예:

```bash
cambrian patch intent .cambrian/brain/runs/<run-id>/report.json
```

만드는 것:

- `.cambrian/patch_intents/patch_intent_*.yaml`

실제 source 수정: 아니오
자동 adoption: 아니오

### `cambrian patch intent-fill`

patch intent form에 old/new text를 채우고, 원하면 proposal과 isolated validation까지 이어집니다.

자주 쓰는 예:

```bash
cambrian patch intent-fill .cambrian/patch_intents/<intent>.yaml \
  --old-choice old-1 \
  --new-text "return username.strip().lower()"

cambrian patch intent-fill .cambrian/patch_intents/<intent>.yaml \
  --old-choice old-1 \
  --new-text "return username.strip().lower()" \
  --propose \
  --execute
```

만드는 것:

- intent 업데이트
- 선택 시 patch proposal / task spec / isolated validation artifacts

실제 source 수정: 아니오
자동 adoption: 아니오

### `cambrian patch propose`

명시적 patch intent를 patch proposal로 바꾸고, 선택적으로 isolated validation을 수행합니다.

자주 쓰는 예:

```bash
cambrian patch propose --from-intent .cambrian/patch_intents/<intent>.yaml
cambrian patch propose --from-intent .cambrian/patch_intents/<intent>.yaml --execute
```

만드는 것:

- `.cambrian/patches/patch_proposal_*.yaml`
- `.cambrian/tasks/task_patch_*.yaml`
- 선택 시 `.cambrian/patches/workspaces/...`

실제 source 수정: 아니오
자동 adoption: 아니오

### `cambrian patch apply`

검증된 patch proposal을 실제 프로젝트 workspace에 적용합니다.

자주 쓰는 예:

```bash
cambrian patch apply .cambrian/patches/<proposal>.yaml --reason "normalize username before login"
```

만드는 것:

- adoption record
- latest pointer
- backups

실제 source 수정: 예
명시적 reason 필요: 예
자동 adoption: 아니오
post-apply tests: 예

## 고급 명령

### `cambrian brain`

고급 실행 하네스 명령입니다.
TaskSpec 기반 실행, run 조회, handoff 생성 같은 내부/운영 흐름에 사용합니다.

### `cambrian evolution`

고급 진화 아티팩트 명령입니다.
evolution ledger 재구성, generation 계보 확인, pressure 조회 같은 내부 분석 작업에 사용합니다.
