# Task 28 (P1) — Harness-to-Adoption Handoff

**작성일**: 2026-04-14
**대상**: brain run → adoption/provenance 공식 handoff contract
**판정**: ✅ 완료

---

## 1. 개요

Task 27에서 brain run 결과물(`report.json`의 `provenance_handoff` 섹션)은 생성되지만, Cambrian의 adoption/provenance 세계와 연결할 공식 계약이 없었다.

이번 Task에서 그 연결부 — **brain run → handoff artifact → (미래) adoption record** 의 첫 칸인 **handoff artifact 생성 레이어**를 구현했다. 나머지 adoption 연결은 향후 Task에서 이 artifact를 소비하는 방식으로 진행 가능.

---

## 2. 신규 파일 (1개)

| 파일 | LOC | 역할 |
|---|---|---|
| `engine/brain/handoff.py` | 330 | `HandoffRecord` dataclass + `HandoffValidator` 10단계 규칙 + `HandoffGenerator` atomic write |

---

## 3. 수정 파일 (2개)

### `engine/cli.py`
- `brain handoff <run_id>` 서브파서 추가 (`--runs-dir`, `--handoffs-dir`, `--force`, `--json` 옵션)
- 디스패치 엔트리 1줄 추가
- `_resolve_brain_handoffs_dir()` 헬퍼
- `_handle_brain_handoff()` 핸들러 — ready / blocked / invalid 3가지 human-readable 출력

### `tests/test_brain.py`
- 기존 27개 테스트 무수정
- 헬퍼 `_create_complete_brain_run()` 추가 — include_* 플래그로 의도적 결손 시뮬레이션
- **12개 신규 테스트 추가**

---

## 4. 수정 금지 파일 (준수 확인)

- ✅ `engine/brain/models.py`, `pipeline.py`, `runner.py`, `checkpoint.py`, `report.py`, `adapters/` 일체 무변경
- ✅ `engine/` 코어 전체 무변경
- ✅ 기존 `tests/test_brain.py` 테스트 함수 27개 무수정
- ✅ brain run source files (`run_state.json`, `report.json`, `task_spec.yaml`, `iterations/*.json`) **handoff 생성 과정에서 전혀 수정되지 않음** — test_handoff_source_immutability 검증

---

## 5. Handoff Validation 10단계

| # | 검증 항목 | 실패 시 status | block_reason |
|---|---|---|---|
| 1 | `runs_dir/<run_id>/` 디렉토리 존재 | invalid | `run directory not found: {path}` |
| 2 | `run_state.json` 존재 + 파싱 | invalid | `run_state.json missing or malformed` |
| 3 | `report.json` 존재 + 파싱 | invalid | `report.json missing or malformed` |
| 4 | `task_spec.yaml` 존재 | invalid | `task_spec.yaml missing` |
| 5 | `run_state.status == "completed"` | blocked | `run not completed: status={actual}` |
| 6 | `report.provenance_handoff` 섹션 존재 | invalid | `provenance_handoff section missing in report` |
| 7 | `provenance_handoff.stable_ref` 존재 + 비어있지 않음 | invalid | `stable_ref missing or empty` |
| 8 | `provenance_handoff.reviewer_passed == True` | blocked | `reviewer did not pass` |
| 9 | `provenance_handoff.adoption_ready == True` | blocked | `adoption_ready is false` |
| 10 | `provenance_handoff.test_exit_code == 0` | blocked | `tests did not pass: exit_code={code}` |

**최종 status 결정**:
- invalid 사유가 1개라도 있으면 → `invalid`
- invalid 없고 blocked 사유가 있으면 → `blocked`
- 사유 없으면 → `ready`

**artifact 생성 정책**:
- `ready` / `blocked` → 저장 (증거 기록 목적)
- `invalid` → 저장하지 않음 (source 자체가 없거나 깨져 있음)

---

## 6. 저장 파일 구조

```
.cambrian/brain/
├── runs/                                       # brain run 결과 (read-only by handoff layer)
│   └── brain-20260414-152310-ad11/
│       ├── task_spec.yaml
│       ├── run_state.json
│       ├── iterations/iter_000.json
│       └── report.json
└── handoffs/                                   # [신규] handoff artifacts
    └── handoff_20260414_155740_brain-20260414-152310-ad11.json
```

