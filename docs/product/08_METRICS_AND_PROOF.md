# Metrics and Proof

## 1. 문서 목적

이 문서는 Cambrian이 “좋아 보이는 시스템”이 아니라 **실제로 더 좋은 결과를 내는 시스템인지** 판단하기 위한 지표와 증명 구조를 정의한다.

Cambrian의 핵심 주장은 다음이다.

> **AI에 검증된 일꾼과 작업반을 설치하면, 더 적은 사람 개입으로 더 자주 validated proposal까지 갈 수 있다.**

이 주장이 제품적으로 의미 있으려면 반드시 측정 가능해야 한다.

이 문서는 다음 질문에 답한다.

- Cambrian의 북극성 지표는 무엇인가?
- 어떤 지표를 매주 봐야 하는가?
- benchmark와 proof pack은 어떤 역할을 하는가?
- canary, qualification, replay는 왜 필요한가?
- “하네스가 진화한다”는 것을 어떻게 숫자로 증명하는가?
- 어떤 지표는 허수 지표인가?
- 어떤 기준이면 Cambrian이 실제로 좋아지고 있다고 볼 수 있는가?

---

## 2. 핵심 원칙

Cambrian의 metrics 철학은 단순하다.

> **기능이 많아지는 것이 아니라, 결과가 좋아져야 한다.**

따라서 Cambrian은 다음을 측정해야 한다.

- 더 자주 validated proposal까지 가는가
- 사람이 덜 개입하는가
- validation까지 더 빨리 가는가
- 설치된 team/template/agent가 실제로 도움이 되는가
- 반복 작업에서 시간이 지날수록 더 좋아지는가
- raw AI보다 Cambrian full path가 더 나은가

이 질문에 답하지 못하는 지표는 핵심 지표가 아니다.

---

## 3. North Star Metric

Cambrian의 북극성 지표는 다음이다.

```text
validated_proposal_rate
```

Cambrian의 north star metric은 `validated_proposal_rate`다.

정의:

> **전체 요청 중, 사람이 결과를 크게 다시 작성하지 않고 validated proposal까지 도달한 비율**

수식:

```text
validated_proposal_rate =
  validated proposal 도달 요청 수 / 전체 요청 수
```

이 지표가 중요한 이유:

* Cambrian이 실제로 일을 끝까지 밀어주는지 보여준다.
* 단순 분석이나 계획이 아니라, 검증 가능한 결과물까지 갔는지 본다.
* human intervention, autonomy, template quality, bridge quality가 모두 이 지표에 영향을 준다.

Cambrian이 좋은 제품이 되려면 이 지표가 올라가야 한다.

---

## 4. 10 Core Metrics

Cambrian은 주간 단위로 아래 10개 지표를 추적한다.

| # | Metric | 의미 |
| --- | --- | --- |
| 1 | validated_proposal_rate | 북극성. 요청이 validated proposal까지 간 비율 |
| 2 | adoption_rate | validated proposal 중 실제 채택된 비율 |
| 3 | regression_free_apply_rate | apply 후 regression 없이 테스트가 통과한 비율 |
| 4 | median_time_to_validated_proposal | 요청 시작부터 validated proposal까지 걸린 중간 시간 |
| 5 | human_intervention_rate | 중간에 사람이 직접 크게 개입한 비율 |
| 6 | validation_autonomy_rate | 사람이 다시 쓰지 않아도 validation까지 간 비율 |
| 7 | lead_agent_hit_rate | 처음 선택한 lead agent가 끝까지 유효했던 비율 |
| 8 | team_template_recommendation_hit_rate | 추천된 team/template가 실제로 accepted/used된 비율 |
| 9 | reuse_lift | memory/team/template/policy reuse가 없는 경우 대비 성공률 상승분 |
| 10 | repeat_task_improvement_rate | 같은 작업군에서 이전 baseline 대비 개선된 정도 |

---

## 5. Metric Definitions

### 5.1 validated_proposal_rate

정의:

```text
validated_proposal_rate =
  validated_proposal == true 인 요청 수 / 전체 요청 수
```

관련 artifact:

* `.cambrian/sessions/`
* `.cambrian/requests/`
* `.cambrian/proposals/`
* `.cambrian/metrics/`

성공 조건:

* proposal이 생성됨
* validation이 완료됨
* source apply/adoption 전이어도 됨

중요:

* apply까지 가지 않아도 된다.
* Cambrian의 초기 핵심 목표는 apply가 아니라 validated proposal이다.

---

