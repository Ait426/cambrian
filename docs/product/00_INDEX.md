# Cambrian Product Documents

## 166R Current Product Identity

Cambrian is an installable AI company runtime.
Every project becomes an AI company.

## 167R Product Constitution

The current source of truth is:

1. `14_PRODUCT_CONSTITUTION.md`
2. `42_TEN_YEAR_ARCHITECTURE.md`
3. `15_AI_COMPANY_BOOTSTRAP.md`
4. `16_JOB_START_RUNTIME_CONTRACT.md`
5. `17_CODEX_CLAUDE_REQUEST_PACKET.md`
6. `18_AI_REPLY_INGEST_CONTRACT.md`
7. `19_JOB_VALIDATE_TRUST_GATE.md`
8. `20_JOB_COMPLETE_OUTCOME_CONTRACT.md`
9. `21_EVOLUTION_REVIEW_SIGNAL_CONTRACT.md`
10. `22_EVOLUTION_PROPOSAL_PREVIEW_CONTRACT.md`
11. `23_EVOLUTION_APPLY_AUDIT_CONTRACT.md`
12. `24_EVOLUTION_ROLLBACK_CONTRACT.md`
13. `25_AUTO_TASK_DIRECTIVE_BRIDGE.md`
14. `26_AUTO_STEP_RESULT_INTAKE.md`
15. `27_AUTO_RESULT_REPORT_HANDOFF.md`
16. `28_AUTO_BOARDROOM_REPORT_REVIEW.md`
17. `29_AUTO_PLAN_FROM_HANDOFF.md`
18. `30_AUTO_CYCLE_COMMAND.md`
19. `31_CODEX_RESULT_CONTRACT_HARDENING.md`
20. `32_AUTO_LOOP_DONE_GATE.md`
21. `33_AUTO_NEXT_ITERATION_GATE.md`
22. `34_ROLE_SPECIFIC_AUTO_DIRECTIVES.md`
23. `35_ROLE_SPECIFIC_RESULT_COMPLIANCE.md`
24. `36_AUTO_RESULT_QUALITY_SCORING.md`
25. `37_QUALITY_AWARE_AUTO_PLAN_SELECTION.md`
26. `38_RELEASE_GATE_EVIDENCE_PACKAGE.md`
27. `39_RELEASE_GATE_DECISION_LOOP.md`
28. `40_AUTO_ITERATION_ARCHIVE_FRESH_START.md`
29. `41_EXPLICIT_NEXT_GOAL_CONTRACT.md`
30. `13_AI_COMPANY_RUNTIME.md`
31. `02_PRODUCT_DEFINITION.md`
32. `04_SYSTEM_ARCHITECTURE.md`
33. `11_CONVERSATIONAL_HARNESS_BUILDER.md`
34. `12_HARNESS_ENGINEERING_SYSTEM.md`

All older AI worker, pack, lane, and preset language is compatibility vocabulary unless a section explicitly marks it as current product identity.

Long-term future branch:

1. `43_AGENT_MARKETPLACE_FUTURE.md`

This future document does not replace the current product identity.
It frames a possible proof-backed agent marketplace after Cambrian has strong runtime, proof, signed pack, evolution, and registry foundations.

먼저 읽을 문서:

1. `14_PRODUCT_CONSTITUTION.md`
2. `42_TEN_YEAR_ARCHITECTURE.md`
3. `15_AI_COMPANY_BOOTSTRAP.md`
4. `16_JOB_START_RUNTIME_CONTRACT.md`
5. `17_CODEX_CLAUDE_REQUEST_PACKET.md`
6. `18_AI_REPLY_INGEST_CONTRACT.md`
7. `19_JOB_VALIDATE_TRUST_GATE.md`
8. `20_JOB_COMPLETE_OUTCOME_CONTRACT.md`
9. `21_EVOLUTION_REVIEW_SIGNAL_CONTRACT.md`
10. `22_EVOLUTION_PROPOSAL_PREVIEW_CONTRACT.md`
11. `23_EVOLUTION_APPLY_AUDIT_CONTRACT.md`
12. `24_EVOLUTION_ROLLBACK_CONTRACT.md`
13. `25_AUTO_TASK_DIRECTIVE_BRIDGE.md`
14. `26_AUTO_STEP_RESULT_INTAKE.md`
15. `27_AUTO_RESULT_REPORT_HANDOFF.md`
16. `28_AUTO_BOARDROOM_REPORT_REVIEW.md`
17. `29_AUTO_PLAN_FROM_HANDOFF.md`
18. `30_AUTO_CYCLE_COMMAND.md`
19. `31_CODEX_RESULT_CONTRACT_HARDENING.md`
20. `32_AUTO_LOOP_DONE_GATE.md`
21. `33_AUTO_NEXT_ITERATION_GATE.md`
22. `34_ROLE_SPECIFIC_AUTO_DIRECTIVES.md`
23. `35_ROLE_SPECIFIC_RESULT_COMPLIANCE.md`
24. `36_AUTO_RESULT_QUALITY_SCORING.md`
25. `37_QUALITY_AWARE_AUTO_PLAN_SELECTION.md`
26. `38_RELEASE_GATE_EVIDENCE_PACKAGE.md`
27. `39_RELEASE_GATE_DECISION_LOOP.md`
28. `40_AUTO_ITERATION_ARCHIVE_FRESH_START.md`
29. `41_EXPLICIT_NEXT_GOAL_CONTRACT.md`
30. `13_AI_COMPANY_RUNTIME.md`
31. `02_PRODUCT_DEFINITION.md`
32. `04_SYSTEM_ARCHITECTURE.md`
33. `11_CONVERSATIONAL_HARNESS_BUILDER.md`
34. `12_HARNESS_ENGINEERING_SYSTEM.md`

## 1. 문서 목적

이 폴더는 Cambrian의 제품 철학, 아키텍처, 실행 루프, 상태 모델, 웹/로컬 경계, metrics/proof 체계를 고정하기 위한 공식 제품 문서 세트다.

Cambrian은 기능이 많아질수록 방향이 흐려질 위험이 크다.
따라서 이 문서 세트는 다음 역할을 한다.

- Cambrian이 무엇인지 정의한다.
- Cambrian이 무엇이 아닌지 정의한다.
- 외부 제품 언어와 내부 아키텍처 언어를 구분한다.
- Web control plane과 Local runtime의 경계를 고정한다.
- AI company / harness / workforce / agent / skill / authority / auto mode 개념을 정리한다.
- AI worker / pack / lane / template / canary / proof 언어는 legacy compatibility vocabulary로 격리한다.
- 이후 모든 기능 개발의 기준점이 된다.

이 문서 세트는 제품의 헌법이다.

---

## 2. Cambrian 한 문장 정의

**Cambrian은 각 프로젝트를 AI 회사로 바꾸는 설치형 AI 회사 런타임이다.**

영문:

```text
Cambrian is an installable AI company runtime.
Every project becomes an AI company.
```

사용자가 제품 목표를 맡기면 Cambrian은 그 프로젝트 안에 AI 회사를 세운다.
그 회사는 CEO, CTO, COO, PM, 엔지니어, QA, 릴리즈 매니저 역할을 만들고, 하네스·인력·스킬·권한·검증·진화 루프를 통해 제품을 끝까지 만든다.

### Legacy compatibility vocabulary

아래 표현은 과거 wedge와 호환 문서에서만 사용한다. 현재 제품 중심 정의가 아니다.

이전 외부 표현:

```text
AI Worker Installer
AI 인력 설치기
AI 작업반 설치 시스템
```

이전 내부 표현:

```text
evidence-based harness engineering runtime
```

현재 해석:

