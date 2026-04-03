# Cambrian SDD (Software Design Document)

> **Version**: 1.0.0 | **Date**: 2026-04-02
> **Author**: Opus (Architecture Review) | **Target**: Sonnet (Implementation)
> **Status**: Phase 1 Complete

---

## 1. System Overview

### 1.1 목적
Cambrian은 **자가 진화 AI 스킬 엔진**이다.
AI 에이전트가 태스크 실행에 실패하면, 외부 스킬을 탐색/흡수하거나
기존 스킬의 instruction(SKILL.md)을 LLM으로 변이시켜 스스로 강화되는 시스템.

### 1.2 핵심 루프
```
Task 입력 → Registry 검색 → Executor 실행 → 성공? → 결과 반환
                                    ↓ 실패
                              Autopsy 분석
                                    ↓
                    ┌───────────────┼───────────────┐
              외부 흡수(Absorber)   재시도        진화(Evolver)
                    ↓                               ↓
              SecurityScan              mutate(LLM) → 비교 → 채택/폐기
                    ↓
              skill_pool/ 등록
```

### 1.3 기술 스택
| 항목 | 선택 | 이유 |
|------|------|------|
| Language | Python 3.11+ | 타입 힌트, match문, 빠른 프로토타이핑 |
| DB | SQLite (직접 SQL) | ORM 오버헤드 없이 단일 파일 DB |
| Schema | jsonschema (Draft7) | 스킬 포맷 검증 표준화 |
| YAML | pyyaml | 스킬 메타데이터 파싱 |
| LLM | anthropic SDK (선택) | Mode A 실행 + 진화 변이 |
| Test | pytest | 표준 테스트 프레임워크 |
| Sandbox | subprocess + timeout | Phase 1 경량 격리 (Docker는 Phase 2) |

---

## 2. Architecture

### 2.1 모듈 의존성 그래프
```
                          cli.py
                            │
                         loop.py (CambrianEngine)
                       ┌────┼────────┬──────────┐
                       │    │        │          │
                  absorber.py   evolution.py  benchmark.py
                       │    │        │          │
                       │  ┌─┴────────┴──────────┘
                       │  │
                  security.py  executor.py ←── anthropic SDK (선택)
                       │       │
                  loader.py ───┘
                       │
                  validator.py
                       │
                  models.py + exceptions.py
```

### 2.2 계층 구조
| Layer | 모듈 | 역할 |
|-------|------|------|
| **Presentation** | `cli.py` | argparse CLI, 11개 명령어 |
| **Orchestration** | `loop.py` | CambrianEngine: 전체 루프 조율 |
| **Domain Logic** | `evolution.py`, `benchmark.py`, `autopsy.py`, `absorber.py` | 진화/비교/분석/흡수 |
| **Execution** | `executor.py` | Mode A(LLM)/Mode B(subprocess) 실행 |
| **Data Access** | `registry.py` | SQLite CRUD + 검색 + fitness 계산 |
| **Foundation** | `loader.py`, `validator.py`, `security.py` | 검증/로드/보안 |
| **Shared** | `models.py`, `exceptions.py` | 도메인 객체, 커스텀 예외 |

---

## 3. Module Design

### 3.1 models.py — 도메인 객체

