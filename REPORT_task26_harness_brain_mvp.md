# Task 26 (Harness Brain MVP) — 완료 보고서

**작성일**: 2026-04-14
**대상**: Cambrian Harness Brain MVP (engine/brain/ 패키지 신규)
**판정**: ✅ 완료

---

## 1. 개요

Cambrian 엔진 위에 작업 실행 하네스 레이어 `engine/brain/`를 신규 추가했다. TaskSpec YAML을 입력으로 받아 planner → executor → tester → reviewer 4-role 파이프라인을 RALF-style로 반복 실행하고, 모든 상태를 `.cambrian/brain/runs/<run-id>/` 아래 파일로 저장한다.

기존 `engine/` 코어 파일은 **읽기만** 하며, 지시서에 명시된 수정 금지 파일 6개(models/loop/harness/provenance/executor/decision)는 전혀 건드리지 않았다.

---

## 2. 신규 파일 (7개)

| 파일 | LOC | 역할 |
|------|-----|------|
| `engine/brain/__init__.py` | 9 | 패키지 init + version |
| `engine/brain/models.py` | 246 | TaskSpec / WorkItem / StepResult / RunState + YAML/JSON 직렬화 |
| `engine/brain/checkpoint.py` | 225 | CheckpointManager + atomic write (tempfile → os.replace) |
| `engine/brain/pipeline.py` | 253 | RolePipeline 4개 역할 규칙 기반 stub |
| `engine/brain/runner.py` | 256 | RALFRunner — phase 전이 + 종료 조건 + iteration slice |
| `engine/brain/report.py` | 91 | generate_report — changes/tests/risks/next_actions 집계 |
| `tests/test_brain.py` | 355 | 11개 테스트 (지시서 10개 + e2e 1개) |

---

## 3. 수정 파일 (1개)

### `engine/cli.py`
- `brain` 서브파서 그룹 (run/resume/show 3개) 추가 (66줄)
- `elif args.command == "brain"` 디스패치 1줄 추가
- 핸들러 4개 함수 추가 (파일 끝에 133줄): `_resolve_brain_runs_dir`, `_handle_brain`, `_handle_brain_run`, `_handle_brain_resume`, `_handle_brain_show`
- 기존 코드는 전혀 수정하지 않음

---

## 4. 수정 금지 파일 (준수 확인)

다음 파일은 일체 수정하지 않음:
- `engine/models.py`, `engine/loop.py`, `engine/harness.py`
- `engine/provenance.py`, `engine/executor.py`, `engine/decision.py`
- 기존 `tests/test_*.py` 전체 (47개)

---

## 5. 완료 기준 체크

| # | 기준 | 상태 |
|---|------|------|
| 1 | TaskSpec YAML → planner → executor → tester → reviewer 흐름 수행 | ✅ |
| 2 | `.cambrian/brain/runs/<run-id>/` 아래 파일로 상태 저장 | ✅ (task_spec.yaml / run_state.json / iterations/iter_NNN.json / report.json) |
| 3 | `cambrian brain resume <run-id>`로 재개 가능 | ✅ test_ralf_loop_resume 검증 |
| 4 | RALF-style 반복 + max iteration safety | ✅ test_ralf_loop_max_iterations 검증 |
| 5 | report.json에 changes/tests/risks/next_actions 포함 | ✅ test_generate_report 검증 |
| 6 | 기존 `engine/` 코어 파일 수정 없음 | ✅ (cli.py만 신규 핸들러 추가) |
| 7 | 모든 상태가 파일 기반 (DB 없음, 메모리 전용 없음) | ✅ |
| 8 | `tests/test_brain.py` 10개 이상 통과 | ✅ 11/11 |

---

## 6. 테스트 결과

### brain 테스트만
```
tests/test_brain.py ............  11 passed in 0.37s
```

### 전체 회귀
```
664 passed, 14 skipped in 48.04s
```
- 기존 653 passed + brain 11 = 664
- 0 failed, 회귀 없음

### 테스트 목록
1. `test_task_spec_from_yaml` — YAML 로드 + 필수 필드 검증
2. `test_task_spec_round_trip` — to_yaml → from_yaml 동등성
3. `test_checkpoint_save_load` — RunState 저장/로드 라운드트립
4. `test_checkpoint_atomic_write` — atomic 보장 + tmp 잔존 없음 + 반복 저장 내성
5. `test_pipeline_planner` — scope 3개 → WorkItem 3개 + 재실행 시 skipped
6. `test_pipeline_full_cycle` — 4 role 순차 실행 + status 검증
7. `test_ralf_loop_max_iterations` — 5 scope / max=2 → max_iter_reached
8. `test_ralf_loop_all_done` — scope 1개 → completed + report.json 생성
9. `test_ralf_loop_resume` — max=1 중단 → max=10 resume → completed
10. `test_generate_report` — 모든 필드 검증 + failed 시 next_actions
11. `test_e2e_smoke` — TaskSpec YAML → runner → report.json + 디렉토리 구조