### 5.2 adoption_rate

정의:

```text
adoption_rate =
  adoption_succeeded == true 인 결과 수 / validated proposal 수
```

의미:

* validated proposal이 실제로 쓸 만했는지 본다.

주의:

* adoption은 explicit action이어야 한다.
* auto adoption은 금지된다.
* adoption_rate가 낮으면 validation은 통과했지만 실제 품질이 낮을 수 있다.

---

### 5.3 regression_free_apply_rate

정의:

```text
regression_free_apply_rate =
  apply 후 tests passed 수 / 전체 apply 수
```

의미:

* Cambrian이 안전한 결과를 내는지 본다.

주의:

* apply가 적으면 null 또는 insufficient data일 수 있다.
* regression-free apply는 중요하지만, 초기 북극성은 validated proposal이다.

---

### 5.4 median_time_to_validated_proposal

정의:

```text
median_time_to_validated_proposal =
  request_started_at → proposal_validated_at 까지 걸린 시간의 median
```

의미:

* Cambrian이 빨라지고 있는지 본다.
* bridge fast path, safe autonomy, no-retype path의 효과가 여기 반영된다.

좋은 변화:

* 같은 workset에서 시간이 줄어듦
* human intervention이 줄면서 시간도 줄어듦

---

### 5.5 human_intervention_rate

정의:

```text
human_intervention_rate =
  human_intervention == true 인 요청 수 / 전체 요청 수
```

human intervention 예:

* source file을 사람이 직접 선택
* test file을 사람이 직접 선택
* old_text를 사람이 다시 입력
* new_text를 사람이 다시 입력
* agent/team/template를 사람이 강제로 override
* bridge reply를 사람이 크게 재작성

의미:

* Cambrian이 실제로 손을 덜 타는지 본다.

좋은 변화:

* 낮을수록 좋다.

---

### 5.6 validation_autonomy_rate

정의:

```text
validation_autonomy_rate =
  사람이 크게 다시 쓰지 않고 validation까지 도달한 요청 수 / 전체 요청 수
```

의미:

* Cambrian이 “자동으로 어디까지 일하는가”를 보여준다.

주의:

* apply/adoption 자동화와 다르다.
* validation boundary까지 안전하게 도달하는 것을 의미한다.

---

### 5.7 lead_agent_hit_rate

정의:

```text
lead_agent_hit_rate =
  처음 선택한 lead agent가 validated/adopted 결과까지 유지된 요청 수
  / agent-routed 요청 수
```

의미:

* agent routing이 실제로 맞는지 본다.

낮으면:

* agent 추천이 부정확함
* team 구성 문제
* lane fit 문제
* request classification 문제

---

### 5.8 team_template_recommendation_hit_rate

정의:

```text
team_template_recommendation_hit_rate =
  추천된 team/template가 accepted, kept, applied, bootstrapped, 또는 실제 used된 비율
```

의미:

* Cambrian의 hiring / install / recommendation layer가 실제로 유효한지 본다.

관련 흐름:

* team recommend
* template recommend
* template board
* canary
* qualification
* lane playbook

---

### 5.9 reuse_lift

정의:

```text
reuse_lift =
  reuse_context == true 요청군의 성공률
  -
  reuse_context == false 요청군의 성공률
```

reuse_context 예:

* memory
* harness policy
* team policy
* template
* bridge
* persistent improvement overlay
* evolved template
* lane default

의미:

* Cambrian이 축적한 학습이 실제로 도움이 되는지 본다.

이 지표가 양수면:

* 설치된 하네스/템플릿/팀/메모리가 실제로 효과가 있다는 뜻이다.

---

### 5.10 repeat_task_improvement_rate

정의:

```text
repeat_task_improvement_rate =
  같은 request_class 또는 workset의 최근 성과
  -
  이전 baseline 성과
```

비교 대상:

* success rate
* validated proposal rate
* intervention rate
* autonomy rate
* median duration

의미:

* “하네스가 진화하는가”를 가장 직접적으로 보여준다.

---

## 6. Weekly Metrics Report

주간 metrics는 다음 명령으로 생성된다.

```bash
cambrian metrics week
```

저장 명령:

```bash
cambrian metrics week --save
```

권장 저장 위치:

```text
.cambrian/metrics/weekly_YYYY_WW.yaml
.cambrian/metrics/latest.yaml
```

주간 report는 최소 아래를 보여줘야 한다.