```python
@dataclass
class SkillRuntime:
    language: str                    # "python"
    needs_network: bool = False
    needs_filesystem: bool = False
    timeout_seconds: int = 30

@dataclass
class SkillLifecycle:
    status: str = "newborn"          # active | newborn | dormant | fossil
    fitness_score: float = 0.0       # 0.0 ~ 1.0
    total_executions: int = 0
    successful_executions: int = 0
    last_used: str | None = None
    crystallized_at: str | None = None

@dataclass
class Skill:
    id: str                          # ^[a-z][a-z0-9_]{1,63}$
    version: str                     # SemVer (1.0.0)
    name: str
    description: str
    domain: str                      # "utility", "data_visualization" 등
    tags: list[str]
    mode: str                        # "a" (LLM) | "b" (subprocess)
    runtime: SkillRuntime
    lifecycle: SkillLifecycle
    skill_path: Path                 # 스킬 디렉토리 절대 경로
    interface_input: dict = {}       # JSON Schema
    interface_output: dict = {}      # JSON Schema
    skill_md_content: str | None = None
    author: str | None = None
    license: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

@dataclass
class ExecutionResult:
    skill_id: str
    success: bool
    output: dict | None = None
    error: str = ""
    stderr: str = ""
    exit_code: int = 0
    execution_time_ms: int = 0
    mode: str = "b"

class FailureType(Enum):
    SKILL_MISSING = "skill_missing"
    EXECUTION_ERROR = "execution_error"
    TIMEOUT = "timeout"
    INPUT_MISMATCH = "input_mismatch"
    OUTPUT_INVALID = "output_invalid"
    UNKNOWN = "unknown"

@dataclass
class AutopsyReport:
    skill_id: str
    failure_type: FailureType
    root_cause: str
    stderr_summary: str
    recommendation: str
    needed_skill: SkillNeed | None = None
    retry_suggested: bool = False
    fitness_penalty: float = 0.0

@dataclass
class EvolutionRecord:
    id: int
    skill_id: str
    parent_skill_md: str
    child_skill_md: str
    parent_fitness: float
    child_fitness: float
    adopted: bool
    mutation_summary: str
    feedback_ids: str                # JSON array
    created_at: str

@dataclass
class BenchmarkEntry:
    skill_id: str
    success: bool
    output: dict | None
    error: str
    execution_time_ms: int
    fitness_score: float
    mode: str
    rank: int = 0

@dataclass
class BenchmarkReport:
    entries: list[BenchmarkEntry]
    best_skill_id: str | None
    total_candidates: int
    successful_count: int
    domain: str
    tags: list[str]
    timestamp: str
```

### 3.2 exceptions.py — 예외 계층

```
CambrianError (base)
├── SkillLoadError(skill_path, reason)
├── SkillValidationError(skill_path, errors: list[str])
├── SkillExecutionError(skill_id, reason, stderr)
├── SkillNotFoundError(query)
└── SecurityViolationError(skill_path, violations: list[str])
```

### 3.3 validator.py — 스킬 포맷 검증

**SkillValidator(schemas_dir)**
- `validate(skill_dir) → ValidationResult`
  - 5단계 순서: 필수 파일 존재 → YAML 파싱 → JSON Schema 검증 → mode별 execute 체크 → AST run() 확인
- `validate_meta(meta_path) → list[str]`
- `validate_interface(interface_path) → list[str]`

### 3.4 loader.py — 스킬 로드

**SkillLoader(schemas_dir)**
- `load(skill_dir) → Skill`: 단일 스킬 로드 (검증 → 파싱 → 객체 생성)
- `load_directory(base_dir) → list[Skill]`: 디렉토리 전체 로드 (실패 스킬 skip)
- 내부: `_parse_yaml()`, `_build_runtime()`, `_build_lifecycle()`, `_filter_validation_errors()`

**설계 결정**:
- mode "a" 스킬은 lifecycle 블록 생략 가능 (기본값 적용)
- SKILL.md가 있으면 내용을 `skill_md_content`에 로드

### 3.5 executor.py — 실행기

**SkillExecutor**
- `execute(skill, input_data) → ExecutionResult`
  - **Mode B**: `subprocess.run([python, main.py], input=json, timeout=N)`
    - stdin: JSON → stdout: JSON
    - 타임아웃 → exit_code=-1
    - JSON 파싱 실패 → success=False
  - **Mode A**: `Anthropic.messages.create(model="claude-sonnet-4-6", system=SKILL.md, ...)`
    - `_extract_json(text)`: 순수 JSON → 코드블록 → 부분 추출 → fallback `{"raw_output": text}`
    - API 키 없음/패키지 미설치 → graceful failure (success=False)
- `validate_input(skill, data) → list[str]`
- `validate_output(skill, data) → list[str]`

### 3.6 registry.py — 스킬 레지스트리

**SkillRegistry(db_path=":memory:")**