**파일명 규칙**: `handoff_<YYYYMMDD_HHMMSS>_<brain_run_id>.json`
**handoff_id 규칙**: `handoff-<YYYYMMDD-HHMMSS>-<4자리 hex>` (파일명의 timestamp와 별개로 record 내부용)

---

## 7. HandoffRecord 스키마 (24 필드)

```json
{
  "schema_version": "1.0.0",
  "handoff_id": "handoff-20260414-155740-2b04",
  "created_at": "2026-04-14T15:57:40+00:00",

  "brain_run_id": "brain-20260414-152310-ad11",
  "task_id": "task-t27-real",
  "source_report_path": ".cambrian/brain/runs/.../report.json",
  "source_run_state_path": ".cambrian/brain/runs/.../run_state.json",
  "source_task_spec_path": ".cambrian/brain/runs/.../task_spec.yaml",
  "source_iterations_dir": ".cambrian/brain/runs/.../iterations/",

  "run_status": "completed",
  "reviewer_passed": true,
  "adoption_ready": true,
  "files_created": ["test_add.py"],
  "files_modified": [],
  "tests_executed": ["test_add.py"],
  "test_exit_code": 0,
  "reviewer_conclusion": "...",
  "remaining_risks": [],
  "next_actions": [],

  "handoff_status": "ready",
  "block_reasons": [],

  "adoption_record_ref": null,
  "decision_ref": null
}
```

**source 경로는 모두 프로젝트 루트 기준 상대 경로**로 고정 — 다른 환경에서 artifact를 열어도 참조 일관성 유지.

**adoption_record_ref / decision_ref**는 nullable 예약 필드. 미래 adoption이 생성되면 이 필드에 경로 기록 가능.

---

## 8. acceptance criteria 체크

| # | 기준 | 상태 |
|---|---|---|
| 1 | completed + adoption_ready=true → ready handoff 생성 | ✅ test_handoff_generate_ready + CLI smoke |
| 2 | reviewer 실패 or adoption_ready=false → blocked handoff 생성 | ✅ test_handoff_generate_blocked + CLI smoke |
| 3 | source 없음 → invalid + artifact 미생성 | ✅ test_handoff_generate_invalid_no_artifact |
| 4 | source brain artifact 경로가 handoff에 포함 | ✅ 4개 source_*_path 필드 |
| 5 | `.cambrian/brain/handoffs/`에 JSON 저장 (DB 없음) | ✅ atomic write (tempfile + os.replace) |
| 6 | source files 무수정 | ✅ test_handoff_source_immutability (바이트 단위 비교) |
| 7 | CLI human-readable 요약 | ✅ 3가지 상태별 포맷팅 검증 완료 |
| 8 | 기존 전체 테스트 green | ✅ 692 passed / 0 failed |
| 9 | 신규 12개 테스트 green | ✅ 12/12 |

---

## 9. 테스트 결과

### brain 테스트 (27 기존 + 12 신규 = 39개)
```
tests/test_brain.py ......................................... 39 passed in 2.87s
```

**신규 12개 breakdown**:

**Validator (5)**
- `test_handoff_validator_ready` — completed + adoption_ready=true → ready
- `test_handoff_validator_blocked_reviewer` — reviewer_passed=false → blocked
- `test_handoff_validator_blocked_tests` — test_exit_code=1 → blocked
- `test_handoff_validator_invalid_missing_report` — report.json 없음 → invalid
- `test_handoff_validator_invalid_no_run_dir` — run 디렉토리 없음 → invalid

**Generator (4)**
- `test_handoff_generate_ready` — artifact 파일 생성 + handoff_status="ready"
- `test_handoff_generate_blocked` — blocked도 artifact 저장 + block_reasons 기록
- `test_handoff_generate_invalid_no_artifact` — invalid는 파일 미생성
- `test_handoff_source_immutability` — source 3개 파일 바이트 단위 불변 확인

**E2E (2)**
- `test_handoff_e2e_ready_path` — 완전 ready 흐름 + source_report_path 검증 + adoption_record_ref=None
- `test_handoff_e2e_blocked_path` — reviewer fail + adoption_ready=false → blocked

**Schema (1)**
- `test_handoff_record_all_fields` — 24개 필수 필드 전부 존재 + SCHEMA_VERSION 확인

### 전체 회귀
```
692 passed, 14 skipped in 46.73s
```
- 직전 680 + handoff 12 = 692
- 0 failed, 회귀 없음

---

## 10. CLI 실제 동작 검증

