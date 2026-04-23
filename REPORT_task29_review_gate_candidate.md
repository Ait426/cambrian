# Task 29 (P1) — Handoff Review Gate / Adoption Candidate

**작성일**: 2026-04-14
**대상**: ready handoff → candidate 승격 레이어
**판정**: ✅ 완료 (단, Task 28↔29 contract 간극 식별 — §11 참조)

---

## 1. 개요

Task 28에서 brain → handoff artifact 경로가 열렸다. Task 29에서는 그 다음 칸 — **handoff → adoption candidate** 승격 레이어를 구현했다.

`.cambrian/adoption_candidates/` 디렉토리에 `pending_review` 상태의 candidate JSON이 생성되며, 이는 향후 adoption record로 전환될 수 있는 공식 검토 단위가 된다.

```
brain run → handoff artifact → [REVIEW GATE] → candidate → (미래) adoption record
                                 Task 29
```

---

## 2. 신규 파일 (1개)

| 파일 | LOC | 역할 |
|---|---|---|
| `engine/brain/candidate.py` | 411 | `CandidateRecord` dataclass + `ReviewGate` 10단계 판정 + `CandidateGenerator` (dedup + atomic write) |

---

## 3. 수정 파일 (2개)

### `engine/cli.py`
- 기존 `adoption` 서브파서에 `review` 서브커맨드 추가 (인자: `handoff_path`, `--candidates-dir`, `--json`)
- `_handle_adoption` 분기에 `"review"` 케이스 1줄 추가
- `_resolve_candidates_dir` 헬퍼 + `_handle_adoption_review` 핸들러 추가 (4가지 result_type별 human-readable 출력)

### `tests/test_brain.py`
- 기존 39개 테스트 무수정
- `_create_handoff_file` 헬퍼 추가 — stable_ref/reviewer_passed/adoption_ready/handoff_status 등을 파라미터로 조절 + `omit_fields` / `make_invalid_json` 옵션
- **10개 신규 테스트 추가**

---

## 4. 수정 금지 파일 (준수 확인)

- ✅ `engine/brain/handoff.py` 무변경
- ✅ `engine/brain/models.py`, `pipeline.py`, `runner.py`, `checkpoint.py`, `report.py`, `adapters/` 무변경
- ✅ `engine/` 코어 전체 무변경
- ✅ 기존 `tests/test_brain.py` 테스트 39개 무수정
- ✅ handoff 파일 / brain source files `test_candidate_source_immutability`로 바이트 단위 불변 검증

---

## 5. ReviewGate 10단계 규칙

| # | 검증 항목 | 실패 시 result | reason |
|---|---|---|---|
| 1 | handoff_path 파일 존재 | invalid | `handoff file not found: {path}` |
| 2 | JSON 파싱 가능 | invalid | `handoff file is not valid JSON` |
| 3 | `schema_version` 필드 | invalid | `not a valid handoff artifact: missing schema_version` |
| 4 | `handoff_status` 필드 | invalid | `not a valid handoff artifact: missing handoff_status` |
| 5 | `handoff_status == "ready"` | reject | `handoff is not ready: status={actual}` |
| 6 | `stable_ref` 존재+비어있지 않음 | invalid | `stable_ref missing or empty` |
| 7 | `reviewer_passed == True` | reject | `reviewer did not pass` |
| 8 | `adoption_ready == True` | reject | `adoption_ready is false` |
| 9 | `brain_run_id` 필드 | invalid | `brain_run_id missing` |
| 10 | `source_report_path` 필드 | invalid | `source_report_path missing` |

**result 결정 로직**:
- invalid 사유 존재 → `invalid` (reject 사유도 함께 표시)
- invalid 없고 reject 사유 존재 → `reject`
- 사유 없음 → `pass`

---

## 6. Result Type 매트릭스

| result_type | 조건 | artifact 생성 | record 반환 |
|---|---|---|---|
| `created` | gate pass + 중복 없음 | ✅ | CandidateRecord |
| `duplicate` | gate pass + 기존 stable_ref candidate 존재 | ❌ (기존 재사용) | 기존 CandidateRecord |
| `rejected` | gate reject | ❌ | None |
| `invalid` | gate invalid | ❌ | None |

