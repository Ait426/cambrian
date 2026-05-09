# 166R AI Company Runtime Loop

Cambrian은 각 프로젝트에 AI 회사를 설치하고, 그 회사가 제품 목표를 처리하도록 실행 루프를 구성한다.

```text
project scan
-> harness interview
-> harness engineering
-> workforce generation
-> skill generation
-> authority mode
-> auto mode
-> boardroom decision
-> execution
-> validation
-> release gate
-> evolution
```

Manual job mode는 사람이 개별 일을 맡기는 경로다.

```text
job start
-> agent and skill selection
-> AI execution engine handoff
-> reply ingest
-> validation
-> evidence
```

Auto mode는 AI 회사가 boardroom decision과 plan에 따라 제품 제작 전 과정을 운영하는 경로다. V1은 bounded run과 evidence 기록까지만 수행하며 source code를 자동 수정하지 않는다.

# 165R Authority And Auto Product Organization Loop

Cambrian의 오토 실행은 권한 프로파일 안에서만 동작합니다.

```text
authority profile
-> auto init
-> boardroom decision
-> auto plan
-> bounded auto run
-> execution evidence
```

기본 권한은 `proposal_only`입니다. `full_authority`는 사용자가 명시적으로 `cambrian authority grant --mode full-authority`를 실행했을 때만 활성화됩니다.

V1의 `auto run`은 source code를 수정하지 않습니다. 계획 step을 권한에 따라 진행 가능/차단으로 분류하고 `.cambrian/auto/execution_log.yaml` 및 `.cambrian/evidence/authority_log.yaml`에 기록합니다.

금지:

- secret 자동 사용
- deploy 자동 실행
- payment/메일/외부 사용자 발송
- 무한 루프
- 사용자 승인 없는 full authority 기본값

# 163R Evidence-Based Evolution Loop

Cambrian의 진화는 자동 적용이 아니라 evidence 기반 제안과 승인 기반 적용으로만 진행한다.

```text
job start
-> AI reply ingest
-> job validate
-> job complete
-> evolve review
-> evolve propose
-> evolve apply --confirm
```

`job complete`는 사람이 outcome과 notes를 기록하는 단계다.

```bash
cambrian job complete latest --outcome partial --notes "test command가 틀렸고 refresh token 경로를 놓쳤음"
```

저장 위치:

```text
.cambrian/jobs/<job-id>/outcome.yaml
.cambrian/evidence/outcomes.yaml
```

`evolve review`는 최근 outcome evidence를 요약하고, `evolve propose`는 하네스/인력/스킬 metadata 변경안을 만든다.

`evolve apply`는 `--confirm` 없이는 차단된다. 승인 후에도 변경 대상은 로컬 `.cambrian/` metadata뿐이다.

허용:

- `.cambrian/harness.yaml` important paths, validation 기준 보강
- `.cambrian/agents/*.yaml` responsibility 보강
- `.cambrian/skills/*.yaml` procedure, when_to_use, validation 기준 보강
- `.cambrian/evolution/history.yaml` 기록

금지:

- source code 자동 수정
- preset 원본 수정
- provider API 호출
- 자동 patch apply

# 162R-REPLACE-V3 Agent And Skill Dispatch Loop

설치 단계와 실행 단계는 분리됩니다.

설치 단계:

```text
harness design -> workforce generate -> skill generate -> harness install --confirm
```

실행 단계:

```text
job start -> generated agent and skill selection -> AI reply ingest -> job validate -> local evidence
```

`harness install --confirm`은 하네스, 인력, 스킬을 설치할 뿐, 작업을 자동 시작하지 않습니다.

작업 시작:

```bash
cambrian job start "로그인 세션 만료 문제 확인해"
```

`job start`는 `.cambrian/workforce.yaml`과 `.cambrian/skills/*.yaml`을 읽고 작업에 필요한 agent와 skill을 함께 선택합니다.

# 162R-REPLACE-V2 Dispatch On Demand Execution Loop

설치 단계와 실행 단계는 분리됩니다.

설치 단계:

```text
harness design -> workforce generate -> harness install --confirm
```

실행 단계:

```text
job start -> generated agent selection -> AI reply ingest -> job validate -> local evidence
```

`harness install --confirm`은 하네스와 인력을 설치할 뿐, 작업을 자동 시작하지 않습니다.

작업 시작:

```bash
cambrian job start "로그인 세션 만료 문제 확인해"
```

명시적 agent 실행:

```bash
cambrian agent run auth-flow-investigator "Bearer 토큰 검증 흐름 점검해"
```

AI provider 호출, 자동 patch apply, 자동 git commit은 실행 loop에 포함되지 않습니다.

# 162R Custom Harness Execution Loop

Custom harness가 설치된 뒤 실행 loop는 다음을 따른다.

```text
agent dispatch -> AI reply ingest -> job validate -> local evidence
```

`agent dispatch`는 `.cambrian/harness.yaml`, `.cambrian/agents.yaml`, `.cambrian/validation.yaml`을 읽어 job을 생성합니다.

