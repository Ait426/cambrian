# SDD: LLM Judge 기반 진화 시스템 개선

> **Version**: 2.0.0 | **Date**: 2026-04-02
> **Author**: Opus (Architecture) | **Target**: Sonnet / GPT (Implementation)
> **Base**: Cambrian Phase 1 완료 상태 (108 passed, 12 skipped)

---

## 0. 변경 개요

| # | 변경 | 신규/수정 | 영향 파일 |
|---|------|-----------|-----------|
| 1 | LLM Judge 모듈 | **신규** | `engine/judge.py` |
| 2 | evolve() 다중 시행 + Judge 통합 | 수정 | `engine/evolution.py` |
| 3 | JudgeVerdict 모델 | **신규** | `engine/models.py` |
| 4 | fitness에 Judge 점수 반영 | 수정 | `engine/registry.py` |
| 5 | 자가 진화 제안 + --auto-evolve | 수정 | `engine/loop.py`, `engine/cli.py` |
| — | 테스트 | **신규** | `tests/test_judge.py`, 기존 테스트 업데이트 |

**수정 파일 총 6개, 신규 파일 2개.**

---

## 1. 변경 1: LLM Judge 모듈 (engine/judge.py)

### 1.1 목적
두 스킬 출력(원본 vs variant)을 LLM이 **블라인드 채점**하여 품질 점수를 산출한다.
기존 `variant.success` 바이너리 판단을 정량적 점수 비교로 대체.

### 1.2 클래스: SkillJudge

```python
"""Cambrian 스킬 출력 품질 심사기."""

from __future__ import annotations

import json
import logging
import os
import random

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

from engine.models import JudgeVerdict

logger = logging.getLogger(__name__)


class SkillJudge:
    """두 스킬 출력을 익명화(A/B)하여 LLM에게 비교 채점시킨다."""

    def judge(
        self,
        original_output: dict | None,
        variant_output: dict | None,
        skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        """두 출력을 비교 채점한다.

        Args:
            original_output: 원본 스킬의 실행 결과 output dict
            variant_output: variant 스킬의 실행 결과 output dict
            skill_description: 스킬 설명 (meta.yaml description 필드)
            feedback_list: 이번 진화에 사용된 피드백 리스트

        Returns:
            JudgeVerdict

        Raises:
            RuntimeError: anthropic 미설치 또는 API 키 미설정
        """
```

### 1.3 Judge 프롬프트 설계

**시스템 프롬프트**:
```
You are a skill output quality judge for the Cambrian engine.
You receive two outputs (A and B) from the same skill, along with the skill's purpose and user feedback.
Your job: score each output on a 0-10 scale and pick a winner.

Scoring criteria:
1. Correctness: Does the output fulfill the skill's purpose? (0-3 points)
2. Feedback adherence: Does the output address the user feedback? (0-4 points)
3. Quality: Is the output well-structured, detailed, and professional? (0-3 points)

Rules:
- Score each output independently on the 0-10 scale
- If both outputs failed (null/empty), score both 0
- If one output is null/empty and the other is valid, the valid one wins
- Respond with ONLY a JSON object, no explanation
```

**유저 메시지**:
```
## Skill Purpose
{skill_description}

## User Feedback (what needs improvement)
{formatted_feedback}

## Output A
{output_a_json}

## Output B
{output_b_json}
```

**응답 형식**:
```json
{
  "score_a": 7,
  "score_b": 9,
  "reasoning": "Output B addressed the gradient feedback and includes data labels.",
  "winner": "b"
}
```

### 1.4 익명화 로직

```python
    def _build_judge_prompt(
        self,
        original_output: dict | None,
        variant_output: dict | None,
        skill_description: str,
        feedback_list: list[dict],
    ) -> tuple[str, str, bool]:
        """Judge용 프롬프트를 생성한다. A/B 순서를 랜덤화.

        Returns:
            (system_prompt, user_message, swapped)
            swapped=True면 A=variant, B=original
        """
```

**핵심**: `random.choice([True, False])`로 A/B 순서를 랜덤화한다.
- `swapped=False`: A=original, B=variant
- `swapped=True`: A=variant, B=original
- 결과 파싱 시 `swapped` 기준으로 점수를 원래 위치에 매핑

### 1.5 결과 파싱

