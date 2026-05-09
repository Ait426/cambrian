# Win Lane

## 0. 160R Win Lane 정정

현재 첫 검증 lane은 `auth-bug-core`이지만, 제품의 중심은 pack 직접 선택이 아니다.

제품 중심 흐름은 다음이다.

```text
cambrian project scan
cambrian harness plan
cambrian harness install
cambrian agent dispatch "로그인 에러 수정해"
```

`auth-bug-core`는 Python + pytest + auth/login bug에 맞는 첫 built-in harness preset으로 남긴다.
다른 프로젝트는 `project scan` 결과에 따라 preset 미지원 상태를 명확히 보여주고, 억지로 Python preset을 추천하지 않는다.

## 1. 문서 목적

이 문서는 Cambrian의 **현재 strongest lane** 을 명시적으로 고정하기 위한 문서다.

이 문서는 다음 질문에 답해야 한다.

- 지금 Cambrian이 어디서 제일 강한가?
- 어디까지를 현재 제품의 “주력 승리 영역”으로 볼 것인가?
- 어떤 요청은 in-lane이고, 어떤 요청은 near-lane이며, 어떤 요청은 outside-lane인가?
- 현재 strongest lane에 맞는 기본 team / template / benchmark / policy는 무엇인가?
- 왜 지금은 이 좁은 lane에 집중해야 하는가?
- 제품 표면, benchmark, proof, canary, improvement loop가 왜 이 lane 중심으로 정렬되어야 하는가?

이 문서는 broad promise를 막고,
제품 증명과 제품 개발의 초점을 고정하기 위한 문서다.

---

## 2. 한 문장 정의

**Cambrian의 현재 strongest lane은 `Python + pytest + narrow auth/login bug fix` 이다.**

기존 CLI와 docs consistency에서 쓰는 canonical label은 `Python + pytest + auth/login narrow bug fix` 이다.

더 자연어로 쓰면:

> **Cambrian은 현재 Python 프로젝트에서, pytest 기반 검증이 가능한, 좁은 auth/login/account-adjacent bug fix를 가장 잘 푸는 방향으로 최적화되어 있다.**

---

## 3. 왜 strongest lane이 필요한가

Cambrian은 장기적으로 더 넓은 범위를 다룰 수 있다.
하지만 현재 단계에서 가장 중요한 것은 **모든 분야를 조금씩 잘하는 것**이 아니라,
**하나의 좁은 문제군에서 raw AI보다 실제로 더 잘한다는 것을 증명하는 것**이다.

strongest lane을 고정해야 하는 이유는 다음과 같다.

### 3.1 증명 가능성

범위를 좁혀야 benchmark, replay, proof pack이 정직해진다.

### 3.2 추천 품질

team, template, policy, bridge fast path가 같은 방향을 바라보게 된다.

### 3.3 자동화 품질

source/test ambiguity가 줄어들고,
validated proposal까지 안전하게 가는 비율을 끌어올리기 쉬워진다.

### 3.4 제품 신뢰

사용자에게 “다 잘합니다”라고 말하는 대신,
“지금은 여기에서 가장 강합니다”라고 정직하게 말할 수 있다.

### 3.5 진화 루프 효율

반복 작업군이 좁을수록

- benchmark compare
- bottleneck 분석
- intervention
- canary
- promotion/rollback

이 훨씬 선명해진다.

즉 strongest lane은 제한이 아니라,
**제품이 실제로 이기기 위한 집중 장치**다.

---

## 4. Current Strongest Lane

### 4.1 기술적 정의

Cambrian의 현재 strongest lane은 아래 조건에 가장 잘 맞는 요청과 프로젝트다.

- **Language / stack**
  - Python
- **test discipline**
  - pytest
- **request class**
  - narrow bug fix
- **domain focus**
  - auth / login / account-adjacent work
- **working style**
  - test-first
  - narrow-scope
  - review-support

### 4.2 대표 요청 예시

아래 요청은 strongest lane 안에 들어간다.

- 로그인 에러 수정해
- username normalize 버그 수정해
- auth edge case 테스트 깨지는 거 고쳐줘
- login flow에서 narrow fix만 해줘
- account state validation 버그 잡아줘
- tests/test_auth.py 기준으로 작은 패치 만들어줘

### 4.3 대표 작업 형태

- single-file 또는 small multi-file bug fix
- auth/login/account 흐름의 validation / normalization / guard logic 수정
- regression test를 같이 확인할 수 있는 작업
- broad refactor 없이 해결 가능한 수정
- review support가 유효한 변경

---

## 5. In-Lane / Near-Lane / Outside-Lane

현재 요청과 프로젝트를 아래 세 단계로 분류한다.

### 5.1 In-Lane

다음 특징이 대부분 맞으면 in-lane이다.

- Python 프로젝트
- pytest 기반 테스트 존재
- bug_fix / regression_test 중심
- auth/login/account 관련 키워드 또는 파일명 존재
- 작은 수정으로 해결 가능
- review-support / narrow-scope와 잘 맞음