AI provider 호출, 자동 patch apply, 자동 git commit은 실행 loop에 포함하지 않습니다.

# Execution Loops

## 161R Validation Lane

`agent dispatch`는 active harness를 기준으로 job을 생성합니다.

- `auth-bug-core`: Python + pytest validation lane
- `typescript-jest-auth-core`: TypeScript + Jest validation lane

TypeScript + Jest job은 pytest 경로로 검증하지 않습니다. Jest 자동 실행이 준비되지 않았으면 fake PASS 대신 수동 Jest command와 다음 액션을 반환합니다.

## 0. 160R 실행 루프 정정

기본 실행 루프는 pack-first가 아니라 project-first다.

```text
project scan
→ Project Profile 저장
→ harness plan
→ built-in harness preset 선택
→ harness install
→ agent dispatch
→ AI reply ingest
→ job validate
→ local evidence 기록
```

`agent dispatch`는 내부적으로 기존 pack job creation을 재사용할 수 있지만, 사용자가 보는 기본 행동은 “pack start”가 아니라 “하네스에 에이전트를 파견한다”이다.

## 1. 문서 목적

이 문서는 Cambrian이 실제로 어떻게 사용되고, 어떻게 증명되고, 어떻게 진화하는지를 **loop 단위**로 정의한다.

Cambrian은 단일 명령어 제품이 아니다.
Cambrian은 설치, 작업, 검증, 진화가 반복되는 운영 시스템이다.

이 문서는 다음 질문에 답한다.

- 사용자는 Cambrian을 어떤 순서로 쓰는가?
- AI 일꾼을 설치한 뒤 실제 작업은 어떻게 진행되는가?
- 결과가 좋은지 어떻게 증명하는가?
- 좋은 실험은 어떻게 다음 기본값으로 승격되는가?
- 안 좋은 실험은 어떻게 되돌리는가?
- 각 loop에서 source-of-truth와 derived artifact는 무엇인가?

Cambrian의 핵심 loop는 네 가지다.

```text
Install Loop
Work Loop
Proof Loop
Evolution Loop
```

공식 alias는 Install loop, Work loop, Proof loop, Evolution loop다.

---

## 2. 전체 구조

Cambrian은 아래 흐름으로 움직인다.

```text
Install Loop
→ Work Loop
→ Proof Loop
→ Evolution Loop
→ 다시 Work Loop / Install Loop로 반영
```

각 loop의 역할은 다르다.

| Loop | 목적 |
| --- | --- |
| Install Loop | AI 일꾼과 작업반을 로컬에 설치한다 |
| Work Loop | 사용자의 실제 요청을 처리한다 |
| Proof Loop | 결과가 실제로 좋았는지 증명한다 |
| Evolution Loop | 좋은 실험을 다음 기본값으로 승격한다 |

이 네 loop가 연결될 때 Cambrian은 단순 CLI가 아니라
**AI 일꾼 설치·검증·진화 runtime** 이 된다.

---

# Part 1. Install Loop

## 3. Install Loop 정의

Install Loop는 사용자가 AI 일꾼, 팀, 템플릿, lane pack을 선택하고 로컬 Cambrian에 설치하는 흐름이다.

한 문장으로:

> **Install Loop는 웹 또는 로컬 catalog에서 고른 AI 작업반을 `.cambrian/` 로컬 library에 등록하는 과정이다.**

설치는 current project source code를 수정하지 않는다.
설치는 current runtime을 자동으로 바꾸지 않는다.
설치는 future use를 위한 library state를 준비한다.

---

## 4. Install Loop 단계

```text
pack 선택
→ manifest 확인
→ local install
→ doctor
→ optional apply/bootstrap
```

### 4.1 Pack 선택

사용자는 웹 catalog 또는 local catalog에서 pack을 고른다.

Pack 종류:

* worker pack
* team pack
* template pack
* lane pack

초기 주력 pack:

```text
auth-bug-core
```

### 4.2 Manifest 확인

Pack은 local catalog entry를 통해 고르거나, install manifest path를 직접 지정해 설치된다.
`cambrian install pack <id>`는 local catalog에서 manifest path를 찾은 뒤 같은 manifest installer를 사용한다.

Manifest는 다음을 포함해야 한다.

* pack id
* pack kind
* included workers
* included teams
* included templates
* compatibility
* warnings
* install policy

### 4.3 Local install

설치 시 `.cambrian/` 아래 library state가 업데이트된다.

예:

```text
.cambrian/agents/
.cambrian/templates/
.cambrian/benchmarks/
.cambrian/lane/
.cambrian/install/
```

### 4.4 Doctor

설치 후 Cambrian은 pack 상태를 검증해야 한다.

확인할 것:

* agent 존재 여부
* team 존재 여부
* template 존재 여부
* benchmark workset 존재 여부
* strongest lane fit
* missing dependencies
* source mutation 없음

### 4.5 Optional apply/bootstrap

설치 자체는 apply가 아니다.

현재 프로젝트에 적용하려면:

```bash
cambrian template apply auth-bug-template
```

새 프로젝트 초기화에 쓰려면:

```bash
cambrian init --template auth-bug-template
```

---

## 5. Install Loop 예시

```bash
cambrian pack list
cambrian pack show auth-bug-core
cambrian install pack auth-bug-core
cambrian install doctor
cambrian pack doctor auth-bug-core
cambrian pack setup auth-bug-core
cambrian pack setup-apply latest
cambrian pack activate auth-bug-core
cambrian pack next
cambrian pack start "로그인 에러 수정해"
cambrian pack job-paste job-...
cambrian pack job-validate job-...
cambrian pack job-apply job-...
cambrian pack job-apply job-... --confirm
cambrian pack job-adopt job-... --accepted --reason "validated and applied cleanly"
cambrian pack job-retro job-...
cambrian pack retro-summary auth-bug-core
cambrian pack improve auth-bug-core
cambrian pack improvement-show item-...
cambrian pack improvement-accept item-... --resolution "Will evolve auth-bug-template context defaults"
cambrian pack proof auth-bug-core
cambrian template show auth-bug-template
cambrian benchmark proof auth-bug-workset
```

`pack activate` is an explicit first-job onboarding step.
It does not apply a template, bootstrap the project, switch a lane default, or mutate source code.
`pack doctor` is the readiness gate before activation: it checks whether the installed or catalog pack fits the current project stack, test framework, artifact refs, digest/lockfile state, known limits, and first-job path.
It does not install, activate, apply, bootstrap, replay benchmarks, or mutate source code; it returns `ready`, `partial`, `blocked`, `unsupported`, or `unknown` with exact next actions.
`pack setup` is the guided repair plan after doctor. It separates safe Cambrian-state fixes from user actions, then `pack setup-apply` can apply only safe actions such as activation, readiness refresh, and next-guide regeneration.
It will not install dependencies, install pytest, create source/test files, apply templates, bootstrap the project, or mutate source code.
`pack start` is the pack-first job entry. It creates a pack job artifact and bridge packet for the selected worker pack, preserves pack/team/template/lane context for usage attribution, and prints the exact next command.
`pack job-paste` attaches the AI reply to the pack job and reuses the bridge fast path; `pack job-validate` carries validation-ready patch candidates into the existing validation path.
`pack job-apply` previews the validated proposal first and mutates source only when `--confirm` is passed through the existing patch apply path.
`pack job-adopt` records accepted/rejected/skipped explicitly so validated proposal, apply, and adoption remain separate evidence.
`pack job-retro` turns the final job evidence into local feedback signals and improvement suggestions; `pack retro-summary` aggregates them at pack level for proof/release/evolution inputs.
`pack improve` converts those retrospective signals into a concrete pack improvement queue with priority, confidence, affected metrics, evidence refs, and suggested next commands.
`pack improvement-accept` and `pack improvement-dismiss` are decision records only; they do not evolve templates, create benchmark cases, draft/build packs, publish, or mutate source code.
It does not call an AI provider, auto-apply code, auto-adopt changes, auto-evolve packs, bootstrap the project, or mutate source outside confirmed apply.

설치된 pack의 lifecycle 관리는 같은 Install Loop 안에서 preview-first로 진행된다.

```bash
cambrian install diff auth-bug-core
cambrian install update auth-bug-core
cambrian install update auth-bug-core --confirm
cambrian uninstall pack auth-bug-core
cambrian uninstall pack auth-bug-core --confirm
```

`install update`와 `uninstall pack`은 `--confirm` 없이는 preview만 출력한다.
local derivatives와 proof/session/metrics history는 삭제하거나 덮어쓰면 안 된다.

또는 웹 catalog에서 install manifest를 받은 경우:

```bash
cambrian install manifest ./auth-bug-core.cambrian-pack.yaml
cambrian install doctor
```

---

## 6. Install Loop 산출물

Install Loop가 만들 수 있는 artifact:

```text
.cambrian/install/installed_packs.yaml
.cambrian/install/diffs/
.cambrian/install/updates/
.cambrian/install/uninstall_plans/
.cambrian/install/uninstalls/
.cambrian/agents/registry.yaml
.cambrian/agents/teams.yaml
.cambrian/templates/templates.yaml
.cambrian/benchmarks/worksets/
.cambrian/lane/playbook.yaml
```

이 중 일부는 source-of-truth다.

예:

* installed_packs.yaml
* templates.yaml
* teams.yaml
* lane/playbook.yaml

---

## 7. Install Loop의 금지 사항

Install Loop는 절대 다음을 하면 안 된다.

* project source code 수정
* template 자동 apply
* team 자동 apply
* lane default 자동 switch
* benchmark 자동 실행
* AI provider 자동 호출
* patch apply
* adoption
* local derivative 자동 overwrite
* proof/metrics/session history 삭제

Install은 **고용/등록**이지 **실행/적용**이 아니다.

---

# Part 2. Work Loop

## 8. Work Loop 정의

Work Loop는 사용자가 실제 요청을 Cambrian에 넣고, Cambrian이 AI와 로컬 runtime을 연결해 작업을 진행하는 흐름이다.