| 메서드 | 설명 |
|--------|------|
| `register(skill)` | INSERT OR REPLACE |
| `unregister(skill_id)` | DELETE + SkillNotFoundError |
| `get(skill_id) → dict` | SELECT by PK |
| `search(domain, tags, status, mode, min_fitness) → list[dict]` | 복합 WHERE + ORDER BY fitness DESC |
| `list_all() → list[dict]` | 전체 목록 |
| `count() → int` | 총 개수 |
| `update_after_execution(skill_id, result)` | 실행 통계 + fitness 재계산 |
| `update_status(skill_id, new_status)` | 상태 변경 (4종 유효성 검사) |
| `add_feedback(skill_id, rating, comment, ...) → int` | 피드백 저장 |
| `get_feedback(skill_id, limit=10) → list[dict]` | 최신순 피드백 |
| `add_evolution_record(record) → int` | 진화 기록 저장 |
| `get_evolution_history(skill_id, limit=10) → list[dict]` | 진화 이력 |
| `get_feedback_by_ids(ids) → list[dict]` | ID 기반 피드백 조회 |

**Fitness 공식**:
```python
fitness = (successful / total) * min(total / 10, 1.0)
```
- 성공률 × 신뢰도(최소 10회 실행 시 100%)
- 실행 0회 → fitness=0.0

### 3.7 security.py — 보안 스캐너

**SecurityScanner**
- `scan_file(file_path, needs_network=False) → list[str]`
- `scan_skill(skill_dir, needs_network=False) → list[str]`

| 금지 항목 | 목록 |
|-----------|------|
| **호출** | eval, exec, compile, \_\_import\_\_, globals, locals, getattr, setattr, delattr |
| **import** | subprocess, os, shutil, socket, ctypes, importlib, pickle, shelve, marshal, code, codeop, compileall |
| **네트워크** (needs_network=False 시) | requests, httpx, urllib, aiohttp, http, socket, ftplib, smtplib, xmlrpc |

### 3.8 absorber.py — 외부 스킬 흡수

**SkillAbsorber(schemas_dir, skill_pool_dir, registry)**
- `absorb(source_path) → Skill`
  1. Validator → 포맷 검증
  2. Loader → 스킬 로드
  3. SecurityScanner → 보안 검사
  4. `shutil.copytree()` → skill_pool/{id}/ 복사
  5. Reload → Registry 등록
- `is_absorbed(skill_id) → bool`
- `remove(skill_id)`: 파일 삭제 + Registry 해제

### 3.9 autopsy.py — 실패 분석

**Autopsy**
- `analyze(result, skill, task_description) → AutopsyReport`
- `_classify(result, skill) → FailureType`

| 조건 | FailureType | fitness_penalty |
|------|-------------|----------------|
| skill=None | SKILL_MISSING | 0.0 |
| exit_code=-1 | TIMEOUT | 0.3 |
| stderr에 TypeError/KeyError/ValidationError | INPUT_MISMATCH | 0.1 |
| stderr에 ValueError/ModuleNotFoundError 등 | EXECUTION_ERROR | 0.2~0.5 |
| "Invalid JSON output" | OUTPUT_INVALID | 0.2 |
| 기타 | UNKNOWN | 0.1 |

### 3.10 benchmark.py — 벤치마크 러너

**SkillBenchmark(loader, executor)**
- `run(candidates, input_data, domain, tags) → BenchmarkReport`
  - 모든 후보를 동일 입력으로 실행
  - 순위 기준: `(not success, -fitness_score, execution_time_ms)`
- `_rank(entries) → list[BenchmarkEntry]`

### 3.11 evolution.py — 진화 코어

**SkillEvolver(loader, executor, registry)**

#### mutate(skill, feedback_list) → str
1. 시스템 프롬프트: "SKILL.md를 개선하라. Output Format 섹션 보존 필수"
2. 피드백을 "Rating: N/5 | Comment: ..." 형식으로 포맷
3. Claude claude-sonnet-4-6 호출 → 개선된 SKILL.md 반환
4. JSON 출력 지시 검증 (없으면 원본 Output Format 섹션 append)