```text
North Star:
  validated proposal rate

Outcome:
  adoption rate
  regression-free apply rate

Automation:
  human intervention rate
  validation autonomy rate
  median time to validated proposal

Routing / Staffing:
  lead agent hit rate
  team/template recommendation hit rate

Evolution:
  reuse lift
  repeat task improvement rate
```

---

## 7. Benchmark Proof

Weekly metrics는 실사용 기반이라 noise가 있다.
따라서 Cambrian은 benchmark proof도 필요하다.

Benchmark는 다음을 고정한다.

* 같은 workset
* 같은 case set
* 같은 replay semantics
* mode별 비교

대표 workset:

```text
auth-bug-workset
```

비교 mode:

```text
raw_ai
bridge_only
cambrian_guided
cambrian_full
```

핵심 질문:

> **Cambrian Full이 strongest lane에서 raw AI보다 실제로 더 나은가?**

---

## 8. Benchmark Artifacts

Benchmark 관련 artifact는 아래에 저장된다.

```text
.cambrian/benchmarks/cases/
.cambrian/benchmarks/worksets/
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

각 artifact 역할:

| Artifact | 역할 |
| --- | --- |
| cases | 개별 benchmark 요청 |
| worksets | case 묶음 |
| results | mode별 결과 |
| reports | workset report |
| baselines | 기준점 |
| compares | baseline 대비 비교 |
| replays | case replay |
| workset_replays | workset replay |
| autonomy_boards | 자동화 stage 증거 |
| bottlenecks | 주요 병목 |
| proof | 한 장짜리 증명 보고서 |

---

## 9. Baseline Compare

Baseline compare는 현재 결과가 과거보다 좋아졌는지 본다.

명령:

```bash
cambrian benchmark baseline-save auth-bug-workset
cambrian benchmark compare auth-bug-workset
```

결과 verdict:

```text
improved
mixed
regressed
insufficient_data
```

비교 지표:

* validated_proposal_rate
* adoption_rate
* regression_free_apply_rate
* human_intervention_rate
* validation_autonomy_rate
* median_duration_seconds

baseline compare는 “좋아졌는가”를 보는 핵심 도구다.

---

## 10. Replay and Autonomy

Replay는 같은 case/workset을 현재 Cambrian 상태로 다시 돌려보는 것이다.

Case replay:

```bash
cambrian benchmark replay login-bug --mode cambrian_full
```

Workset replay:

```bash
cambrian benchmark replay-workset auth-bug-workset --mode cambrian_full
```

Autonomy board:

```bash
cambrian benchmark autonomy-board auth-bug-workset
```

Replay stage:

```text
request_start
context_ready
diagnosed
patch_intent_ready
proposal_validated
```

Replay는 auto apply/adoption을 하지 않는다.
목표는 안전하게 **validated proposal boundary**까지 얼마나 가는지 보는 것이다.

---

## 11. Bottleneck Analysis

Bottleneck analysis는 자동화가 어디서 막히는지 본다.

명령:

```bash
cambrian benchmark bottlenecks auth-bug-workset
```

대표 bottleneck:

```text
ambiguous_context_selection
no_safe_context_candidate
missing_patch_candidate
validation_failure_cluster
bridge_dependency_gap
weak_team_fit
weak_template_fit
review_support_gap
narrow_scope_gap
memory_hygiene_drag
```

Bottleneck은 improvement cycle의 입력이다.

---

## 12. Proof Pack

Proof pack은 여러 evidence를 한 장으로 묶는다.

명령:

```bash
cambrian benchmark proof auth-bug-workset
```

Proof pack이 합치는 source:

* weekly metrics
* benchmark report
* baseline compare
* autonomy board
* bottleneck report
* strongest lane profile

Proof verdict:

```text
wins_now
promising
mixed
regressed
insufficient_data
```

Proof pack은 다음을 보여줘야 한다.

* best mode now
* previous best mode
* why it wins
* where it fails
* next one fix

Proof pack은 외부나 내부 의사결정에서 가장 읽기 좋은 증거 문서다.

---

## 13. Canary Metrics

Template canary는 stable default가 되기 전 후보 template다.

Canary는 아래 evidence를 가져야 한다.

### 13.1 Canary ledger

```text
surfaced_count
selected_count
skipped_count
bootstrap_count
apply_count
replay_count
replay_validated_count
replay_blocked_count
```

### 13.2 Canary outcome attribution

```text
selected_with_outcome_count
selected_then_validated_count
selected_then_adopted_count
selected_then_regression_free_apply_count
selected_validation_autonomy_rate
selected_human_intervention_rate
median_selected_duration_seconds
```

### 13.3 Canary freshness

```text
fresh
warming
review_due
stale
expired
insufficient_data
```

Canary는 단순히 “좋아 보이는 후보”가 아니다.
Canary는 실제 exposure, selection, outcome, freshness evidence를 가져야 한다.

---

## 14. Qualification Metrics

Qualification은 derivative template가 parent/reference보다 나은지 보는 비교다.

명령:

```bash
cambrian template qualify auth-bug-template-local --workset auth-bug-workset
```

비교 지표:

* validated_proposal_rate
* human_intervention_rate
* validation_autonomy_rate
* median_duration_seconds
* stop reason distribution

결과:

```text
candidate_stronger
mixed
regressed
inconclusive
```

Qualification은 template promotion의 근거다.
Qualification 없이 lane default를 쉽게 바꾸면 안 된다.

---

## 15. Challenge Matrix Metrics

Challenge matrix는 stable default, active canary, queued challengers를 같은 workset에서 비교한다.

명령:

```bash
cambrian template challenge-matrix --workset auth-bug-workset
```

목표:

* next_best_challenger를 evidence 기반으로 고른다.

비교 대상:

* stable default
* active canary
* queued challengers

비교 지표:

* validated_proposal_rate
* human_intervention_rate
* validation_autonomy_rate
* median_duration_seconds

이 matrix는 “다음 canary로 누구를 태울지”를 결정하는 증거다.

---

## 16. Improvement Metrics

Improvement loop는 한 번에 하나의 병목만 줄인다.

명령:

```bash
cambrian improve next auth-bug-workset
cambrian improve evaluate cycle-...
```

Before/after snapshot은 최소 아래를 가져야 한다.

* validated_proposal_rate
* human_intervention_rate
* validation_autonomy_rate
* reuse_lift
* repeat_task_improvement_rate

Improvement verdict:

```text
improved
mixed
regressed
inconclusive
```

좋은 intervention은 keep될 수 있고, persistent overlay가 된다.

```bash
cambrian improve keep intervention-...
```

---

## 17. Metrics Context

Request/session artifact는 metrics 계산을 위해 최소한의 context를 가져야 한다.

예:

```yaml
metrics_context:
  request_class: bug_fix
  source_mode: bridge_fastpath
  autonomy_mode: safe

  template_name: auth-bug-template-local
  team_id: auth-bug-team
  lead_agent_id: bug-fix-agent

  reused_context:
    memory: true
    harness_policy: true
    team_policy: true
    template: true
    bridge: true
    persistent_improvement: true

  human_interventions:
    source_selected_manually: false
    test_selected_manually: false
    old_text_overridden: false
    new_text_overridden: false
    explicit_agent_override: false
    explicit_team_override: false
    explicit_template_choice: false

  milestones:
    request_started_at: "..."
    diagnosed_at: "..."
    patch_intent_ready_at: "..."
    proposal_validated_at: "..."

  results:
    validated_proposal: true
    adoption_succeeded: false
    apply_tests_passed: null
