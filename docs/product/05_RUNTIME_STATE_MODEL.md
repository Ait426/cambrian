# Runtime State Model

## 1. 문서 목적

이 문서는 Cambrian의 `.cambrian/` 상태 모델을 정의한다.

Cambrian은 local-first, file-first runtime이다.
따라서 중요한 운영 상태는 로컬 프로젝트의 `.cambrian/` 아래에 artifact로 남아야 한다.

이 문서는 다음 질문에 답한다.

- `.cambrian/` 안에는 어떤 종류의 상태가 있는가?
- 어떤 파일이 source-of-truth이고, 어떤 파일이 derived artifact인가?
- current runtime state와 future default state는 어떻게 구분되는가?
- bridge, benchmark, improvement, template, lane state는 어떤 경계를 가지는가?
- 어떤 상태가 source/project file을 수정할 수 있고, 어떤 상태는 절대 수정하면 안 되는가?

이 문서의 핵심 원칙은 다음이다.

> **Cambrian은 모든 중요한 판단과 변화의 provenance를 file-first artifact로 남긴다.
> 단, source-of-truth와 derived artifact를 반드시 분리한다.**

---

## 2. 최상위 상태 구조

Cambrian의 로컬 상태는 기본적으로 `.cambrian/` 아래에 저장된다.

권장 구조는 다음과 같다.

```text
.cambrian/
  project.yaml
  rules.yaml
  skills.yaml
  profile.yaml

  harness/
  agents/
  templates/
  lane/
  bridge/
  benchmarks/
  metrics/
  improvement/
  notes/
  memory/
  sessions/
  requests/
  patch_intents/
  proposals/
  summary/
```

각 디렉토리는 서로 다른 역할을 가진다.

| 영역 | 역할 |
| --- | --- |
| project/rules/skills/profile | 프로젝트 기본 source-of-truth |
| harness | 현재 하네스 상태와 정책 |
| agents | agent/team/staffing library |
| templates | template library, evolution, qualification, canary |
| lane | strongest lane, lane playbook, challenger state |
| bridge | AI entry packet/reply/handoff/materialization |
| benchmarks | benchmark workset, replay, compare, proof |
| metrics | weekly metrics and KPI reports |
| improvement | bottleneck cycle, interventions, persistent learning |
| notes | human-authored project notes |
| memory | project lessons, hygiene, overrides |
| sessions/requests | active and historical work state |
| patch_intents/proposals | patch flow artifacts |
| summary | usage and project summaries |

공식 상태 카테고리 alias는 runtime state, library state, bridge state, metrics/benchmark/proof state, improvement state, lane playbook state다.

---

## 3. Source-of-Truth vs Derived Artifact

Cambrian은 많은 파일을 만든다.
모든 파일이 같은 권위를 가지면 안 된다.

### 3.1 Source-of-truth

source-of-truth는 사람이 명시적으로 설정하거나, 운영 결정으로 채택한 상태다.

예:

```text
.cambrian/project.yaml
.cambrian/rules.yaml
.cambrian/skills.yaml
.cambrian/profile.yaml
.cambrian/templates/templates.yaml
.cambrian/templates/library_decisions.yaml
.cambrian/templates/qualification_decisions.yaml
.cambrian/lane/playbook.yaml
.cambrian/improvement/decisions.yaml
.cambrian/improvement/persistent_overlay.yaml
.cambrian/agents/teams.yaml
.cambrian/agents/staffing_decisions.yaml
```

source-of-truth 변경은 반드시 explicit command를 통해 일어나야 한다.

예:

* `template evolve-accept`
* `template qualify-accept`
* `improve keep`
* `team apply`
* `agent hire`
* `template fork`

### 3.2 Derived artifact

derived artifact는 계산, 집계, 비교, 검증, 증명을 위해 생성되는 파일이다.

예:

```text
.cambrian/metrics/weekly_*.yaml
.cambrian/benchmarks/reports/*.yaml
.cambrian/benchmarks/compares/*.yaml
.cambrian/benchmarks/proof/*.yaml
.cambrian/templates/canary_reports/*.yaml
.cambrian/templates/canary_ledgers/*.yaml
.cambrian/templates/canary_outcomes/
.cambrian/templates/canary_reviews/
.cambrian/bridge/reviews/
.cambrian/bridge/materialized/
.cambrian/bridge/checklists/
```

derived artifact는 source-of-truth를 직접 바꾸면 안 된다.
source-of-truth를 바꾸려면 별도의 explicit accept/keep/promote/apply 명령이 필요하다.

---

## 4. Current Runtime State vs Future Default State

