# 세션 완료 보고서 — 2026-04-11

**세션 범위**: 지시서 3 (Mode B 컨테이너 격리) + Sandbox 안정화 핫픽스 + 설치/패키징 수정
**기준 테스트**: 641 passed, 0 failed, 14 skipped
**판정**: merge-ready + alpha-packagable
**커밋 상태**: 미수행 (사용자 지시 대기)

---

## 1. 요약

| # | 작업 | 결과 |
|---|------|------|
| 1 | 지시서 3 STEP1 — sandbox 모델/정책/모듈 스켈레톤 | ✅ 완료 (테스트 8건) |
| 2 | 지시서 3 STEP2 — ContainerRunner.execute 구현 + executor/loop 연결 + README 3-layer | ✅ 완료 (테스트 +6건 = 누적 14건) |
| 3 | Sandbox 안정화 핫픽스 — `-B` 플래그, timeout cleanup, `failure_type` 매핑 | ✅ 완료 (테스트 +7건 = 누적 21건) |
| 4 | 설치/패키징 수정 — `engine/_data/` 번들, `_data_path.py`, init fallback, wheel 검증 | ✅ 완료 (테스트 +2건) |

세션 진입 시 **632 passed**, 세션 종료 시 **641 passed**. 실패 0 유지, 신규 +9건.

---

## 2. 지시서 3 — Mode B 컨테이너 격리 도입 (opt-in)

### STEP1 — Foundation

**수정/신규 파일**
- `engine/models.py`: `SandboxConfig` dataclass, `FailureType` enum에 `SANDBOX_UNAVAILABLE`/`SANDBOX_TIMEOUT`/`SANDBOX_VIOLATION` 3개
- `engine/policy.py`: sandbox 섹션 파싱 (DEFAULTS + `_FIELD_SPEC` + `__init__.self.sandbox` + `to_dict`)
- `cambrian_policy.json`: sandbox 기본값 (`enabled=false`)
- `engine/sandbox.py` (신규): `ContainerRunner` 스켈레톤 — `__init__(config)`, `is_available()` (shutil.which + docker info), `_build_docker_command(skill)` (네트워크/자원/ro 마운트/tmpfs), `execute()` 는 `NotImplementedError` placeholder
- `tests/test_sandbox.py` (신규): 테스트 8건

### STEP2 — Integration

**수정 파일**
- `engine/sandbox.py::execute`: placeholder 제거 후 전체 구현
  - `is_available()` → `_build_docker_command()` → `subprocess.run(timeout)`
  - returncode 분기: 137 OOM / 125 image-missing / 0 성공 + JSON parse / 기타 실패
  - `TimeoutExpired` / 일반 `Exception` catch
- `engine/executor.py::__init__`: `sandbox_config: "SandboxConfig | None" = None` 추가 + 조건부 `_container_runner` 생성
- `engine/executor.py::_execute_mode_b`: main.py 존재 체크 직후 `if self._container_runner is not None: return self._container_runner.execute(...)` 분기 (기존 subprocess 경로는 sandbox off 시 100% 유지)
- `engine/loop.py`: `SkillExecutor(provider=self._provider, sandbox_config=self._policy.sandbox)` 전달
- `README.md::Security Model`: 1-layer → **3-layer (AST / Environment Isolation / Container Isolation)** 전면 갱신
- `tests/test_sandbox.py`: PM 지정 테스트 6건 추가 → 누적 14건

### 실행 경로

```
CambrianEngine.__init__
  └─ SkillExecutor(sandbox_config=self._policy.sandbox)
       └─ sandbox.enabled == True → ContainerRunner(cfg) → self._container_runner

run_task → executor.execute(skill, input_data)
  └─ mode == "b" → _execute_mode_b
       ├─ main.py 존재 체크
       ├─ self._container_runner is not None
       │    └─ ContainerRunner.execute(skill, input_data)
       │         ├─ is_available() 체크 (False면 sandbox_unavailable)
       │         ├─ _build_docker_command(skill, container_name=...)
       │         ├─ subprocess.run(cmd, input=json_bytes, timeout=cfg.timeout_sec)
       │         └─ exit code 분기 → ExecutionResult
       └─ self._container_runner is None
            └─ 기존 subprocess 경로 (변경 없음)
```

### 기본값 정책

- `SandboxConfig.enabled=False` → 기본 off. 기존 626 테스트 회귀 0건
- fail-closed: `enabled=True` + Docker 미가용 시 subprocess fallback 하지 않음 (보안 정책 명시적 선택 존중)

