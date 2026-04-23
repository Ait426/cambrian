"""Cambrian Harness Brain → Adoption/Provenance Handoff Layer.

brain run 결과를 adoption/provenance 시스템이 소비할 수 있는
표준 handoff artifact로 변환한다.

핵심 원칙:
- source brain run files는 절대 수정하지 않는다 (read-only).
- readiness validation 통과 시 'ready', 통과 실패 시 'blocked' 또는 'invalid'.
- invalid 상태는 artifact 파일을 생성하지 않는다 (source 자체가 없음).
- blocked는 증거 기록 목적으로 artifact를 생성한다.
- DB 없음. 모든 결과는 .cambrian/brain/handoffs/<file>.json 으로 파일 저장.
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


SCHEMA_VERSION: str = "1.1.0"


# ═══════════════════════════════════════════════════════════════════
# HandoffRecord
# ═══════════════════════════════════════════════════════════════════

@dataclass
class HandoffRecord:
    """brain run → adoption/provenance 전달용 공식 handoff artifact.

    schema_version은 문서화된 필드 스펙과 호환되는 상수.
    handoff_status 값: "ready" | "blocked" | "invalid".
    """

    # === 메타 ===
    schema_version: str
    handoff_id: str
    created_at: str

    # === source refs ===
    stable_ref: str
    brain_run_id: str
    task_id: str
    source_report_path: str
    source_run_state_path: str
    source_task_spec_path: str
    source_iterations_dir: str

    # === 실행 결과 요약 ===
    run_status: str
    reviewer_passed: bool
    adoption_ready: bool
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    tests_executed: list[str] = field(default_factory=list)
    test_exit_code: int = -1
    reviewer_conclusion: str = ""
    remaining_risks: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    # === handoff 판정 ===
    handoff_status: str = "invalid"
    block_reasons: list[str] = field(default_factory=list)

    # === 미래 adoption 연결용 (nullable) ===
    adoption_record_ref: str | None = None
    decision_ref: str | None = None

    def to_dict(self) -> dict:
        """JSON 직렬화용 dict."""
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════
# HandoffValidator
# ═══════════════════════════════════════════════════════════════════

class HandoffValidator:
    """brain run의 handoff 자격을 검증한다.

    10단계 규칙을 순서대로 실행하되, invalid 사유와 blocked 사유를
    각각 누적한 뒤 최종 status를 결정한다.
    """

    def validate(
        self,
        runs_dir: Path,
        run_id: str,
    ) -> tuple[str, list[str]]:
        """handoff 자격 검증.

        Args:
            runs_dir: .cambrian/brain/runs/
            run_id: 검증할 brain run ID

        Returns:
            (handoff_status, block_reasons)
            - handoff_status: "ready" | "blocked" | "invalid"
            - block_reasons: 사유 리스트 (ready면 빈 리스트)
        """
        invalid_reasons: list[str] = []
        blocked_reasons: list[str] = []

        run_dir = runs_dir / run_id

        # ── 1. run 디렉토리 존재 ─────────────────────────────
        if not run_dir.exists() or not run_dir.is_dir():
            return (
                "invalid",
                [f"run directory not found: {run_dir}"],
            )

        # ── 2. run_state.json 존재 + 파싱 ────────────────────
        run_state_path = run_dir / "run_state.json"
        run_state: dict | None = None
        if not run_state_path.exists():
            invalid_reasons.append("run_state.json missing or malformed")
        else:
            try:
                run_state = json.loads(
                    run_state_path.read_text(encoding="utf-8"),
                )
                if not isinstance(run_state, dict):
                    invalid_reasons.append(
                        "run_state.json missing or malformed"
                    )
                    run_state = None
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                invalid_reasons.append("run_state.json missing or malformed")

        # ── 3. report.json 존재 + 파싱 ───────────────────────
        report_path = run_dir / "report.json"
        report: dict | None = None
        if not report_path.exists():
            invalid_reasons.append("report.json missing or malformed")
        else:
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                if not isinstance(report, dict):
                    invalid_reasons.append(
                        "report.json missing or malformed"
                    )
                    report = None
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                invalid_reasons.append("report.json missing or malformed")

        # ── 4. task_spec.yaml 존재 ───────────────────────────
        task_spec_path = run_dir / "task_spec.yaml"
        if not task_spec_path.exists():
            invalid_reasons.append("task_spec.yaml missing")

        # ── 5. run_state.status == "completed" ───────────────
        if run_state is not None:
            actual_status = str(run_state.get("status", ""))
            if actual_status != "completed":
                blocked_reasons.append(
                    f"run not completed: status={actual_status or 'unknown'}"
                )

        # ── 6. provenance_handoff 섹션 존재 ──────────────────
        handoff_section: dict = {}
        if report is not None:
            section = report.get("provenance_handoff")
            if not isinstance(section, dict):
                invalid_reasons.append(
                    "provenance_handoff section missing in report"
                )
            else:
                handoff_section = section

        # ── 7. stable_ref 존재 및 비어있지 않음 ───────────────
        if handoff_section:
            # backward compatibility:
            # 오래된 report는 stable_ref가 없을 수 있으므로 run_id로 보정한다.
            stable_ref = handoff_section.get("stable_ref") or run_id
            if not stable_ref or not str(stable_ref).strip():
                invalid_reasons.append("stable_ref missing or empty")

        # ── 8. reviewer_passed == True ───────────────────────
        if handoff_section:
            reviewer_passed = bool(
                handoff_section.get("reviewer_passed", False)
            )
            if not reviewer_passed:
                blocked_reasons.append("reviewer did not pass")

        # ── 9. adoption_ready == True ────────────────────────
        if handoff_section:
            adoption_ready = bool(
                handoff_section.get("adoption_ready", False)
            )
            if not adoption_ready:
                blocked_reasons.append("adoption_ready is false")

        # ── 10. test_exit_code == 0 ──────────────────────────
        if handoff_section:
            exit_code = handoff_section.get("test_exit_code", -1)
            try:
                exit_int = int(exit_code)
            except (TypeError, ValueError):
                exit_int = -1
            if exit_int != 0:
                blocked_reasons.append(
                    f"tests did not pass: exit_code={exit_int}"
                )

        # ── 최종 status 결정 ──────────────────────────────────
        if invalid_reasons:
            # invalid가 하나라도 있으면 invalid. blocked 사유도 같이 보고.
            all_reasons = invalid_reasons + blocked_reasons
            return ("invalid", all_reasons)
        if blocked_reasons:
            return ("blocked", blocked_reasons)
        return ("ready", [])


# ═══════════════════════════════════════════════════════════════════
# HandoffGenerator
# ═══════════════════════════════════════════════════════════════════

class HandoffGenerator:
    """handoff artifact를 생성하고 파일로 저장한다.

    source brain run files를 읽기만 하고 수정하지 않는다.
    invalid 결과는 artifact를 생성하지 않고 HandoffRecord만 반환한다.
    blocked/ready는 artifact를 생성한다.
    """

    def __init__(
        self,
        runs_dir: Path | str,
        handoffs_dir: Path | str,
    ) -> None:
        """초기화.

        Args:
            runs_dir: .cambrian/brain/runs/ 경로
            handoffs_dir: .cambrian/brain/handoffs/ 경로
        """
        self._runs_dir = Path(runs_dir)
        self._handoffs_dir = Path(handoffs_dir)
        self._validator = HandoffValidator()

    # ═══════════════════════════════════════════════════════════
    # 공개 API
    # ═══════════════════════════════════════════════════════════

    def generate(self, run_id: str) -> HandoffRecord:
        """brain run 결과에서 handoff artifact를 생성한다.

        Args:
            run_id: brain run ID

        Returns:
            HandoffRecord (invalid여도 반환)
        """
        handoff_status, reasons = self._validator.validate(
            self._runs_dir, run_id,
        )

        report = self._load_report(run_id)
        run_state = self._load_run_state(run_id)

        record = self._build_record(
            run_id=run_id,
            report=report,
            run_state=run_state,
            handoff_status=handoff_status,
            block_reasons=reasons,
        )

        if handoff_status == "invalid":
            logger.warning(
                "handoff invalid for run=%s: %s", run_id, reasons,
            )
            # invalid는 artifact 저장하지 않음
            return record

        saved_path = self._save_record(record)
        logger.info(
            "handoff artifact 저장: %s (status=%s)",
            saved_path, handoff_status,
        )
        return record

    # ═══════════════════════════════════════════════════════════
    # 내부 — 로드
    # ═══════════════════════════════════════════════════════════

    def _load_report(self, run_id: str) -> dict:
        """report.json 로드. 실패 시 빈 dict."""
        path = self._runs_dir / run_id / "report.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            logger.warning("report.json 로드 실패 (%s): %s", run_id, exc)
            return {}

    def _load_run_state(self, run_id: str) -> dict:
        """run_state.json 로드. 실패 시 빈 dict."""
        path = self._runs_dir / run_id / "run_state.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            logger.warning("run_state.json 로드 실패 (%s): %s", run_id, exc)
            return {}

    # ═══════════════════════════════════════════════════════════
    # 내부 — HandoffRecord 구성
    # ═══════════════════════════════════════════════════════════

    def _build_record(
        self,
        run_id: str,
        report: dict,
        run_state: dict,
        handoff_status: str,
        block_reasons: list[str],
    ) -> HandoffRecord:
        """HandoffRecord 인스턴스를 구성한다.

        source files를 최대한 보수적으로 읽어 누락 시에도 크래시하지 않는다.
        """
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        handoff_id = (
            f"handoff-{now.strftime('%Y%m%d-%H%M%S')}-"
            f"{secrets.token_hex(2)}"
        )

        # source 경로는 저장소 루트 기준 상대 경로로 고정한다.
        base_rel = f".cambrian/brain/runs/{run_id}"
        source_report_path = f"{base_rel}/report.json"
        source_run_state_path = f"{base_rel}/run_state.json"
        source_task_spec_path = f"{base_rel}/task_spec.yaml"
        source_iterations_dir = f"{base_rel}/iterations/"

        # task_id 추출: report > run_state > "" 우선순위
        task_id = str(
            report.get("task_id")
            or (run_state.get("task_spec") or {}).get("task_id")
            or ""
        )

        # run_status
        run_status = str(
            run_state.get("status")
            or report.get("status")
            or "unknown"
        )

        # provenance_handoff 섹션
        prov: dict = {}
        raw_prov = report.get("provenance_handoff")
        if isinstance(raw_prov, dict):
            prov = raw_prov

        reviewer_passed = bool(prov.get("reviewer_passed", False))
        adoption_ready = bool(prov.get("adoption_ready", False))
        files_created = list(prov.get("files_created") or [])
        files_modified = list(prov.get("files_modified") or [])
        tests_executed = list(prov.get("tests_executed") or [])
        try:
            test_exit_code = int(prov.get("test_exit_code", -1))
        except (TypeError, ValueError):
            test_exit_code = -1
        reviewer_conclusion = str(prov.get("reviewer_conclusion", ""))
        stable_ref = str(prov.get("stable_ref") or run_id)

        # remaining_risks / next_actions는 report 최상위에서
        remaining_risks = list(report.get("remaining_risks") or [])
        next_actions = list(report.get("next_actions") or [])

        return HandoffRecord(
            schema_version=SCHEMA_VERSION,
            handoff_id=handoff_id,
            created_at=created_at,
            stable_ref=stable_ref,
            brain_run_id=run_id,
            task_id=task_id,
            source_report_path=source_report_path,
            source_run_state_path=source_run_state_path,
            source_task_spec_path=source_task_spec_path,
            source_iterations_dir=source_iterations_dir,
            run_status=run_status,
            reviewer_passed=reviewer_passed,
            adoption_ready=adoption_ready,
            files_created=files_created,
            files_modified=files_modified,
            tests_executed=tests_executed,
            test_exit_code=test_exit_code,
            reviewer_conclusion=reviewer_conclusion,
            remaining_risks=remaining_risks,
            next_actions=next_actions,
            handoff_status=handoff_status,
            block_reasons=list(block_reasons),
            adoption_record_ref=None,
            decision_ref=None,
        )

    # ═══════════════════════════════════════════════════════════
    # 내부 — 저장 (atomic write)
    # ═══════════════════════════════════════════════════════════

    def _save_record(self, record: HandoffRecord) -> Path:
        """handoff record를 handoffs_dir에 atomic write로 저장한다.

        파일명: handoff_<YYYYMMDD_HHMMSS>_<brain_run_id>.json

        Returns:
            저장된 파일 경로
        """
        self._handoffs_dir.mkdir(parents=True, exist_ok=True)

        # 파일명용 timestamp: _ 구분자 (handoff_id는 - 구분자)
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%d_%H%M%S")
        filename = f"handoff_{ts}_{record.brain_run_id}.json"
        target = self._handoffs_dir / filename

        content = json.dumps(
            record.to_dict(), indent=2, ensure_ascii=False,
        )
        self._atomic_write(target, content)
        return target

    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        """tmp 파일에 쓴 뒤 os.replace로 원자적 교체.

        checkpoint.py와 동일한 패턴.
        """
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