```

이 context가 없으면 metrics가 추정에 의존하게 된다.
가능한 한 request/session에 직접 남겨야 한다.

---

## 18. What Counts as Human Intervention

다음 중 하나라도 true면 human intervention으로 볼 수 있다.

* source_selected_manually
* test_selected_manually
* old_text_overridden
* new_text_overridden
* explicit_agent_override
* explicit_team_override
* explicit_template_choice
* bridge reply를 사람이 크게 수정

단, 모든 사람 입력이 나쁜 것은 아니다.
중요한 것은 **반복 작업에서 불필요한 재작성과 수동 선택이 줄어드는가**다.

---

## 19. What Counts as Reuse

reuse는 Cambrian이 과거 학습이나 설치된 구성으로 도움을 준 경우다.

예:

* memory lesson 사용
* harness policy 사용
* team policy 사용
* template default 사용
* bridge context hint 사용
* persistent improvement overlay 사용
* evolved template 사용
* lane playbook default 사용
* canary/qualification evidence 사용

reuse_lift는 이 reuse가 실제로 성공률을 올리는지 본다.

---

## 20. What Counts as Evolution

Cambrian에서 evolution은 단순히 artifact가 늘어나는 것이 아니다.

진짜 evolution은 다음이다.

> **같은 작업군을 시간이 지난 뒤 더 적은 개입으로, 더 높은 검증률로, 더 안전하게 처리하는 것**

Evolution evidence:

* validated_proposal_rate 상승
* human_intervention_rate 하락
* validation_autonomy_rate 상승
* repeat_task_improvement_rate 상승
* bottleneck frequency 감소
* stronger template qualification
* canary promotion readiness
* proof verdict 개선

---

## 21. 허수 지표

아래는 조심해야 한다.

* agent 개수
* template 개수
* pack 개수
* notes 개수
* artifact 개수
* command 개수
* suggestion 개수
* dashboard 항목 개수

이것들은 product activity를 보여줄 수는 있지만, product quality를 직접 증명하지 않는다.

Cambrian의 진짜 질문은:

> **더 나은 결과를 더 적은 개입으로 냈는가?**

이다.

---

## 22. Good / Bad Interpretations

### 22.1 validated_proposal_rate는 오르지만 regression_free_apply_rate가 떨어진다

의미:

* 빨리 proposal은 만들지만 안전성이 약할 수 있다.

대응:

* validation support 강화
* review-support bias
* test-first defaults 강화

### 22.2 team_template_hit_rate는 높은데 validated_proposal_rate가 낮다

의미:

* 추천은 그럴듯하지만 실제 결과 품질이 약하다.

대응:

* benchmark replay로 실제 성과 확인
* template qualification 재검토

### 22.3 human_intervention_rate가 높다

의미:

* 사용자가 여전히 source/test/old/new를 많이 손으로 고친다.

대응:

* bridge no-retype path 강화
* context hints 강화
* safe autonomy 개선

### 22.4 reuse_lift가 0 이하

의미:

* 설치된 하네스/템플릿/팀/메모리가 실제로 도움이 안 되고 있을 수 있다.

대응:

* persistent overlay 검토
* lane default rollback
* template qualification 재실행

### 22.5 repeat_task_improvement_rate가 낮다

의미:

* Cambrian이 축적은 하지만 진화하지 못하고 있을 수 있다.

대응:

* bottleneck loop 강제
* one intervention per week
* before/after compare 정리

---

## 23. Proof Thresholds

초기 알파 단계에서 사용할 수 있는 rough threshold는 다음이다.

### validated_proposal_rate

* green: 35%+
* yellow: 20~35%
* red: <20%

### human_intervention_rate

* green: <30%
* yellow: 30~50%
* red: >50%

### validation_autonomy_rate

* green: 30%+
* yellow: 10~30%
* red: <10%

### team_template_recommendation_hit_rate

* green: 60%+
* yellow: 40~60%
* red: <40%

### reuse_lift

* green: +10pt 이상
* yellow: 0~10pt
* red: 음수

이 threshold는 고정 진리가 아니다.
초기 제품 검증을 위한 가이드다.

---

## 24. Strongest Lane Proof Criteria

현재 strongest lane은:

```text
Python + pytest + narrow auth/login bug fix
```

이 lane에서 Cambrian이 “이기고 있다”고 말하려면 최소 아래가 필요하다.

1. `auth-bug-workset` 존재
2. raw_ai / bridge_only / cambrian_guided / cambrian_full 비교 가능
3. cambrian_full이 validated_proposal_rate에서 우세
4. cambrian_full이 human_intervention_rate에서 우세
5. regression-free quality에서 심각하게 밀리지 않음
6. baseline compare가 improved 또는 최소 mixed 이상
7. top bottleneck가 명확하고 개선 loop가 진행 중

---

## 25. Reporting Surfaces

Metrics와 proof는 여러 surface에 표시될 수 있다.

### status

짧게만 표시한다.

예:

```text
Weekly metrics:
  validated : 41%
  intervention: 28%
  reuse lift: +12pt