**중복 판정**: `_check_duplicate(stable_ref)`가 `.cambrian/adoption_candidates/candidate_*_{stable_ref}.json` glob. 매칭 있으면 첫 번째 반환.

**정책**: 동일 stable_ref는 한 번만 candidate 생성. 이는 같은 brain run이 여러 번 handoff되어도 review queue에 단일 항목만 쌓이도록 하는 의도.

---

## 7. 저장 파일 구조

```
.cambrian/
├── brain/
│   ├── runs/             # immutable brain run results
│   └── handoffs/         # handoff artifacts (Task 28)
└── adoption_candidates/  # [신규] review gate 통과한 candidates
    └── candidate_<YYYYMMDD_HHMMSS>_<stable_ref>.json
```

파일명 규칙:
- candidate 파일명: `candidate_<timestamp>_<stable_ref>.json`
- candidate_id (record 내부): `candidate-<YYYYMMDD-HHMMSS>-<4자리 hex>`

---

## 8. CandidateRecord 스키마 (24 필드)

```json
{
  "schema_version": "1.0.0",
  "candidate_id": "candidate-20260414-162116-f00d",
  "created_at": "2026-04-14T16:21:16+00:00",
  "candidate_status": "pending_review",

  "stable_ref": "brain-spec-001",
  "handoff_ref": "handoff-spec-001",
  "brain_run_id": "brain-spec-001",
  "task_id": "task-spec",

  "source_handoff_path": "/tmp/.../handoff_ready.json",
  "source_report_path": ".cambrian/brain/runs/.../report.json",
  "source_run_state_path": ".cambrian/brain/runs/.../run_state.json",
  "source_task_spec_path": ".cambrian/brain/runs/.../task_spec.yaml",

  "reviewer_conclusion": "완료",
  "files_created": ["test.py"],
  "files_modified": [],
  "tests_executed": ["test.py"],
  "test_exit_code": 0,
  "remaining_risks": [],
  "next_actions": [],

  "candidate_ready_for_adoption": true,
  "gate_passed_at": "2026-04-14T16:21:16+00:00",

  "adoption_record_ref": null,
  "decision_ref": null,
  "review_notes": null
}
```

**source chain 3단 연결**:
```
stable_ref            ← brain run ID (chain 전체의 불변 식별자)
handoff_ref           ← handoff_id
source_handoff_path   ← handoff 파일 실제 경로
```

---

## 9. acceptance criteria 체크

| # | 기준 | 상태 |
|---|---|---|
| 1 | ready handoff → `.cambrian/adoption_candidates/`에 candidate artifact | ✅ test_candidate_generate_created + CLI smoke |
| 2 | blocked/invalid handoff → candidate 미생성 + 명시적 사유 | ✅ test_candidate_generate_rejected + CLI smoke |
| 3 | candidate에 source handoff + source brain refs 포함 | ✅ 4개 source_*_path 필드 |
| 4 | file-first (DB 없음) | ✅ atomic write만 사용 |
| 5 | 동일 stable_ref 중복 방지 + 기존 재사용 | ✅ test_candidate_generate_duplicate |
| 6 | `cambrian adoption review <handoff>` human-readable 출력 | ✅ 4경로 검증 완료 |
| 7 | handoff/source files 무수정 | ✅ test_candidate_source_immutability |
| 8 | 기존 전체 테스트 green | ✅ 702 passed |
| 9 | 신규 10개 테스트 green | ✅ 10/10 |

---

## 10. 테스트 결과

### brain 테스트 (39 기존 + 10 신규 = 49개)
```
tests/test_brain.py ................................................. 49 passed in 2.88s
```

**신규 10개 breakdown**:

**ReviewGate (4)**
- `test_review_gate_pass` — ready handoff → ("pass", [])
- `test_review_gate_reject_blocked` — handoff_status=blocked → reject + "status=blocked" 포함
- `test_review_gate_reject_reviewer_failed` — ready+reviewer_passed=false → reject
- `test_review_gate_invalid_missing_file` — 존재하지 않는 파일 → invalid

