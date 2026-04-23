"""Cambrian Harness → Adoption Review Gate / Candidate Layer.

ready handoff artifact를 adoption review 후보(candidate)로 승격시킨다.
blocked/invalid handoff는 명시적으로 거절한다.

핵심 원칙:
- ready handoff만 candidate 승격 가능
- 동일 stable_ref는 한 번만 candidate 생성 (중복 방지)
- handoff 파일과 brain source files는 일체 수정하지 않음 (read-only)
- candidate는 pending_review 상태로 생성 (자동 adoption 아님)
- DB 없음, file-first
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


SCHEMA_VERSION: str = "1.0.0"
CANDIDATE_STATUS_PENDING: str = "pending_review"


# ═══════════════════════════════════════════════════════════════════
# CandidateRecord
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CandidateRecord:
    """adoption review 대상 후보 artifact."""

    # === 메타 ===
    schema_version: str
    candidate_id: str
    created_at: str
    candidate_status: str

    # === source chain ===
    stable_ref: str
    handoff_ref: str
    brain_run_id: str
    task_id: str

    # === source file paths ===
    source_handoff_path: str
    source_report_path: str
    source_run_state_path: str
    source_task_spec_path: str

    # === 실행 결과 요약 (handoff에서 전사) ===
    reviewer_conclusion: str = ""
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    tests_executed: list[str] = field(default_factory=list)
    test_exit_code: int = -1
    remaining_risks: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    # === review gate 결과 ===
    candidate_ready_for_adoption: bool = True
    gate_passed_at: str = ""

    # === 미래 adoption 연결용 (nullable) ===
    adoption_record_ref: str | None = None
    decision_ref: str | None = None
    review_notes: str | None = None

    def to_dict(self) -> dict:
        """JSON 직렬화용 dict."""
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════
# ReviewGate
# ═══════════════════════════════════════════════════════════════════

class ReviewGate:
    """handoff artifact의 candidate 승격 자격을 판정한다.

    10단계 규칙을 순서대로 실행하되, invalid 사유와 reject 사유를
    각각 누적한 뒤 최종 gate_result를 결정한다.
    """

    def evaluate(
        self,
        handoff_path: Path | str,
    ) -> tuple[str, list[str]]:
        """handoff 자격 검증.

        Args:
            handoff_path: handoff JSON 파일 경로

        Returns:
            (gate_result, rejection_reasons)
            - gate_result: "pass" | "reject" | "invalid"
            - rejection_reasons: 사유 리스트 (pass면 빈 리스트)
        """
        path = Path(handoff_path)
        invalid_reasons: list[str] = []
        reject_reasons: list[str] = []

        # ── 1. 파일 존재 ────────────────────────────────────
        if not path.exists() or not path.is_file():
            return (
                "invalid",
                [f"handoff file not found: {path}"],
            )

        # ── 2. JSON 파싱 ─────────────────────────────────────
        data: dict | None = None
        try:
            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
            else:
                invalid_reasons.append("handoff file is not valid JSON")
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            invalid_reasons.append("handoff file is not valid JSON")

        if data is None:
            return ("invalid", invalid_reasons)

        # ── 3. schema_version ────────────────────────────────
        if "schema_version" not in data:
            invalid_reasons.append(
                "not a valid handoff artifact: missing schema_version"
            )

        # ── 4. handoff_status 필드 존재 ───────────────────────
        if "handoff_status" not in data:
            invalid_reasons.append(
                "not a valid handoff artifact: missing handoff_status"
            )

        # ── 5. handoff_status == "ready" ─────────────────────
        actual_status = data.get("handoff_status")
        if actual_status is not None and actual_status != "ready":
            reject_reasons.append(
                f"handoff is not ready: status={actual_status}"
            )

        # ── 6. stable_ref 존재 및 비어있지 않음 ──────────────
        # backward compatibility:
        # Task 28의 old-style handoff는 stable_ref가 없고 brain_run_id만 있을 수 있다.
        stable_ref = data.get("stable_ref") or data.get("brain_run_id")
        if not stable_ref or not str(stable_ref).strip():
            invalid_reasons.append("stable_ref missing or empty")

        # ── 7. reviewer_passed == True ───────────────────────
        # 존재 여부가 아니라 값이 True인지를 본다.
        reviewer_passed = bool(data.get("reviewer_passed", False))
        if not reviewer_passed:
            reject_reasons.append("reviewer did not pass")

        # ── 8. adoption_ready == True ────────────────────────
        adoption_ready = bool(data.get("adoption_ready", False))
        if not adoption_ready:
            reject_reasons.append("adoption_ready is false")

        # ── 9. brain_run_id 존재 ─────────────────────────────
        brain_run_id = data.get("brain_run_id")
        if not brain_run_id or not str(brain_run_id).strip():
            invalid_reasons.append("brain_run_id missing")

        # ── 10. source_report_path 존재 ──────────────────────
        source_report_path = data.get("source_report_path")
        if not source_report_path or not str(source_report_path).strip():
            invalid_reasons.append("source_report_path missing")

        # ── 결정 ────────────────────────────────────────────
        if invalid_reasons:
            # invalid가 최우선. reject 사유도 함께 반환 (CLI에서 표시).
            all_reasons = invalid_reasons + reject_reasons
            return ("invalid", all_reasons)
        if reject_reasons:
            return ("reject", reject_reasons)
        return ("pass", [])


# ═══════════════════════════════════════════════════════════════════
# CandidateGenerator
# ═══════════════════════════════════════════════════════════════════

class CandidateGenerator:
    """candidate artifact를 생성한다.

    ready handoff만 승격시키고, 동일 stable_ref는 한 번만 생성한다.
    handoff 파일과 brain source files는 수정하지 않는다.
    """

    def __init__(self, candidates_dir: Path | str) -> None:
        """초기화.

        Args:
            candidates_dir: .cambrian/adoption_candidates/ 경로
        """
        self._dir = Path(candidates_dir)
        self._gate = ReviewGate()

    # ═══════════════════════════════════════════════════════════
    # 공개 API
    # ═══════════════════════════════════════════════════════════

    def generate(
        self,
        handoff_path: Path | str,
    ) -> tuple[CandidateRecord | None, str, list[str]]:
        """handoff artifact에서 candidate를 생성한다.

        Args:
            handoff_path: handoff JSON 파일 경로

        Returns:
            (record, result_type, reasons)
            - record: CandidateRecord 또는 None (invalid/rejected)
            - result_type: "created" | "duplicate" | "rejected" | "invalid"
            - reasons: reject/invalid 사유 리스트 (성공 시 빈 리스트)
        """
        path = Path(handoff_path)

        gate_result, reasons = self._gate.evaluate(path)

        if gate_result == "invalid":
            logger.warning(
                "review gate invalid for %s: %s", path, reasons,
            )
            return (None, "invalid", reasons)

        if gate_result == "reject":
            logger.info(
                "review gate rejected for %s: %s", path, reasons,
            )
            return (None, "rejected", reasons)

        # pass: handoff 로드
        handoff_data = self._load_handoff(path)
        if handoff_data is None:
            # 게이트는 통과했으나 로드 실패 — 이례적이지만 방어
            return (None, "invalid", ["handoff reload failed after gate pass"])

        stable_ref = str(
            handoff_data.get("stable_ref")
            or handoff_data.get("brain_run_id")
            or ""
        )

        # 중복 확인
        existing = self._check_duplicate(stable_ref)
        if existing is not None:
            existing_record = self._load_candidate(existing)
            logger.info(
                "duplicate candidate reused: %s (stable_ref=%s)",
                existing, stable_ref,
            )
            return (existing_record, "duplicate", [])

        # 신규 record 구성
        record = self._build_record(
            handoff_path=path,
            handoff_data=handoff_data,
            stable_ref=stable_ref,
        )

        saved = self._save_record(record)
        logger.info(
            "candidate 생성: %s (stable_ref=%s)",
            saved, stable_ref,
        )
        return (record, "created", [])

    # ═══════════════════════════════════════════════════════════
    # 내부 — 중복 확인
    # ═══════════════════════════════════════════════════════════

    def _check_duplicate(self, stable_ref: str) -> Path | None:
        """동일 stable_ref의 기존 candidate 파일을 찾는다.

        파일명 패턴: candidate_*_{stable_ref}.json

        Args:
            stable_ref: dedupe에 사용할 안정 참조값

        Returns:
            기존 candidate 파일 경로 (없으면 None)
        """
        if not stable_ref or not self._dir.exists():
            return None
        matches = sorted(
            self._dir.glob(f"candidate_*_{stable_ref}.json")
        )
        return matches[0] if matches else None

    # ═══════════════════════════════════════════════════════════
    # 내부 — 로드
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _load_handoff(path: Path) -> dict | None:
        """handoff JSON 로드. 실패 시 None."""
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            logger.warning("handoff JSON 로드 실패 (%s): %s", path, exc)
            return None

    @classmethod
    def _load_candidate(cls, path: Path) -> CandidateRecord | None:
        """candidate JSON 로드 → CandidateRecord.

        누락 필드는 dataclass 기본값으로 처리.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            return cls._record_from_dict(data)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            logger.warning("candidate JSON 로드 실패 (%s): %s", path, exc)
            return None

    @staticmethod
    def _record_from_dict(data: dict) -> CandidateRecord:
        """dict → CandidateRecord (누락 필드는 기본값)."""
        def _get_list(key: str) -> list:
            value = data.get(key)
            return list(value) if isinstance(value, list) else []

        return CandidateRecord(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            candidate_id=str(data.get("candidate_id", "")),
            created_at=str(data.get("created_at", "")),
            candidate_status=str(
                data.get("candidate_status", CANDIDATE_STATUS_PENDING)
            ),
            stable_ref=str(data.get("stable_ref", "")),
            handoff_ref=str(data.get("handoff_ref", "")),
            brain_run_id=str(data.get("brain_run_id", "")),
            task_id=str(data.get("task_id", "")),
            source_handoff_path=str(data.get("source_handoff_path", "")),
            source_report_path=str(data.get("source_report_path", "")),
            source_run_state_path=str(data.get("source_run_state_path", "")),
            source_task_spec_path=str(data.get("source_task_spec_path", "")),
            reviewer_conclusion=str(data.get("reviewer_conclusion", "")),
            files_created=_get_list("files_created"),
            files_modified=_get_list("files_modified"),
            tests_executed=_get_list("tests_executed"),
            test_exit_code=int(data.get("test_exit_code", -1) or -1),
            remaining_risks=_get_list("remaining_risks"),
            next_actions=_get_list("next_actions"),
            candidate_ready_for_adoption=bool(
                data.get("candidate_ready_for_adoption", True)
            ),
            gate_passed_at=str(data.get("gate_passed_at", "")),
            adoption_record_ref=data.get("adoption_record_ref"),
            decision_ref=data.get("decision_ref"),
            review_notes=data.get("review_notes"),
        )

    # ═══════════════════════════════════════════════════════════
    # 내부 — record 구성
    # ═══════════════════════════════════════════════════════════

    def _build_record(
        self,
        handoff_path: Path,
        handoff_data: dict,
        stable_ref: str,
    ) -> CandidateRecord:
        """handoff data → CandidateRecord 인스턴스."""
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        candidate_id = (
            f"candidate-{now.strftime('%Y%m%d-%H%M%S')}-"
            f"{secrets.token_hex(2)}"
        )

        def _list_from(key: str) -> list:
            value = handoff_data.get(key)
            return list(value) if isinstance(value, list) else []

        try:
            test_exit_code = int(handoff_data.get("test_exit_code", -1))
        except (TypeError, ValueError):
            test_exit_code = -1

        return CandidateRecord(
            schema_version=SCHEMA_VERSION,
            candidate_id=candidate_id,
            created_at=created_at,
            candidate_status=CANDIDATE_STATUS_PENDING,
            stable_ref=stable_ref,
            handoff_ref=str(handoff_data.get("handoff_id", "")),
            brain_run_id=str(handoff_data.get("brain_run_id", stable_ref)),
            task_id=str(handoff_data.get("task_id", "")),
            source_handoff_path=str(handoff_path),
            source_report_path=str(
                handoff_data.get("source_report_path", "")
            ),
            source_run_state_path=str(
                handoff_data.get("source_run_state_path", "")
            ),
            source_task_spec_path=str(
                handoff_data.get("source_task_spec_path", "")
            ),
            reviewer_conclusion=str(
                handoff_data.get("reviewer_conclusion", "")
            ),
            files_created=_list_from("files_created"),
            files_modified=_list_from("files_modified"),
            tests_executed=_list_from("tests_executed"),
            test_exit_code=test_exit_code,
            remaining_risks=_list_from("remaining_risks"),
            next_actions=_list_from("next_actions"),
            candidate_ready_for_adoption=True,
            gate_passed_at=created_at,
            adoption_record_ref=None,
            decision_ref=None,
            review_notes=None,
        )

    # ═══════════════════════════════════════════════════════════
    # 내부 — atomic write
    # ═══════════════════════════════════════════════════════════

    def _save_record(self, record: CandidateRecord) -> Path:
        """candidate를 atomic write로 저장한다.

        파일명: candidate_<YYYYMMDD_HHMMSS>_<stable_ref>.json

        Returns:
            저장된 파일 경로
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%d_%H%M%S")
        filename = f"candidate_{ts}_{record.stable_ref}.json"
        target = self._dir / filename

        content = json.dumps(
            record.to_dict(), indent=2, ensure_ascii=False,
        )
        self._atomic_write(target, content)
        return target

    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        """tmp 파일에 쓴 뒤 os.replace로 원자적 교체."""
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent),
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