- AI Worker Installer: 과거 public wedge
- worker pack / team pack / template pack / lane pack: seed/preset distribution vocabulary
- auth-bug-core: Python + pytest auth/login seed preset

이 표현들은 삭제하지 않지만, 제품 중심으로 올리지 않는다.

---

## 3. 핵심 철학

Cambrian의 핵심 철학은 아래와 같다.

### 3.1 AI 회사를 설치한다

사용자는 단순 하네스 파일을 사지 않는다.
사용자는 프로젝트 안에 일하는 AI 회사가 생기기를 원한다.

### 3.2 AI를 대체하지 않는다

Cambrian은 Claude, GPT, Cursor, local model을 대체하지 않는다.
Cambrian은 사용자가 이미 쓰는 AI 위에 작업복을 입힌다.

### 3.3 설치는 AI company bootstrap이다

사용자는 agent를 직접 설계하는 것이 아니라, 프로젝트 scan과 interview를 통해 custom harness, workforce, skill, authority, auto mode를 설치해야 한다.

Preset pack은 bootstrap의 참고 seed일 수 있지만 기본 설치물이 아니다.

### 3.4 증거가 있어야 승격된다

좋아 보이는 template/team/agent는 바로 주력이 되지 않는다.
benchmark, replay, qualification, canary, proof를 거쳐야 한다.

### 3.5 진화는 자동 생성이 아니라 evidence-backed adoption이다

Cambrian의 진화는 새로운 artifact를 많이 만드는 것이 아니다.
좋은 결과를 다음 기본값으로 승격하고, 나쁜 결과를 되돌리는 것이다.

---

## 4. 문서 읽는 순서

처음 읽는 사람은 아래 순서로 읽는다.

1. `01_PRODUCT_THESIS.md`
2. `02_PRODUCT_DEFINITION.md`
3. `04_SYSTEM_ARCHITECTURE.md`
4. `03_WIN_LANE.md`
5. `06_PACKS_AND_INSTALL.md`
6. `07_EXECUTION_LOOPS.md`
7. `05_RUNTIME_STATE_MODEL.md`
8. `08_METRICS_AND_PROOF.md`
9. `09_WEB_CONTROL_PLANE.md`
10. `10_GLOSSARY.md`
11. `11_ARCHITECTURE_INVENTORY.md`
12. `11_CONVERSATIONAL_HARNESS_BUILDER.md`
13. `12_HARNESS_ENGINEERING_SYSTEM.md`
14. `13_AI_COMPANY_RUNTIME.md`
15. `14_PRODUCT_CONSTITUTION.md`
16. `42_TEN_YEAR_ARCHITECTURE.md`
17. `15_AI_COMPANY_BOOTSTRAP.md`
18. `16_JOB_START_RUNTIME_CONTRACT.md`
19. `17_CODEX_CLAUDE_REQUEST_PACKET.md`
20. `18_AI_REPLY_INGEST_CONTRACT.md`
21. `19_JOB_VALIDATE_TRUST_GATE.md`
22. `20_JOB_COMPLETE_OUTCOME_CONTRACT.md`
23. `21_EVOLUTION_REVIEW_SIGNAL_CONTRACT.md`
24. `22_EVOLUTION_PROPOSAL_PREVIEW_CONTRACT.md`
25. `23_EVOLUTION_APPLY_AUDIT_CONTRACT.md`
26. `24_EVOLUTION_ROLLBACK_CONTRACT.md`
27. `25_AUTO_TASK_DIRECTIVE_BRIDGE.md`
28. `26_AUTO_STEP_RESULT_INTAKE.md`
29. `27_AUTO_RESULT_REPORT_HANDOFF.md`
30. `28_AUTO_BOARDROOM_REPORT_REVIEW.md`
31. `29_AUTO_PLAN_FROM_HANDOFF.md`
32. `30_AUTO_CYCLE_COMMAND.md`
33. `31_CODEX_RESULT_CONTRACT_HARDENING.md`
34. `32_AUTO_LOOP_DONE_GATE.md`
35. `33_AUTO_NEXT_ITERATION_GATE.md`
36. `34_ROLE_SPECIFIC_AUTO_DIRECTIVES.md`
37. `35_ROLE_SPECIFIC_RESULT_COMPLIANCE.md`
38. `36_AUTO_RESULT_QUALITY_SCORING.md`
39. `37_QUALITY_AWARE_AUTO_PLAN_SELECTION.md`
40. `38_RELEASE_GATE_EVIDENCE_PACKAGE.md`
41. `39_RELEASE_GATE_DECISION_LOOP.md`
42. `40_AUTO_ITERATION_ARCHIVE_FRESH_START.md`
43. `41_EXPLICIT_NEXT_GOAL_CONTRACT.md`
44. `43_AGENT_MARKETPLACE_FUTURE.md`

