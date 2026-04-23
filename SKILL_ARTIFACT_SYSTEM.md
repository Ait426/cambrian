# SKILL_ARTIFACT_SYSTEM.md

## 1. 목표

Cambrian에서 스킬이 어떤 파일 세트로 존재해야 하는지 정의한다.

이 정의의 목적은 3가지다.

- 스킬을 실행 가능한 후보로 만든다
- 하네스가 스킬을 비교 가능한 대상으로 다룰 수 있게 한다
- search / absorb / fuse / generate가 모두 같은 계약 위에서 움직이게 한다

즉, 스킬은 그냥 코드 폴더가 아니라
**Cambrian이 이해할 수 있는 후보 실행 단위**여야 한다.

## 2. 스킬 한 줄 정의

스킬은 특정 task를 수행할 수 있는 교체 가능한 후보 실행자이며, Cambrian은 이를 실행/비교/평가/승격/격리할 수 있어야 한다.

즉 스킬은:

- 어떤 일을 할 수 있어야 하고
- 어떤 입력을 받아야 하고
- 어떤 출력을 내야 하고
- 어떤 조건에서 실행 가능한지 설명돼 있어야 한다

## 3. 최소 디렉토리 구조

MVP에서는 이 구조면 충분하다.

```
skills/
  <skill_id>/
    meta.yaml
    interface.yaml
    SKILL.md
    execute/
      main.py
```

이 4개가 최소 필수 세트다.

## 4. 파일별 역할

### A. meta.yaml

**역할**: 스킬의 정체성, 상태, 분류, 운영 정보를 담는 파일

**왜 필요한가**: Cambrian은 스킬을 그냥 폴더로 다루지 않고, 비교 대상 / search 대상 / 승격 대상 / 격리 대상으로 다뤄야 한다. 그래서 메타정보가 필요하다.

**최소 필드 추천**:

```yaml
id: pytest_scaffold
name: Pytest Scaffold
version: 1
mode: b
domain: testing
tags:
  - pytest
  - testing
  - python
description: Generate a basic pytest test file for a target Python module.
status: active
```

**추가 운영 필드 추천**:

```yaml
lifecycle:
  total_executions: 0
  successful_executions: 0
  last_used: null
  crystallized_at: null
```

**핵심 원칙**:
- 사람이 읽을 수 있어야 함
- search와 governance가 이 파일을 사용해야 함
- status는 active, candidate, quarantined, newborn 정도로 제한하는 게 좋음

### B. interface.yaml

**역할**: 스킬의 입출력 계약을 정의

**왜 필요한가**: 하네스가 후보를 비교하려면 입력과 출력이 최소한 같은 틀 안에 있어야 한다.

**예시**:

```yaml
input:
  type: object
  required:
    - target_file
  properties:
    target_file:
      type: string
    project_root:
      type: string

output:
  type: object
  required:
    - success
    - artifact_path
  properties:
    success:
      type: boolean
    artifact_path:
      type: string
    summary:
      type: string
```

**핵심 원칙**:
- 하네스는 이 계약을 기준으로 실행 전/후 검증할 수 있어야 함
- 너무 복잡하게 하지 말고 실행 최소 계약만 넣는 게 좋음

### C. SKILL.md

**역할**: 스킬의 의도, 사용 방식, 제약, 품질 기준을 설명

**왜 필요한가**: Mode A에서는 직접 실행 프롬프트 역할을 할 수 있고, Mode B에서도 search/ranking/이해에 도움을 준다.

**들어갈 내용**:
- 무엇을 하는 스킬인지
- 언제 써야 하는지
- 무엇을 하지 않는지
- 기대 출력이 무엇인지
- 실패 조건이 무엇인지

**예시**:

```markdown
# Pytest Scaffold

## Purpose
Generate a starter pytest file for a Python module.

## Use when
- A small Python project lacks tests
- The user wants a starting point, not a full test suite

## Do not use when
- The project is not Python
- The target file is extremely large or dynamic

## Output expectations
- Valid pytest syntax
- At least one meaningful test
- No placeholder-only output
```

**핵심 원칙**:
- 사람도 읽고 모델도 읽을 수 있어야 함
- 마케팅 문서가 아니라 실행 설명서여야 함

### D. execute/main.py

**역할**: 실제 실행 코드

**왜 필요한가**: Mode B 스킬의 본체다.

**기본 계약**:
- JSON 입력 받음
- JSON 출력 반환
- 실패 시 구조화된 에러 출력 가능
- timeout, sandbox, interface 검증과 호환 가능해야 함

**핵심 원칙**:
- side effect는 최소화
- 입력/출력 계약을 깨지 말 것
- 로컬 실행 / sandbox 실행 둘 다 가능해야 함

## 5. 선택적 파일

MVP에서는 필수는 아니지만, 이후 붙일 수 있다.