```python
    def _parse_verdict(
        self,
        response_text: str,
        swapped: bool,
    ) -> JudgeVerdict:
        """LLM 응답에서 JudgeVerdict를 파싱한다.

        JSON 추출 실패 시 tie(5:5) 반환.
        """
```

**파싱 전략**: `executor.py`의 `_extract_json()`과 동일한 3단계 (순수 JSON → 코드블록 → 부분 추출).
코드 중복을 피하려면 `_extract_json`을 유틸리티로 추출하거나, `judge.py` 내부에 동일 로직을 독립 구현한다.

**파싱 실패 시**: `JudgeVerdict(original_score=5, variant_score=5, reasoning="Judge parse failed", winner="tie")`

### 1.6 에러 핸들링

| 상황 | 처리 |
|------|------|
| anthropic 미설치 | `RuntimeError("anthropic package not installed")` |
| API 키 없음 | `RuntimeError("ANTHROPIC_API_KEY not set")` |
| 양쪽 output=None | `JudgeVerdict(0, 0, "Both outputs are empty", "tie")` |
| 한쪽만 None | None 쪽 score=0, 유효한 쪽 score=5, winner=유효한 쪽 |
| LLM 호출 실패 | `logger.warning()` 후 tie(5:5) 반환 (진화를 블록하지 않음) |
| JSON 파싱 실패 | tie(5:5) 반환 |

### 1.7 LLM 호출 상세

```python
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,          # Judge 응답은 짧음
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
```

- **모델**: `claude-sonnet-4-6` (judge는 저비용 모델로 충분)
- **max_tokens**: 1024 (채점 + 1줄 reasoning)
- **temperature**: 기본값 (결정적 채점을 위해 낮은 온도가 이상적이나, anthropic SDK default 사용)

---

## 2. 변경 2: evolve() 다중 시행 + Judge 통합 (engine/evolution.py)

### 2.1 현재 상태 (evolution.py:196-219)

```python
# 현재: 1회 실행, success 바이너리 판단
variant_registered = False
variant_skill = self._loader.load(variant_dir)
variant_result = self._executor.execute(variant_skill, test_input)
original_result = self._executor.execute(original_skill, test_input)
adopted = variant_result.success
child_fitness = 1.0 if variant_result.success else 0.0
```

### 2.2 변경 후 로직

```python
# 변경: 3회 실행 + Judge 채점 + 평균 비교
TRIAL_COUNT = 3

variant_registered = False

# variant를 직접 로드 (registry 등록 불필요)
variant_skill = self._loader.load(variant_dir)

# 다중 시행 실행
original_results: list[ExecutionResult] = []
variant_results: list[ExecutionResult] = []

for _ in range(TRIAL_COUNT):
    orig_result = self._executor.execute(original_skill, test_input)
    var_result = self._executor.execute(variant_skill, test_input)
    original_results.append(orig_result)
    variant_results.append(var_result)

# 원본 lifecycle 갱신 (마지막 결과로 1회만)
self._registry.update_after_execution(skill_id, original_results[-1])

# Judge 채점
judge = SkillJudge()
verdicts: list[JudgeVerdict] = []

for orig_r, var_r in zip(original_results, variant_results):
    verdict = judge.judge(
        original_output=orig_r.output,
        variant_output=var_r.output,
        skill_description=original_skill.description,
        feedback_list=feedback_list,
    )
    verdicts.append(verdict)

# 평균 점수 계산
avg_original = sum(v.original_score for v in verdicts) / len(verdicts)
avg_variant = sum(v.variant_score for v in verdicts) / len(verdicts)

# 채택 기준: variant 평균 > original 평균
adopted = avg_variant > avg_original
child_fitness = avg_variant / 10.0  # 0~10 → 0.0~1.0 정규화

if adopted:
    (original_skill.skill_path / "SKILL.md").write_text(
        child_skill_md, encoding="utf-8"
    )
    logger.info(
        "Evolution adopted for skill '%s' (variant %.1f > original %.1f)",
        skill_id, avg_variant, avg_original,
    )
else:
    logger.info(
        "Evolution discarded for skill '%s' (variant %.1f <= original %.1f)",
        skill_id, avg_variant, avg_original,
    )
```

### 2.3 import 변경 (evolution.py 상단)

```python
# 추가
from engine.judge import SkillJudge
from engine.models import EvolutionRecord, ExecutionResult, JudgeVerdict, Skill
```

