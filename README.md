# Cambrian

**Evolutionary trust harness for AI work.**

Cambrian은 AI 위에 입히는 프로젝트용 진화형 신뢰 하네스입니다.

프로젝트 기억, 실행 규칙, 검증, 명시적 채택, 학습 기록을 AI 작업 위에 덧씌워 더 일관되고 안전하게 일하게 만듭니다.

Cambrian은 project memory와 explicit adoption 흐름을 통해 AI 출력을 바로 밀어 넣지 않고, 진단과 검증을 거쳐 안전하게 이어지게 돕습니다.

## Quick Start

```bash
pip install -e ".[anthropic,dev]"
export ANTHROPIC_API_KEY=sk-ant-...

# 프로젝트 하네스 맞추기
cambrian init --wizard

# 자연어 요청 시작
cambrian init --wizard

cambrian do "fix the login bug"

cambrian do --continue

# 현재 프로젝트 기억과 최근 여정 확인
cambrian status

# 지금까지 Cambrian이 로컬에서 무엇을 도왔는지 요약 확인
cambrian summary
```

Cambrian은 AI 결과를 자동으로 곧바로 적용하지 않습니다.
먼저 diagnose, validation, patch proposal, explicit apply/adoption 흐름을 거칩니다.

문서:

- [첫 실행 demo](docs/FIRST_RUN_DEMO.md)
- [알파 설치 / doctor / smoke](docs/ALPHA_INSTALL.md)
- [프로젝트 모드 빠른 시작](docs/PROJECT_MODE_QUICKSTART.md)
- [명령어 안내](docs/COMMANDS.md)
- [아티팩트 안내](docs/ARTIFACTS.md)

## Installation

```bash
pip install cambrian
```

### LLM Provider (하나만 선택)

```bash
# Anthropic Claude (기본)
pip install cambrian[anthropic]
export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI GPT
pip install cambrian[openai]
export OPENAI_API_KEY=sk-...
export CAMBRIAN_LLM_PROVIDER=openai

# Google Gemini
pip install cambrian[google]
export GOOGLE_API_KEY=...
export CAMBRIAN_LLM_PROVIDER=google

# 전부 설치
pip install cambrian[all]
```

CLI에서 프로바이더 지정:
```bash
cambrian run -d utility -t greeting -i '...' --provider openai --llm-model gpt-4o
```

## 핵심 루프

```
태스크 → 경쟁 실행 → 최적 결과 반환 → fitness 갱신
              │
          전원 실패 → 부검(Autopsy) → 스킬 검색 → 흡수 → 재시도
```

## 아키텍처

```
┌──────────────────────────────────────────┐
│           Main Loop (loop.py)            │
│                                          │
│  Task → 후보 검색                         │
│           │                              │
│     후보 1개 → 즉시 실행                   │
│     후보 2개+ → 경쟁 실행 (최적 선택)       │
│           │                              │
│       성공 → fitness 갱신 → 결과 반환      │
│       실패 → Autopsy → Absorber → 재시도   │
│                                          │
│  피드백 3채널:                               │
│  [AUTO]   실패 분석 자동 (rating 1)         │
│  [CRITIC] 비판적 분석 수동 (rating 2)       │
│  (수동)   사용자 피드백 (rating 1~5)        │
│                                          │
│  진화 루프 (피드백 기반):                   │
│  feedback → mutate(LLM) → 3회 실행        │
│  → Judge(LLM) 블라인드 채점 → 채택/폐기    │
│                                          │
│  생명주기 자동 관리:                        │
│  30일 미사용 → dormant / 90일 → fossil     │
└──────────────────────────────────────────┘
```

## 부품

| 부품 | 파일 | 역할 |
|------|------|------|
| LLM | engine/llm.py | 프로바이더 추상화 (Anthropic / OpenAI / Google) |
| Validator | engine/validator.py | 스킬 포맷 검증 (JSON Schema) |
| Loader | engine/loader.py | 스킬 파일 → Skill 객체 |
| Executor | engine/executor.py | 스킬 실행 (Mode A: LLM / Mode B: subprocess) |
| Registry | engine/registry.py | SQLite 스킬 DB + 검색 + fitness + 퇴화 |
| Autopsy | engine/autopsy.py | 실패 분석 + 필요 스킬 진단 |
| Absorber | engine/absorber.py | 외부 스킬 흡수 + 보안 검사 |
| Security | engine/security.py | AST 기반 정적 코드 분석 |
| Benchmark | engine/benchmark.py | 동일 입력으로 다수 스킬 비교 실행 |
| Evolution | engine/evolution.py | LLM 기반 SKILL.md 변이 + 다중 시행 비교 |
| Judge | engine/judge.py | 두 출력을 익명화(A/B)하여 LLM 비교 채점 |
| Portability | engine/portability.py | 스킬 export/import (.cambrian 패키지) |
| Critic | engine/critic.py | LLM 기반 SKILL.md 비판적 분석 |
| Loop | engine/loop.py | 전체 루프 오케스트레이션 + 경쟁 실행 + 자가 진화 제안 |
| CLI | engine/cli.py | argparse CLI (16개 명령어) |

## 시드 스킬 (14개)

| Skill | Mode | Domain | 용도 |
|-------|------|--------|------|
| hello_world | B | utility | 기본 동작 테스트 |
| slow_skill | B | testing | 타임아웃 테스트 |
| crash_skill | B | testing | 오류 처리 테스트 |
| csv_to_chart | A | data_visualization | CSV → HTML 차트 |
| json_to_dashboard | A | data_visualization | JSON → 대시보드 |
| landing_page | A | design | 랜딩 페이지 생성 |
| inventory_anomaly_report | A | hotel_analytics | OTA 재고 불일치 분석 |
| email_draft | A | writing | 상황 → 이메일 초안 |
| meeting_summary | A | writing | 회의록 → 요약 |
| code_review | A | coding | 코드 → 리뷰 피드백 |
| data_cleaner | A | data | CSV 정제 |
| seo_meta | A | marketing | SEO 메타태그 생성 |
| api_doc | A | coding | API 문서 생성 |
| expense_report | A | analytics | 지출 분석 리포트 |