권장 순서가 번호 순서와 완전히 같지는 않다.
처음에는 철학과 아키텍처를 먼저 이해하고, 그다음 상태 모델과 세부 용어를 보면 된다.

---

## 5. 문서 목록

### `01_PRODUCT_THESIS.md`

Cambrian이 왜 필요한지 설명한다.

핵심 질문:

* 사용자는 왜 AI 일꾼 설치가 필요한가?
* 왜 에이전트 생성보다 설치/검증/진화가 중요한가?
* Cambrian의 moat는 무엇인가?
* 왜 외부에는 “AI 일꾼 설치기”로 설명해야 하는가?

핵심 문장:

```text
Cambrian은 AI를 더 똑똑하게 만드는 제품이 아니라,
AI를 더 믿고 더 자주 일하게 만드는 설치·검증·진화 시스템이다.
```

---

### `02_PRODUCT_DEFINITION.md`

Cambrian이 정확히 무엇이고 무엇이 아닌지 정의한다.

핵심 질문:

* 외부 제품 정의는 무엇인가?
* 내부 runtime 정의는 무엇인가?
* 지금 약속하는 것과 약속하지 않는 것은 무엇인가?
* current strongest lane은 무엇인가?
* 제품의 핵심 성공 기준은 무엇인가?

핵심 문장:

```text
Cambrian은 사용자가 이미 쓰는 AI에 검증된 AI 일꾼과 작업반을 설치하고,
benchmark·canary·rollback을 통해 더 좋은 기본값으로 계속 진화시키는 evidence-based local runtime이다.
```

---

### `03_WIN_LANE.md`

현재 Cambrian의 strongest lane을 정의한다.

현재 strongest lane:

```text
Python + pytest + narrow auth/login bug fix
```

핵심 질문:

* 어떤 요청이 in-lane인가?
* 어떤 요청이 near-lane인가?
* 어떤 요청이 outside-lane인가?
* 왜 지금은 strongest lane에 집중해야 하는가?
* benchmark/proof/canary는 왜 이 lane에서 먼저 돌아야 하는가?

핵심 문장:

```text
Cambrian은 지금 모든 일을 다 잘하는 것이 아니라,
Python + pytest + auth/login 좁은 bug fix에서 실제로 더 잘하기 위해 설계된 시스템이다.
```

---

### `04_SYSTEM_ARCHITECTURE.md`

Cambrian의 5-layer architecture를 정의한다.

5개 layer:

```text
1. Web Control Plane
2. Local Cambrian Runtime
3. AI Bridge
4. Evidence & Proof
5. Evolution & Governance
```

핵심 질문:

* 웹은 무엇을 하고 무엇을 하지 않는가?
* 로컬 runtime의 책임은 무엇인가?
* AI bridge는 어떤 계약층인가?
* evidence layer는 왜 moat인가?
* evolution layer는 어떻게 좋은 실험을 기본값으로 바꾸는가?

핵심 문장:

```text
웹은 고용판이고, 로컬 Cambrian은 현장 엔진이다.
```

---