### 10.1 Ready 경로
```
$ cambrian brain handoff brain-20260414-152310-ad11
[HANDOFF] brain-20260414-152310-ad11
  Task      : task-t27-real
  Status    : ready [OK]
  Reviewer  : passed
  Tests     : exit 0
  Files     : 1 created, 0 modified
  Conclusion: 모든 acceptance criteria 충족 및 모든 작업 완료 (1/1)
  Risks     : none
  Artifact  : ./.cambrian/brain/handoffs/handoff_20260414_155740_brain-....json
  Next      : ready for adoption review
```

### 10.2 Blocked 경로
```
$ cambrian brain handoff brain-blocked-fake
[HANDOFF] brain-blocked-fake
  Task      : task-blocked
  Status    : blocked [FAIL]
  Reasons   :
    - reviewer did not pass
    - adoption_ready is false
    - tests did not pass: exit_code=1
  Artifact  : ./.cambrian/brain/handoffs/handoff_....json
  Next      : fix reviewer/test issues, re-run brain, then retry handoff
```

### 10.3 Invalid 경로
```
$ cambrian brain handoff nonexistent-run-999
[HANDOFF] nonexistent-run-999
  Task      : (unknown)
  Status    : invalid [FAIL]
  Reasons   :
    - run directory not found: ....
  Artifact  : not created
```

**Windows cp949 호환**: 기호는 텍스트(`[OK]`, `[FAIL]`)로 대체하여 인코딩 이슈 방지.

---

## 11. 주요 구현 결정

1. **validator와 generator 분리**: `HandoffValidator`는 판정만, `HandoffGenerator`는 validate → build → save. 단일 책임 원칙. 테스트도 독립적으로 작성 가능.

2. **invalid에서도 HandoffRecord 반환**: 파일은 생성 안 하지만 객체는 반환하여 CLI가 이유를 출력할 수 있음. 호출자가 record.handoff_status로 분기 가능.

3. **source 경로 상대화**: `.cambrian/brain/runs/<run_id>/report.json` 형식. 환경 이동해도 참조 유효.

4. **atomic write 패턴 재사용**: checkpoint.py와 동일한 `tempfile.mkstemp → os.fsync → os.replace`. 중복 구현이지만 checkpoint 모듈 수정 금지 제약 하에서는 최선.

5. **nullable 예약 필드**: `adoption_record_ref`, `decision_ref`는 이번 Task에서 항상 None. 미래 adoption 트리거가 이 필드에 경로를 기록하게 될 확장 지점.

6. **readiness 정책**:
   - test_exit_code 0만 통과 (exit 5 "no tests collected"는 통과 아님 — blocked 판정)
   - → 이건 Task 27의 tester_v1에서 exit 5를 success로 매핑한 것과 구분. handoff 단계에서는 **실제 테스트가 있고 통과했는지**를 더 엄격히 본다.

7. **PyYAML + stdlib만 사용**: 외부 패키지 추가 없음.

---

## 12. 주의점 / 알려진 제약

- `--force` 플래그는 선언만 되어 있고 현재 MVP에서는 blocked도 항상 artifact를 생성하므로 동작 변화 없음 (향후 정책 변경 대비)
- handoff artifact는 누적만 됨 (삭제 정책 없음). 장기 운영 시 cleanup 메커니즘 v2 필요
- `brain show` 서브커맨드는 handoff 정보를 출력하지 않음 — 분리된 `brain handoff` 서브커맨드만 제공
- schema_version은 1.0.0 고정. 향후 스키마 변경 시 validator에서 버전 호환 로직 필요

---

## 13. 파일 트리 (이번 Task 28 변경)

```
cambrian/
├── engine/
│   ├── brain/
│   │   └── handoff.py                       # [신규]
│   └── cli.py                               # [수정 — brain handoff 서브커맨드만 추가]
├── tests/
│   └── test_brain.py                        # [append only — 12개 추가]
└── REPORT_task28_harness_to_adoption_handoff.md  # [신규]
```

---

## 14. 완료 선언

```
DONE: Task 28 — Harness-to-Adoption Handoff
Files created: engine/brain/handoff.py,
               REPORT_task28_harness_to_adoption_handoff.md
Files modified: engine/cli.py (brain handoff 서브커맨드 + 핸들러),
                tests/test_brain.py (12개 추가, 기존 27개 무수정)
Tests: 39/39 (brain) — 692/692 (전체, 14 skipped)
Remaining: 없음
```
