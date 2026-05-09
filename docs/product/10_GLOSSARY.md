# Glossary

## 166R Official Glossary

### AI Company

Cambrian이 프로젝트 안에 설치하는 실행 조직.

### Cambrian

각 프로젝트를 AI 회사로 바꾸는 설치형 AI 회사 런타임.

### Harness

AI 회사가 일하는 운영 체계. 규칙, 금지 범위, 검증 방식, evidence 저장 구조를 포함한다.

### Workforce

프로젝트를 위해 생성된 AI 인력 조직.

### Agent

회사 내 역할을 가진 AI 인력. 예: CEO, CTO, PM, engineering, QA, release manager, domain specialist.

### Skill

인력이 사용하는 반복 가능한 작업 능력. 입력, 출력, 절차, 금지사항, 검증 기준을 가진다.

### Boardroom

CEO/CTO/COO/PM 등 의사결정 회의 구조.

### Authority Mode

사용자가 AI 회사에 부여한 실행 권한 범위. 기본값은 `proposal_only`이고, `full_authority`는 명시 grant가 필요하다.

### Auto Mode

AI 회사가 제품 제작 전 과정을 자동 운영하는 모드. V1은 상태, boardroom, plan, bounded run, evidence 기록을 제공한다.

### Claude / Codex

Cambrian이 사용하는 실행 엔진. Cambrian의 제품 정체성은 특정 모델이 아니라 프로젝트별 AI company runtime이다.

### Preset

선택 가능한 참고 템플릿. 기본 설치물이 아니다. `auth-bug-core`는 seed preset이며 Cambrian의 제품 중심이 아니다.

## 1. 문서 목적

이 문서는 Cambrian에서 사용하는 핵심 용어를 정의한다.

Cambrian은 내부 구조가 깊다.
하지만 외부 사용자에게는 쉬운 언어로 보여야 한다.

따라서 이 문서는 두 가지 목적을 가진다.

1. 내부 개발자가 같은 의미로 같은 용어를 쓰게 한다.
2. 외부 제품 언어와 내부 아키텍처 언어를 구분한다.

가장 중요한 원칙은 다음이다.

> **Cambrian은 각 프로젝트를 AI 회사로 바꾸는 설치형 AI 회사 런타임이다.**

AI 일꾼, 작업반, pack 언어는 compatibility vocabulary다. 현재 제품 중심은 AI Company, Harness, Workforce, Agent, Skill, Authority, Auto Mode다.

---

## 2. Product Language

### Cambrian

각 프로젝트를 AI 회사로 바꾸는 설치형 AI 회사 런타임.

사용자가 제품 목표를 맡기면 Cambrian은 프로젝트 안에 회사 구조, 역할, 스킬, 의사결정 방식, 권한 규칙, 검증 루프, 실행 체계를 설치한다.

현재 표현:
- installable AI company runtime
- AI company per project
- local-first AI company runtime

Legacy compatibility vocabulary:
- AI Worker Installer
- AI 인력 설치기
- AI 작업반 설치 시스템

내부 구성 표현:
- evidence-based harness engineering runtime
- local-first AI workforce runtime

---

### AI Worker Installer

Cambrian의 과거 외부 제품 포지션.

의미:
- 사용자가 직접 에이전트를 설계하지 않아도 됨
- 필요한 AI 일꾼이나 작업반을 고름
- Cambrian이 로컬 프로젝트에 설치함
- 결과를 검증하고 진화시킴

현재 제품 정의에서는 이 표현을 중심 문장으로 쓰지 않는다.
AI Worker Installer는 preset/pack compatibility 문맥에서만 사용한다.

---

### AI Workforce Runtime

Cambrian의 외부/중간 제품 표현.

의미:
- AI 일꾼이 단순 프롬프트가 아니라 runtime 안에서 설치·배치·검증·개선되는 구조
- 여러 worker/team/template가 함께 운영됨
- 결과는 metrics와 benchmark로 증명됨

---

### Harness

AI 회사가 특정 프로젝트에서 일하는 운영 체계.