한 문장으로:

> **Work Loop는 사용자의 요청을 project harness, AI bridge, agent/team/template context, validation flow를 통해 safe proposal까지 보내는 과정이다.**

Work Loop의 목표는 무조건 apply가 아니다.
초기 핵심 목표는:

```text
validated proposal
```

이다.

---

## 9. Work Loop의 두 가지 진입점

Cambrian Work Loop에는 두 가지 주요 entry가 있다.

### 9.1 Direct do path

```bash
cambrian do "로그인 에러 수정해"
```

또는 strongest lane에서:

```bash
cambrian do "로그인 에러 수정해" --safe-autonomy
```

### 9.2 AI bridge path

```bash
cambrian bridge prepare "로그인 에러 수정해"
# AI에 packet 붙여넣기
cambrian bridge paste --packet packet-...
```

Bridge path는 사용자가 이미 쓰는 AI에 Cambrian 작업복을 입히는 핵심 entry다.

---

## 10. Work Loop 단계

```text
request
→ context
→ diagnose
→ intent / reply handling
→ proposal
→ validation
→ optional apply
```

### 10.1 Request

사용자 요청이 들어온다.

예:

```text
로그인 에러 수정해
```

Cambrian은 request class를 추정한다.

예:

```text
bug_fix
auth/login
narrow_scope
```

### 10.2 Context

Cambrian은 관련 source/test 후보를 찾는다.

정보 source:

* project profile
* memory
* notes
* bridge context hints
* template context defaults
* improvement overlay
* lane playbook

### 10.3 Diagnose

Cambrian은 context 기반으로 문제를 좁힌다.
이 단계는 source mutation 없이 진행된다.

### 10.4 Intent / Reply Handling

경로에 따라 달라진다.

Direct path:

* patch intent
* context-assisted run
* clarify path

Bridge path:

* patch_candidate → patch intent draft
* analysis → analysis brief / context hint
* review → review note
* plan → checklist

### 10.5 Proposal

patch intent가 충분하면 proposal이 생성될 수 있다.

### 10.6 Validation

proposal은 tests / validation path를 통해 검증된다.

목표:

```text
proposal_validated
```

### 10.7 Optional Apply

Apply는 항상 별도 explicit action이어야 한다.

금지:

* Work Loop가 자동 apply/adoption까지 몰래 진행

---

## 11. Bridge Work Loop

Bridge는 Cambrian의 model-agnostic AI entry다.

### 11.1 Prepare

```bash
cambrian bridge prepare "로그인 에러 수정해"
```

Cambrian은 AI에 붙여넣을 packet을 만든다.

Packet 포함:

* request
* project harness
* active team
* template/policy hints
* memory summary
* response contract

### 11.2 AI reply

AI는 structured reply를 반환한다.

가능한 kind:

* patch_candidate
* analysis
* review
* plan

### 11.3 Paste / Ingest

```bash
cambrian bridge paste --packet packet-...
```

또는:

```bash
cambrian bridge ingest reply.yaml --packet packet-... --auto-route
```

### 11.4 Fast path routing

* patch_candidate → patch intent draft → linked session → continue --validate
* analysis → analysis_brief → context_hint
* review → review_note
* plan → plan_record → checklist

### 11.5 No-retype principle

patch_candidate가 아래를 포함하면:

* target_path
* old_text
* new_text
* reason

사용자가 다시 입력하지 않아도 된다.

다음 명령으로 이어져야 한다.

```bash
cambrian continue --session do-... --validate
```

---

## 12. Safe Autonomy Work Loop

Strongest lane 안에서는 명시적 safe autonomy를 사용할 수 있다.

```bash
cambrian do "로그인 에러 수정해" --safe-autonomy
```

또는:

```bash
cambrian continue --session do-... --safe-autonomy
```

safe autonomy는 가능한 단계까지 자동 진행한다.

```text
request_start
→ context_ready
→ diagnosed
→ patch_intent_ready
→ proposal_validated
```

하지만 다음은 하지 않는다.

* apply
* adoption
* source mutation
* broad refactor automation

safe autonomy는 strong lane에서만 적극 동작한다.

---

## 13. Work Loop 산출물

Work Loop가 만들 수 있는 artifact:

```text
.cambrian/requests/
.cambrian/sessions/
.cambrian/bridge/packets/
.cambrian/bridge/replies/
.cambrian/bridge/fastpath/
.cambrian/bridge/handoffs/
.cambrian/patch_intents/
.cambrian/proposals/
.cambrian/autonomy/runs/
```

이 artifact들은 current runtime state다.

---

## 14. Work Loop 성공 기준

Work Loop의 주요 성공은 다음이다.

* context ambiguity 감소
* old/new 재입력 감소
* patch intent draft 생성
* validation까지 도달
* human intervention 감소
* no source mutation before explicit apply

북극성:

```text
validated_proposal_rate
```

보조 지표:

* human_intervention_rate
* validation_autonomy_rate
* median_time_to_validated_proposal

---

# Part 3. Proof Loop

## 15. Proof Loop 정의

