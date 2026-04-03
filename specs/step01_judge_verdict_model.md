# STEP 1: JudgeVerdict 모델 추가

> **대상 파일**: `engine/models.py` (수정 1개)
> **신규 파일**: 없음
> **의존성**: 없음 (이 Step이 모든 후속 Step의 기반)

---

## GPT 지시

아래 스펙대로 코드만 출력하라. 설명, 주석 외 산문 없이 코드 블록만 반환하라.

---

## 수정: engine/models.py

### 현재 상태 (Line 127~141)

```python
@dataclass
class EvolutionRecord:
    """진화 시도 기록."""

    id: int
    skill_id: str
    parent_skill_md: str
    child_skill_md: str
    parent_fitness: float
    child_fitness: float
    adopted: bool
    mutation_summary: str
    feedback_ids: str
    created_at: str
```

### 변경 내용

`EvolutionRecord` 클래스 **바로 위**에 `JudgeVerdict` dataclass를 삽입한다.

### 삽입할 코드

```python
@dataclass
class JudgeVerdict:
    """LLM Judge의 비교 채점 결과."""

    original_score: float              # 0.0 ~ 10.0
    variant_score: float               # 0.0 ~ 10.0
    reasoning: str                     # Judge의 채점 근거
    winner: str                        # "original" | "variant" | "tie"
```

### 정확한 삽입 위치

```
Line 125: (빈 줄)
Line 126: (빈 줄)
→ 여기에 JudgeVerdict 삽입
Line 127: @dataclass
Line 128: class EvolutionRecord:
```

### 변경하면 안 되는 것

- 기존 dataclass 전부 (Skill, ExecutionResult, FailureType, SkillNeed, AutopsyReport, EvolutionRecord, BenchmarkEntry, BenchmarkReport) 수정 금지
- import 문 변경 불필요 (dataclass, field, Enum, Path 이미 import됨)
- 파일 끝의 BenchmarkReport 이후 코드 없음 — 건드리지 말 것

### 최종 파일에서 클래스 순서

```
SkillRuntime
SkillLifecycle
Skill
ExecutionResult
FailureType
SkillNeed
AutopsyReport
JudgeVerdict          ← 신규
EvolutionRecord
BenchmarkEntry
BenchmarkReport
```

---

## 호환성

| 항목 | 영향 |
|------|------|
| 기존 import `from engine.models import ...` | **영향 없음** — 새 클래스 추가만, 기존 이름 변경 없음 |
| 기존 테스트 전체 | **영향 없음** — JudgeVerdict를 import하는 코드가 아직 없음 |

---

## 검증 명령 (Sonnet 실행)

```bash
PYTHON="/c/Users/user/AppData/Local/Programs/Python/Python314/python.exe"
cd C:/Users/user/Desktop/cambrain/cambrian

# 1. JudgeVerdict import 가능 확인
PYTHONIOENCODING=utf-8 "$PYTHON" -c "from engine.models import JudgeVerdict; v = JudgeVerdict(original_score=7.0, variant_score=8.5, reasoning='test', winner='variant'); print(f'OK: {v.winner}, {v.original_score}, {v.variant_score}')"

# 2. 기존 모델 import 깨지지 않음 확인
PYTHONIOENCODING=utf-8 "$PYTHON" -c "from engine.models import Skill, ExecutionResult, EvolutionRecord, BenchmarkEntry, BenchmarkReport, FailureType, AutopsyReport; print('All imports OK')"

# 3. 전체 테스트 (기존 통과 기준: 108 passed, 12 skipped)
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/ -v --tb=short -k "not Api" 2>&1 | tail -5
```

### 합격 기준

```
1. JudgeVerdict 인스턴스 생성 성공
2. 기존 7개 모델 전부 import 성공
3. 108 passed, 12 skipped, 0 failed
```