Harness는 규칙, 금지 범위, 검증 방식, evidence 저장 구조를 포함한다.

Harness가 포함할 수 있는 것:
- project context
- policy
- team
- template
- memory
- bridge contract
- validation habit
- benchmark evidence

---

### Harness Engineering

AI가 더 잘 일하도록 작업복을 설계하고, 검증하고, 진화시키는 활동.

Cambrian의 내부 정체성은 harness engineering이다.
하지만 제품 정체성은 더 상위 개념인 installable AI company runtime이다.

현재 외부 표현:
- 프로젝트 안에 AI 회사를 설치한다
- AI 회사가 제품을 계획, 실행, 검증, 진화한다
- Claude/Codex를 실행 엔진으로 사용한다

---

## 3. Worker / Agent Terms

### Worker

외부 사용자에게 보여줄 수 있는 쉬운 표현.
특정 일을 맡는 AI 일꾼.

예:
- bug-fix worker
- review worker
- test worker
- research worker

Worker는 사용자 친화적인 말이다.

---

### Agent

내부 runtime에서의 실행 단위 또는 역할 단위.

Agent는 capability, role, history, passport를 가질 수 있다.

예:
- bug-fix-agent
- regression-test-agent
- review-agent

외부에서는 agent보다 worker라는 표현이 더 쉽다.

---

### Agent Passport

agent의 이력과 능력, 사용 결과를 기록하는 로컬 문서.

포함 가능:
- capabilities
- source kind
- prior usage
- review history
- import/export provenance
- local success/failure hints

Agent passport는 “이 일꾼의 경력서”에 가깝다.

---

### Lead Agent

작업의 중심이 되는 agent.

예:
- bug-fix-agent가 auth bug 작업의 lead가 될 수 있음

---

### Support Agent

lead agent를 보조하는 agent.

예:
- regression-test-agent
- review-agent

Support agent는 validation, review, test-first practice를 강화하는 데 중요하다.

---

## 4. Pack Terms

### Pack

설치 가능한 운영 단위.

Pack은 단순 파일 묶음이 아니라, AI 일꾼을 프로젝트에 배치하기 위한 설치 가능한 package다.

종류:
- worker pack
- team pack
- template pack
- lane pack

---

### Worker Pack

하나 또는 소수의 worker/agent를 설치하는 pack.

예:
- auth-bug-fix-worker
- review-worker
- regression-test-worker

초기 사용자에게는 Worker Pack보다 Team Pack이나 Lane Pack이 더 이해하기 쉬울 수 있다.

---

### Team Pack

실제로 함께 일하는 agent 조합을 설치하는 pack.

예:
- auth-bug-team
- safe-patch-team
- review-heavy-team

Team Pack은 lead/support 구조를 포함한다.

---

### Template Pack

프로젝트 운영 기본값을 설치하는 pack.

포함 가능:
- project defaults
- safety defaults
- agent defaults
- team defaults
- policy defaults
- context defaults
- fit hints

예:
- auth-bug-template
- safe-patch-template

---

### Lane Pack

특정 작업군을 바로 수행할 수 있게 worker, team, template, policy, benchmark를 묶은 가장 큰 설치 단위.

초기 제품에서 가장 중요한 판매 단위.

예:
- auth-bug-core

Lane Pack은 사용자가 이렇게 이해해야 한다.

> “로그인/인증 버그를 안전하게 고치는 작업반을 설치한다.”

---

### Install Manifest

웹 또는 catalog에서 제공하는 pack 설치 정의 파일.

로컬 Cambrian runtime은 install manifest를 읽고 pack을 설치한다.

중요:
- manifest는 실행 명령이 아니다.
- source code를 수정하지 않는다.
- auto apply 하지 않는다.
- local library에 등록하는 입력이다.

---

## 5. Team / Template / Lane Terms

### Team

agent들의 조합.

Team은 lead agent와 support agents를 가질 수 있다.

예:
```text
auth-bug-team
  lead: bug-fix-agent
  support:
    - regression-test-agent
    - review-agent
```