예:

- `src/auth.py`
- `tests/test_auth.py`
- login normalization bug
- account state validation regression

이 경우 Cambrian은:

- strongest lane match를 표시할 수 있고
- team/template 추천을 강하게 쓸 수 있고
- safe autonomy도 가장 적극적으로 시도할 수 있다.

---

### 5.2 Near-Lane

다음 같은 경우는 near-lane이다.

- Python + pytest는 맞음
- bug fix도 맞음
- 그러나 auth/login 특화 신호는 약함
- 또는 auth 계열이지만 review/test-first 정렬이 약함
- 또는 regression fix지만 narrow-scope가 살짝 흔들림

예:

- settings validation bug
- generic API auth-adjacent edge case
- user state sync bug

이 경우 Cambrian은:

- strongest lane에 가깝다고 표시할 수 있음
- 하지만 auth-bug core만큼의 자동화 품질은 장담하지 않음

---

### 5.3 Outside-Lane

다음 같은 경우는 outside-lane이다.

- docs-heavy work
- broad refactor
- multi-service migration
- wide architecture changes
- non-python stack
- test discipline이 약하거나 없음
- auth/login/account와 무관한 대규모 변경

예:

- 문서 전체 정리
- React UI redesign
- monorepo migration
- database schema rewrite
- broad auth system rewrite
- multi-file refactor across unrelated modules

이 경우 Cambrian은:

- 수행 자체를 막지는 않음
- 하지만 “현재 strongest lane 바깥”이라고 정직하게 알려야 한다
- 자동화 / 추천 / canary / proof의 신뢰도는 낮아질 수 있다

---

## 6. Strongest Lane 기본 구성

strongest lane 안에서는 아래 기본 구성들이 주력으로 사용된다.

### 6.1 기본 team

- `auth-bug-team`

의도:

- bug-fix
- regression-test
- review-support

### 6.2 기본 template

- `auth-bug-template`

의도:

- Python + pytest
- narrow bug fix
- test-first
- narrow-scope
- review-support defaults

### 6.3 기본 benchmark workset

- `auth-bug-workset`

의도:

- strongest lane의 benchmark proof 중심 workset
- raw AI / bridge_only / guided / full 비교의 기준판

### 6.4 기본 policy 성향

- test-first practice
- narrow change scope
- review support
- regression-test awareness

---

## 7. Strongest Lane가 제품 표면에 미치는 영향

strongest lane은 단순 설명 문구가 아니라,
제품 전반에 영향을 주는 “현재 주력 방향”이다.

### 7.1 status

`status`는 현재 프로젝트가 strongest lane 안에 있는지 정직하게 보여줘야 한다.

예:

- strong
- partial
- outside

### 7.2 harness show

기본 team / template / workset을 보여줘야 한다.

### 7.3 do

현재 요청이 strongest lane 안인지, 근처인지, 밖인지 surface해야 한다.

### 7.4 template recommend

`auth-bug-template` 같은 strongest lane template가 현재 프로젝트에 더 잘 맞을 때 우선적으로 surface될 수 있다.

### 7.5 team recommend

`auth-bug-team`이 strongest lane default team으로 보일 수 있다.

### 7.6 benchmark proof

`auth-bug-workset`가 현재 제품 증명의 가장 중요한 benchmark여야 한다.

### 7.7 canary / qualification

lane evolution은 strongest lane 안에서 먼저 일어나야 한다.

---

## 8. Strongest Lane에서 약속하는 것

in-lane 요청에 대해서 Cambrian은 아래를 더 강하게 약속할 수 있다.

### 8.1 더 높은 validated proposal 가능성

narrow bug fix, auth-related context, pytest discipline이 맞으면 validated proposal까지 갈 가능성이 높다.

### 8.2 더 낮은 human intervention 가능성

source/test 후보가 상대적으로 좁혀지고,
bridge prefill도 더 잘 맞는다.

### 8.3 더 강한 template/team 추천 품질

auth-bug-template / auth-bug-team / review-support / narrow-scope defaults가 정렬된다.

### 8.4 더 의미 있는 benchmark / replay / compare

같은 문제군을 반복 측정하기 쉬워진다.

### 8.5 더 실제적인 canary / promotion / rollback

template evolution을 strongest lane 안에서 더 믿고 돌릴 수 있다.

---

## 9. Strongest Lane에서 약속하지 않는 것

strongest lane 안에 있다고 해서 아래를 약속하는 것은 아니다.

- auto apply
- auto adoption
- 완전 무인 코드 수정
- broad refactor까지 자동 처리
- 모든 auth-related work 자동 성공
- 모든 provider/model에서 동일 품질
- docs-heavy / migration-heavy work까지 동일하게 잘함

즉 strongest lane은 **“현재 가장 잘하는 영역”** 이지,
**“완전 자동화가 보장되는 영역”** 은 아니다.