```
skills/
  <skill_id>/
    examples/
      sample_input.json
      sample_output.json
    tests/
      test_execute.py
    assets/
      templates/
```

**추천 용도**:
- `examples/`: search 결과나 문서에서 예시 제공
- `tests/`: 스킬 단위 회귀 검증
- `assets/`: 템플릿, 고정 문구, 스캐폴드 파일

하지만 처음엔 필수로 두지 않는 게 맞다.

## 6. 스킬의 최소 실행 계약

Cambrian에서 스킬은 최소한 아래 조건을 만족해야 한다.

### 1. 식별 가능

meta.yaml에 id, mode, domain, status가 있어야 함

### 2. 실행 가능

- Mode B면 execute/main.py가 있어야 함
- Mode A면 SKILL.md가 실행 설명서 역할을 해야 함

### 3. 비교 가능

interface.yaml로 입출력 계약이 정의돼 있어야 함

### 4. 검색 가능

meta.yaml + SKILL.md만으로도 search가 어느 정도 의미 있는 결과를 낼 수 있어야 함

즉, 스킬은 단순 코드 파일이 아니라
**식별 + 실행 + 비교 + 검색이 가능한 단위**여야 한다.

## 7. Mode A와 Mode B의 차이

### Mode A 스킬

- 본체는 SKILL.md
- 실행자는 LLM
- execute/main.py가 없을 수 있음

### Mode B 스킬

- 본체는 execute/main.py
- 로컬 코드 실행
- API 키 없이도 동작 가능
- 하네스 E2E 검증에 유리

### 정리

- Mode A = 유연하지만 외부 의존 있음
- Mode B = 안정적이고 로컬 검증 가능

실제 제품 데모/검증/회귀 측면에서는 **Mode B가 하네스 검증 재료로 더 중요**하다.

## 8. 스킬과 하네스의 관계

이게 제일 중요하다.

### 하네스가 스킬에게 요구하는 것

- 같은 task를 수행할 수 있어야 함
- 같은 입력 계약을 이해해야 함
- 결과를 비교할 수 있어야 함
- 실패를 구조적으로 남길 수 있어야 함

### 스킬이 하네스에게 기대하는 것

- 어떤 입력으로 시험받는지
- 어떤 출력이 좋은지
- 어떤 기준으로 승격되는지
- 어떤 실패가 치명적인지

즉, 둘은 분리되지만 **계약으로 연결**된다.

## 9. 추천 스킬 아티팩트 규칙

아래 규칙으로 고정한다.

### 규칙 1

스킬은 하나의 명확한 task만 담당한다

나쁜 예: 테스트도 만들고 README도 쓰고 요약도 하는 스킬

좋은 예:
- pytest 초안 생성
- README 초안 생성
- 프로젝트 요약 생성

### 규칙 2

출력은 가능한 한 **하네스가 비교 가능한 구조**여야 한다

### 규칙 3

metadata는 search와 governance에 충분할 정도로만 넣는다

### 규칙 4

스킬은 자산이 아니라 **후보**라는 관점을 유지한다

즉, 멋지게 만드는 것보다
**Cambrian이 잘 다룰 수 있게 만드는 게 중요**하다.

## 10. MVP에서 필요한 최소 스킬 타입

"스킬을 많이 만들자"가 아니라
하네스 검증용 최소 후보풀만 확보하면 된다.

추천 최소 타입:

1. **testing 계열 1개**: 예) pytest_scaffold
2. **documentation 계열 1개**: 예) readme_generator
3. **project understanding 계열 1개**: 예) project_summary

이 정도면 하네스가 실제 비교/실행/판정을 돌려볼 수 있다.

## 11. source vs generated 구분

### source skill

사람이 만들거나 관리하는 원본 스킬: `skills/`

### acquired/generated/fused skill

시스템이 가져오거나 만든 후보: `skill_pool/`

이 구분은 꼭 있어야 한다.

왜냐하면:
- seed skill은 신뢰도 높은 기본 자산
- generated/fused/acquired는 실험 후보

이기 때문이다.

## 12. 최종 정리

**스킬은 무엇인가**: 프로젝트의 특정 task를 수행하는 교체 가능한 후보 실행자

**스킬 파일 세트는 무엇인가**: `meta.yaml + interface.yaml + SKILL.md + execute/main.py`

**왜 필요한가**: 하네스가 비교/평가/승격/격리할 대상을 제공하기 위해

**무엇이 중요하지 않은가**:
- 스킬 수를 많이 늘리는 것
- 스킬을 제품의 주인공으로 보는 것

**무엇이 중요한가**:
- 하네스가 잘 다룰 수 있는 최소 후보 단위로 만드는 것

## 13. 한 문장 결론

스킬은 하네스가 시험하는 후보 실행자이며, Cambrian에서는 "식별 가능하고, 실행 가능하고, 비교 가능한 파일 세트"로 존재해야 한다.