---

### Team Preset

저장된 team 구성.

예:

* auth-bug-team
* safe-patch-team

Team preset은 재사용 가능해야 한다.

---

### Active Team

현재 프로젝트 또는 session에서 사용 중인 team.

주의:

* active team 변경은 명시적이어야 한다.
* 추천되었다고 자동 active가 되면 안 된다.

---

### Template

프로젝트 운영 기본값 묶음.

Template은 agent/team보다 더 넓은 운영 기본값을 가진다.

포함 가능:

* project defaults
* safety defaults
* agent defaults
* team defaults
* policy defaults
* context defaults
* fit hints

---

### Current Template

현재 프로젝트에 실제 적용된 template marker.

주의:

* lane default template와 current template는 다르다.
* lane default가 바뀌어도 current template가 자동으로 바뀌면 안 된다.

---

### Lane

특정 작업군과 그 작업군에 맞는 운영 기본값의 묶음.

현재 strongest lane:

```text
Python + pytest + narrow auth/login bug fix
```

Lane은 제품 증명의 중심 단위다.

---

### Strongest Lane

현재 Cambrian이 가장 잘할 수 있다고 공식적으로 인정하는 좁은 작업 영역.

현재 strongest lane:

* Python
* pytest
* auth/login bug fix
* narrow-scope
* test-first
* review-support

---

### Lane Playbook

strongest lane의 운영 기본값을 관리하는 source-of-truth.

포함 가능:

* stable default template
* backup templates
* retired templates
* active canary
* queued challengers

중요:

* lane playbook은 future-facing default다.
* current runtime을 자동으로 바꾸지 않는다.

---

## 6. Bridge Terms

### Bridge

Cambrian과 외부 AI를 연결하는 model-agnostic entry layer.

Bridge는 provider-specific API에 의존하지 않는다.
Claude, GPT, Cursor, local model 등 어떤 AI에도 packet을 붙여넣을 수 있어야 한다.

---

### Bridge Packet

AI에 전달하는 Cambrian 작업 패킷.

포함:

* request
* project harness summary
* team/agent summary
* policy hints
* memory summary
* response contract

---

### Bridge Reply

AI가 Cambrian response contract에 맞춰 돌려준 structured reply.

가능한 response_kind:

* patch_candidate
* analysis
* review
* plan

---

### Response Contract

AI가 어떤 형식으로 답해야 하는지 정의하는 계약.

목표:

* 자유 텍스트를 줄임
* Cambrian이 reply를 ingest하고 다음 artifact로 연결할 수 있게 함

---

### Patch Candidate

AI가 제안한 patch 후보.

필수 필드 예:

* target_path
* old_text
* new_text
* reason

Patch candidate는 바로 apply되지 않는다.
먼저 patch intent draft로 handoff되고 validate되어야 한다.

---

### Analysis Brief

analysis reply를 안전한 로컬 운영 artifact로 변환한 것.

용도:

* 추천 파일
* 추천 테스트
* 주의점
* context hint 생성

---

### Review Note

review reply를 안전한 로컬 운영 artifact로 변환한 것.

용도:

* caution
* positive/negative review signal
* next action hint

Human note와는 구분한다.
AI-derived artifact다.

---

### Plan Record

plan reply를 단계형 운영 기록으로 변환한 것.

Plan record는 checklist로 handoff될 수 있다.

---

### Bridge Checklist

plan_record를 사람이 따라갈 수 있는 step tracking artifact로 변환한 것.

상태:

* todo
* done
* blocked
* skipped

Checklist는 실행 자동화가 아니다.
사람이 진행 상태를 표시하는 운영판이다.

---

### Bridge Fast Path

prepare → paste/ingest → auto-route → next command까지 이어지는 daily-use bridge path.

목표:

* old/new 재입력 감소
* patch_candidate는 continue --validate로 연결
* analysis/plan/review도 길을 잃지 않게 함

---

## 7. Work / Patch Terms

### Request

사용자가 Cambrian에 넣는 작업 요청.