Cambrian에서 가장 중요한 경계 중 하나다.

### 4.1 Current runtime state

current runtime state는 지금 이 프로젝트에서 실제 진행 중인 작업 상태다.

예:

```text
.cambrian/sessions/
.cambrian/requests/
.cambrian/patch_intents/
.cambrian/proposals/
.cambrian/bridge/replies/
.cambrian/bridge/handoffs/
```

이 상태는 현재 작업을 설명한다.

* 지금 어떤 request가 진행 중인가
* 어떤 session이 active인가
* 어떤 patch intent가 준비됐는가
* validation까지 갔는가
* bridge reply가 어떤 session에 연결됐는가

### 4.2 Future default state

future default state는 다음 추천, 다음 bootstrap, 다음 template selection에 영향을 주는 상태다.

예:

```text
.cambrian/lane/playbook.yaml
.cambrian/templates/library_decisions.yaml
.cambrian/templates/qualification_decisions.yaml
.cambrian/templates/qualification_stages.yaml
.cambrian/improvement/persistent_overlay.yaml
```

이 상태는 현재 실행 중인 session을 자동으로 바꾸면 안 된다.
예를 들어 lane default template가 바뀌어도, 현재 프로젝트에 이미 적용된 template가 자동으로 바뀌면 안 된다.

### 4.3 원칙

> **current runtime은 지금의 작업 상태이고, future default는 다음 추천과 설치의 기본값이다.
> 둘을 섞으면 안 된다.**

---

## 5. Project Base State

프로젝트 기본 상태는 `.cambrian/`의 가장 핵심 source-of-truth다.

```text
.cambrian/project.yaml
.cambrian/rules.yaml
.cambrian/skills.yaml
.cambrian/profile.yaml
```

### 5.1 project.yaml

프로젝트의 기본 identity를 담는다.

예:

* project name
* project type
* root path
* initialized state
* bootstrap origin

### 5.2 rules.yaml

프로젝트 운영 규칙을 담는다.

예:

* source mutation policy
* explicit apply/adoption requirement
* validation expectation
* safety defaults

### 5.3 skills.yaml

프로젝트에서 필요한 작업 능력 또는 skill hints를 담는다.

예:

* bug fix
* review
* test practice
* docs update

### 5.4 profile.yaml

프로젝트 감지 결과와 high-level summary를 담는다.

예:

* stack
* test command
* primary use cases
* detected tooling

이 파일들은 일반적으로 source-of-truth에 가깝다.
다만 일부 필드는 detection 결과일 수 있으므로 schema에서 구분이 필요하다.

---

## 6. Harness State

하네스 상태는 프로젝트 운영 환경을 표현한다.

권장 위치:

```text
.cambrian/harness/
  profile.yaml
  policy_overlay.yaml
  decisions.yaml
  evolution_suggestions.yaml
```

### 6.1 harness/profile.yaml

현재 하네스의 snapshot이다.

예:

* project type
* stack
* test command
* primary use cases
* active agents
* safety mode

### 6.2 harness/decisions.yaml

사람이 명시적으로 accept/dismiss한 harness decision이다.

예:

* strengthen_test_practice
* narrow_change_scope
* increase_review_support
* promote_request_focus

### 6.3 harness/policy_overlay.yaml

decisions.yaml에서 파생된 derived policy snapshot이다.

예:

* test_first_practice: true
* narrow_change_scope: true
* preferred_support_agents

이 파일은 derived artifact다.
원천은 decisions.yaml이다.

### 6.4 evolution_suggestions.yaml

하네스 개선 제안이다.
자동 적용되면 안 된다.

---

## 7. Agent and Team State

agent와 team 관련 상태는 `.cambrian/agents/` 아래에 둔다.

권장 구조:

```text
.cambrian/agents/
  registry.yaml
  passports/
  imported/
  teams.yaml
  team_decisions.yaml
  team_policy_overlay.yaml
  staffing_decisions.yaml
  dispatch_board.yaml
  trials/
  team_trials/
```

### 7.1 registry.yaml

사용 가능한 agent와 active/equipped 상태를 담는다.

### 7.2 passports/

agent의 local history와 capability record를 담는다.

### 7.3 imported/

외부에서 가져온 agent passport를 보관한다.

### 7.4 teams.yaml

저장된 team preset의 source-of-truth다.

### 7.5 team_decisions.yaml

team accept/dismiss/apply/backup/watch decision을 담는다.

### 7.6 team_policy_overlay.yaml

team_decisions.yaml에서 파생된 derived overlay다.