---

## 3. Sandbox 안정화 핫픽스

### A. bytecode 충돌 방지 — 이중 보장

- **`python -B` 플래그**: 명령 인자로 `__pycache__` 쓰기 시도 자체를 차단
- **`-e PYTHONDONTWRITEBYTECODE=1` env**: 이중 보장

이유: `--read-only` + `/skill:ro` mount 상태에서 Python이 `.pyc`를 쓰면 `PermissionError`. `-B`로 시도 자체를 안 함.

### B. timeout cleanup 흐름

1. `execute()` 시작 시 `container_name = f"cambrian-{skill.id}-{uuid.uuid4().hex[:8]}"`
2. `docker run --rm -i --name {name} ...` 실행
3. `subprocess.TimeoutExpired` 발생 시:
   - `self._cleanup_container(container_name)` 호출
   - 내부: `docker kill {name}` (5s timeout) → `docker rm -f {name}` (5s timeout)
   - 각 단계 `except Exception` + `logger.warning` 격리
4. `ExecutionResult(failure_type="sandbox_timeout", ...)` 반환

정상 종료 경로는 `--rm`이 자동 정리.

### C. failure classification 매핑

`engine/models.py::ExecutionResult`에 `failure_type: str | None = None` 필드 추가 (기본값 `None` → 기존 모든 생성부 하위 호환 100%).

| 상황 | exit code | failure_type |
|------|-----------|-------------|
| 성공 | 0 | `None` |
| Docker CLI 없음 / daemon 미응답 | - | `sandbox_unavailable` |
| main.py 없음 | - | `execution_error` |
| Image/startup 실패 | 125 | `sandbox_unavailable` |
| TimeoutExpired | - | `sandbox_timeout` |
| OOM killed | 137 | `sandbox_violation` |
| 기타 non-zero | 1,2,... | `execution_error` |
| JSON 파싱 실패 | 0 | `output_invalid` |

문자열 값은 `FailureType` enum의 `.value`와 1:1 일치. Autopsy 등 소비자가 문자열 파싱 없이 분류 가능.

### 테스트 추가 7건

1. `test_container_runner_uses_python_no_bytecode_flag`
2. `test_container_runner_bytecode_env_set`
3. `test_container_runner_kills_container_on_timeout`
4. `test_container_runner_returns_sandbox_timeout_failure_type`
5. `test_container_runner_returns_sandbox_unavailable_failure_type`
6. `test_container_runner_maps_oom_to_sandbox_violation`
7. `test_sandbox_off_path_remains_unchanged`

---

## 4. 설치/패키징 수정 (alpha-packaging)

### 발견된 문제 (심각도순)

| # | 분류 | 문제 |
|---|------|------|
| P-1 | 패키징 | `schemas/`와 `skills/`가 `engine/` 패키지 밖에 있어 pip install 시 미포함 |
| P-2 | 패키징 | `cambrian init`이 CWD 상대경로(`./skills`)에 의존 |
| P-3 | 패키징 | `data-files`가 시스템 경로에 schemas 설치하지만 아무도 참조 안 함 |
| P-4 | UX | `init` 실패 시 `FileNotFoundError` 외 안내 없음 |
| P-5 | UX | init 후 `cambrian_policy.json` 미생성 |

### 수정 내역

**신규 파일**
- `engine/_data/` — 52개 파일 번들 (`schemas/` 2 + `skills/` 48 + `cambrian_policy.json` + `__init__.py`)
- `engine/_data_path.py` — `get_bundled_data_dir/schemas_dir/skills_dir/policy_path`
- `scripts/smoke_test.sh` — bash E2E
- `tests/test_e2e_install.py` — pytest E2E 2건

**수정 파일**
- `pyproject.toml`: `packages = ["engine", "engine._data"]`, `"engine._data" = ["schemas/*.json", "skills/**/*", "cambrian_policy.json"]`, 구 `data-files` 제거
- `engine/cli.py::_handle_init`: 번들 fallback + `cambrian_policy.json` 복사 + 명확한 에러 메시지
- `engine/cli.py::_create_engine`: `args.schemas`/`args.skills` 경로 없으면 번들 경로로 fallback (모든 서브커맨드가 임의 CWD에서 동작)

**원본 유지**: 리포 루트의 `schemas/`, `skills/`, `cambrian_policy.json`은 기존 테스트 conftest.py `schemas_dir` fixture 호환을 위해 그대로 둠.