예:

```text
로그인 에러 수정해
```

---

### Request Class

요청 유형.

예:

* bug_fix
* docs
* review
* refactor
* unknown

현재 strongest lane에서는 `bug_fix`가 가장 중요하다.

---

### Session

하나의 작업 흐름 상태.

포함 가능:

* request
* stage
* selected context
* lead agent
* team/template context
* bridge context
* metrics_context

---

### Patch Intent

패치 의도 또는 draft.

Patch intent는 proposal보다 이전 단계다.

Bridge-origin patch intent는 `bridge_prefill`을 가질 수 있다.

---

### Bridge Prefill

AI patch_candidate에서 가져온 old_text / new_text / reason을 patch intent draft에 미리 채우는 구조.

목표:

* 사용자가 old/new를 다시 입력하지 않게 함

---

### Proposal

실제 patch proposal.

Proposal은 validation될 수 있다.

---

### Validated Proposal

검증을 통과한 proposal.

Cambrian의 북극성 지표는 validated proposal rate다.

중요:

* validated proposal은 apply와 다르다.
* apply는 별도 explicit action이다.

---

### Apply

proposal을 실제 project source에 반영하는 action.

Apply는 explicit이어야 한다.
Cambrian이 몰래 auto apply하면 안 된다.

---

### Adoption

적용된 결과를 최종적으로 받아들이는 decision.

Adoption도 explicit이어야 한다.

---

## 8. Evidence / Proof Terms

### Metrics

Cambrian의 실사용 성과 지표.

핵심:

* validated_proposal_rate
* human_intervention_rate
* validation_autonomy_rate
* reuse_lift
* repeat_task_improvement_rate

---

### Weekly Metrics

주간 단위 metrics report.

명령:

```bash
cambrian metrics week
```

---

### Benchmark Case

반복 측정 가능한 개별 작업 사례.

예:

```text
login-bug
```

---

### Benchmark Workset

benchmark case 묶음.

현재 canonical workset:

```text
auth-bug-workset
```

---

### Benchmark Result

case와 mode별 결과.

mode 예:

* raw_ai
* bridge_only
* cambrian_guided
* cambrian_full
* manual_baseline

---

### Baseline

과거 기준점.

Baseline은 현재 결과가 좋아졌는지 비교하기 위한 snapshot이다.

---

### Compare

현재 benchmark report와 baseline을 비교하는 report.

verdict:

* improved
* mixed
* regressed
* insufficient_data

---

### Replay

같은 benchmark case/workset을 현재 Cambrian 상태로 다시 돌려보는 safe proof run.

목표:

* 어디까지 자동으로 가는지 확인
* source mutation 없이 validated proposal boundary까지 측정

---

### Autonomy Board

workset replay 결과를 모아 automation stage를 보는 board.

보여줄 것:

* stage distribution
* stop reasons
* validation autonomy
* human intervention estimate

---

### Bottleneck

Cambrian이 자동화나 validation에서 자주 멈추는 원인.

예:

* ambiguous_context_selection
* missing_patch_candidate
* validation_failure_cluster
* review_support_gap

---

### Proof Pack

metrics, benchmark, compare, autonomy, bottleneck을 한 장으로 묶은 증명 보고서.

질문:

> Cambrian이 strongest lane에서 실제로 이기고 있는가?

---

## 9. Evolution Terms

### Improvement Cycle

한 번에 하나의 병목을 선택하고, 가설을 세우고, 개선 전후를 비교하는 운영 cycle.

원칙:

* one bottleneck per week
* one hypothesis
* one intervention
* before/after verdict

---

### Intervention

선택된 병목을 줄이기 위한 작고 되돌릴 수 있는 실험 overlay.

예:

* strengthen_context_hints
* increase_review_support
* narrow_scope_defaults
* strengthen_test_practice

Intervention은 source code를 수정하지 않는다.

---

### Active Overlay

현재 적용 중인 실험 overlay.

한 번에 하나만 active여야 한다.

---

### Persistent Overlay