**CandidateGenerator (4)**
- `test_candidate_generate_created` — candidate_status="pending_review", artifact 파일 생성
- `test_candidate_generate_rejected` — blocked handoff → None + candidates_dir 비어있음
- `test_candidate_generate_duplicate` — 2회 호출 시 2회째 duplicate + 파일 1개만 존재
- `test_candidate_source_immutability` — handoff 파일 바이트 단위 불변

**E2E + Schema (2)**
- `test_candidate_e2e_ready_path` — source chain (stable_ref/handoff_ref/source_handoff_path) 전부 검증 + adoption 연결 필드 None
- `test_candidate_all_fields_present` — 24개 필수 키 전부 존재

### 전체 회귀
```
702 passed, 14 skipped in 45.72s
```
- 직전 692 + candidate 10 = 702
- 0 failed, 회귀 없음

---

## 11. ⚠ Task 28 ↔ Task 29 Contract 간극 (식별)

### 현상
Task 28 `HandoffRecord`의 실제 필드 구성:
```
schema_version / handoff_id / created_at /
brain_run_id / task_id / source_*_path / ...
```
**stable_ref 필드 없음** — `brain_run_id`만 존재.

Task 29 `ReviewGate` 규칙 6번은 `stable_ref` 필드 존재를 invalid 판정 기준으로 삼는다. 결과적으로 **Task 28이 실제로 생성한 handoff 파일은 Task 29 ReviewGate에서 항상 invalid로 판정됨**.

### 재현
```bash
# Task 28 smoke에서 생성된 실제 handoff 파일
$ cambrian adoption review .cambrian/brain/handoffs/handoff_20260414_155740_brain-*.json
[REVIEW GATE] (invalid)
  Gate Result : invalid [FAIL]
  Reasons     :
    - stable_ref missing or empty
```

### 원인
- Task 28 spec 3.4 HandoffRecord 정의에 `stable_ref` 필드가 없음 — `brain_run_id`만 있음
- Task 29 spec 3.5 ReviewGate 규칙 6이 `stable_ref` 필드를 필수로 요구
- Task 28 _tests_ `_create_complete_brain_run`은 report의 `provenance_handoff.stable_ref`를 채우지만, 이 값이 Task 28 HandoffRecord로 전사되지 않음 (`_build_record`에 매핑 없음)
- Task 29 _tests_ `_create_handoff_file`은 명시적으로 `stable_ref`를 최상위에 넣어서 fixture 단에서 회피 → 모든 테스트는 green

### 해결 옵션 (차기 Task 후보)
1. **handoff.py 수정 (Task 30)**: HandoffRecord에 `stable_ref: str` 필드 추가 + `_build_record`에서 `provenance_handoff.stable_ref`를 전사. schema_version 1.1.0으로 bump 고려
2. **ReviewGate fallback**: `stable_ref or brain_run_id` 허용 — 하지만 Task 29 spec 위반이므로 별도 decision 필요
3. **현상 유지**: spec대로 동작. 새 Task에서 handoff.py를 1.1.0으로 고쳐서 Task 29와 연결

### 판단
- 이번 Task 29 구현은 spec 100% 준수 — 모든 테스트/acceptance criteria 통과
- Task 28 handoff.py는 수정 금지 (Task 29 제약)
- 차기 Task에서 Task 28 재방문 시 `stable_ref` 필드 추가가 자연스러운 확장점

---

## 12. CLI 실제 동작 검증 (4경로)

spec 준수 handoff (stable_ref 필드 포함) 기준:

### 12.1 Created
```
$ cambrian adoption review handoff_ready.json
[REVIEW GATE] handoff-spec-001
  Task        : task-spec
  Stable Ref  : brain-spec-001
  Gate Result : pass [OK]
  Candidate   : pending_review
  Reviewer    : 완료
  Tests       : exit 0
  Files       : 1 created, 0 modified
  Risks       : none
  Artifact    : ./.cambrian/adoption_candidates/candidate_20260414_162116_brain-spec-001.json
  Next        : candidate registered — ready for adoption decision
```

### 12.2 Duplicate
```
$ cambrian adoption review handoff_ready.json   # 재호출
[REVIEW GATE] handoff-spec-001
  Gate Result : pass [OK] (existing candidate)
  Artifact    : ./.cambrian/adoption_candidates/candidate_20260414_162116_brain-spec-001.json
  Next        : existing candidate reused — no new artifact created
```

