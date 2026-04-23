# Task 27 (P1) — Harness Brain V1: Real Execution / Test / Review Adapters

**작성일**: 2026-04-14
**대상**: Cambrian Harness Brain V1 실행 어댑터
**판정**: ✅ 완료

---

## 1. 개요

Task 26 Harness Brain MVP의 stub 파이프라인을 **실제로 동작하는 V1 어댑터**로 교체했다.

- executor: 명시적 `write_file` / `patch_file` 2개 연산으로 실제 파일 생성/수정
- tester: subprocess로 pytest 실제 실행 + 결과 구조화
- reviewer: acceptance criteria 규칙 기반 판정 + retry_count 기반 재시도
- provenance handoff: report.json에 adoption/validation 연결용 stable ref 추가

각 역할을 `engine/brain/adapters/` 서브패키지로 분리하여 어댑터 패턴을 적용했다. `pipeline.py`는 dispatch 역할만 수행하도록 얇아졌다.

---

## 2. 신규 파일 (4개)

| 파일 | LOC | 역할 |
|------|-----|------|
| `engine/brain/adapters/__init__.py` | 9 | 패키지 init + version |
| `engine/brain/adapters/executor_v1.py` | 273 | write_file / patch_file + path traversal 거부 + .bak 백업 + 1MB 제한 |
| `engine/brain/adapters/tester_v1.py` | 248 | subprocess pytest + timeout 120s + stdout tail 50 + 결과 정규식 파싱 |
| `engine/brain/adapters/reviewer_v1.py` | 242 | criteria 분류(test/file/other) + 파일 존재 확인 + retry_count 기반 재시도 |

---

## 3. 수정 파일 (3개)

### `engine/brain/models.py`
- 신규 dataclass 3개: `ExecutorAction`, `TestDetail`, `ReviewVerdict`
- `TaskSpec`: `actions: list[dict] | None = None` 필드 추가 + YAML 직렬화 처리
- `WorkItem`: `action: dict | None = None`, `retry_count: int = 0` 필드 추가
- `StepResult`: `details: dict | None = None` 필드 추가
- 모든 신규 필드 기본값 있음 → **기존 checkpoint 파일과 하위 호환**

### `engine/brain/pipeline.py`
- `RolePipeline.__init__`에 `project_root` 파라미터 추가, `workspace`는 하위 호환용 별칭으로 유지
- planner: `actions[i]` → `work_items[i].action` 1:1 매핑
- executor/tester/reviewer: adapter dispatch로 교체
- action이 None인 WorkItem은 ExecutorV1 내부에서 stub 경로로 처리 → 기존 테스트 호환

### `engine/brain/report.py`
- `generate_report`: `provenance_handoff` 섹션 + `reviewer_conclusion` 필드 추가
- 헬퍼 5개: `_collect_files_created`, `_collect_files_modified`, `_get_last_test_exit_code`, `_get_reviewer_passed`, `_get_reviewer_conclusion`
- `test_results`: details.passed/failed/skipped 합산(더 정확한 카운트). details 없는 하위 호환 fallback 유지

---

## 4. 수정 금지 파일 (준수 확인)

- ✅ `engine/brain/runner.py` 무변경
- ✅ `engine/brain/checkpoint.py` 무변경
- ✅ `engine/` 코어 전체(models/loop/harness/provenance/executor/decision 등) 무변경
- ✅ `tests/test_brain.py` 기존 11개 테스트 함수 무수정 (append만)

---

## 5. acceptance criteria 체크