improved로 평가되어 keep된 interventions를 합친 장기 learning overlay.

Persistent overlay는 local learning이다.

---

### Keep

성공한 intervention을 지속 학습으로 채택하는 decision.

기본적으로 improved verdict가 필요하다.

---

### Dismiss

실험 또는 suggestion을 유지하지 않겠다는 decision.

Dismiss는 실패가 아니라 운영 판단이다.

---

### Template Evolution

persistent overlay에서 얻은 좋은 학습을 reusable template defaults로 승격하는 과정.

예:

* test_first_practice 활성화
* narrow_change_scope 활성화
* preferred context path 추가
* support agent 추가

---

## 10. Qualification / Canary Terms

### Template Fork

template를 local derivative로 복제하는 것.

주로 imported template를 직접 mutate하지 않고 로컬에서 진화시키기 위해 사용한다.

---

### Local Derivative

fork로 생성된 local template.

Local derivative는 evolve, qualify, canary, promote될 수 있다.

---

### Lineage

template의 parent/root 관계.

예:

```text
imported-auth-bug-template
→ auth-bug-template-local
→ auth-bug-template-local-v2
```

---

### Qualification

candidate template가 parent/reference template보다 나은지 같은 workset에서 비교하는 proof.

verdict:

* candidate_stronger
* mixed
* regressed
* inconclusive

---

### Qualification Decision

qualification 결과를 accept/dismiss하는 운영 decision.

---

### Qualification Adoption

qualification accept로 실제 library standing이나 lane default가 바뀐 adoption snapshot.

Rollback의 근거가 된다.

---

### Qualification Rollback

qualification adoption을 되돌리는 explicit rollback.

중요:

* qualification proof는 삭제하지 않는다.
* 운영 상태만 복구한다.

---

### Canary

stable default로 바로 올리기 전 controlled alternative로 stage된 template.

Canary는 default가 아니다.
추천/부트스트랩에서 더 잘 보이는 대안이다.

---

### Canary Stage

qualified candidate를 canary로 세우는 action.

Stable default는 유지된다.

---

### Canary Report

canary의 burn-in evidence report.

verdict:

* promote_ready
* keep_canary
* clear_canary
* insufficient_data

---

### Canary Ledger

canary가 얼마나 노출/선택/스킵/리플레이/검증되었는지 기록하는 ledger.

예:

* surfaced_count
* selected_count
* skipped_count
* replay_validated_count

---

### Canary Outcome Attribution

canary가 선택된 뒤 실제로 validated/adopted/intervention 감소로 이어졌는지 연결하는 evidence.

핵심:

* selected_then_validated_count
* selected_then_adopted_count
* selected_human_intervention_rate
* selected_validation_autonomy_rate

---

### Canary Review

canary evidence의 freshness를 평가하는 review.

status:

* fresh
* warming
* review_due
* stale
* expired
* insufficient_data

---

### Champion

현재 stable default template.

---

### Challenger

stable default를 대체할 후보 template.

종류:

* active canary
* queued challenger

---

### Challenger Queue

다음 canary로 태워볼 template 후보군.

---

### Challenge Board

stable default, active canary, queued challengers를 함께 보는 board.

---

### Challenge Matrix

stable default, active canary, queued challengers를 같은 workset에서 replay 비교하는 evidence matrix.

목표:

* next_best_challenger를 evidence-backed로 고름

---

## 11. Lane Governance Terms

### Stable Default

현재 lane의 future-facing 기본 template.

주의:

* current applied template와 다르다.
* stable default가 바뀌어도 현재 project runtime이 자동으로 바뀌면 안 된다.

---

### Backup Template

stable default의 대안으로 유지되는 template.

---

### Retired Template

보존은 하지만 기본 추천하지 않는 template.

삭제가 아니다.

---

### Lane Default Switch

stable default template를 다른 template로 바꾸는 operation.

주의:

* future-facing default 변경이다.
* current project applied template 변경이 아니다.

---

### Lane Default Rollback

lane default switch를 adoption snapshot 기준으로 되돌리는 operation.