```

### benchmark proof

한 장짜리 핵심 증명.

### template show

template별 qualification/canary/outcome evidence.

### harness show

lane playbook과 current proof summary.

### web catalog

나중에는 pack 상세 페이지에 proof summary를 표시할 수 있다.

중요:
웹에 보여주는 proof는 과장하면 안 된다.
local proof 기반이어야 한다.

---

## 26. Data Safety

Metrics와 proof는 local-first여야 한다.

원칙:

* source code 원문을 cloud로 보내는 것이 moat가 아니다.
* 구조화된 outcome evidence가 moat다.
* raw code보다 validated/adopted/intervention/replay 결과가 중요하다.
* enterprise 사용자는 local proof와 private registry를 원할 수 있다.

따라서 Cambrian은 다음을 우선해야 한다.

* local metrics
* local benchmark
* local proof
* explicit export only
* raw data 최소화

---

## 27. Metrics and Web Control Plane

웹이 생기면 proof는 pack catalog의 핵심이 된다.

Pack page는 나중에 아래를 보여줄 수 있다.

* latest validated_proposal_rate
* best workset
* proof verdict
* canary status
* known limits
* compatibility
* install command

하지만 웹은 runtime이 아니다.
웹은 proof를 보여줄 수 있지만, proof는 기본적으로 local Cambrian runtime에서 생성된다.

---

## 28. Metrics and Product Decisions

다음 decision은 metrics/proof를 근거로 삼아야 한다.

### pack release-check

`cambrian pack release-check <manifest-or-pack-id>`는 pack을 local catalog에 올리기 전에 schema, integrity, compatibility, known limits, evidence refs를 점검한다.
release gate는 pack maturity와 proof status를 보수적으로 계산한다.

```text
maturity:
  draft
  candidate
  verified
  canary
  recommended
  retired

