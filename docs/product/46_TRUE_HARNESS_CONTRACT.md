# True Harness Contract

## Problem Redefined

Cambrian의 본질은 하네스 설명을 생성하는 것이 아니다.
Cambrian의 본질은 AI가 제품을 만들 때 흔들리는 품질, 과도한 수정 범위, 검증 없는 낙관, 반복 실수를 통제하는 실행 제어면이다.

형님이 실제로 해결하려는 문제는 "AI에게 일을 시키는 방법"이 아니라 "AI가 매번 상급 결과물을 내도록 강제하는 운영 체계"다.

## Non-Negotiable Definition

Cambrian harness is an enforceable AI execution control plane.

A harness is not a prompt, a template, a role list, or a YAML bundle.

A harness is a closed control loop that turns project intent into bounded AI action, blocks low-evidence output, verifies results, records proof, and changes future behavior from outcomes.

The shortest definition:

```text
Harness = Bound -> Route -> Gate -> Verify -> Learn
```

If any verb is missing, the product is not yet a real harness.

하네스라고 부르려면 아래 조건을 만족해야 한다.

1. AI가 무엇을 할 수 있고 무엇을 하면 안 되는지 범위를 제한한다.
2. 코드베이스 evidence 없이 도메인, 에이전트, 스킬을 확정하지 않는다.
3. 품질 기준을 통과하지 못하면 설치, 실행, 완료, 진화를 막는다.
4. 실행 결과가 테스트, 로그, diff, review, outcome evidence로 남는다.
5. 실패가 기록되고 다음 실행의 기본값을 바꾼다.
6. status와 show가 실제 장착 상태를 진실하게 보여준다.
7. agent/skill/workforce 문서는 실행 게이트와 연결될 때만 의미가 있다.

이 조건을 만족하지 못하면 그것은 하네스가 아니라 하네스 문서 또는 설정 초안이다.

## Minimum Viable Harness

The minimum viable harness is not the smallest installer.
It is the smallest loop that can make AI behavior repeatably better.

Minimum requirements:

1. `bound`: allowed scope, forbidden scope, authority mode, and write boundary exist.
2. `route`: request is mapped to explicit agents/skills because of evidence, not keyword vibes.
3. `gate`: install, job start, validate, complete, and evolve have blocking conditions.
4. `verify`: result is checked against tests, logs, review criteria, or explicit manual proof.
5. `learn`: outcome changes future routing, warnings, defaults, or candidate promotion.
6. `truth`: status reports the real installed state, including partial/broken state.

Without this, Cambrian may still be useful, but it is not yet fulfilling its core promise.

## Harness Maturity Model

Cambrian should measure itself by harness maturity, not by feature count.

```text
L0 Description
  Static roles, YAML, prompts, docs.
  Not a harness.

L1 Guided Setup
  Scan/interview generates project-specific config.
  Still mostly advisory.

L2 Installed Control
  Status truth, authority, active agents, skills, validation, and policy are wired.
  This is the first real harness level.

L3 Blocking Gates
  Low evidence, missing tests, unsafe scope, and proof gaps block install/job/complete/evolve.

L4 Outcome Learning
  Failures and wins change routing, skill selection, warnings, and default decisions.

L5 Self-Improving Harness
  Candidate harnesses compete on evidence, canary results, rollback safety, and project fit.
```

Release target:

```text
External alpha must reach L2.
Gold path must reach L3.
Long-term Cambrian must reach L5.
```

## Product Boundary

### True Harness

- `project scan`: 정체성 evidence, 코드 evidence, 검증 evidence, 위험 evidence를 분리한다.
- `harness engineer review`: domain spec, evaluator contract, candidate lineage, execution boundary를 검사한다.
- `harness install`: project mode, authority, workforce, skill, validation, status를 한 번에 장착한다.
- `job start`: active harness의 agent, skill, policy, validation command를 request packet에 주입한다.
- `job validate`: 결과물이 evaluator contract와 proof gate를 통과했는지 판정한다.
- `job complete`: outcome evidence를 저장하고 learning signal로 만든다.
- `evolution`: evidence가 있는 실패와 성공만 기본값 변경 후보가 된다.