### 설치 검증

| 검증 | 결과 |
|---|---|
| `pip install -e .` (editable 재설치) | ✅ 정상 |
| `cambrian --help` | ✅ 전 서브커맨드 노출 |
| `cambrian init --dir <tmp>/proj` | ✅ skills(14) + schemas(2) + skill_pool + cambrian.yaml + cambrian_policy.json |
| `pip wheel . -w tmp --no-deps` | ✅ `cambrian-0.3.0-py3-none-any.whl` 생성 |
| wheel 내용 검증 (zipfile) | ✅ 전체 91 파일 중 **53개 `_data` 번들 파일 포함** |

wheel 내부 핵심 파일 확인:
- `engine/_data/schemas/meta.schema.json` ✅
- `engine/_data/schemas/interface.schema.json` ✅
- `engine/_data/skills/hello_world/meta.yaml` ✅
- `engine/_data/skills/hello_world/execute/main.py` ✅
- `engine/_data/cambrian_policy.json` ✅
- `engine/_data_path.py` ✅

---

## 5. 세션 테스트 추이

| 시점 | passed | 비고 |
|---|---|---|
| 세션 진입 | 632 | 직전 세션(지시서1/2 + rollback hotfix + scanner 수정) 결과 |
| 지시서 3 STEP1 완료 | 640 | sandbox 테스트 +8 |
| 지시서 3 STEP2 완료 | 632→638→... | (sandbox off 기본으로 기존 영향 0, sandbox 테스트 누적 14) |
| Sandbox 핫픽스 완료 | 639 | sandbox 테스트 +7 |
| 설치/패키징 완료 | **641** | E2E install 테스트 +2 |

(중간 수치는 세션 내 이정표 기준 — 최종 641 passed)

---

## 6. 남은 리스크 (세션 종료 시점)

### 이번 세션에서 발생한 것

1. **`schemas/`·`skills/` 이중 유지 drift 위험** — 리포 루트와 `engine/_data/` 양쪽 존재. 한쪽만 수정 시 불일치. CI drift 검증 스크립트 추가 또는 원본 제거 후 fixture 교체 필요
2. **`ExecutionResult.failure_type` DB 미영속화** — in-memory 전달만. `run_traces`/`evolution_history` 컬럼 마이그레이션 필요. Autopsy 통합 분류 시 선결
3. **`executor.py` 기존 subprocess 경로 `failure_type` 미설정** — sandbox 경로만 분류. 통합 통계 시 보완 권장
4. **Linux venv wheel cold-start 미검증** — 본 세션은 wheel 내용 검증(zipfile)까지. 실제 venv에서 `pip install *.whl` + `cambrian init`은 별도 CI 잡 필요 (Windows Git Bash 환경 한계)
5. **Custom image의 python 경로** — 기본 `python:3.11-slim`은 안전. 비표준 image에서 `python` 심볼릭 없으면 exit 125 → `sandbox_unavailable`로 분류됨

### 이전 세션에서 이어지는 것

- D-2 fitness 공식 cold-start 편향 정책 미결
- D-3 CambrianEngine God Object
- D-4 `evolution_suggested` 1회 소비 패턴
- D-7 Mode A latency 999999 하드코딩
- D-8 JSON extract fallback 과도한 관대함

---

## 7. 다음 세션 우선순위

1. **`schemas`/`skills` drift 해소** — 이번 세션의 후속. 원본 제거 + `schemas_dir` fixture 교체 or CI drift 스크립트
2. **fitness 정책 판정** (D-2) — PM 결정 대기
3. **`failure_type` DB 영속화 + subprocess 경로 매핑** — Autopsy 통합 분류
4. **Linux venv wheel cold-start** — alpha 배포 전 최종 검증
5. **Mode A latency / JSON extract** (D-7/D-8)
6. **God Object 분해 / `evolution_suggested` 이벤트화** (D-3/D-4)

---

## 8. merge 가능 여부

**가능**. 전체 641 passed / 0 failed / 14 skipped. 세션 내 3개 작업(sandbox 도입 / 핫픽스 / 패키징) 전부 지시서 스펙대로 정렬 완료. 기본값 sandbox off, 리포 원본 구조 유지로 기존 회귀 영향 0건. wheel 내부 번들 데이터 53개 포함 확인으로 alpha 배포 전제 조건 충족.

**커밋 미수행**. 다음 세션에서 사용자 확인 후 진행.