### `05_RUNTIME_STATE_MODEL.md`

`.cambrian/` 내부 상태 모델을 정의한다.

핵심 질문:

* 어떤 artifact가 source-of-truth인가?
* 어떤 artifact가 derived artifact인가?
* current runtime state와 future default state는 어떻게 다르다?
* bridge, benchmark, template, improvement, lane state는 어디에 저장되는가?

핵심 문장:

```text
Cambrian의 상태 모델은 AI 일꾼을 설치하고, 일하게 하고, 증거를 남기고,
좋은 기본값으로 진화시키되, 모든 중요한 변경을 추적 가능하고 되돌릴 수 있게 만드는
local file-first 운영 모델이다.
```

---

### `06_PACKS_AND_INSTALL.md`

Cambrian의 pack과 install 모델을 정의한다.

Pack 종류:

```text
worker pack
team pack
template pack
lane pack
```

핵심 질문:

* 사용자는 무엇을 설치하는가?
* install은 apply와 어떻게 다른가?
* 웹 catalog와 로컬 runtime은 어떻게 연결되는가?
* install manifest는 무엇인가?
* pack install이 절대 하면 안 되는 것은 무엇인가?

핵심 문장:

```text
A Cambrian pack is an installable AI workforce unit that gives a user ready-to-run workers,
teams, templates, and proof paths without requiring them to design agents from scratch.
```

---

### `07_EXECUTION_LOOPS.md`

Cambrian의 네 가지 핵심 실행 루프를 정의한다.

4개 loop:

```text
Install Loop
Work Loop
Proof Loop
Evolution Loop
```

핵심 질문:

* 사용자는 어떤 순서로 Cambrian을 쓰는가?
* AI reply는 어떻게 workflow로 들어오는가?
* 결과는 어떻게 증명되는가?
* 좋은 실험은 어떻게 기본값이 되는가?

핵심 문장:

```text
Cambrian은 AI 일꾼을 설치하고, 일하게 하고, 증명하고,
더 나은 일꾼과 작업복으로 진화시키는 반복 루프 시스템이다.
```

---

### `08_METRICS_AND_PROOF.md`

Cambrian의 metrics와 proof 체계를 정의한다.

North Star:

```text
validated_proposal_rate
```

핵심 질문:

* Cambrian이 실제로 더 잘한다는 것을 어떻게 측정하는가?
* weekly metrics는 무엇인가?
* benchmark와 replay는 왜 필요한가?
* canary와 qualification은 어떤 proof를 제공하는가?
* 하네스 진화는 어떤 숫자로 보여야 하는가?

핵심 문장:

```text
Cambrian의 proof system은 AI 일꾼이 진짜 일을 잘했는가를 측정하고,
좋은 일꾼을 다음 기본값으로 승격시키기 위한 evidence layer다.
```

---

### `09_WEB_CONTROL_PLANE.md`

웹 제품의 역할과 한계를 정의한다.

핵심 질문:

* 웹은 무엇인가?
* 웹은 무엇을 하면 안 되는가?
* pack catalog는 어떻게 보여야 하는가?
* install manifest는 어떻게 작동하는가?
* local runtime과 웹의 경계는 무엇인가?

핵심 문장:

```text
Cambrian 웹은 AI 일꾼을 고용하는 채용 데스크이고,
로컬 Cambrian은 그 일꾼을 프로젝트에 배치하고 검증하고 진화시키는 현장 엔진이다.
```

---

### `10_GLOSSARY.md`

Cambrian의 핵심 용어를 정의한다.

핵심 범주:

* product language
* worker / agent
* pack
* team / template / lane
* bridge
* work / patch
* evidence / proof
* evolution
* qualification / canary
* metrics

핵심 문장:

```text
외부에는 AI 일꾼 설치로 말하고,
내부에는 하네스 엔지니어링 runtime으로 설계한다.
```

---

### `11_ARCHITECTURE_INVENTORY.md`