#### evolve(skill_id, test_input, feedback_list) → EvolutionRecord
```
1. 원본 스킬 로드 (mode "a"만 허용)
2. mutate() → child_skill_md 생성
3. variant 디렉토리 생성 (copytree + SKILL.md 교체 + meta.yaml id 변경)
4. variant 직접 실행 (executor.execute)
5. 원본도 실행 (lifecycle 통계 갱신용)
6. 채택 기준: variant.success == True → 채택
7. 채택 시: 원본 SKILL.md를 child_skill_md로 덮어쓰기
8. EvolutionRecord 저장
9. finally: variant 디렉토리 정리 (shutil.rmtree)
```

### 3.12 loop.py — 메인 오케스트레이터

**CambrianEngine(schemas_dir, skills_dir, skill_pool_dir, db_path, external_skill_dirs)**

#### run_task(domain, tags, input_data, max_retries=3) → ExecutionResult
```
attempt = 0
while attempt <= max_retries:
    candidates = registry.search(active) + registry.search(newborn)
    
    if no candidates:
        absorbed = _try_absorb_from_external(domain, tags)
        if absorbed: attempt++; continue
        else: return FAIL("No matching skill found")
    
    for candidate in candidates:
        result = executor.execute(skill, input_data)
        registry.update_after_execution(skill_id, result)
        
        if result.success:
            return result  # 성공!
        
        report = autopsy.analyze(result, skill)
        if report.failure_type == SKILL_MISSING:
            _try_absorb_from_external()
        
    attempt++
    
return last_result  # 최종 실패
```

#### 기타 메서드
| 메서드 | 설명 |
|--------|------|
| `feedback(skill_id, rating, comment, input_data, output_data) → int` | 피드백 저장 |
| `evolve(skill_id, test_input) → EvolutionRecord` | 1회 진화 (피드백 필수) |
| `benchmark(domain, tags, input_data) → BenchmarkReport` | 다수 스킬 비교 실행 |
| `list_skills() → list[dict]` | 전체 스킬 목록 |
| `get_skill_count() → int` | 등록 스킬 수 |
| `get_registry() → SkillRegistry` | 테스트/디버깅용 |

### 3.13 cli.py — CLI 인터페이스

| 명령어 | 설명 | 주요 옵션 |
|--------|------|-----------|
| `run` | 태스크 실행 | --domain, --tags, --input (JSON), --retries |
| `skills` | 스킬 목록 | — |
| `skill <id>` | 상세 정보 | — |
| `absorb <path>` | 외부 스킬 흡수 | — |
| `remove <id>` | 흡수 스킬 제거 | — |
| `stats` | 엔진 통계 | — |
| `benchmark` | 벤치마크 실행 | --domain, --tags, --input |
| `feedback <id> <rating> <comment>` | 피드백 저장 | — |
| `evolve <id>` | 1회 진화 | --input (JSON) |
| `history <id>` | 진화 이력 | --limit |
| `rollback <id> <record_id>` | SKILL.md 롤백 | — |

공통 옵션: `--db`, `--schemas`, `--skills`, `--pool`, `--external`, `--verbose`

---

## 4. Database Schema

### 4.1 skills 테이블
```sql
CREATE TABLE skills (
    id                    TEXT PRIMARY KEY,
    version               TEXT NOT NULL,
    name                  TEXT NOT NULL,
    description           TEXT NOT NULL,
    domain                TEXT NOT NULL,
    tags                  TEXT NOT NULL,          -- JSON array
    mode                  TEXT NOT NULL,          -- "a" | "b"
    language              TEXT NOT NULL,
    needs_network         INTEGER NOT NULL DEFAULT 0,
    needs_filesystem      INTEGER NOT NULL DEFAULT 0,
    timeout_seconds       INTEGER NOT NULL DEFAULT 30,
    skill_path            TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'newborn',
    fitness_score         REAL NOT NULL DEFAULT 0.0,
    total_executions      INTEGER NOT NULL DEFAULT 0,
    successful_executions INTEGER NOT NULL DEFAULT 0,
    last_used             TEXT,                   -- ISO 8601
    crystallized_at       TEXT,                   -- ISO 8601
    registered_at         TEXT NOT NULL           -- ISO 8601
);
```