---

## 12. State Terms

### Source of Truth

명시적 decision 또는 definition으로 관리되는 상태.

예:

* templates.yaml
* teams.yaml
* lane/playbook.yaml
* improvement/decisions.yaml
* qualification_decisions.yaml

---

### Derived Artifact

계산, 집계, 증명, review 결과로 생성되는 artifact.

예:

* metrics report
* proof pack
* canary report
* benchmark compare
* autonomy board

Derived artifact는 source-of-truth를 직접 바꾸면 안 된다.

---

### Current Runtime State

현재 프로젝트에서 진행 중인 작업 상태.

예:

* sessions
* requests
* patch intents
* proposals
* bridge replies

---

### Future Default State

다음 추천, bootstrap, lane behavior에 영향을 주는 상태.

예:

* lane playbook
* persistent overlay
* library decisions
* qualification decisions

Current runtime state와 future default state는 반드시 분리한다.

---

### Provenance

어떤 artifact가 어디서 왔는지 추적하는 정보.

Cambrian은 중요한 모든 상태에 provenance를 남겨야 한다.

---

## 13. Metric Terms

### validated_proposal_rate

전체 요청 중 validated proposal까지 간 비율.

Cambrian의 북극성.

---

### adoption_rate

validated proposal 중 실제 채택된 비율.

---

### regression_free_apply_rate

apply 후 regression 없이 테스트가 통과한 비율.

---

### median_time_to_validated_proposal

요청 시작부터 validated proposal까지 걸린 중간 시간.

---

### human_intervention_rate

사람이 중간에 직접 크게 개입한 요청 비율.

---

### validation_autonomy_rate

사람이 다시 쓰지 않아도 validation까지 도달한 요청 비율.

---

### lead_agent_hit_rate

처음 선택한 lead agent가 최종 결과까지 유효했던 비율.

---

### team_template_recommendation_hit_rate

추천된 team/template가 실제 accepted/used/applied/bootstrap된 비율.

---

### reuse_lift

memory/team/template/policy/bridge/persistent learning reuse가 없는 경우 대비 성공률 상승분.

---

### repeat_task_improvement_rate

같은 작업군에서 이전 baseline 대비 성과가 좋아진 정도.

---

## 14. Terms to Avoid in External Copy

아래 용어는 내부 문서나 개발자용 문서에서는 가능하지만, 외부 세일즈 문구에서는 조심해야 한다.

* harness engineering substrate
* orchestration fabric
* policy overlay topology
* multi-agent runtime abstraction
* artifact lineage graph

대신 외부에서는 아래 표현을 쓴다.

* AI 일꾼 설치
* AI 작업반 고용
* 검증된 작업복
* 내 AI에 바로 붙이기
* AI를 바로 일하게 만들기

---

## Required Term Index

아래 항목은 docs consistency가 drift를 잡기 위해 요구하는 canonical heading이다.

## harness

See `Harness`.

## worker

See `Worker`.

## agent

See `Agent`.

## worker pack

See `Worker Pack`.

## team pack

See `Team Pack`.

## template pack

See `Template Pack`.

## lane pack

See `Lane Pack`.

## bridge

See `Bridge`.

## canary

See `Canary`.

## qualification

See `Qualification`.

## proof pack

See `Proof Pack`.

## improvement cycle

See `Improvement Cycle`.

## persistent overlay

See `Persistent Overlay`.

---

## 15. Final Summary

Cambrian의 용어는 두 층으로 나뉜다.

외부적으로는:

> **AI 일꾼을 설치하고 작업반을 고용하는 제품**

내부적으로는:

> **하네스, evidence, benchmark, canary, rollback으로 AI 작업을 검증하고 진화시키는 local runtime**

이 두 층을 혼동하지 않는 것이 중요하다.

한 문장으로 요약하면:

> **Cambrian은 AI를 일꾼처럼 설치하고, 그 일꾼의 실제 성과를 증거로 검증하며, 좋은 결과를 다음 기본값으로 진화시키는 시스템이다.**
