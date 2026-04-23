# HARNESS_ARTIFACT_SYSTEM.md

## 1. 목표

Cambrian이 프로젝트마다 자동 또는 반자동으로 생성·관리해야 하는 하네스 아티팩트 세트를 파일 단위로 정의한다.

이 아티팩트들의 목적은 아래다.

- 이 프로젝트에서 무엇을 검증할지 고정
- 어떤 입력으로 검증할지 고정
- 무엇을 좋은 결과라고 볼지 고정
- 어떤 경우 merge 가능 / hold / rollback 인지 고정
- 실패를 누적해서 다음 검증에 재사용

즉, 하네스는 "로직"이 아니라
**프로젝트에 붙는 검증 운영 파일 세트**다.

## 2. 핵심 원칙

### 원칙 1

스킬은 교체 가능, 하네스는 축적 자산

### 원칙 2

하네스 아티팩트는 사람이 읽고 수정할 수 있어야 함

### 원칙 3

source artifact와 generated artifact를 분리해야 함

### 원칙 4

MVP에서는 파일 수를 최소화해야 함

> 처음부터 파일을 너무 많이 만들지 말고, 6개 핵심 파일 + 2개 생성 파일로 간다.

## 3. 추천 디렉토리 구조

```
.cambrian/
  harness/
    harness.yaml
    eval_cases.jsonl
    replay_cases.jsonl
    judge_rubric.md
    promotion_policy.json
    rollback_policy.json

  reports/
    latest_verdict.json
    latest_benchmark.json

  history/
    run_traces.jsonl
    failure_log.jsonl
```

### 구분

- `harness/` = 사람이 수정 가능한 핵심 계약 파일
- `reports/` = 실행 결과로 생성되는 현재 상태 산출물
- `history/` = 누적되는 운영 로그

## 4. 파일별 정의

### A. `.cambrian/harness/harness.yaml`

**역할**: 이 프로젝트 하네스의 루트 메타파일

**왜 필요한가**: 하네스 전체를 한 파일에서 식별해야 한다.

**담아야 할 것**:
- 프로젝트 이름
- 대상 언어/프레임워크
- 주요 검증 목표
- 주요 capability gap
- 어떤 아티팩트를 참조하는지
- 기본 verdict 기준

**예시**:

```yaml
version: 1
project_name: todo_cli
language: python
objective: "AI 변경이 merge 가능한지 검증"
focus_areas:
  - testing
  - documentation
artifacts:
  eval_cases: ".cambrian/harness/eval_cases.jsonl"
  replay_cases: ".cambrian/harness/replay_cases.jsonl"
  judge_rubric: ".cambrian/harness/judge_rubric.md"
  promotion_policy: ".cambrian/harness/promotion_policy.json"
  rollback_policy: ".cambrian/harness/rollback_policy.json"
default_verdict: hold
```

**성격**: source of truth / 사람이 수정 가능 / scan+bootstrap이 초안 생성

### B. `.cambrian/harness/eval_cases.jsonl`

**역할**: 기본 검증 케이스 모음

**왜 필요한가**: 좋은 후보인지 보려면 같은 입력 세트로 계속 비교해야 한다.

**한 줄 = 한 케이스**:

```json
{"id":"eval-001","task":"generate pytest skeleton","input":{"target":"utils.py"},"expected_properties":["creates_valid_pytest_file","no_syntax_error"],"priority":"high"}
```

**최소 필드**: id, task, input, expected_properties, priority

**성격**: 핵심 하네스 파일 / 사람이 수정 가능 / scan+bootstrap이 초안 생성 / 사람이 보강 가능

### C. `.cambrian/harness/replay_cases.jsonl`

**역할**: 실패했거나 경계에 걸렸던 케이스 재검증용 세트

**왜 필요한가**: 진화의 핵심은 새로 잘하는 것보다 **예전에 실패한 걸 다시 안 망치는 것**이다.

**예시**:

```json
{"id":"replay-014","source_run":"run-20260412-0014","reason":"generated invalid json","input":{"target":"README.md"},"severity":"high"}
```

**최소 필드**: id, source_run, reason, input, severity

**성격**: 반자동 축적 파일 / 시스템이 추가 / 사람도 정리 가능

### D. `.cambrian/harness/judge_rubric.md`

**역할**: 무엇을 "좋은 결과"로 볼지 적은 판정 기준 문서

**왜 필요한가**: 성공/실패만으로는 부족하다. README 생성, 테스트 생성, 요약 생성은 질 기준이 있어야 한다.

**예시**:

```markdown
# Judge Rubric

## Testing tasks
- pytest 문법이 유효해야 함
- 최소 1개 이상 핵심 함수 테스트 포함
- placeholder test만 있으면 불합격

## Documentation tasks
- 실제 프로젝트 구조를 반영해야 함
- 없는 명령어를 쓰면 불합격
- 설치/실행 방법이 빠지면 감점
```

**성격**: 사람이 읽는 규칙 파일 / Cambrian이 judge/benchmark 시 참조 / 사람이 다듬을수록 품질 상승

### E. `.cambrian/harness/promotion_policy.json`