### 4.2 feedback 테이블
```sql
CREATE TABLE feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id    TEXT NOT NULL,
    rating      INTEGER NOT NULL,    -- 1~5
    comment     TEXT NOT NULL DEFAULT '',
    input_data  TEXT NOT NULL DEFAULT '{}',
    output_data TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL         -- ISO 8601
);
```

### 4.3 evolution_history 테이블
```sql
CREATE TABLE evolution_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id         TEXT NOT NULL,
    parent_skill_md  TEXT NOT NULL,
    child_skill_md   TEXT NOT NULL,
    parent_fitness   REAL NOT NULL DEFAULT 0.0,
    child_fitness    REAL NOT NULL DEFAULT 0.0,
    adopted          INTEGER NOT NULL DEFAULT 0,
    mutation_summary TEXT NOT NULL DEFAULT '',
    feedback_ids     TEXT NOT NULL DEFAULT '[]',  -- JSON array
    created_at       TEXT NOT NULL                 -- ISO 8601
);
```

---

## 5. Skill Format Specification

### 5.1 디렉토리 구조
```
<skill_id>/
├── meta.yaml          # 필수: 식별/런타임/생명주기
├── interface.yaml     # 필수: 입출력 JSON Schema
├── SKILL.md           # 필수: Mode A는 LLM 프롬프트, Mode B는 문서
└── execute/
    └── main.py        # Mode B만 필수: run(input_data) -> dict
```

### 5.2 Mode A vs Mode B

| 항목 | Mode A (LLM) | Mode B (Subprocess) |
|------|-------------|---------------------|
| 실행 방식 | SKILL.md = system prompt | execute/main.py subprocess |
| 입력 전달 | JSON user message | stdin JSON |
| 출력 수집 | LLM 응답에서 JSON 추출 | stdout JSON |
| 진화 가능 | **가능** (SKILL.md 변이) | 불가 |
| execute/ 필요 | 불필요 | **필수** |
| 비용 | API 호출 비용 | 무료 |

### 5.3 시드 스킬 6개

| Skill ID | Mode | Domain | 용도 |
|----------|------|--------|------|
| hello_world | B | utility | 기본 동작 테스트 |
| slow_skill | B | utility | 타임아웃 테스트 |
| crash_skill | B | utility | 오류 처리 테스트 |
| csv_to_chart | A | data_visualization | CSV → HTML Chart |
| json_to_dashboard | A | data_visualization | JSON → Dashboard |
| landing_page | A | design | 랜딩 페이지 생성 |

---

## 6. Data Flow

### 6.1 태스크 실행 흐름
```
User/Agent
    │
    ▼
CambrianEngine.run_task(domain, tags, input_data)
    │
    ├─→ Registry.search(domain, tags, status=active|newborn)
    │       │
    │       ├─ 후보 있음 ──→ Loader.load(skill_path)
    │       │                     │
    │       │                     ▼
    │       │              Executor.execute(skill, input_data)
    │       │                     │
    │       │               ┌─────┴─────┐
    │       │            성공          실패
    │       │               │           │
    │       │               ▼           ▼
    │       │          결과 반환    Autopsy.analyze()
    │       │                          │
    │       │                     보고서 반환
    │       │                    (다음 후보 시도)
    │       │
    │       └─ 후보 없음 ──→ _try_absorb_from_external()
    │                              │
    │                         ┌────┴────┐
    │                      흡수 성공   흡수 실패
    │                         │           │
    │                      retry       최종 실패
    │
    ▼
ExecutionResult (success/failure)
```