---

## 7. CLI 실제 동작 확인

```bash
$ cambrian brain run task.yaml --runs-dir ./runs --max-iterations 5
Brain Run: brain-20260414-144603-75ff
============================================================
Task:        task-smoke — CLI smoke 테스트
Status:      completed
Iterations:  2 / 5
Termination: all_items_done
Work items:  2
  done:      2
  failed:    0
  pending:   0
Report:      ./runs/brain-20260414-144603-75ff/report.json

$ cambrian brain show brain-20260414-144603-75ff --runs-dir ./runs
Brain Run: brain-20260414-144603-75ff
============================================================
...
Work Items (2):
  [done      ] work-001: 첫 번째 작업
  [done      ] work-002: 두 번째 작업

Step Results (7):
  [planner  success ] scope 2개 → WorkItem 2개 생성
  [executor success ] WorkItem 'work-001' 실행 완료 (stub): 첫 번째 작업
  [tester   skipped ] related_tests 비어있음 → tester 스킵
  [reviewer success ] done=1 failed=0 pending=1 ...
  [executor success ] WorkItem 'work-002' 실행 완료 (stub): 두 번째 작업
  [tester   skipped ] related_tests 비어있음 → tester 스킵
  [reviewer success ] 모든 작업 완료 (2/2)
```

생성된 report.json:
```json
{
  "run_id": "brain-20260414-144603-75ff",
  "task_id": "task-smoke",
  "status": "completed",
  "changes_summary": ["첫 번째 작업", "두 번째 작업"],
  "test_results": {"passed": 0, "failed": 0, "skipped": 2},
  "remaining_risks": [],
  "next_actions": [],
  "total_iterations": 2,
  "termination_reason": "all_items_done",
  "started_at": "2026-04-14T14:46:03.109643+00:00",
  "finished_at": "2026-04-14T14:46:03.137009+00:00",
  "provenance_ref": "brain-20260414-144603-75ff"
}
```

---

## 8. 주요 구현 결정

1. **run_id 형식**: `brain-YYYYMMDD-HHMMSS-XXXX` (XXXX = `secrets.token_hex(2)`)
2. **atomic write**: `tempfile.mkstemp(dir=target.parent)` → `os.fsync` → `os.replace` 3단계. Windows/POSIX 모두 rename atomicity 보장.
3. **종료 조건 우선순위**: (1) 이미 종료 상태 → (2) 모든 work_items done/skipped (단, phase가 "executor"일 때만 — reviewer가 최소 1회 돈 뒤) → (3) max_iterations 도달
4. **iteration slice**: iteration 0은 4 step (planner 포함), 이후는 3 step씩. `_slice_current_iteration` 이 reviewer 종료 시점에 정확히 잘라서 `iter_NNN.json`에 저장.
5. **reviewer retry**: failed → pending 재설정은 item별 최대 1회. step_results의 `errors[0] = "retry:<item_id>"` 태그로 중복 방지.
6. **provenance_ref**: report.json에 run_id 예약 필드만 포함. 실제 adoption 연결은 미구현(지시서 범위 밖).
7. **PyYAML만 사용**: 외부 패키지 추가 없음. stdlib + 기존 의존성(yaml)만 사용.

---

## 9. 파일 트리 (신규/수정)

```
cambrian/
├── engine/
│   ├── brain/                          # [신규]
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── checkpoint.py
│   │   ├── pipeline.py
│   │   ├── runner.py
│   │   └── report.py
│   └── cli.py                          # [수정 — brain 서브커맨드만 추가]
└── tests/
    └── test_brain.py                   # [신규]
```

---

## 10. 알려진 제약 / v2 예약

- 각 역할은 stub (실제 LLM 호출 없음) — 지시서 범위 준수
- `related_tests` 실행은 파일 존재 여부만 확인 (pytest 실제 실행은 v2)
- `executor`는 파일 수정 없이 WorkItem status만 "done" 처리
- provenance → adoption 연결은 필드만 예약 (`provenance_ref`)
- Cambrian 스킬과 자동 연동 없음 (v2 범위)

---

## 11. 완료 선언

```
DONE: Task 26 — Cambrian Harness Brain MVP
Files created: engine/brain/__init__.py, engine/brain/models.py,
               engine/brain/checkpoint.py, engine/brain/pipeline.py,
               engine/brain/runner.py, engine/brain/report.py,
               tests/test_brain.py
Files modified: engine/cli.py (brain 서브커맨드 + 핸들러만 추가)
Tests: 11/11 passed (brain) — 664/664 passed (전체, 14 skipped)
Remaining: 없음
```