### Supporting Configuration

- `.cambrian/harness.yaml`
- `.cambrian/agents.yaml`
- `.cambrian/validation.yaml`
- `.cambrian/profile.yaml`
- `.cambrian/skills/*.yaml`
- `.cambrian/company/*`

이 파일들은 하네스 자체가 아니다.
이 파일들이 실행 게이트, status truth, validation proof에 연결될 때만 하네스의 일부가 된다.

### Fake Harness Signals

아래 상태는 출시 가능한 하네스가 아니다.

- YAML 파일만 생성되고 `cambrian status`가 not fitted로 보이는 상태
- 도메인 키워드 몇 개로 엉뚱한 agent가 설치되는 상태
- 검증 명령이 없는데 quality score가 높게 나오는 상태
- evidence가 weak인데 설치가 진행되는 상태
- AI가 Cambrian 설정을 무시해도 아무 제약이 없는 상태
- marketplace, MCP, zip, landing page가 있어도 runtime gate가 없는 상태

## Operating Spine

Cambrian의 제품 spine은 아래 순서로 고정한다.

```text
scan
-> interview
-> engineer design
-> engineer review
-> dry-run
-> install
-> status truth
-> job start
-> validate
-> complete
-> learn
-> evolve
```

어떤 기능도 이 spine을 우회하면 안 된다.

## Release Priority

지금 출시 막바지에서 가장 중요한 것은 설치 채널이 아니다.
MCP, zip, PyPI, landing page는 distribution layer다.

먼저 고쳐야 하는 것은 harness truth layer다.

1. 설치하면 `status`가 fitted여야 한다.
2. fitted라면 active harness, agent, skill, validation, authority가 보여야 한다.
3. job은 active harness 없이는 시작되면 안 된다.
4. validate는 proof 없이 success가 되면 안 된다.
5. complete는 outcome evidence 없이 learning으로 들어가면 안 된다.

## MCP Direction

MCP는 올바른 미래 배포/연결 방향이다.
하지만 MCP 서버가 먼저가 아니다.

MCP가 노출해야 할 것은 하네스 설명 생성 API가 아니라 아래 control plane이다.

- `scan_project`
- `fit_harness`
- `show_harness_status`
- `start_job`
- `validate_job`
- `complete_job`
- `review_evolution`

즉, MCP는 Cambrian의 본질이 강해진 뒤 그것을 Claude, Codex, Cursor, 외부 PC에 붙이는 표면이어야 한다.

## 2026-05-22 Local MCP Adapter Boundary

Cambrian now has a thin local MCP adapter entry point:

```bash
cambrian-mcp
```

Equivalent module form:

```bash
python -m engine.project_mcp_server
```

This adapter exposes allowlisted local Cambrian CLI tools over stdio MCP:

```text
cambrian_doctor
cambrian_project_scan
cambrian_harness_interview_infer
cambrian_harness_engineer_design
cambrian_harness_engineer_review
cambrian_harness_engineer_dry_run
cambrian_workforce_generate
cambrian_skill_generate
cambrian_harness_install
cambrian_job_start
cambrian_job_ingest
cambrian_job_validate
cambrian_job_complete
cambrian_company_snapshot
```

The adapter is intentionally thin.
It does not expose arbitrary shell execution.
Every tool requires explicit `cwd`.
Every tool returns command output and safety boundary metadata.
`cambrian_harness_install` is blocked unless `confirm=true`.

This MCP layer is part of external-user operability, not a replacement for One Good Harness.

## Decision

Cambrian의 다음 제품 판단 기준은 단순하다.

```text
Does this change make AI behavior more controlled, more evidenced, more repeatable, and more truthful?
```

그렇지 않다면 지금 단계에서는 후순위다.