Task 132 product doctrine과 실제 codebase/CLI/artifact 구조의 정렬 상태를 감사한다.

핵심 질문:

* 5-layer architecture 중 무엇이 구현됐고 무엇이 planned인가?
* 문서에 있는 command와 실제 CLI command가 일치하는가?
* `.cambrian/` artifact 구조가 Runtime State Model과 맞는가?
* 가장 큰 architecture drift는 무엇인가?
* 다음 구현 우선순위는 무엇인가?

핵심 문장:

```text
Cambrian은 local evidence-based harness runtime과 local pack install front door를 갖췄지만,
remote registry와 proof-backed web distribution은 아직 planned다.
```

---

### `42_TEN_YEAR_ARCHITECTURE.md`

Cambrian의 현재 방향을 점검하고 2026-2036 장기 아키텍처 방향을 정의한다.

핵심 질문:

* 지금 방향은 옳은가?
* Cambrian의 10년 목적지는 무엇인가?
* 어떤 순서로 신뢰, evidence, registry, multi-lane, AI company network를 키워야 하는가?
* 어떤 기능은 아직 만들면 안 되는가?
* 앞으로 큰 기능은 어떤 gate를 통과해야 하는가?

핵심 문장:

```text
Cambrian의 10년 아키텍처는 모델 경쟁이 아니라 신뢰 경쟁이다.
```

---

## 6. 제품의 현재 공식 방향

Cambrian의 현재 제품 방향은 아래와 같다.

### 외부 포지셔닝

```text
AI Worker Installer
```

사용자가 이미 쓰는 AI에 검증된 일꾼과 작업반을 설치한다.

### 내부 아키텍처

```text
Local-first evidence-based harness runtime
```

로컬 프로젝트 안에서 설치, 실행, 검증, 진화를 관리한다.

### 현재 strongest lane

```text
Python + pytest + narrow auth/login bug fix
```

Consistency alias:

```text
Python + pytest + auth/login narrow bug fix
```

### 첫 pack

```text
auth-bug-core
```

### 첫 proof target

```text
auth-bug-workset
```

### 북극성

```text
validated_proposal_rate
```

### 10년 방향

```text
Cambrian은 모든 프로젝트 안에 검증 가능한 AI 회사를 설치하고,
그 회사가 안전하게 일하고, 증거로 배우고, 더 좋은 기본값으로 진화하게 만드는
로컬 우선 AI company operating system이 된다.
```

---

## 7. 제품의 현재 non-goals

현재 Cambrian이 하지 않는 것:

* 모든 분야에서 높은 자동화 약속
* broad general AI OS 주장
* cloud execution runtime
* browser-based code execution
* source code 자동 apply/adoption
* provider-specific deep integration
* public marketplace full launch
* multi-tenant SaaS orchestration

현재 Cambrian은 먼저 strongest lane에서 이겨야 한다.
그다음 넓힌다.

---

## 8. 가장 중요한 경계

### 8.1 Web vs Local Runtime

웹:

```text
catalog / hiring / install manifest
```

로컬:

```text
install / bridge / validate / benchmark / evolution
```

### 8.2 Current Runtime vs Future Default

current runtime:

```text
현재 session / request / patch intent / proposal
```

future default:

```text
lane playbook / template default / canary / persistent overlay
```

### 8.3 Source-of-Truth vs Derived Artifact

source-of-truth:

```text
explicit decisions / definitions / playbook
```

derived artifact:

```text
metrics / reports / proof / reviews / ledgers
```

### 8.4 External Language vs Internal Language

external:

```text
AI 일꾼 설치
```

internal:

```text
harness engineering runtime
```

---

## 9. 이후 개발 원칙

이 문서 세트 이후의 모든 기능 개발은 아래 질문을 통과해야 한다.

### 9.1 어느 loop에 속하는가?

* Install Loop
* Work Loop
* Proof Loop
* Evolution Loop