## 경쟁 실행

같은 도메인+태그에 후보가 2개 이상이면 자동으로 경쟁 실행:

- **Mode B 후보**: 전원 실행 (subprocess라 빠름)
- **Mode A 후보**: fitness 상위 2개만 실행 (API 비용 제한)
- 성공한 결과 중 fitness가 가장 높은 스킬의 결과를 반환

## 진화 시스템

### 흐름

```
1. feedback(skill_id, rating, comment) 저장
2. evolve(skill_id, test_input) 호출
3. mutate(): LLM이 SKILL.md + 피드백(입력/출력 이력 포함)으로 개선
   - Input/Output Format 섹션은 원본 그대로 보존
   - 변경 이력을 Changelog 섹션에 추가
4. 원본 3회 + variant 3회 실행
5. 각 시행마다 LLM Judge가 블라인드 채점 (0~10점)
6. variant 평균 > original 평균 → 채택
```

### LLM Judge

- A/B 익명화 (순서 랜덤), 채점 근거(reasoning) 기록
- 채점: 정확성(0~3) + 피드백 반영도(0~4) + 품질(0~3)

### Fitness 공식

```
fitness = execution_fitness x 0.5 + judge_fitness x 0.5
execution_fitness = 성공률 x min(실행횟수/10, 1.0)
judge_fitness = avg_judge_score / 10.0  (EMA 갱신)
```

## 퇴화와 멸종

엔진 시작 시 자동 정리:

| 조건 | 변경 |
|------|------|
| active + 30일 미사용 | → dormant |
| newborn + 등록 30일 후 미사용 | → dormant |
| dormant + 90일 미사용 | → fossil |

fossil은 기본 검색에서 자동 제외.

## 스킬 포맷

```
skill/
├── meta.yaml        # 신원 정보 (id, version, domain, tags, mode, runtime)
├── interface.yaml   # 입출력 계약 (JSON Schema)
├── SKILL.md         # LLM용 지시서 (Mode A)
└── execute/
    └── main.py      # 실행 코드 (Mode B만)
```

## CLI Reference

```bash
# 프로젝트 초기화
cambrian init [--dir ./path]

# 태스크 실행
cambrian run -d <domain> -t <tags...> -i '<json>' [--auto-evolve] [--provider anthropic] [--llm-model claude-sonnet-4-6]

# 스킬 관리
cambrian skills                          # 목록
cambrian skill <id>                      # 상세
cambrian absorb <path>                   # 외부 흡수
cambrian remove <id>                     # 제거
cambrian stats                           # 통계

# 진화
cambrian feedback <id> <rating> <comment>
cambrian evolve <id> -i '<json>'
cambrian history <id> [--detail <record_id>]
cambrian rollback <id> <record_id>
cambrian benchmark -d <domain> -t <tags...> -i '<json>'
cambrian critique <id>                   # 비판적 분석

# 패키지
cambrian export <id> [-o ./output]       # .cambrian 패키지 내보내기
cambrian import <path.cambrian>          # 패키지 가져오기
```

## 테스트

```bash
pytest tests/ -v --tb=short -k "not Api"
# 180 passed, 12 skipped
```

## 기술 스택

- Python 3.11+
- pyyaml, jsonschema (필수)
- anthropic / openai / google-generativeai (선택, LLM 프로바이더)
- SQLite (ORM 없이 직접)
- pytest

## Security Model

Cambrian applies a layered security model for Mode B skill execution:

**Layer 1 — AST Static Scanner** (`engine/security.py`)
Blocks known dangerous patterns (eval, exec, subprocess, os imports) at
skill load time. This is a basic defense line and cannot detect all evasion.

**Layer 2 — Environment Isolation** (`engine/executor.py`)
Subprocess execution uses a minimal environment variable whitelist.
Parent process secrets are not forwarded to child processes.

**Layer 3 — Container Isolation** (`engine/sandbox.py`, opt-in)
When `sandbox.enabled = true` in policy, Mode B skills run inside a
Docker container with:
- Network disabled by default (`--network none`)
- Read-only root filesystem (`--read-only`)
- Memory, CPU, and PID limits
- Skill directory mounted read-only
- Writable tmpfs for /tmp only

**Current limitations:**
- Container isolation is Mode B only. Mode A (LLM) is not sandboxed.
- Docker-based isolation is not a complete security guarantee.
- Linux + Docker is the primary supported environment.
- Sandbox is opt-in; default is subprocess execution.
- nsjail, rootless hardening, and cross-platform support are future work.

**Recommendation:** Enable sandbox for any skill from untrusted sources.

## Fitness Scoring

Skill fitness is calculated as:

```
raw = successful_executions / total_executions
confidence = min(total_executions / 10, 1.0)
fitness = raw * confidence
```

This means skills with fewer than 10 executions are penalized by a confidence
factor. A skill with 100% success rate and 5 executions will have
fitness = 1.0 × 0.5 = 0.5. This is intentional cold-start protection but
creates a structural disadvantage for newborn skills in competitive execution.

When LLM Judge scores are available, fitness combines execution success (50%)
and judge score (50%).

## Mode A vs Mode B in Competitive Execution

Mode A (LLM-based) skills report actual execution time but are sorted with
a fixed latency of 999999ms in competitive runs. This means Mode B (code-based)
skills are always preferred when both succeed. This is a deliberate design
choice favoring deterministic execution.