Proof Loop는 Cambrian이 실제로 더 좋은 결과를 내는지 증명하는 흐름이다.

한 문장으로:

> **Proof Loop는 Work Loop의 결과를 metrics, benchmark, replay, compare, proof pack으로 검증하는 과정이다.**

Cambrian은 “좋아 보인다”가 아니라
**실제로 더 낫다**를 보여줘야 한다.

---

## 16. Proof Loop 단계

```text
metrics
→ benchmark result
→ baseline compare
→ replay
→ autonomy board
→ bottleneck
→ proof pack
```

### 16.1 Metrics

```bash
cambrian metrics week
```

핵심 KPI:

* validated_proposal_rate
* adoption_rate
* regression_free_apply_rate
* median_time_to_validated_proposal
* human_intervention_rate
* validation_autonomy_rate
* lead_agent_hit_rate
* team_template_recommendation_hit_rate
* reuse_lift
* repeat_task_improvement_rate

### 16.2 Benchmark

```bash
cambrian benchmark report auth-bug-workset
```

Benchmark는 반복 가능한 case/workset 기반이다.

### 16.3 Baseline Compare

```bash
cambrian benchmark compare auth-bug-workset
```

이전 baseline 대비:

* improved
* mixed
* regressed
* insufficient_data

를 판단한다.

### 16.4 Replay

```bash
cambrian benchmark replay-workset auth-bug-workset --mode cambrian_full
```

현재 하네스가 같은 case를 어디까지 자동으로 진행하는지 본다.

### 16.5 Autonomy Board

```bash
cambrian benchmark autonomy-board auth-bug-workset
```

workset 전체에서:

* stage reached
* stop reasons
* validation autonomy
  를 집계한다.

### 16.6 Bottleneck

```bash
cambrian benchmark bottlenecks auth-bug-workset
```

어디서 자주 막히는지 분석한다.

### 16.7 Proof Pack

```bash
cambrian benchmark proof auth-bug-workset
```

한 장짜리 증명 보고서를 만든다.

---

## 17. Proof Loop 산출물

Proof Loop가 만들 수 있는 artifact:

```text
.cambrian/metrics/
.cambrian/benchmarks/results/
.cambrian/benchmarks/reports/
.cambrian/benchmarks/baselines/
.cambrian/benchmarks/compares/
.cambrian/benchmarks/replays/
.cambrian/benchmarks/workset_replays/
.cambrian/benchmarks/autonomy_boards/
.cambrian/benchmarks/bottlenecks/
.cambrian/benchmarks/proof/
```

대부분 derived artifact다.
이 파일들은 decision의 근거지만, decision 그 자체는 아니다.

---

## 18. Proof Loop의 핵심 질문

Proof Loop는 아래 질문에 답해야 한다.

### 18.1 Cambrian이 raw AI보다 나은가?

비교 대상:

* raw_ai
* bridge_only
* cambrian_guided
* cambrian_full

### 18.2 Cambrian이 지난 baseline보다 나아졌는가?

compare verdict:

* improved
* mixed
* regressed
* insufficient_data

### 18.3 자동으로 어디까지 가는가?

stage:

* context_ready
* diagnosed
* patch_intent_ready
* proposal_validated

### 18.4 어디서 자주 막히는가?

stop reason:

* ambiguous_context_selection
* missing_patch_candidate
* validation_failure_cluster
* weak_team_fit
* weak_template_fit

### 18.5 다음에 무엇을 고칠 것인가?

top bottleneck과 top next fix를 하나 고른다.

---

## 19. Proof Loop 성공 기준

Proof Loop가 성공하려면 다음이 보여야 한다.

* strongest lane에서 Cambrian Full이 raw_ai보다 나음
* validated_proposal_rate가 상승
* human_intervention_rate가 하락
* validation_autonomy_rate가 상승
* repeat_task_improvement_rate가 non-negative
* top bottleneck가 줄어듦

Proof Loop는 제품의 믿음을 만든다.

---

# Part 4. Evolution Loop

## 20. Evolution Loop 정의

Evolution Loop는 proof와 bottleneck을 바탕으로 Cambrian의 기본값을 개선하는 흐름이다.

한 문장으로:

> **Evolution Loop는 하나의 병목을 선택하고, 작은 intervention을 적용하고, 결과를 다시 측정해, 좋으면 persistent learning이나 template evolution으로 승격하는 과정이다.**

Cambrian의 “진화”는 자동 생성이 아니다.
Cambrian의 진화는 **evidence-backed adoption** 이다.

---

## 21. Evolution Loop 단계

```text
bottleneck
→ improvement cycle
→ intervention
→ evaluate
→ keep / dismiss
→ persistent overlay
→ template evolution
→ qualification
→ canary
→ promote / rollback
```

### 21.1 Bottleneck

```bash
cambrian benchmark bottlenecks auth-bug-workset
```

반복적으로 막히는 원인을 찾는다.

예:

* ambiguous_context_selection
* missing_patch_candidate
* review_support_gap

### 21.2 Improvement Cycle

```bash
cambrian improve next auth-bug-workset
```