proof_status:
  none
  local_only
  partial
  verified
  strong
```

`--require-proof`를 쓰면 proof evidence가 부족한 pack publish는 blocked가 된다.
proof 없는 pack은 candidate 또는 local proof required로 표시해야 하며, fake proof나 실제 artifact 없는 metrics 숫자를 만들면 안 된다.

### web-sync proof surface

`cambrian pack web-sync`는 `packs/catalog.yaml`의 maturity/proof metadata를 static web catalog asset으로 반영한다.
웹 catalog는 사용자가 pack을 고르기 전에 known limits와 proof status를 볼 수 있게 해야 한다.
이 surface는 `team_template_recommendation_hit_rate`, `reuse_lift`, `repeat_task_improvement_rate` 해석을 돕지만, proof 자체를 생성하지는 않는다.

### pack usage ledger

`cambrian pack usage`, `cambrian pack events`, and `cambrian pack outcomes` are local-only evidence surfaces.
They record when an active pack is surfaced or used in bridge/do/continue/safe autonomy/benchmark flows, then link those usage events to local session, proposal, replay, and benchmark outcomes when the artifacts contain enough context.

Pack outcome summaries may compute:

* used_count
* bridge_used_count
* do_used_count
* benchmark_used_count
* validated_proposal_count
* adopted_count
* regression_free_apply_count
* human_intervention_count
* validation_autonomy_count
* median_time_to_validated_proposal

Attribution must stay honest.
If a usage event exists but no outcome source can be found, Cambrian records partial attribution instead of inventing proof.
These summaries can later inform release-check, maturity, recommendation, and web catalog proof copy, but they must not trigger auto ranking, auto promotion, or cloud telemetry upload.

### pack job apply / adoption closure

`cambrian pack job-apply <job>` is preview-only by default. It shows the validated proposal target and next command without mutating source.
Source mutation is allowed only through `cambrian pack job-apply <job> --confirm`, which reuses the existing patch apply path instead of creating a new pack-specific patch engine.

`cambrian pack job-adopt <job> --accepted|--rejected|--skipped` is the explicit pack-level adoption decision.
This separates:

* validated proposal: the AI worker reached a validated proposal
* apply: the proposal was explicitly applied through the safe apply path
* adoption: a human accepted, rejected, or skipped the result

Pack usage/outcome summaries can then count `applied_count`, `accepted_count`, `rejected_count`, and `skipped_count` without inventing adoption evidence.
Apply test results feed `regression_free_apply_rate`; adoption decisions feed `adoption_rate`; both remain local-only evidence for pack proof.

### pack job retrospective

`cambrian pack job-retro <job>` reviews a completed pack job after validation/apply/adoption closure.
It keeps human feedback separate from system evidence:

* human feedback: accepted/rejected/skipped decision and reason
* system evidence: validated proposal, applied, adoption succeeded, regression-free apply, human intervention, validation autonomy, duration

Retrospectives classify outcomes such as `worked_well`, `validated_but_not_adopted`, `applied_but_rejected`, `blocked_before_validation`, and `regression_or_safety_issue`.
They also create pack-level signals for context fit, team fit, template fit, bridge quality, validation quality, intervention cost, adoption quality, and lane fit.

`cambrian pack retro-summary <pack>` aggregates those local signals so proof cards and release-check can explain why metrics moved, not only whether they moved.
Suggestions such as `strengthen_context_hints`, `improve_response_contract`, `improve_validation_support`, `update_known_limits`, and `add_benchmark_case` are advisory only.
Cambrian must not auto-evolve templates, mutate packs, create benchmark cases, upload retrospective details, or mutate source from retrospective output.

### pack improvement queue

`cambrian pack improve <pack>` converts retrospective summary, pack proof, usage/outcome, and release evidence into `.cambrian/packs/improvements/queue.yaml`.
Each queue item has:

* kind such as `strengthen_context_hints`, `improve_response_contract`, `improve_validation_support`, `update_known_limits`, `add_benchmark_case`, `review_team_fit`, `review_template_fit`, or `create_pack_derivative`
* priority and confidence
* affected metrics
* evidence refs
* next commands

Signal mapping stays explicit:

* negative `context_fit` becomes context hint and benchmark-case candidates for `validated_proposal_rate`, `human_intervention_rate`, and `median_time_to_validated_proposal`.
* negative `adoption_quality` or rejected feedback becomes known-limit/template-fit/derivative candidates for `adoption_rate` and `team_template_recommendation_hit_rate`.
* regression or safety signals become validation support and known-limit candidates to protect `regression_free_apply_rate`.
* negative `intervention_cost` becomes first-job/context guidance candidates to reduce `human_intervention_rate`.
* negative `validation_quality` becomes validation support candidates for `validation_autonomy_rate`.
* negative team/template fit becomes review candidates for recommendation hit rate.
* repeated `worked_well` becomes benchmark/docs candidates that feed `reuse_lift` and `repeat_task_improvement_rate`.

`cambrian pack improvement-accept <item>` and `cambrian pack improvement-dismiss <item>` only record decisions in `.cambrian/packs/improvements/decisions.yaml`.
They do not run `benchmark case-add`, `template evolve`, `pack draft`, `pack build`, publish, or mutate source. Actual implementation remains an explicit later command.

### pack proof card

`cambrian pack proof [pack-id]` is the local proof-card surface for installed AI worker packs.
It combines pack usage summaries, outcome attribution, installed provenance, active pack context, release metadata, and benchmark evidence when available.

The reputation verdict is conservative:

```text
unproven
promising
useful
strong
regressed
insufficient_data
```

The proof card explains pack-level `validated_proposal_rate`, `adoption_rate`, `regression_free_apply_rate`, `human_intervention_rate`, `validation_autonomy_rate`, and `median_time_to_validated_proposal` only when local evidence exists.
Missing evidence stays null or `unknown`; Cambrian must not invent fake percentages.

Saved proof cards live under:

```text
.cambrian/packs/proof/
```

Proof cards may inform `pack show`, `status`, `pack recommend`, and `pack release-check`, but they do not trigger auto promotion, auto ranking, cloud telemetry upload, or public proof publishing.

### pack proof export

`cambrian pack proof-export [pack-id]` is the privacy-safe bridge from local proof to public catalog proof.
It is explicit opt-in and writes a local export record under `.cambrian/packs/proof_exports/`.
With `--out packs/proof_exports/<pack-id>.public-proof.yaml`, it also writes a public-safe copy that `cambrian pack web-sync` can include in the static web catalog.

The public export may include:

* reputation verdict
* proof status
* maturity hint
* used_count and outcome_linked_count
* aggregate rates such as validated_proposal_rate, adoption_rate, regression_free_apply_rate, human_intervention_rate, and validation_autonomy_rate
* median_time_to_validated_proposal when available
* known limits, caveats, and safe claims

The public export must not include:

* raw request text
* source code
* patch old_text/new_text or patch text
* session logs
* proposal text
* absolute local paths
* private notes

If proof is sparse, the export still says `insufficient` or `unproven` and includes a sample-size caveat.
If sensitive raw fields are detected, the export is classified as `blocked_sensitive` and no public copy is written.
This separation lets the web hiring desk show why a pack may help without leaking local project detail or inventing fake proof.

### pack derivative proof loop

Accepted improvements explain what Cambrian should try in the next pack version.
`cambrian pack derivative-plan <pack>` groups accepted improvement evidence into vNext changes such as context hint strengthening, validation support, known-limit updates, team/template review, benchmark cases, and response contract work.

```bash
cambrian pack improve auth-bug-core
cambrian pack improvement-accept item-...
cambrian pack derivative-plan auth-bug-core
cambrian pack derivative-create latest --as auth-bug-core-v2
```

This keeps `repeat_task_improvement_rate` and `reuse_lift` explainable: Cambrian can point to which accepted retrospective signals were carried into a vNext draft.
Context, bridge, and validation changes target `validated_proposal_rate`, `human_intervention_rate`, and `validation_autonomy_rate`.
Team/template changes target `team_template_recommendation_hit_rate`, while adoption feedback can become known limits or a pack derivative.

Derivative artifacts are local-only and do not mean the improvements are implemented. Unresolved changes remain in draft metadata and release-check warnings until explicit build/release work is done.

### pack vNext workbench proof loop

The derivative workbench records whether the accepted improvements were actually executed before release:

```bash
cambrian pack derivative-workbench latest
cambrian pack workorders auth-bug-core
cambrian pack workorder-done wo-... --evidence .cambrian/templates/evolution_proposals/proposal_...yaml
cambrian pack release-check packs/generated/auth-bug-core-v2.cambrian-pack.yaml
```

Open required work orders explain why a derivative draft is not release-ready. Done work orders keep artifact refs or notes so future proof can connect `repeat_task_improvement_rate` and `reuse_lift` to concrete vNext execution. Context/template/validation work orders target `validated_proposal_rate`, `human_intervention_rate`, and `validation_autonomy_rate`; team/template review targets `team_template_recommendation_hit_rate`; known-limit updates preserve adoption feedback for `adoption_rate`.

The workbench remains local-only. It does not auto-mutate templates, source code, teams, benchmark cases, or pack manifests, and it does not upload proof.

### pack release candidate and local release

```bash
cambrian pack rc .cambrian/packs/drafts/draft_auth-bug-core-v2.yaml
cambrian pack rc-show latest
cambrian pack release-local latest
cambrian pack release-local latest --confirm
cambrian pack rollout auth-bug-core-v2
cambrian pack rollout-apply latest --confirm --install --activate
```

Release candidates freeze completed vNext workorders, derivative evidence, build output, release-check results, changelog, known limits, and lineage.
This makes `repeat_task_improvement_rate` measurable because Cambrian can compare the previous pack and the released vNext pack using the same proof/usage chain.
Lineage and local release records preserve `reuse_lift`; completed workorders explain why `validated_proposal_rate`, `human_intervention_rate`, `validation_autonomy_rate`, `team_template_recommendation_hit_rate`, `adoption_rate`, and `regression_free_apply_rate` should move after release.

`pack release-local` is preview-first. Only `--confirm` updates the local catalog via the existing `publish-local` path.
It does not upload remotely, auto-install the new pack, uninstall the old pack, mutate source code, or promote maturity automatically.

Rollout connects the released vNext pack to actual project usage without hidden runtime mutation.
The rollout plan compares previous and new proof/readiness evidence, records whether the new pack is installed or active, and preserves the old pack as a rollback baseline.
That makes the next run of `validated_proposal_rate`, `human_intervention_rate`, `validation_autonomy_rate`, `team_template_recommendation_hit_rate`, `adoption_rate`, `reuse_lift`, and `repeat_task_improvement_rate` interpretable as a controlled upgrade experiment rather than an invisible automatic update.

### improve keep

기본적으로 improved verdict가 있어야 한다.

### template evolve-accept

kept improvement가 있어야 한다.

### template qualify-accept

candidate_stronger qualification이 있어야 한다.

### canary-promote

promote_ready + fresh evidence가 있어야 한다.

### lane default switch

qualification / canary / proof evidence가 있어야 한다.

즉 Cambrian에서 중요한 승격은 모두 evidence-backed여야 한다.

---

## 29. Minimum Weekly Review

매주 최소 아래를 확인한다.

```bash
cambrian metrics week --save
cambrian benchmark compare auth-bug-workset
cambrian benchmark proof auth-bug-workset
cambrian benchmark bottlenecks auth-bug-workset
```

질문:

1. validated proposal rate는 올랐나?
2. human intervention은 줄었나?
3. validation autonomy는 올랐나?
4. reuse lift는 양수인가?
5. repeat task improvement는 보이는가?
6. 가장 큰 bottleneck은 무엇인가?
7. 이번 주 하나만 고칠 것은 무엇인가?

---

## 30. Final Summary

Cambrian의 metrics와 proof는 기능이 많다는 것을 보여주기 위한 것이 아니다.

목적은 하나다.

> **설치된 AI 일꾼과 작업반이 실제로 더 좋은 결과를 내고, 더 적은 사람 개입으로 validated proposal까지 가며, 반복할수록 더 좋아진다는 것을 증명하는 것.**

한 문장으로 요약하면:

> **Cambrian의 proof system은 “AI 일꾼이 진짜 일을 잘했는가”를 측정하고, 좋은 일꾼을 다음 기본값으로 승격시키기 위한 evidence layer다.**
