# Cambrian Alpha Release Gate

**작성일**: 2026-04-12
**버전**: v0.3.0
**판정**: alpha candidate

---

## 현재 제품 상태

| 항목 | 판정 |
|------|------|
| 엔지니어링 안정성 | merge-ready |
| 설치 가능성 | alpha candidate |
| 운영 하드닝 | 미완료 |
| 보안 격리 | 제한적 (opt-in sandbox) |

**테스트**: 641 passed, 0 failed, 14 skipped

## Alpha 통과 기준

아래 전체가 green이면 alpha 배포 가능으로 판정한다.

| 기준 | 상태 | 검증 방법 |
|------|------|----------|
| wheel 빌드 성공 | ✅ | `python -m build --wheel` |
| cold-install 후 CLI 실행 | ✅ | CI cold-install job |
| `cambrian --help` 정상 | ✅ | CI 검증 |
| `cambrian init` 정상 | ✅ | CI 검증 |
| 번들 데이터 포함 (schemas, skills, policy) | ✅ | CI init 구조 검증 |
| `cambrian scan` smoke 통과 | ✅ | CI smoke 검증 |
| 전체 테스트 0 failed | ✅ | `pytest` |
| Python 3.11+ 지원 | ✅ | CI matrix |

## Known Limitations (alpha에서 허용)

아래는 alpha 단계에서 인지하고 허용하는 제한사항이다.

### 보안

- AST 스캐너는 기본 방어선. 완전한 격리 미보장.
- Docker sandbox는 opt-in. 기본값은 subprocess 실행.
- 신뢰할 수 없는 스킬 실행 시 sandbox 활성화 필수.

### 런타임

- `engine/_data/`와 루트 `schemas/`, `skills/`가 이중 유지 구조.
  드리프트 방지 CI 체크로 대응.
- `failure_type` 필드가 DB에 영속화되지 않음 (런타임에만 존재).
- `evolution_suggested`가 1회 소비 패턴.

### 설계

- `CambrianEngine`이 God Object 경향. `__init__`에서 10+ 컴포넌트 직접 생성.
- fitness cold-start 편향 (`min(total/10, 1.0)`). 정책 결정 대기 중.
- `_ensure_output_format`이 str.replace 기반 (인덱스 교체 미적용 시).

### 플랫폼

- Linux 우선. Windows/macOS는 CI 미검증.
- Docker sandbox는 Linux + Docker Engine 필요.

## Release Blocker vs Non-Blocker

### Blocker (alpha 전에 해결 완료)

| 항목 | 상태 |
|------|------|
| wheel 빌드 + 설치 | ✅ 해결 |
| CLI entry point 동작 | ✅ 해결 |
| init 번들 데이터 포함 | ✅ 해결 |
| 전체 테스트 green | ✅ 해결 |

### Non-Blocker (alpha 이후 해결)

| 항목 | 우선순위 |
|------|---------|
| Docker sandbox default-on | 높음 |
| failure_type DB 영속화 | 중간 |
| fitness 정책 결정 | 중간 |
| God Object 리팩터링 | 낮음 |
| Windows/macOS CI | 낮음 |

## 다음 우선순위

1. **sandbox default-on 전환 판정**: 충분한 opt-in 검증 후 기본값 전환 여부 결정
2. **failure_type 영속화**: DB 스키마에 failure_type 컬럼 추가, Autopsy 연동
3. **fitness 정책 결정**: cold-start 편향 유지 vs 조정

## Python 지원 범위

| 버전 | 상태 |
|------|------|
| 3.11 | ✅ 공식 지원. CI 검증. |
| 3.12 | ✅ 공식 지원. CI 검증. |
| 3.13 | 미검증. 향후 추가. |
| < 3.11 | 미지원. `requires-python = ">=3.11"` |