한 번에 하나의 병목만 선택한다.

### 21.3 Intervention

```bash
cambrian improve pack cycle-...
cambrian improve apply intervention-...
```

작고 reversible한 overlay를 적용한다.

예:

* context hint bias
* review support bias
* narrow scope bias
* test-first bias

### 21.4 Evaluate

```bash
cambrian improve evaluate cycle-...
```

before / after를 비교한다.

verdict:

* improved
* mixed
* regressed
* inconclusive

### 21.5 Keep or Dismiss

```bash
cambrian improve keep intervention-...
```

또는:

```bash
cambrian improve dismiss intervention-...
```

### 21.6 Persistent Overlay

kept improvement는 `.cambrian/improvement/persistent_overlay.yaml`에 남는다.

### 21.7 Template Evolution

```bash
cambrian template evolve auth-bug-template
cambrian template evolve-accept proposal-...
```

좋은 local learning을 reusable template default로 승격한다.

### 21.8 Qualification

```bash
cambrian template qualify auth-bug-template-local --workset auth-bug-workset
```

candidate가 parent/reference보다 나은지 같은 workset에서 검증한다.

### 21.9 Canary

```bash
cambrian template qualify-stage qualification-...
```

candidate를 바로 stable default로 올리지 않고 canary로 태운다.

### 21.10 Promote / Rollback

```bash
cambrian template canary-promote auth-bug-template-local
```

또는:

```bash
cambrian template qualify-revert adoption-...
```

---

## 22. Evolution Loop 산출물

Evolution Loop가 만들 수 있는 artifact:

```text
.cambrian/improvement/cycles/
.cambrian/improvement/interventions/
.cambrian/improvement/overlay.yaml
.cambrian/improvement/persistent_overlay.yaml
.cambrian/improvement/decisions.yaml

.cambrian/templates/evolution_proposals/
.cambrian/templates/evolution_decisions.yaml
.cambrian/templates/qualifications/
.cambrian/templates/qualification_decisions.yaml
.cambrian/templates/qualification_adoptions/
.cambrian/templates/qualification_rollbacks/
.cambrian/templates/qualification_stages.yaml
.cambrian/templates/canary_reports/
.cambrian/templates/canary_events/
.cambrian/templates/canary_outcomes/
.cambrian/templates/canary_reviews/
.cambrian/templates/challengers.yaml
.cambrian/templates/challenge_boards/
.cambrian/templates/challenge_matrices/
.cambrian/lane/playbook.yaml
```

---

## 23. Evolution Loop의 핵심 규칙

### 23.1 한 번에 하나의 병목

여러 병목을 동시에 고치면 무엇 때문에 좋아졌는지 알 수 없다.

### 23.2 Intervention은 reversible해야 한다

적용과 되돌림이 가능해야 한다.

### 23.3 좋아야 keep한다

기본적으로 improved evidence가 있을 때만 persistent overlay로 승격한다.

### 23.4 imported template는 fork 후 evolve한다

imported template를 in-place mutate하지 않는다.

### 23.5 candidate는 qualification을 거친다

좋아 보이는 derivative라도 parent/reference와 같은 workset에서 비교해야 한다.

### 23.6 stable default 전 canary를 태운다

stronger candidate라도 바로 default로 올리지 않는다.

### 23.7 rollback 가능해야 한다

승격은 되돌릴 수 있어야 한다.

---

## 24. Evolution Loop 성공 기준

Evolution Loop가 성공했다는 것은 다음을 의미한다.

* top bottleneck frequency가 줄어든다
* validated_proposal_rate가 올라간다
* human_intervention_rate가 내려간다
* validation_autonomy_rate가 올라간다
* repeat_task_improvement_rate가 non-negative 또는 positive다
* 좋은 experiment가 template/lane default로 승격된다
* 안 좋은 default는 rollback된다

즉 진화는 “파일이 늘어남”이 아니라
**반복 작업에서 실제로 더 잘함** 이다.

---

# Part 5. Loop 연결

## 25. Install → Work

Install Loop는 Work Loop에 필요한 library와 defaults를 준비한다.

예:

```bash
cambrian install pack auth-bug-core
cambrian bridge prepare "로그인 에러 수정해"
```

Pack 설치가 Work Loop의 harness/team/template context를 만든다.

---

## 26. Work → Proof

Work Loop 결과는 Proof Loop의 입력이 된다.

예:

* session
* request
* patch intent
* proposal
* validation
* bridge reply
* apply/adoption result

이 정보가 metrics와 benchmark result로 연결된다.

---

## 27. Proof → Evolution

Proof Loop는 Evolution Loop에 병목과 개선 방향을 제공한다.

예:

```bash
cambrian benchmark bottlenecks auth-bug-workset
cambrian improve next auth-bug-workset
```

---

## 28. Evolution → Install / Work

Evolution Loop는 다음 install/work 흐름의 기본값을 바꾼다.

예:

* persistent overlay
* evolved template
* qualified derivative
* canary template
* lane default switch

하지만 current runtime을 자동으로 바꾸면 안 된다.
future default로만 반영한다.