### 6.2 진화 흐름
```
User
    │
    ├─→ engine.feedback(skill_id, rating, comment)
    │       └─→ Registry.add_feedback()
    │
    ├─→ engine.evolve(skill_id, test_input)
    │       │
    │       ├─→ Registry.get_feedback(skill_id)
    │       │
    │       ├─→ SkillEvolver.mutate(skill, feedback_list)
    │       │       └─→ Anthropic API → 개선된 SKILL.md
    │       │
    │       ├─→ variant 디렉토리 생성 (copytree + SKILL.md 교체)
    │       │
    │       ├─→ Executor.execute(variant, test_input)
    │       │       │
    │       │   variant.success?
    │       │       │
    │       │   ┌───┴───┐
    │       │  True    False
    │       │   │        │
    │       │  채택     폐기
    │       │   │        │
    │       │  원본 SKILL.md   변경 없음
    │       │  덮어쓰기
    │       │
    │       ├─→ Executor.execute(original, test_input) → lifecycle 갱신
    │       │
    │       ├─→ Registry.add_evolution_record()
    │       │
    │       └─→ finally: variant 디렉토리 삭제
    │
    ▼
EvolutionRecord (adopted: bool)
```

---

## 7. Security Model

### 7.1 AST 기반 정적 분석
- Mode B 스킬의 모든 .py 파일을 `ast.parse()` → `ast.walk()`
- 금지 호출 8개, 금지 import 12개, 네트워크 import 11개
- needs_network=True인 스킬만 네트워크 import 허용

### 7.2 실행 격리
- Mode B: `subprocess.run()` + `timeout_seconds` 제한
- Mode A: Anthropic API 호출 (코드 실행 없음)
- CWD: 스킬 디렉토리로 제한

### 7.3 흡수 시 보안
- 3단계 검증: Format → Security → Load
- 위반 시 `SecurityViolationError` 발생, 흡수 거부

---

## 8. Error Handling Strategy

### 8.1 원칙
- 빈 catch 블록 금지
- 모든 예외는 `CambrianError` 계층 사용
- `logging` 모듈 사용 (print 금지)

### 8.2 에러 흐름
| 상황 | 예외 | 처리 |
|------|------|------|
| 스킬 디렉토리 없음 | SkillLoadError | 로그 후 skip |
| meta.yaml 스키마 위반 | SkillValidationError | 에러 목록 반환 |
| 실행 타임아웃 | (내부 처리) | ExecutionResult(exit_code=-1) |
| JSON 파싱 실패 | (내부 처리) | ExecutionResult(success=False) |
| API 키 없음 | (내부 처리) | ExecutionResult(success=False, error="ANTHROPIC_API_KEY not set") |
| 보안 위반 | SecurityViolationError | 흡수 거부 |
| 스킬 미발견 | SkillNotFoundError | CLI에서 exit(1) |

---

## 9. Test Architecture

### 9.1 현황
```
전체: 124 tests
  - 108 passed (API 키 없는 환경)
  - 12 skipped (Mode A 실제 API 호출)
  - 4 API E2E (deselected with -k "not Api")
```

### 9.2 테스트 파일 매핑
| 테스트 파일 | 대상 모듈 | 테스트 수 |
|------------|-----------|-----------|
| test_validator.py | validator.py | 8 |
| test_loader.py | loader.py | 7 |
| test_executor.py | executor.py | 7 |
| test_registry.py | registry.py | 10 |
| test_security.py | security.py | 7 |
| test_absorber.py | absorber.py | 7 |
| test_autopsy.py | autopsy.py | 8 |
| test_benchmark.py | benchmark.py | 8 |
| test_evolution.py | evolution.py | 11 |
| test_e2e.py | loop.py (통합) | 4 |
| test_e2e_evolution.py | evolution + loop (통합) | 8 |
| test_loop.py | loop.py | 6 |
| test_cli.py | cli.py | 8 |
| test_cli_evolution.py | cli.py (진화) | 7 |
| test_mode_a.py | executor.py (Mode A) | 6 |
| test_practical_skills.py | 실용 스킬 | 9 |