어느 loop에도 속하지 않으면 보류한다.

### 9.2 어떤 지표를 개선하는가?

최소 하나를 직접 개선하거나 측정 가능하게 해야 한다.

* validated_proposal_rate
* human_intervention_rate
* validation_autonomy_rate
* median_time_to_validated_proposal
* team_template_recommendation_hit_rate
* reuse_lift
* repeat_task_improvement_rate

### 9.3 source-of-truth를 건드리는가?

건드린다면 explicit command와 rollback path가 있어야 한다.

### 9.4 current runtime을 바꾸는가?

future default 변경과 current runtime 변경을 혼동하면 안 된다.

### 9.5 strongest lane에 도움이 되는가?

초기에는 strongest lane에서 먼저 증명해야 한다.

---

## 10. 문서 관리 원칙

### 10.1 이 문서 세트는 product source-of-truth다

새로운 큰 기능을 추가하기 전에 이 문서 세트와 맞는지 확인해야 한다.

### 10.2 용어 drift를 막는다

외부 문서에서 internal jargon을 과하게 쓰지 않는다.

피해야 할 외부 표현:

* harness engineering substrate
* policy overlay topology
* orchestration fabric

권장 외부 표현:

* AI 일꾼 설치
* AI 작업반 고용
* 검증된 작업복
* 내 AI에 바로 붙이기

### 10.3 문서와 CLI가 어긋나면 안 된다

문서에 있는 명령이 아직 구현되지 않았다면:

* planned
* future
* proposed

중 하나로 표시해야 한다.

### 10.4 strongest lane 문구는 일관되어야 한다

공식 문구:

```text
Python + pytest + narrow auth/login bug fix
```

Consistency alias:

```text
Python + pytest + auth/login narrow bug fix
```

또는 자연어:

```text
Python + pytest + auth/login bug fixes
```

### 10.5 웹은 runtime이 아니라 control plane이다

이 문구는 모든 웹 관련 문서에서 유지되어야 한다.

---

## 11. 추천 docs consistency checks

다음 문구는 테스트로 drift를 막을 수 있다.

필수 문구:

* `AI Worker Installer`
* `local-first`
* `evidence-based`
* `Web Control Plane`
* `Local Cambrian Runtime`
* `Python + pytest`
* `auth/login`
* `validated_proposal_rate`
* `worker pack`
* `team pack`
* `template pack`
* `lane pack`

검증 대상:

* `README.md`
* `docs/product/*.md`
* `docs/FIRST_RUN_DEMO.md`
* onboarding docs

---

## 12. 빠른 요약

Cambrian의 제품 정의는 아래 네 문장으로 요약된다.

1. **Cambrian은 AI 일꾼을 설치하는 제품이다.**
2. **로컬 runtime이 실제 실행과 검증을 담당한다.**
3. **웹은 고용/선택/설치 manifest를 담당하는 control plane이다.**
4. **좋은 결과는 evidence로 증명되고, 좋은 실험은 다음 기본값으로 진화한다.**

---

## 13. 다음에 읽을 문서

처음 읽는 사람은 다음 순서로 보면 된다.

```text
01_PRODUCT_THESIS.md
02_PRODUCT_DEFINITION.md
04_SYSTEM_ARCHITECTURE.md
03_WIN_LANE.md
06_PACKS_AND_INSTALL.md
07_EXECUTION_LOOPS.md
05_RUNTIME_STATE_MODEL.md
08_METRICS_AND_PROOF.md
09_WEB_CONTROL_PLANE.md
10_GLOSSARY.md
11_ARCHITECTURE_INVENTORY.md
```

---

## 14. 최종 문장

> **Cambrian은 AI를 더 똑똑하게 만든다고 주장하는 제품이 아니다.
> Cambrian은 이미 강한 AI를 더 믿고, 더 안전하게, 더 자주 일하게 만드는 AI 일꾼 설치·검증·진화 runtime이다.**