---

# Part 6. Loop별 Safety Boundary

## 29. Install Loop safety

금지:

* source code mutation
* auto apply
* auto bootstrap
* auto promotion

허용:

* local library registration
* install provenance
* doctor check

---

## 30. Work Loop safety

금지:

* auto apply
* auto adoption
* hidden source mutation

허용:

* bridge packet
* reply ingest
* patch intent draft
* validation
* no-retype continue path

---

## 31. Proof Loop safety

금지:

* auto execution mutation
* source mutation
* promotion mutation

허용:

* metrics
* benchmark
* replay
* compare
* proof pack

---

## 32. Evolution Loop safety

금지:

* auto fix
* auto promote
* auto rollback
* current runtime mutation without explicit command

허용:

* intervention overlay
* keep/dismiss
* template evolution proposal
* qualification
* canary
* explicit promotion/rollback

---

# Part 7. Canonical First Product Loop

## 33. Strongest Lane canonical loop

현재 strongest lane 기준 canonical loop는 다음이다.

```bash
# 1. Install
cambrian pack show auth-bug-core
cambrian install pack auth-bug-core
cambrian install doctor

# 2. Activate
cambrian pack activate auth-bug-core
cambrian pack next

# 3. Work
cambrian pack start "로그인 에러 수정해"
cambrian pack job-paste job-...
cambrian pack job-validate job-...
cambrian pack job-apply job-...
cambrian pack job-apply job-... --confirm
cambrian pack job-adopt job-... --accepted --reason "validated and applied cleanly"
cambrian pack job-retro job-...
cambrian pack retro-summary auth-bug-core
cambrian pack improve auth-bug-core

# 4. Proof
cambrian metrics week
cambrian benchmark proof auth-bug-workset
cambrian pack outcomes auth-bug-core
cambrian pack proof auth-bug-core --save

# 5. Evolution
cambrian benchmark bottlenecks auth-bug-workset
cambrian improve next auth-bug-workset
```

이 loop가 현재 제품 증명의 중심이다.

---

## 34. Minimal useful loop

사용자가 처음 경험해야 하는 최소 loop:

```bash
cambrian pack start "로그인 에러 수정해"
cambrian pack job-paste job-...
cambrian pack job-validate job-...
cambrian pack job-apply job-...
cambrian pack job-adopt job-...
cambrian pack job-retro job-...
cambrian pack improve auth-bug-core
```

이게 매끈해야 한다.
이 loop가 불편하면 Cambrian은 “AI 일꾼 설치기”처럼 느껴지지 않는다.

---

## 35. Proof-oriented loop

제품 내부 운영에서 가장 중요한 loop:

```bash
cambrian benchmark replay-workset auth-bug-workset --mode cambrian_full
cambrian benchmark autonomy-board auth-bug-workset
cambrian benchmark compare auth-bug-workset
cambrian benchmark proof auth-bug-workset
cambrian pack usage auth-bug-core
cambrian pack outcomes auth-bug-core
cambrian pack proof auth-bug-core
```

이 loop는 Cambrian이 실제로 이기는지 보여준다.

---

## 36. Evolution-oriented loop

진짜 하네스 진화 loop:

```bash
cambrian benchmark bottlenecks auth-bug-workset
cambrian improve next auth-bug-workset
cambrian improve pack cycle-...
cambrian improve apply intervention-...
# replay / compare / metrics
cambrian improve evaluate cycle-...
cambrian improve keep intervention-...
cambrian template evolve auth-bug-template
```

이 loop가 돌면 좋은 실험이 다음 기본값이 된다.

---

# Part 8. Loop Drift 방지 원칙

## 37. 새 기능은 loop 중 하나에 속해야 한다

새 기능이 아래 중 어디에도 속하지 않으면 보류해야 한다.

* Install Loop
* Work Loop
* Proof Loop
* Evolution Loop

## 38. 새 기능은 핵심 지표 중 하나를 개선해야 한다

최소 하나를 직접 개선하거나 측정 가능하게 해야 한다.

* validated_proposal_rate
* human_intervention_rate
* validation_autonomy_rate
* median_time_to_validated_proposal
* team_template_recommendation_hit_rate
* reuse_lift
* repeat_task_improvement_rate

## 39. 새 기능은 source-of-truth와 derived artifact를 혼동하면 안 된다

예:

* proof pack은 source-of-truth가 아니다
* qualification report는 source-of-truth가 아니다
* qualify-accept는 source-of-truth decision이다

## 40. 새 기능은 current runtime과 future default를 혼동하면 안 된다

예:

* lane default switch는 current template apply가 아니다
* canary promotion은 current session mutation이 아니다
* persistent overlay는 source code mutation이 아니다

---

## 40.1 Pack Authoring Loop Extension

Pack authoring은 Install Loop와 Evolution Loop를 이어주는 local production path다.
좋게 진화한 worker/team/template/lane은 다시 installable pack으로 빌드되어 local catalog에 publish될 수 있다.

