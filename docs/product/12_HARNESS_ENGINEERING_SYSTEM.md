# Harness Engineering System

## 166R Role In AI Company Runtime

Harness engineering is the quality gate before Cambrian installs an AI company into a project.

It checks whether the future company has a clear goal, operating rules, workforce, skills, validation commands, authority boundaries, and dry-run evidence before installation.

The result is not a preset install. The result is a project-specific operating system for the AI company.

2026-05-20 correction:

Harness engineering must compile enforceable gates, not just descriptive YAML.
If installation does not make `cambrian status` show a fitted active harness with authority, validation, evidence, and workforce context, the harness is not installed.

Cambrian의 초기 설치물은 단순 설정 파일이 아니라 하네스 엔지니어링 공정의 결과물이어야 한다.

기본 흐름:

```bash
cambrian project scan --json
cambrian harness interview start --json
cambrian harness interview answer --answers .cambrian/interview/answers.yaml --json
cambrian harness engineer design --json
cambrian harness engineer review --json
cambrian harness engineer dry-run "로그인 문제 봐줘" --json
cambrian harness install --confirm --json
```

## Design

`harness engineer design`은 `.cambrian/profile.yaml` 또는 `.cambrian/project/profile.yaml`의 project profile과 `.cambrian/interview/answers.yaml`을 바탕으로 설계 후보를 만든다.

저장 위치:

```text
.cambrian/engineering/design_candidate.yaml
```

설계 후보에는 아래가 포함된다.

- harness candidate
- workforce candidate
- agent candidates
- skill candidates
- validation candidate
- generated files preview
- quality score

## Meta-Harness Alignment

Cambrian의 하네스 엔지니어링은 Meta-Harness식 population search를 당장 자동화하는 단계가 아니다.
먼저 각 프로젝트에 대해 후보를 평가할 수 있는 domain spec, evaluator, lineage 계약을 설치해야 한다.

`design_candidate.yaml`은 아래 항목을 반드시 설명해야 한다.

- domain spec: 이 프로젝트에서 풀 문제, 허용 쓰기 범위, 금지 범위, 검증 명령, 통과 기준
- evaluator contract: validation command, judge rubric, proof gate가 어떤 verdict를 낼지
- candidate lineage: 후보의 부모, 생성 이유, 변경된 가정, 승격 또는 보류 조건
- execution boundary: sandbox, timeout, approval policy, 외부 전송 금지 여부

초기 구현에서는 별도 복잡한 population runner를 만들지 않는다.
`harness.yaml`, `validation.yaml`, `operating_rules.yaml`, `judge_rubric.md`에 위 계약을 흡수하고, review 단계에서 누락 여부를 막는다.
자동 세대 진화는 실제 pilot evidence와 rollback 경로가 검증된 뒤 strongest lane에서만 활성화한다.

## Review

`harness engineer review`는 설계 후보를 검수한다.

검수 기준:

- primary goal 존재
- test command 존재
- forbidden scope 존재
- important paths 존재
- agent 3~5명
- 모든 agent에 skill 최소 1개 연결
- 모든 skill에 procedure 존재
- validation success criteria 존재
- domain spec 필드 존재
- evaluator verdict 계약 존재
- candidate lineage 필드 존재
- sandbox, timeout, approval policy 존재
- `auto_apply` false

품질 점수 기준:

```text
70 이상: dry-run 및 install 가능
50~69: review 필요
50 미만: 추가 정보 필요
```

저장 위치:

```text
.cambrian/engineering/review.yaml
```

## Dry-Run

`harness engineer dry-run`은 실제 job을 만들지 않고 투입될 agent와 skill을 시뮬레이션한다.

저장 위치:

```text
.cambrian/engineering/dry_run.yaml
```

Dry-run은 `.cambrian/jobs/`나 `.cambrian/packs/jobs/`를 만들면 안 된다.

## Install Gate

`harness install --confirm`은 아래 조건을 모두 만족해야 설치된다.

- `design_candidate.yaml` 존재
- review 통과
- blocking issue 없음
- dry-run 1회 이상 실행
- quality score 70 이상

조건을 만족하지 못하면 `engineering_gate_not_passed`로 차단한다.

## Safety

- 프리셋 자동 설치 없음
- 사용자 승인 없는 install 없음
- review/dry-run 없는 install 없음
- 설치 즉시 dispatch 없음
- provider API 호출 없음
- 자동 patch apply 없음
- 자동 git commit 없음
- source code 자동 수정 없음