### 7.7 staffing_decisions.yaml

agent-level hire/fire/keep/prefer decision을 담는다.

### 7.8 dispatch_board.yaml

현재 agent staffing 상황에 대한 derived board다.

### 7.9 trials / team_trials

agent 또는 team의 shadow trial 결과다.
이 파일은 증거 artifact이며, 자동 hire/fire를 의미하지 않는다.

---

## 8. Template State

template 상태는 Cambrian의 재사용성과 진화성을 담당한다.

권장 구조:

```text
.cambrian/templates/
  templates.yaml
  current_template.yaml
  bootstrap_record.yaml
  bootstrap_choice.yaml

  recommendation.yaml
  diff_report.yaml
  decisions.yaml
  reviews/

  exports/
  imported/
  forks/
  lineage.yaml

  evolution_proposals/
  evolution_decisions.yaml

  qualifications/
  qualification_decisions.yaml
  qualification_adoptions/
  qualification_rollbacks/

  qualification_stages.yaml
  canary_reports/
  canary_ledgers/
  canary_events/
  canary_outcomes/
  canary_reviews/

  challengers.yaml
  challenge_boards/
  challenge_matrices/
```

### 8.1 templates.yaml

template library의 source-of-truth다.

포함:

* template name
* project defaults
* safety defaults
* agent defaults
* team defaults
* policy defaults
* optional context defaults
* source_kind
* lineage metadata

### 8.2 current_template.yaml

현재 프로젝트에 적용된 template marker다.
이 파일이 있다면 current runtime/configuration 의미를 갖는다.

중요:

* lane default가 바뀐다고 current_template이 자동으로 바뀌면 안 된다.

### 8.3 bootstrap_record.yaml

프로젝트가 어떤 template로 bootstrap됐는지 기록한다.

### 8.4 bootstrap_choice.yaml

init/start 시 추천, 선택, skip 여부를 기록한다.

### 8.5 recommendation.yaml

template recommendation derived artifact다.

### 8.6 diff_report.yaml

current project와 template 간 preview/diff artifact다.

### 8.7 reviews/

template 적용 전 review artifact다.

### 8.8 decisions.yaml

template accept/dismiss decision이다.
apply를 자동으로 의미하지 않는다.

### 8.9 lineage.yaml / forks/

template fork 관계를 저장한다.

### 8.10 evolution_proposals/

kept improvement를 template evolution으로 승격하는 proposal이다.

### 8.11 qualifications/

candidate template와 parent/reference template를 benchmark replay로 비교한 proof artifact다.

### 8.12 qualification_decisions.yaml

qualification 결과를 accept/dismiss한 source-of-truth decision이다.

### 8.13 qualification_adoptions/

qualification accept 시점의 before/after snapshot이다.
rollback의 근거가 된다.

### 8.14 qualification_rollbacks/

qualification adoption을 되돌린 기록이다.

### 8.15 qualification_stages.yaml

canary stage 상태다.
stable default를 바꾸지 않는 중간 운영 상태다.

### 8.16 canary_* artifacts

canary의 evidence를 저장한다.

* canary_reports: burn-in verdict
* canary_events: exposure/selection/replay event
* canary_ledgers: event aggregation
* canary_outcomes: selected-to-outcome attribution
* canary_reviews: freshness / review cadence

### 8.17 challengers.yaml

queued challenger templates를 저장한다.

### 8.18 challenge_boards / challenge_matrices

champion-challenger board와 replay matrix를 저장한다.

---

## 9. Lane State

Alias: lane playbook state.

lane 상태는 strongest lane과 future-facing default를 관리한다.

권장 구조:

```text
.cambrian/lane/
  profile.yaml
  playbook.yaml
```

### 9.1 profile.yaml

현재 프로젝트가 strongest lane과 얼마나 맞는지 나타내는 derived profile이다.

예:

* lane_id
* label
* status: strong / partial / outside
* default team/template/workset
* reasons
* cautions

### 9.2 playbook.yaml

lane 운영 source-of-truth다.

포함:

* stable default template
* backup templates
* retired templates
* active canary template
* canary stage id
* queued challenger relation if needed

중요:

* lane playbook은 future-facing default다.
* current project runtime을 자동으로 바꾸면 안 된다.

---

## 10. Bridge State

Bridge는 AI entry layer다.

권장 구조:

```text
.cambrian/bridge/
  packets/
  replies/
  reviews/
  handoffs/
  links.yaml
  materialized/
  context_hints/
  checklists/
  fastpath/
```

### 10.1 packets/

AI에 붙여넣는 Cambrian packet이다.

포함:

* request
* harness summary
* team/agent summary
* policy hints
* memory summary
* response contract

### 10.2 replies/

AI가 반환한 structured reply다.

response_kind:

* patch_candidate
* analysis
* review
* plan

### 10.3 reviews/

reply usability review다.

### 10.4 handoffs/

reply를 다음 workflow로 넘긴 기록이다.

예:

* patch_candidate → patch intent draft
* analysis_brief → context hint
* plan_record → checklist

### 10.5 links.yaml

packet / reply / review / handoff / session / patch_intent 간 lineage를 저장한다.

### 10.6 materialized/

non-patch reply를 AI-derived local operating artifact로 변환한 결과다.

예:

* analysis_brief
* review_note
* plan_record

### 10.7 context_hints/

analysis_brief에서 나온 file/test hints다.

### 10.8 checklists/

plan_record에서 생성된 step tracking artifact다.

### 10.9 fastpath/

prepare → paste/ingest → auto-route 결과를 저장한다.

---

## 11. Benchmark and Evidence State

Alias: metrics/benchmark/proof state.

benchmark와 evidence는 Cambrian의 proof layer다.

권장 구조:

```text
.cambrian/benchmarks/
  cases/
  worksets/
  results/
  reports/
  baselines/
  compares/
  replays/
  workset_replays/
  autonomy_boards/
  bottlenecks/
  proof/
```

### 11.1 cases/

반복 가능한 benchmark case다.

### 11.2 worksets/

case 묶음이다.

### 11.3 results/

case/mode별 결과다.

mode 예:

* raw_ai
* bridge_only
* cambrian_guided
* cambrian_full
* manual_baseline

### 11.4 reports/

workset 단위 benchmark report다.

### 11.5 baselines/

과거 기준점이다.

### 11.6 compares/

current vs baseline 비교다.

### 11.7 replays/

case-level safe replay 결과다.

### 11.8 workset_replays/

workset-level safe replay 결과다.

### 11.9 autonomy_boards/

workset 전체 autonomy evidence board다.

### 11.10 bottlenecks/

autonomy blocker와 improvement suggestion이다.

### 11.11 proof/

한 장짜리 proof pack이다.

---

## 12. Metrics State

weekly metrics는 `.cambrian/metrics/` 아래에 저장된다.

권장 구조:

```text
.cambrian/metrics/
  weekly_YYYY_WW.yaml
  latest.yaml
```

핵심 지표:

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

metrics는 source-of-truth가 아니라 derived report다.
다만 product decision의 중요한 evidence가 된다.

---

## 13. Improvement State

improvement는 bottleneck을 줄이는 운영 루프다.

권장 구조:

```text
.cambrian/improvement/
  cycles/
  interventions/
  overlay.yaml
  persistent_overlay.yaml
  decisions.yaml
  index.yaml
```

### 13.1 cycles/

한 주에 하나의 bottleneck을 잡는 improvement cycle이다.

### 13.2 interventions/

cycle에서 나온 reversible intervention pack이다.

### 13.3 overlay.yaml

현재 active experiment overlay다.

한 번에 하나만 active여야 한다.

### 13.4 persistent_overlay.yaml

improved로 판정되어 keep된 interventions를 합친 장기 overlay다.

### 13.5 decisions.yaml

keep/dismiss decision source-of-truth다.

---

## 14. Notes and Memory State

notes와 memory는 구분해야 한다.

```text
.cambrian/notes/
.cambrian/memory/
```

### 14.1 notes

human-authored project notes다.
사용자가 남긴 운영 판단, friction, caution이다.

### 14.2 memory

project lesson과 hygiene state다.

예:

* lessons
* overrides
* hygiene
* stale/conflicting/suppressed states

중요:

* AI-derived review_note와 human notes를 섞지 않는다.
* bridge materialized review_note는 `.cambrian/bridge/materialized/`에 둔다.

---

## 15. Session and Request State

작업 진행 상태는 sessions와 requests에 저장된다.

```text
.cambrian/sessions/
.cambrian/requests/
```

### 15.1 sessions

작업 흐름의 상태다.

포함 가능:

* session id
* request
* stage
* lead agent
* support agents
* bridge context
* policy context
* team policy context
* template context
* metrics_context

### 15.2 requests

개별 request artifact다.

포함 가능:

* original request
* inferred request class
* context candidates
* selected source/test
* policy hints
* metrics context

### 15.3 metrics_context

request/session에는 최소 계측 필드가 있어야 한다.

예:

```yaml
metrics_context:
  request_class: bug_fix
  source_mode: bridge_fastpath
  autonomy_mode: safe

  reused_context:
    memory: true
    harness_policy: true
    team_policy: false
    template: true
    bridge: true

  human_interventions:
    source_selected_manually: false
    test_selected_manually: false
    old_text_overridden: false
    new_text_overridden: false

  milestones:
    diagnosed_at: ...
    patch_intent_ready_at: ...
    proposal_validated_at: ...

  results:
    validated_proposal: true
    adoption_succeeded: false
    apply_tests_passed: null
```

이 필드는 weekly metrics와 benchmark proof의 근거가 된다.

---

## 16. Patch Intent and Proposal State

patch 관련 artifact는 안전 경계를 분리한다.

```text
.cambrian/patch_intents/
.cambrian/proposals/
```

### 16.1 patch_intents/

패치 의도 또는 draft다.

bridge-origin patch intent는 다음을 가질 수 있다.

```yaml
bridge_prefill:
  enabled: true
  source_bridge_reply_ref: ...
  target_path: ...
  old_text: ...
  new_text: ...
  reason: ...
```

### 16.2 proposals/

patch proposal / validation 결과다.

중요:

* proposal validated는 apply와 다르다.
* apply/adoption은 별도 explicit action이어야 한다.

---

## 17. State Mutation Policy

Cambrian에서 상태 변경은 아래 원칙을 따른다.

### 17.1 Derived artifact creation is safe

다음은 source/project files를 바꾸지 않는다.

* metrics report
* benchmark report
* proof pack
* canary report
* bridge materialization

### 17.2 Source-of-truth mutation requires explicit command

다음은 explicit command로만 가능하다.

* template evolve-accept
* qualify-accept
* qualify-revert
* improve keep/dismiss
* team apply
* template apply
* agent hire/fire

### 17.3 Project source mutation is separate

Cambrian runtime state 변경과 project source code 변경은 분리한다.

* `.cambrian/` artifact 변경은 Cambrian state mutation
* application source file 변경은 project source mutation

auto source mutation은 금지한다.
apply/adoption도 explicit path여야 한다.

---

## 18. Current vs Future Change Examples

### Example 1. template qualify-accept with lane default switch

변경됨:

```text
.cambrian/templates/qualification_decisions.yaml
.cambrian/templates/qualification_adoptions/
.cambrian/lane/playbook.yaml
```

변경되지 않음:

```text
project source files
current active session
current applied template
```

의미:

* future recommendation/bootstrap default가 바뀜
* 현재 프로젝트 runtime은 자동 변경되지 않음

### Example 2. improve keep

변경됨:

```text
.cambrian/improvement/decisions.yaml
.cambrian/improvement/persistent_overlay.yaml
```

변경되지 않음:

```text
project source files
template definitions
current sessions unless later explicit flow uses overlay
```

의미:

* good intervention이 persistent learning으로 남음

### Example 3. bridge paste patch_candidate

변경될 수 있음:

```text
.cambrian/bridge/replies/
.cambrian/bridge/reviews/
.cambrian/bridge/handoffs/
.cambrian/patch_intents/
.cambrian/sessions/
```

변경되지 않음:

```text
project source files
applied code
adoption state
```

의미:

* AI reply가 safe local workflow로 들어옴
* apply는 아직 아님

---

## 19. Backward Compatibility

모든 state loader는 다음을 지켜야 한다.

* missing optional field 허용
* old schema artifact 허용
* unknown fields tolerate
* malformed artifact는 crash 대신 warning
* explicit source-of-truth mutation 전에는 fail-closed

특히 template schema는 evolution, fork, lineage, context_defaults 등으로 계속 확장되므로 backward compatibility가 중요하다.

---

## 20. 최종 원칙

Cambrian state model의 최종 원칙은 아래와 같다.

1. 중요한 것은 file-first artifact로 남긴다.
2. source-of-truth와 derived artifact를 분리한다.
3. current runtime과 future default를 분리한다.
4. AI-derived artifact와 human-authored artifact를 분리한다.
5. evidence는 decision을 돕지만, decision 자체는 explicit command로만 한다.
6. 모든 promotion에는 rollback 또는 dismiss 경로가 있어야 한다.
7. project source mutation은 Cambrian state mutation과 별도로 취급한다.

한 문장으로 요약하면:

> **Cambrian의 상태 모델은 “AI 일꾼을 설치하고, 일하게 하고, 증거를 남기고, 좋은 기본값으로 진화시키되, 모든 중요한 변경을 추적 가능하고 되돌릴 수 있게 만드는 로컬 file-first 운영 모델”이다.**