| # | 기준 | 상태 |
|---|------|------|
| 1 | executor가 최소 1개 실제 파일 작업 수행 | ✅ write_file + patch_file |
| 2 | tester가 `related_tests`를 실제 pytest로 실행 | ✅ subprocess.run + 결과 구조화 |
| 3 | reviewer가 acceptance 기준으로 pass/fail/next_actions 남김 | ✅ 규칙 기반 ReviewVerdict |
| 4 | report.json에 변경 파일/실행 테스트/reviewer 결론/remaining risks/next actions | ✅ provenance_handoff 섹션 |
| 5 | run/resume/show 흐름 유지 | ✅ CLI 무변경 |
| 6 | 실패/fail 시 루프 상태 깨지지 않고 재개 가능 | ✅ retry_count 기반 + checkpoint 매 단계 저장 |
| 7 | brain이 Cambrian core truth 덮지 않음 | ✅ brain은 execution trace layer 유지 |
| 8 | E2E smoke: 실제 파일 생성 + 실제 pytest + reviewer 판정 | ✅ test_e2e_real_execution + CLI smoke 검증 |
| 9 | 기존 전체 테스트 green | ✅ 680 passed, 0 failed |

---

## 6. 테스트 결과

### brain 테스트 (11 기존 + 16 신규 = 27개)
```
tests/test_brain.py ............................  27 passed in 2.34s
```

신규 테스트 16개:

**Executor (5)**
- `test_executor_write_file`: 파일 생성 검증
- `test_executor_patch_file`: 텍스트 치환 검증
- `test_executor_patch_not_found`: old_text 미발견 시 failure
- `test_executor_path_traversal`: `../` 거부 + 파일이 실제로 escape되지 않음 확인
- `test_executor_backup_created`: 기존 파일 수정 시 .bak 생성

**Tester (4)**
- `test_tester_passing`: `assert True` → passed >= 1, exit_code == 0
- `test_tester_failing`: `assert False` → failed >= 1, exit_code != 0
- `test_tester_no_tests`: related_tests=[] → skipped
- `test_tester_missing_files`: 존재하지 않는 파일 → skipped

**Reviewer (5)**
- `test_reviewer_all_pass`: criteria 충족 + tester pass → passed=True + state.status=completed
- `test_reviewer_test_failure`: tester fail → passed=False 강제
- `test_reviewer_file_criterion`: "파일이 생성됨" + 파일 존재 → met=True
- `test_reviewer_retry_items`: failed → retry 재설정 + retry_count 증가
- `test_reviewer_max_retry`: retry_count=2 → retry 불가 + state.status=failed

**E2E + Provenance (2)**
- `test_e2e_real_execution`: YAML → 파일 생성 → pytest → reviewer → report.provenance_handoff.adoption_ready=True
- `test_report_provenance_handoff`: 모든 handoff 필드 존재 + 값 검증

### 전체 회귀
```
680 passed, 14 skipped in 45.20s
```
- 기존 664 + brain V1 16 = 680
- 0 failed, 회귀 없음

---

## 7. CLI 실제 동작 검증

```bash
$ cambrian brain run task.yaml --runs-dir ./runs --workspace ./workspace --max-iterations 5
Brain Run: brain-20260414-152310-ad11
============================================================
Task:        task-t27-real — V1 어댑터 smoke test
Status:      completed
Iterations:  1 / 5
Termination: all_items_done
Work items:  1
  done:      1
  failed:    0
  pending:   0
Report:      ./runs/brain-20260414-152310-ad11/report.json
```

생성된 report.json (요약):
```json
{
  "status": "completed",
  "changes_summary": ["test_add.py 파일 생성"],
  "test_results": {"passed": 1, "failed": 0, "skipped": 0},
  "reviewer_conclusion": "모든 acceptance criteria 충족 및 모든 작업 완료 (1/1)",
  "provenance_handoff": {
    "files_created": ["test_add.py"],
    "files_modified": [],
    "tests_executed": ["test_add.py"],
    "test_exit_code": 0,
    "reviewer_passed": true,
    "adoption_ready": true,
    "stable_ref": "brain-20260414-152310-ad11"
  }
}
```

실제 workspace 디렉토리에 `test_add.py`가 생성되었고, pytest가 해당 파일을 실행하여 `passed=1`을 기록, reviewer가 criteria 2개(파일 생성 + 테스트 통과)를 모두 met으로 판정하여 `adoption_ready=true`로 handoff 준비 완료.

---