```bash
cambrian pack draft auth-bug-core-local --kind lane \
  --template auth-bug-template-local \
  --team auth-bug-team \
  --benchmark auth-bug-workset \
  --lane python-pytest-auth-bug-core
cambrian pack validate .cambrian/packs/drafts/draft_auth-bug-core-local.yaml
cambrian pack build .cambrian/packs/drafts/draft_auth-bug-core-local.yaml
cambrian pack publish-local packs/generated/auth-bug-core-local.cambrian-pack.yaml
cambrian pack publish-local packs/generated/auth-bug-core-local.cambrian-pack.yaml --confirm
```

Authoring artifacts:

```text
.cambrian/packs/drafts/
.cambrian/packs/builds/
.cambrian/packs/publishes/
packs/generated/
packs/catalog.yaml
```

`publish-local`은 local `packs/catalog.yaml`에 등록하는 명령이다.
remote/web publish remains future/planned.
Authoring does not auto install, auto apply, auto bootstrap, auto promote, or auto canary.

---

## 40.2 Pack Derivative Loop Extension

The retrospective-to-action loop closes only when accepted improvements become a concrete vNext plan.
The derivative workspace is the safe bridge between improvement decisions and future pack authoring.

```bash
cambrian pack job-retro job-...
cambrian pack retro-summary auth-bug-core
cambrian pack improve auth-bug-core
cambrian pack improvement-accept item-...
cambrian pack derivative-plan auth-bug-core
cambrian pack derivative-create latest --as auth-bug-core-v2
```

This loop improves `reuse_lift`, `repeat_task_improvement_rate`, `validated_proposal_rate`, `human_intervention_rate`, `validation_autonomy_rate`, `team_template_recommendation_hit_rate`, and `adoption_rate` by keeping accepted learning tied to explicit evidence and follow-up commands.

Derivative plans are local-only design artifacts. They do not mutate templates, teams, benchmark cases, source code, or pack defaults. Draft creation preserves unresolved required changes so `pack validate`, `pack build`, and `pack release-check` cannot pretend the vNext work is complete.

### 40.3 Pack VNext Workbench Extension

The vNext workbench is the execution ledger for a derivative plan. It breaks unresolved changes into explicit work orders and records whether a human completed or skipped each one.

```bash
cambrian pack derivative-workbench latest
cambrian pack workorders auth-bug-core
cambrian pack workorder-show wo-...
cambrian pack workorder-done wo-... --note "Template proposal accepted manually"
```

This improves `repeat_task_improvement_rate` and `reuse_lift` by preserving which accepted improvements were actually executed before a vNext release. Context/template/validation work orders explain movement in `validated_proposal_rate`, `human_intervention_rate`, and `validation_autonomy_rate`. Team/template review work orders protect `team_template_recommendation_hit_rate`, and known-limit updates preserve adoption feedback for `adoption_rate`.

The workbench is not an auto-implementer. It never mutates source code, template semantics, team state, benchmark cases, pack build outputs, or remote registries. Required work orders must be marked done with evidence or a note before release readiness can become true.

### 40.3 Pack vNext local release closure

When required vNext workorders are done, Cambrian can freeze the draft into a local release candidate and then release it to the local catalog with explicit confirmation.

```bash
cambrian pack rc .cambrian/packs/drafts/draft_auth-bug-core-v2.yaml
cambrian pack rc-show latest
cambrian pack release-local latest
cambrian pack release-local latest --confirm
cambrian pack rollout auth-bug-core-v2
cambrian pack rollout-show latest
cambrian pack rollout-apply latest
cambrian pack rollout-apply latest --confirm --install --activate
```

`pack rc` reuses validate/build/release-check and records changelog, release notes, completed workorders, unresolved workorders, proof refs, and lineage from the source pack to vNext.
Open required workorders block RC creation unless `--allow-unresolved` is used, and unresolved candidates remain unsafe for local release.
`pack release-local` previews by default; only `--confirm` updates the local catalog through the existing `publish-local` path.
It never remote-publishes, auto-installs, uninstalls the old pack, mutates source code, or promotes/canaries the pack automatically.

`pack rollout <new-pack>` is the separate safe upgrade path after local release.
It compares previous/current/new pack state, proof/readiness summaries, changelog, and rollback information.
`pack rollout-apply` is preview-only unless `--confirm` is passed; install and activation are separate explicit flags.
Old packs remain installed as rollback candidates, and activation rollback is always an explicit `cambrian pack activate <old-pack>` command.

---

## 41. 최종 요약

Cambrian은 네 개의 loop로 움직인다.

```text
Install Loop:
  AI 일꾼과 작업반을 설치한다.

Work Loop:
  사용자의 AI 작업을 safe proposal까지 보낸다.

Proof Loop:
  결과가 실제로 나은지 증명한다.

Evolution Loop:
  좋은 실험을 다음 기본값으로 승격하고, 나쁜 것은 되돌린다.
```

한 문장으로 요약하면:

> **Cambrian은 AI 일꾼을 설치하고, 일하게 하고, 증명하고, 더 나은 일꾼과 작업복으로 진화시키는 반복 루프 시스템이다.**