### 2.4 EvolutionRecord에 Judge 점수 기록

기존 `mutation_summary` 필드에 Judge 결과를 포함:

```python
judge_summary = (
    f"avg_original={avg_original:.1f}, avg_variant={avg_variant:.1f}, "
    f"trials={TRIAL_COUNT}"
)
mutation_summary = (
    child_skill_md[:150]
    + f"... | Judge: {judge_summary}"
)
```

### 2.5 TRIAL_COUNT 상수

`evolve()` 메서드 상단에 클래스 상수 또는 메서드 내 로컬 상수로 정의:

```python
class SkillEvolver:
    TRIAL_COUNT: int = 3   # 진화 비교 시행 횟수
```

### 2.6 API 호출 비용 분석

| 항목 | 호출 수 | 모델 |
|------|---------|------|
| mutate() | 1회 | claude-sonnet-4-6 |
| original 실행 | 3회 | claude-sonnet-4-6 |
| variant 실행 | 3회 | claude-sonnet-4-6 |
| judge() | 3회 | claude-sonnet-4-6 |
| **합계** | **10회/진화** | — |

기존 대비: 3회 → 10회 (약 3.3배 증가). 예상 비용: $1~2/진화.

---

## 3. 변경 3: JudgeVerdict 모델 (engine/models.py)

### 3.1 추가 위치

`EvolutionRecord` 클래스 바로 위 (Line 128 부근)에 삽입:

```python
@dataclass
class JudgeVerdict:
    """LLM Judge의 비교 채점 결과."""

    original_score: float    # 0.0 ~ 10.0
    variant_score: float     # 0.0 ~ 10.0
    reasoning: str           # Judge의 채점 근거 (1~2문장)
    winner: str              # "original" | "variant" | "tie"
```

### 3.2 검증 규칙

- `original_score`, `variant_score`: 0.0 ~ 10.0 범위. 파싱 시 clamp 처리.
- `winner`: "original", "variant", "tie" 중 하나. 그 외 값은 "tie"로 정규화.
- `reasoning`: 빈 문자열 허용.

---

## 4. 변경 4: fitness에 Judge 점수 반영 (engine/registry.py)

### 4.1 update_after_execution() 시그니처 변경

**현재** (Line 225):
```python
def update_after_execution(self, skill_id: str, result: ExecutionResult) -> None:
```

**변경**:
```python
def update_after_execution(
    self,
    skill_id: str,
    result: ExecutionResult,
    judge_score: float | None = None,
) -> None:
```

- `judge_score`: 0.0~10.0 범위. None이면 기존 로직대로 동작 (하위 호환).
- 기존 호출부 (`loop.py:run_task`, `loop.py:benchmark` 등)는 `judge_score=None`으로 변경 없이 동작.

### 4.2 _calculate_fitness() 시그니처 변경

**현재** (Line 471):
```python
def _calculate_fitness(self, successful: int, total: int) -> float:
```

**변경**:
```python
def _calculate_fitness(
    self,
    successful: int,
    total: int,
    avg_judge_score: float | None = None,
) -> float:
```

### 4.3 새 fitness 공식

```python
def _calculate_fitness(
    self,
    successful: int,
    total: int,
    avg_judge_score: float | None = None,
) -> float:
    """적응도를 계산한다.

    Args:
        successful: 성공 횟수
        total: 전체 실행 횟수
        avg_judge_score: 평균 Judge 점수 (0.0~10.0). None이면 기존 공식.

    Returns:
        계산된 적응도 (0.0~1.0)
    """
    if total == 0:
        return 0.0
    raw = successful / total
    confidence = min(total / 10, 1.0)
    execution_fitness = raw * confidence

    if avg_judge_score is None:
        return round(execution_fitness, 4)

    # 하이브리드: 실행 성공률 50% + Judge 품질 50%
    judge_fitness = avg_judge_score / 10.0  # 0~10 → 0~1 정규화
    combined = execution_fitness * 0.5 + judge_fitness * 0.5
    return round(combined, 4)
```

### 4.4 DB 스키마 변경

**skills 테이블에 컬럼 추가**:

```sql
ALTER TABLE skills ADD COLUMN avg_judge_score REAL DEFAULT NULL;
```

`_create_table()` 메서드의 CREATE TABLE 문에 추가:

```python
# skills 테이블 컬럼 추가 (기존 컬럼 뒤에)
avg_judge_score       REAL DEFAULT NULL,
```

### 4.5 update_after_execution() 내부 변경

```python
def update_after_execution(
    self,
    skill_id: str,
    result: ExecutionResult,
    judge_score: float | None = None,
) -> None:
    current = self.get(skill_id)
    total_executions = current["total_executions"] + 1
    successful_executions = current["successful_executions"] + int(result.success)
    last_used = datetime.now(timezone.utc).isoformat()

    # Judge 점수 이동 평균 (Exponential Moving Average)
    existing_judge = current.get("avg_judge_score")
    if judge_score is not None:
        if existing_judge is None:
            new_avg_judge = judge_score
        else:
            # EMA: 새 점수에 30% 가중, 기존 평균에 70% 가중
            new_avg_judge = existing_judge * 0.7 + judge_score * 0.3
    else:
        new_avg_judge = existing_judge

    fitness_score = self._calculate_fitness(
        successful_executions,
        total_executions,
        new_avg_judge,
    )

    self._conn.execute(
        """
        UPDATE skills
        SET total_executions = ?,
            successful_executions = ?,
            fitness_score = ?,
            last_used = ?,
            avg_judge_score = ?
        WHERE id = ?
        """,
        (
            total_executions,
            successful_executions,
            fitness_score,
            last_used,
            new_avg_judge,
            skill_id,
        ),
    )
    self._conn.commit()
```

### 4.6 _row_to_dict() 업데이트

`avg_judge_score`가 새 컬럼이므로, `_row_to_dict()`에서 특별 처리 불필요 (SQLite Row가 자동 포함). 단, 검색 결과에 `avg_judge_score` 필드가 노출됨.

### 4.7 하위 호환

| 기존 호출부 | 변경 필요 | 이유 |
|------------|-----------|------|
| `loop.py:run_task()` → `update_after_execution(skill_id, result)` | **없음** | `judge_score=None` 기본값 |
| `loop.py:benchmark()` → `update_after_execution(entry.skill_id, ...)` | **없음** | 동일 |
| `evolution.py:evolve()` → `update_after_execution(skill_id, original_results[-1])` | **선택** | Judge 점수 전달 가능 |
| `tests/*` → 모든 기존 update_after_execution 호출 | **없음** | 기본값으로 동작 |

---

## 5. 변경 5: 자가 진화 제안 (engine/loop.py, engine/cli.py)

### 5.1 run_task() 수정 (loop.py)

**현재 흐름**: 실행 결과 반환 후 종료.

**추가 로직**: 실행 성공/실패 무관하게, 사용된 스킬의 fitness를 확인.

```python
def run_task(
    self,
    domain: str,
    tags: list[str],
    input_data: dict,
    max_retries: int = 3,
) -> ExecutionResult:
    # ... 기존 루프 로직 ...

    # === 신규: 진화 제안 체크 ===
    if result.success and result.skill_id:
        try:
            skill_data = self._registry.get(result.skill_id)
            if skill_data["fitness_score"] < 0.3 and skill_data["mode"] == "a":
                logger.info(
                    "Evolution suggested for skill '%s' "
                    "(fitness=%.4f < 0.3)",
                    result.skill_id,
                    skill_data["fitness_score"],
                )
                self._evolution_suggested = result.skill_id
        except Exception:
            pass  # 제안 실패는 무시

    return result
```

**`_evolution_suggested` 인스턴스 변수 추가**:

```python
class CambrianEngine:
    def __init__(self, ...):
        # ... 기존 초기화 ...
        self._evolution_suggested: str | None = None  # 진화 제안 스킬 ID
```

**진화 제안 조회 메서드**:

```python
    def get_evolution_suggestion(self) -> str | None:
        """run_task 후 진화가 제안된 스킬 ID를 반환한다.

        Returns:
            스킬 ID 또는 None
        """
        suggestion = self._evolution_suggested
        self._evolution_suggested = None  # 1회 소비
        return suggestion
```

### 5.2 CLI --auto-evolve 플래그 (cli.py)

**run_parser에 인자 추가**:

```python
run_parser.add_argument(
    "--auto-evolve",
    action="store_true",
    help="fitness < 0.3인 스킬에 자동 진화 실행",
)
```

**_handle_run() 수정**:

```python
def _handle_run(args: argparse.Namespace) -> None:
    # ... 기존 실행 로직 ...

    # 실행 결과 출력 후
    if result.success:
        print("[OK] Success")
        # ... 기존 출력 ...
    else:
        print("[FAIL] Failed")
        # ... 기존 출력 ...
        sys.exit(1)

    # === 신규: auto-evolve ===
    if getattr(args, "auto_evolve", False) and result.success:
        suggestion = engine.get_evolution_suggestion()
        if suggestion:
            print(f"\n[EVOLVE] fitness < 0.3 — auto-evolving '{suggestion}'...")
            try:
                input_data = json.loads(args.input)
                record = engine.evolve(suggestion, input_data)
                status = "adopted" if record.adopted else "discarded"
                print(f"[EVOLVE] Evolution {status}")
                print(f"  Parent fitness: {record.parent_fitness:.4f}")
                print(f"  Child fitness:  {record.child_fitness:.4f}")
            except RuntimeError as exc:
                print(f"[EVOLVE] Skipped: {exc}")
```

### 5.3 auto-evolve 전제 조건

| 조건 | 충족해야 |
|------|---------|
| `--auto-evolve` 플래그 있음 | 필수 |
| `result.success == True` | 필수 (실패한 태스크는 진화 불가) |
| `fitness_score < 0.3` | 필수 |
| `mode == "a"` | 필수 (Mode B는 진화 불가) |
| 피드백 1건 이상 존재 | 필수 (없으면 RuntimeError → Skipped) |
| `ANTHROPIC_API_KEY` 설정 | 필수 (없으면 RuntimeError) |

---

## 6. 파일별 수정 명세 종합

### 6.1 신규 파일

| 파일 | 줄 수 (예상) | 내용 |
|------|-------------|------|
| `engine/judge.py` | ~150줄 | SkillJudge 클래스 |
| `tests/test_judge.py` | ~200줄 | Judge 단위 테스트 |

### 6.2 수정 파일

| 파일 | 수정 위치 | 변경 내용 |
|------|-----------|-----------|
| `engine/models.py` | Line 128 부근 | `JudgeVerdict` dataclass 추가 |
| `engine/evolution.py` | Lines 19-21 (import) | `SkillJudge`, `JudgeVerdict` import 추가 |
| `engine/evolution.py` | Lines 196-219 (evolve 내부) | 다중 시행 + Judge 로직으로 교체 |
| `engine/registry.py` | Lines 225-263 (update_after_execution) | `judge_score` 파라미터 추가 |
| `engine/registry.py` | Lines 471-485 (_calculate_fitness) | `avg_judge_score` 파라미터 + 하이브리드 공식 |
| `engine/registry.py` | Lines 28-53 (_create_table) | `avg_judge_score` 컬럼 추가 |
| `engine/registry.py` | Lines 244-260 (UPDATE SQL) | `avg_judge_score` 포함 |
| `engine/loop.py` | Lines 26-31 (__init__) | `_evolution_suggested` 변수 추가 |
| `engine/loop.py` | Lines 79-179 (run_task) | 종료 전 fitness 체크 + 제안 로직 |
| `engine/loop.py` | 신규 메서드 | `get_evolution_suggestion()` 추가 |
| `engine/cli.py` | Lines 67-86 (run_parser) | `--auto-evolve` 인자 추가 |
| `engine/cli.py` | Lines 240-272 (_handle_run) | auto-evolve 후처리 추가 |

### 6.3 수정하지 않는 파일

| 파일 | 이유 |
|------|------|
| `engine/validator.py` | 스킬 포맷 무관 |
| `engine/loader.py` | 스킬 로드 무관 |
| `engine/security.py` | 보안 스캔 무관 |
| `engine/absorber.py` | 흡수 로직 무관 |
| `engine/autopsy.py` | 실패 분석 무관 |
| `engine/benchmark.py` | 독립 벤치마크 무관 (Judge와 별개) |
| `engine/exceptions.py` | 새 예외 불필요 (Judge는 fallback으로 처리) |
| `schemas/*` | 스키마 수정 금지 규칙 |

---

## 7. 테스트 명세

### 7.1 신규: tests/test_judge.py