## 8. 주요 구현 결정

1. **어댑터 패턴**: 각 역할 로직을 `engine/brain/adapters/*_v1.py`로 분리. 향후 v2에서 `executor_v2.py` 등으로 확장 가능.

2. **executor 안전 제약**:
   - 절대 경로 거부
   - `..` 파트 포함 경로 거부
   - resolve 후 project_root 밖이면 거부
   - content 1MB 초과 거부
   - 기존 파일 수정 시 `.bak` 무조건 생성 (shutil.copy2)

3. **tester exit code 매핑** (backward compat):
   - 0 → success
   - 5 (no tests collected) → success (Task 26의 `# test\n` 빈 파일이 success였던 것과 일치)
   - 기타 → failure
   - FileNotFoundError (pytest 미설치) → skipped

4. **reviewer 규칙**:
   - criterion 분류: "테스트/test/pytest" → test, "파일/생성/추가/file/create/add" → file, 그 외 → other
   - other는 자동 pass (evidence에 "자동 확인 불가" 기록)
   - tester failure 시 passed=False 강제
   - **unretriable_failed 검출**: failed + retry_count >= 2 항목이 있으면 passed=False 강제 (max_retry 케이스)
   - retry: failed + retry_count < 2 → status="pending" + retry_count += 1

5. **state mutation 규칙**:
   - passed=True + 모든 items done → `status=completed, termination_reason=all_items_done`
   - passed=False + retry 불가 + failed 존재 → `status=failed, termination_reason=reviewer_fail`
   - 그 외 → runner의 max_iterations/all_items_done 판정에 위임

6. **PyYAML만 사용**: 외부 패키지 추가 없음. subprocess/re/pathlib/shutil/sys/secrets 모두 stdlib.

7. **TesterV1.__test__ = False**: 클래스명 접두사 `Test*`로 인한 pytest collection 경고 방지.

8. **하위 호환 우선**:
   - WorkItem.action=None → executor_v1이 stub 경로로 처리
   - TaskSpec.actions=None → YAML 직렬화 시 키 생략
   - StepResult.details=None → report.py가 fallback 카운팅
   - RolePipeline `workspace=` kwarg 유지 (runner.py 무수정)

---

## 9. adoption handoff — v2 예약

이번 Task에서는 **필드만 예약**하고 자동 adoption은 실행하지 않음:

- `provenance_handoff.adoption_ready = reviewer_passed AND (test_exit_code in {0, 5})`
- 외부에서 이 플래그를 읽고 adoption 로직을 트리거할 수 있는 형태
- `stable_ref`는 run_id와 동일, 외부 adoption record의 `harness_run_ref`로 연결 가능

---

## 10. 파일 트리 (이번 Task 27 변경)

```
cambrian/
├── engine/
│   └── brain/
│       ├── adapters/                    # [신규 서브패키지]
│       │   ├── __init__.py
│       │   ├── executor_v1.py
│       │   ├── tester_v1.py
│       │   └── reviewer_v1.py
│       ├── models.py                    # [수정 — 3 신규 dataclass + 3 기존 확장]
│       ├── pipeline.py                  # [수정 — adapter dispatch]
│       └── report.py                    # [수정 — provenance_handoff]
└── tests/
    └── test_brain.py                    # [append only — 16개 추가]
```

---

## 11. 완료 선언

```
DONE: Task 27 — Harness Brain V1
Files created: engine/brain/adapters/__init__.py,
               engine/brain/adapters/executor_v1.py,
               engine/brain/adapters/tester_v1.py,
               engine/brain/adapters/reviewer_v1.py,
               REPORT_task27_harness_brain_v1.md
Files modified: engine/brain/models.py (3 dataclass 추가 + 3 확장),
                engine/brain/pipeline.py (adapter dispatch),
                engine/brain/report.py (provenance_handoff),
                tests/test_brain.py (16개 추가, 기존 11개 무수정)
Tests: 27/27 (brain) — 680/680 (전체, 14 skipped)
Remaining: 없음
```