### 9.3 테스트 패턴
- **Fixture**: `conftest.py`의 `schemas_dir`, `create_valid_skill()` 공용 fixture
- **Mock**: LLM 호출은 `monkeypatch`로 `SkillEvolver.mutate`, `SkillExecutor.execute` mock
- **격리**: `db_path=":memory:"` + `tmp_path` 사용
- **API 테스트**: `@pytest.mark.skipif(not ANTHROPIC_API_KEY)` 데코레이터

---

## 10. Known Issues & Constraints

### 10.1 현재 한계
| 항목 | 설명 | 영향 |
|------|------|------|
| Windows cp949 | CLI 출력 한국어 인코딩 | test_cli.py에 encoding="utf-8" 적용 |
| SQLite 파일 락 | engine 종료 전 DB 파일 삭제 불가 | 스크립트 종료 시 DB 잔존 |
| 단일 샘플 진화 | variant 1회 실행으로 채택 판단 | 비결정적 결과 가능 |
| Mode B 진화 불가 | execute/main.py 변이 미지원 | SKILL.md만 진화 대상 |
| Docker 미적용 | subprocess + timeout만 사용 | 파일시스템 격리 부족 |

### 10.2 Phase 2 로드맵 (예정)
- Docker 기반 샌드박스
- Mode B 코드 진화 (AST 변환)
- 스킬 간 의존성 그래프
- 분산 실행 (worker pool)
- 웹 대시보드

---

## 11. File Reference

```
cambrian/
├── engine/
│   ├── __init__.py
│   ├── __main__.py
│   ├── absorber.py        # 112줄 — 외부 스킬 흡수/제거
│   ├── autopsy.py         # 195줄 — 실패 원인 분석
│   ├── benchmark.py       # 116줄 — 비교 벤치마크
│   ├── cli.py             # 546줄 — argparse CLI
│   ├── evolution.py       # 250줄 — LLM 변이 + 채택
│   ├── exceptions.py      #  54줄 — 커스텀 예외
│   ├── executor.py        # 355줄 — Mode A/B 실행
│   ├── loader.py          # 216줄 — 스킬 로드
│   ├── loop.py            # 349줄 — 메인 오케스트레이터
│   ├── models.py          # 168줄 — 도메인 객체
│   ├── registry.py        # 485줄 — SQLite 레지스트리
│   ├── security.py        # 134줄 — AST 보안 스캐너
│   └── validator.py       # 235줄 — 포맷 검증
├── schemas/
│   ├── meta.schema.json
│   └── interface.schema.json
├── skills/                 # 시드 스킬 6개
├── skill_pool/             # 런타임 흡수 스킬
├── tests/                  # pytest 17개 파일
├── scripts/
│   └── real_evolution_test.py  # 실제 API 진화 검증
├── pyproject.toml
├── SPEC.md
├── CLAUDE.md
├── README.md
└── README_EN.md
```

---

## 12. Implementation Guide (for Sonnet)

### 12.1 새 기능 추가 시 체크리스트
1. [ ] `models.py`에 필요한 dataclass 추가
2. [ ] `exceptions.py`에 필요한 예외 추가
3. [ ] 해당 engine 모듈 구현 (타입 힌트 + Google-style docstring)
4. [ ] `tests/test_{module}.py` 테스트 작성
5. [ ] `loop.py`의 `CambrianEngine`에 통합
6. [ ] `cli.py`에 CLI 명령어 추가
7. [ ] 전체 테스트 실행: `pytest tests/ -v --tb=short -k "not Api"`
8. [ ] schemas/ 파일은 **수정 금지**

### 12.2 코드 규칙
- 타입 힌트 필수 (인자 + 리턴)
- Google-style docstring 필수
- `print()` 금지 → `logging` 사용
- 외부 패키지 추가 금지 (승인 필요)
- 에러는 `engine/exceptions.py` 커스텀 예외 사용
- 빈 `except:` 블록 금지

### 12.3 Python/환경 참고
- Python 경로: `/c/Users/user/AppData/Local/Programs/Python/Python314/python.exe`
- Windows cp949 주의: 터미널 출력 시 `PYTHONIOENCODING=utf-8` 필요
- SQLite `:memory:` 옵션으로 테스트 격리