**역할**: 어떤 후보를 승격 가능한지 정의

**왜 필요한가**: "좋아 보인다"와 "올려도 된다"는 다르다.

**예시**:

```json
{
  "min_success_rate": 0.9,
  "must_pass_replay": true,
  "max_regressions": 0,
  "min_eval_cases": 5,
  "verdict_on_pass": "merge"
}
```

**성격**: 정책 파일 / 사람이 수정 가능 / 프로젝트별로 달라져야 함

### F. `.cambrian/harness/rollback_policy.json`

**역할**: 어떤 경우 이전 상태로 격리/롤백할지 정의

**왜 필요한가**: 회귀를 발견했을 때 감으로 대응하면 안 된다.

**예시**:

```json
{
  "rollback_on_replay_failure": true,
  "rollback_on_schema_break": true,
  "rollback_on_output_invalid_count": 2,
  "quarantine_on_timeout": true
}
```

**성격**: 정책 파일 / promotion 정책과 짝을 이룸

### G. `.cambrian/reports/latest_verdict.json`

**역할**: 가장 최근 Cambrian 판정 결과

**왜 필요한가**: 사용자에게 보여줄 최종 결과는 이 파일로 고정할 수 있다.

**예시**:

```json
{
  "run_id": "run-20260412-0017",
  "verdict": "hold",
  "summary": "2 replay failures detected",
  "passed_eval": 4,
  "failed_eval": 2,
  "failed_replay": 2,
  "recommended_next_action": "inspect failing replay cases"
}
```

**성격**: generated / 사람이 직접 수정하지 않음 / CLI 출력과 연결 가능

### H. `.cambrian/reports/latest_benchmark.json`

**역할**: 후보 비교 결과 저장

**왜 필요한가**: 누가 1등이었는지, 왜 이겼는지 남겨야 한다.

**성격**: generated / benchmark 실행 시 갱신

### I. `.cambrian/history/run_traces.jsonl`

**역할**: 실행 기록 누적

**왜 필요한가**: 나중에 replay, failure mining, threshold 보정에 필요하다.

**성격**: generated / 계속 append

### J. `.cambrian/history/failure_log.jsonl`

**역할**: 실패를 구조적으로 기록

**왜 필요한가**: 실패를 그냥 stderr로 버리면 하네스가 진화하지 못한다.

**예시 필드**: run_id, candidate_id, failure_type, task, input_hash, severity, replay_added 여부

## 5. MVP에서 꼭 필요한 최소 세트

처음에는 이것만 있으면 된다.

**필수 6개**:
- harness.yaml
- eval_cases.jsonl
- replay_cases.jsonl
- judge_rubric.md
- promotion_policy.json
- rollback_policy.json

**생성 2개**:
- latest_verdict.json
- run_traces.jsonl

이 정도면 Cambrian이 하네스를 가진다고 말할 수 있다.

## 6. 생성 흐름

### 1단계: scan

프로젝트를 읽고 gap/구조 파악

### 2단계: harness bootstrap

아래를 초안 생성:
- harness.yaml
- eval_cases.jsonl
- judge_rubric.md
- 정책 파일 2개

### 3단계: run / benchmark

후보 실행 및 비교

### 4단계: verdict 생성

- latest_verdict.json
- latest_benchmark.json

### 5단계: replay 누적

실패한 케이스를 replay_cases.jsonl에 추가

즉, Cambrian은 앞으로
**scan → harness 생성 → 후보 실행 → 판정 → replay 축적**
흐름으로 가야 한다.

## 7. source of truth 구분

### 사람이 관리해야 하는 것

- harness.yaml
- eval_cases.jsonl
- judge_rubric.md
- promotion_policy.json
- rollback_policy.json

### 시스템이 관리해야 하는 것

- latest_verdict.json
- latest_benchmark.json
- run_traces.jsonl
- failure_log.jsonl

### 반자동

- replay_cases.jsonl

이 구분이 안 되면 나중에 파일이 다 섞인다.

## 8. 왜 이런 파일 구조가 필요한가

이유는 단순하다.

**하네스가 코드 안에 숨어 있으면 제품 자산이 안 된다.**

파일로 빠져 있어야:
- 프로젝트별로 다른 기준을 가질 수 있고
- 사람이 보고 수정할 수 있고
- Git으로 추적할 수 있고
- replay가 누적되고
- "왜 merge hold 됐는지" 설명 가능해진다

즉, 하네스는 코드 내부 로직이 아니라
**프로젝트에 붙는 운영 계약 파일 세트** 여야 한다.

## 9. PM 추천 결론

다음 단계는 스킬 추가가 아니라
이 하네스 아티팩트 세트를 실제로 생성하는 bootstrap 흐름을 만드는 게 맞다.

### 바로 다음 Task 추천

1. `.cambrian/harness/` 아티팩트 스펙 확정
2. scan 이후 bootstrap 명령 추가
3. `latest_verdict.json` 출력 계약 정의
4. replay 축적 규칙 정의

## 10. 최종 한 줄

Cambrian의 하네스는 개념이 아니라, **프로젝트 안에 생성되는 검증 운영 파일 세트**다.
