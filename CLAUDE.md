# CLAUDE.md

## 절대 규칙
- 한국어로만 답변. 코드 주석도 한국어.
- 명시적 지시 없는 기능/파일/패키지 추가 금지.
- 동일 작업 3회 실패 → 즉시 중단, 시도 내역과 원인 보고.
- 추측으로 코드 짜지 않기. 모르면 "확인 필요" 선언.
- .env/시크릿 절대 출력 금지. git push는 사용자 확인 후만.

## 세션 시작
MEMORY.md → memory/mistakes.md → CLAUDE.md → `git status && git log --oneline -5` (git repo인 경우만) → TODO.md 순으로 파악 후 한줄 요약 보고.

## 프로젝트
Cambrian - 자가 진화하는 스킬 엔진. AI 에이전트가 실패할 때 외부 스킬을 탐색·흡수·융합하여 스스로 강해지는 시스템.

## 기술 스택
- Python 3.11+
- 의존성: pyyaml, jsonschema, anthropic (최소 유지)
- DB: SQLite (ORM 없이 직접 사용)
- 테스트: pytest
- 샌드박스: subprocess + timeout (Docker는 Phase 1)

## 코드 규칙
- 타입 힌트 필수 (모든 함수 인자 + 리턴)
- docstring 필수 (Google style)
- 에러는 커스텀 Exception 사용 (engine/exceptions.py)
- print() 금지 → logging 사용
- 외부 패키지 추가 시 반드시 확인 받을 것
- 에러 핸들링 + 로그 기록 필수 포함. 빈 catch 블록 금지.

## 파일 구조
```
cambrian/
├── engine/          # 핵심 엔진 코드
├── schemas/         # JSON Schema (수정 금지)
├── skills/          # 내장 시드 스킬
├── skill_pool/      # 런타임 흡수 스킬
├── tests/           # pytest 테스트
└── pyproject.toml
```

## 스킬 포맷 (SPEC.md 참고)
- 모든 스킬은 meta.yaml + interface.yaml + SKILL.md 필수
- mode "b" 스킬은 execute/main.py 필수
- 실행 함수 시그니처: `def run(input_data: dict) -> dict`
- CLI: stdin JSON → stdout JSON

## 작업 방식
- 파일 수정 전: 뭘 바꿀지 한줄 선언(복명) → 수정 → 결과 보고(완료)
- 수정 전 반드시 기존 테스트 실행하여 현재 상태 확인
- 한 파일 수정 후 즉시 해당 테스트 실행
- 테스트 추가 없는 기능 추가 금지
- schemas/ 디렉토리 파일은 수정하지 않는다
- 커밋: `{feat|fix|refactor|docs}({scope}): 한국어 설명`

## 메모리
- MEMORY.md 200줄 근접 → 완료 항목 MEMORY_ARCHIVE.md로 이관
- memory/mistakes.md에 반복 실수 기록. 세션 시작 절차에 포함됨.