---

## 10. Outside-Lane Honesty

Cambrian은 strongest lane 밖의 요청도 수행할 수 있다.
하지만 아래 원칙을 반드시 지켜야 한다.

### 10.1 block하지 않는다

outside-lane 요청을 hard block하면 안 된다.

### 10.2 과장하지 않는다

현재 strongest lane 바깥이라고 분명히 말해야 한다.

### 10.3 기대치를 조정한다

- 자동화 품질이 낮을 수 있음
- intervention이 많아질 수 있음
- recommendation hit rate가 떨어질 수 있음
- benchmark proof가 약할 수 있음

### 10.4 strongest lane로 돌아오는 기본값은 유지한다

제품의 기본 demo, benchmark, proof, docs는 strongest lane 중심으로 유지해야 한다.

---

## 11. Win-Lane Fit 판정 기준

strongest lane fit는 deterministic하게 rule-based로 판정한다.

### Strong

- Python
- pytest
- bug_fix or regression_test
- auth/login/account 신호 존재
- narrow-scope와 잘 맞음

### Partial

- Python + pytest + bug_fix는 맞음
- auth/login 특화는 약함
- lane과 가깝지만 중심은 아님

### Outside

- docs-heavy
- broad refactor
- migration
- non-python
- low-test discipline
- auth/login/account focus 부재

중요:

- 이 판정은 제품 honesty를 위한 것이지 hard gating을 위한 것이 아니다.

---

## 12. Strongest Lane와 benchmark의 관계

strongest lane은 benchmark와 직접 연결된다.

### 현재 canonical workset

- `auth-bug-workset`

### canonical compare modes

- raw_ai
- bridge_only
- cambrian_guided
- cambrian_full

### canonical north-star interpretation

strongest lane 안에서:

- validated_proposal_rate
- human_intervention_rate
- validation_autonomy_rate
- median_time_to_validated_proposal

가 특히 중요하다.

### canonical proof question

> Cambrian Full이 auth-bug core에서 raw AI보다 실제로 더 낫는가?

이 질문에 답하는 것이 현재 strongest lane 전략의 중심이다.

---

## 13. Strongest Lane와 진화의 관계

Cambrian은 strongest lane 안에서 먼저 진화해야 한다.

### 먼저 진화해야 하는 것

- context hints
- bridge no-retype path
- safe autonomy
- review support
- narrow-scope defaults
- template qualification
- canary promotion

### 나중에 확장할 것

- docs-heavy lane
- multi-language lane
- wide refactor lane
- migration lane
- enterprise-wide workflow lane

즉 strongest lane은 **전체 제품의 seed crystal** 역할을 한다.
여기서 증명된 구조만 다른 lane으로 확장하는 게 맞다.

---

## 14. 제품 운영 원칙

현재 strongest lane을 기준으로 아래 운영 원칙을 지킨다.

### 14.1 새 기능은 strongest lane 기준으로 먼저 평가

이 기능이 strongest lane에서 validated proposal rate를 올리는가?

### 14.2 benchmark는 strongest lane 기준으로 유지

새로운 benchmark를 추가하더라도 strongest lane benchmark를 깨면 안 된다.

### 14.3 docs/demo는 strongest lane 중심

첫 사용자 경험은 strongest lane을 보여줘야 한다.

### 14.4 evidence도 strongest lane 기준으로 먼저 쌓음

proof pack, canary, qualification, replay는 strongest lane에서 먼저 충분히 성숙해야 한다.

### 14.5 broad promise보다 narrow proof

외부 메시지는 넓게 가져가도 되지만,
proof는 strongest lane에서 먼저 쌓는다.

---

## 15. 현재 strongest lane의 한계

이 strongest lane 정의는 현재 시점의 최선이지, 영원한 진리가 아니다.

한계:

- auth/login 중심이라 범위가 좁다
- Python + pytest outside에서는 추천 품질이 떨어질 수 있다
- broader product messaging와 내부 reality 사이 드리프트가 생길 수 있다
- strongest lane가 바뀌거나 확장될 가능성이 있다

따라서 strongest lane는 고정된 교리가 아니라,
**증거 기반으로 유지/확장/교체될 수 있는 현재의 주력 승리 영역**이다.

---

## 16. 최종 요약

Cambrian의 현재 strongest lane은 다음이다.

> **Python + pytest + narrow auth/login bug fix**

이 strongest lane은:

- 현재 가장 높은 자동화 가능성,
- 가장 정직한 benchmark proof,
- 가장 강한 template/team/policy alignment,
- 가장 현실적인 canary / qualification / promotion loop

를 제공하는 현재 제품의 중심축이다.

한 문장으로 다시 쓰면:

> **Cambrian은 지금 모든 일을 다 잘하는 것이 아니라, Python + pytest + auth/login 좁은 bug fix에서 실제로 더 잘하기 위해 설계된 시스템이다.**