### 12.3 Rejected
```
$ cambrian adoption review handoff_blocked.json
[REVIEW GATE] (rejected)
  Gate Result : rejected [FAIL]
  Reasons     :
    - handoff is not ready: status=blocked
    - reviewer did not pass
    - adoption_ready is false
  Artifact    : not created
```

### 12.4 Invalid
```
$ cambrian adoption review nonexistent.json
[REVIEW GATE] (invalid)
  Gate Result : invalid [FAIL]
  Reasons     :
    - handoff file not found: /path/to/nonexistent.json
  Artifact    : not created
```

Windows cp949 호환을 위해 기호는 `[OK]` / `[FAIL]` 텍스트로 표현.

---

## 13. 주요 구현 결정

1. **ReviewGate와 CandidateGenerator 분리**: 판정 책임과 생성 책임을 분리. 각각 독립 테스트 가능. HandoffValidator/HandoffGenerator 구조와 대칭.

2. **중복 방지 전략 — file scan**: DB가 없으므로 `candidates_dir.glob("candidate_*_{stable_ref}.json")`로 중복 체크. 동일 stable_ref의 첫 번째 파일을 재사용. run 수 수만 미만일 때 O(n) 스캔 허용 가능.

3. **duplicate도 record 반환**: CLI가 기존 파일 경로를 안내할 수 있도록 CandidateRecord를 재로드해서 반환. 호출자가 result_type만 분기하면 됨.

4. **invalid vs rejected**: 구조적 결함(파일 없음/깨짐/필수 필드 누락)은 invalid, 정책 미달(status≠ready, reviewer_passed=false, adoption_ready=false)은 rejected. 실무적으로는 "재실행으로 풀 수 있는가"의 차이.

5. **source_handoff_path 절대 경로**: handoff 파일이 `.cambrian/brain/handoffs/` 밖(예: 테스트 tmp_path)에 있을 수 있으므로 입력받은 경로를 그대로 저장. 상대화는 소비자 책임.

6. **adoption_record_ref/decision_ref/review_notes 예약 필드**: 미래 adoption 트리거 / decision 엔진 / 사람 리뷰 메모용. 이번 Task에서는 항상 None/null.

7. **atomic write 3번째 구현**: checkpoint.py / handoff.py와 동일한 패턴 (`tempfile.mkstemp → os.fsync → os.replace`). 중복 코드는 해당 모듈 수정 금지 제약 하에 어쩔 수 없음. 향후 공용 util 추출 가능.

---

## 14. 주의점 / 알려진 제약

- **Task 28 handoff와 직접 파이프라인 연결 시 invalid 판정** (§11 참조) — 실제 운영 시 handoff.py 확장 필요
- candidate 삭제/만료 정책 없음 — 누적만 됨 (v2)
- review_notes 편집 CLI 없음 — 필요 시 JSON 직접 수정
- 동일 stable_ref가 의도적으로 재실행된 경우에도 duplicate로 판정 → 재생성 원하면 기존 파일 수동 삭제 필요
- candidate 간 선호도/랭킹 없음 — 생성만 함

---

## 15. 파일 트리 (이번 Task 29 변경)

```
cambrian/
├── engine/
│   ├── brain/
│   │   └── candidate.py                           # [신규]
│   └── cli.py                                     # [수정 — adoption review 서브커맨드만 추가]
├── tests/
│   └── test_brain.py                              # [append only — 10개 추가]
└── REPORT_task29_review_gate_candidate.md         # [신규]
```

---

## 16. 완료 선언

```
DONE: Task 29 — Review Gate / Adoption Candidate
Files created: engine/brain/candidate.py,
               REPORT_task29_review_gate_candidate.md
Files modified: engine/cli.py (adoption review 서브커맨드 + 핸들러),
                tests/test_brain.py (10개 추가, 기존 39개 무수정)
Tests: 49/49 (brain) — 702/702 (전체, 14 skipped)
Remaining: 없음 (단, Task 28↔29 contract 간극 1건 식별 — §11)
```