```python
# === 단위 테스트 ===

def test_judge_both_valid_outputs():
    """양쪽 모두 유효한 출력 → 0~10 점수 반환."""

def test_judge_one_null_output():
    """한쪽 output=None → None 쪽 score=0."""

def test_judge_both_null_outputs():
    """양쪽 모두 None → tie(0, 0)."""

def test_judge_anonymization_swapped():
    """A/B 순서가 랜덤화되는지 검증 (seed 고정)."""

def test_judge_parse_valid_json():
    """정상 JSON 응답 파싱."""

def test_judge_parse_code_block():
    """```json 코드블록 응답 파싱."""

def test_judge_parse_failure_returns_tie():
    """파싱 실패 → tie(5, 5)."""

def test_judge_score_clamping():
    """score > 10 또는 < 0 → clamp."""

def test_judge_winner_normalization():
    """winner가 a/b → original/variant 변환."""

def test_judge_api_key_missing():
    """ANTHROPIC_API_KEY 없으면 RuntimeError."""

def test_judge_anthropic_not_installed():
    """anthropic 미설치 → RuntimeError."""

def test_judge_llm_call_failure_returns_tie():
    """LLM 호출 예외 → tie(5, 5) fallback."""
```

**Mock 패턴**: `evolution.py`의 `_FakeAnthropic` 패턴 재사용.

### 7.2 수정: tests/test_evolution.py

```python
# === 기존 테스트 수정 ===

def test_evolve_adopted():
    """변경: fake_execute를 3회 호출 대응 + fake_judge mock 추가."""
    # monkeypatch: SkillJudge.judge → variant_score=8, original_score=5

def test_evolve_discarded():
    """변경: variant 실패 시에도 Judge가 호출되는지 (output=None)."""
    # monkeypatch: SkillJudge.judge → variant_score=0, original_score=7

# === 신규 테스트 ===

def test_evolve_trial_count():
    """executor.execute가 정확히 6회 호출되는지 (원본3 + variant3)."""

def test_evolve_judge_called_per_trial():
    """SkillJudge.judge가 정확히 3회 호출되는지."""

def test_evolve_average_scoring():
    """Judge 점수 평균 계산이 올바른지."""

def test_evolve_tie_not_adopted():
    """variant 평균 == original 평균이면 adopted=False."""
```

### 7.3 수정: tests/test_e2e_evolution.py

```python
# TestMockE2EEvolution._setup_mocks() 수정:
# - fake_execute가 TRIAL_COUNT*2회 호출에 대응하도록 변경
# - SkillJudge.judge mock 추가: variant가 항상 이기도록 설정

# test_fitness_accumulates_across_evolutions() 수정:
# - update_after_execution은 evolve당 1회만 호출됨 (원본 마지막 결과)
# - total_executions 증가 확인 유지
```

### 7.4 수정: tests/test_registry.py

```python
# === 신규 테스트 ===

def test_fitness_with_judge_score():
    """judge_score 전달 시 하이브리드 fitness 계산."""

def test_fitness_without_judge_score():
    """judge_score=None이면 기존 공식 동작 (하위 호환)."""

def test_judge_score_ema():
    """avg_judge_score가 EMA(0.7/0.3)로 갱신되는지."""

def test_avg_judge_score_column_exists():
    """skills 테이블에 avg_judge_score 컬럼 존재."""
```

### 7.5 수정: tests/test_cli.py 또는 tests/test_cli_evolution.py

```python
# === 신규 테스트 ===

def test_auto_evolve_flag_accepted():
    """--auto-evolve 플래그가 파싱되는지."""
```

### 7.6 테스트 수 예측

| 카테고리 | 신규 | 수정 | 합계 |
|---------|------|------|------|
| test_judge.py | 12 | 0 | 12 |
| test_evolution.py | 4 | 2 | 6 |
| test_e2e_evolution.py | 0 | 4 | 4 |
| test_registry.py | 4 | 0 | 4 |
| test_cli*.py | 1 | 0 | 1 |
| **합계** | **21** | **6** | **27** |

---

## 8. 구현 순서

순환 의존 없이 빌드하기 위한 추천 순서:

```
Step 1: models.py — JudgeVerdict 추가
        (의존성 없음, 다른 모듈이 import)

Step 2: judge.py — SkillJudge 신규 생성
        (models.py만 의존)

Step 3: tests/test_judge.py — Judge 단위 테스트
        (judge.py 검증)

Step 4: registry.py — fitness 공식 변경 + DB 스키마
        (models.py만 의존, 하위 호환)

Step 5: tests/test_registry.py — fitness 테스트 추가
        (registry.py 검증)

Step 6: evolution.py — evolve() 다중 시행 + Judge 통합
        (judge.py, models.py, registry.py 의존)

Step 7: tests/test_evolution.py + test_e2e_evolution.py 수정
        (evolution.py 검증)

Step 8: loop.py — 자가 진화 제안
        (registry.py만 의존)

Step 9: cli.py — --auto-evolve 플래그
        (loop.py만 의존)

Step 10: 전체 테스트 실행
         pytest tests/ -v --tb=short -k "not Api"
```

---

## 9. 데이터 흐름 변경 다이어그램

### 9.1 변경 후 진화 흐름

```
User → engine.evolve(skill_id, test_input)
         │
         ├─→ SkillEvolver.mutate() → child_skill_md
         │
         ├─→ variant 디렉토리 생성
         │
         ├─→ [Trial 1..3]
         │     ├─→ executor.execute(original, test_input) → orig_result
         │     └─→ executor.execute(variant, test_input)  → var_result
         │
         ├─→ [Judge 1..3]
         │     └─→ SkillJudge.judge(orig.output, var.output, desc, feedback)
         │           → JudgeVerdict(original_score, variant_score, ...)
         │
         ├─→ avg_variant = mean(verdicts.variant_score)
         │   avg_original = mean(verdicts.original_score)
         │
         ├─→ adopted = (avg_variant > avg_original)
         │     ├─ True  → SKILL.md 덮어쓰기
         │     └─ False → 변경 없음
         │
         ├─→ registry.update_after_execution(skill_id, last_orig, judge_score=avg_original)
         │
         ├─→ registry.add_evolution_record(record)
         │
         └─→ finally: variant 정리
```

### 9.2 변경 후 fitness 흐름

```
update_after_execution(skill_id, result, judge_score=7.5)
    │
    ├─→ total_executions += 1
    ├─→ successful_executions += int(result.success)
    │
    ├─→ avg_judge_score = EMA(existing * 0.7 + new * 0.3)
    │
    └─→ _calculate_fitness(successful, total, avg_judge_score)
          │
          ├─→ execution_fitness = (success_rate) × confidence
          ├─→ judge_fitness = avg_judge_score / 10.0
          └─→ combined = execution_fitness × 0.5 + judge_fitness × 0.5
```

---

## 10. 하위 호환 체크리스트

| 기존 동작 | 보존 여부 | 방법 |
|-----------|-----------|------|
| `update_after_execution(id, result)` 2인자 호출 | **보존** | `judge_score=None` 기본값 |
| `_calculate_fitness(successful, total)` 2인자 호출 | **보존** | `avg_judge_score=None` 기본값 |
| Mode B 스킬 evolve 거부 | **보존** | `if mode != "a": raise` 유지 |
| benchmark.py의 독립 벤치마크 | **보존** | Judge와 무관 |
| CLI 기존 명령어 | **보존** | `--auto-evolve`는 선택 플래그 |
| SQLite 기존 DB 열기 | **주의** | `avg_judge_score` 컬럼 없는 DB → NULL 기본값으로 처리 |
| 피드백 없이 evolve 거부 | **보존** | `loop.py:evolve()` 사전 검사 유지 |
| API 키 없이 graceful fail | **보존** | Judge도 RuntimeError → evolve 전파 |

---

## 11. 위험 및 완화

| 위험 | 영향 | 완화 |
|------|------|------|
| Judge LLM 호출 실패 | 진화 블록 | fallback tie(5:5) → 점수 동점 → 미채택 (안전) |
| 10회 API 호출 비용 | $1~2/진화 | TRIAL_COUNT를 설정 가능하게 하면 좋지만, 현 단계에서는 상수 |
| EMA가 초기에 불안정 | 첫 Judge 점수가 과대 반영 | 기존 fitness가 None이면 첫 점수 그대로 사용 (설계대로) |
| DB 마이그레이션 | 기존 DB에 컬럼 없음 | `_create_table`의 CREATE IF NOT EXISTS + NULL 기본값으로 처리 |
| Judge 프롬프트 편향 | A 또는 B 위치 선호 | 랜덤 스왑으로 완화 |
