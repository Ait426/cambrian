"""Cambrian adoption rollback 레이어.

채택 이력 기반으로 _latest.json을 이전 adoption으로
안전하게 복원한다. 기존 adoption record는 절대 덮어쓰지 않는다.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RollbackError(Exception):
    """rollback 차단 사유를 담은 명시적 예외."""

    pass


def validate_rollback_target(
    target_path: str,
    current_latest: dict,
) -> dict:
    """rollback target의 유효성을 검증한다 (V1~V6).

    V1~V5 실패 시 RollbackError raise.
    V6 실패 시 warnings 리스트에 추가 후 반환.

    Args:
        target_path: target adoption record 파일 경로
        current_latest: 현재 _latest.json 내용 dict

    Returns:
        {"target": <parsed dict>, "warnings": [<str>], "checks_passed": [<str>]}

    Raises:
        RollbackError: V1~V5 검증 실패 시
    """
    checks_passed: list[str] = []
    warnings: list[str] = []

    # V1: 파일 존재
    path = Path(target_path)
    if not path.exists():
        raise RollbackError(f"V1: target file not found: {target_path}")
    checks_passed.append("V1")

    # V2: JSON 파싱
    try:
        target = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RollbackError(f"V2: JSON parse error: {exc}") from exc
    checks_passed.append("V2")

    # V3: skill_name 또는 skill_id 필드 존재
    skill_name = target.get("skill_name") or target.get("skill_id")
    if not skill_name:
        raise RollbackError("V3: target has no skill_name/skill_id field")
    checks_passed.append("V3")

    # V4: target이 현재 latest와 동일한지
    current_run_id = current_latest.get("run_id")
    target_run_id = target.get("run_id")
    if current_run_id and target_run_id and current_run_id == target_run_id:
        raise RollbackError("V4: target is already current (same run_id)")
    checks_passed.append("V4")

    # V5: skill_name 일치
    current_skill = (
        current_latest.get("skill_name")
        or current_latest.get("skill_id")
    )
    if current_skill and skill_name != current_skill:
        raise RollbackError(
            f"V5: skill mismatch (target={skill_name}, current={current_skill})"
        )
    checks_passed.append("V5")

    # V6: scenario/policy metadata 확인 (soft warning)
    if not target.get("scenario_id") and not target.get("decision_provenance"):
        warnings.append("V6: missing scenario/policy metadata")
    checks_passed.append("V6")

    return {
        "target": target,
        "warnings": warnings,
        "checks_passed": checks_passed,
    }


def execute_rollback(
    target_path: str,
    current_latest_path: str,
    human_reason: str | None = None,
    adoptions_dir: str = "adoptions",
    db_conn: sqlite3.Connection | None = None,
) -> dict:
    """rollback을 실행한다.

    순서: validate → record 저장 → lineage INSERT → latest 갱신.
    실패 시 _latest.json은 변경되지 않는다.

    Args:
        target_path: target adoption record 파일 경로
        current_latest_path: 현재 _latest.json 파일 경로
        human_reason: 사람의 rollback 사유
        adoptions_dir: adoption record 저장 디렉토리
        db_conn: SQLite 연결 (lineage 기록용, None이면 스킵)

    Returns:
        rollback record dict

    Raises:
        RollbackError: 검증 실패 또는 record 저장 실패 시
    """
    out_dir = Path(adoptions_dir)
    latest_path = Path(current_latest_path)

    # 1. current_latest 읽기
    if not latest_path.exists():
        raise RollbackError("_latest.json not found")
    current_latest = json.loads(latest_path.read_text(encoding="utf-8"))

    # 2. validate
    validation = validate_rollback_target(target_path, current_latest)
    target = validation["target"]

    skill_name = target.get("skill_name") or target.get("skill_id") or "unknown"
    target_run_id = target.get("run_id") or ""
    target_adopted_at = target.get("timestamp") or target.get("adopted_at") or ""
    current_run_id = current_latest.get("run_id") or ""
    current_adopted_at = current_latest.get("timestamp") or ""

    # 3. rollback record 생성
    timestamp = datetime.now(timezone.utc)
    rollback_record = {
        "schema_version": "1.0",
        "action_type": "rollback",
        "skill_name": skill_name,
        "timestamp": timestamp.isoformat(),
        "previous_latest": {
            "run_id": current_run_id,
            "adopted_at": current_adopted_at,
            "record_path": str(latest_path),
        },
        "target_adoption": {
            "run_id": target_run_id,
            "adopted_at": target_adopted_at,
            "record_path": str(Path(target_path).resolve()),
        },
        "validation_summary": {
            "checks_passed": validation["checks_passed"],
            "warnings": validation["warnings"],
        },
        "human_reason": human_reason,
        "execution_result": "success",
        "operator": "cli",
    }

    # 4. rollback record 파일 저장
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
    record_filename = f"rollback_{skill_name}_{ts_str}.json"
    record_path = out_dir / record_filename

    try:
        record_path.write_text(
            json.dumps(rollback_record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        raise RollbackError(f"Failed to save rollback record: {exc}") from exc

    # 5. lineage INSERT (실패해도 중단하지 않음)
    if db_conn is not None:
        try:
            adopted_at = timestamp.isoformat()
            db_conn.execute(
                """
                INSERT INTO adoption_lineage
                    (child_skill_name, child_run_id, parent_skill_name,
                     parent_run_id, adopted_at, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    skill_name,
                    target_run_id,
                    skill_name,
                    current_run_id,
                    adopted_at,
                    f"[rollback] {human_reason or ''}".strip(),
                ),
            )
            db_conn.commit()
        except Exception as exc:
            logger.warning("Lineage INSERT 실패 (rollback 계속): %s", exc)

    # 6. _latest.json 갱신
    latest_data = {
        "latest_adoption": record_filename,
        "skill_id": skill_name,
        "skill_name": skill_name,
        "run_id": target_run_id,
        "promoted_to": target.get("promoted_to", ""),
        "timestamp": timestamp.isoformat(),
        "action": "rollback",
    }
    latest_path.write_text(
        json.dumps(latest_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    rollback_record["_record_path"] = str(record_path)
    return rollback_record


def resolve_previous_adoption(
    skill_name: str,
    current_run_id: str,
    db_conn: sqlite3.Connection,
    adoptions_dir: str = "adoptions",
) -> Optional[str]:
    """adoption_lineage에서 현재 run_id의 parent를 찾아 경로를 반환한다.

    Args:
        skill_name: 스킬 이름
        current_run_id: 현재 run ID
        db_conn: SQLite 연결
        adoptions_dir: adoption record 디렉토리

    Returns:
        이전 adoption record 경로 또는 None
    """
    row = db_conn.execute(
        """
        SELECT parent_run_id FROM adoption_lineage
        WHERE child_run_id = ? AND child_skill_name = ?
        ORDER BY adopted_at DESC LIMIT 1
        """,
        (current_run_id, skill_name),
    ).fetchone()

    if not row or not row[0]:
        return None

    parent_run_id = row[0]

    # adoptions_dir에서 parent_run_id가 포함된 파일 검색
    adopt_dir = Path(adoptions_dir)
    if not adopt_dir.exists():
        return None

    for f in adopt_dir.glob("adoption_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("run_id") == parent_run_id:
                return str(f)
        except Exception:
            continue

    return None
