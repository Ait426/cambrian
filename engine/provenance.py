"""Cambrian Provenance Layer.

SOURCE OF TRUTH: adoption record files in ADOPTIONS_DIR
DERIVED/CACHE: adoption_lineage table (accelerator only)

RULE-1: authoritative read는 항상 files를 먼저 읽는다.
RULE-2: derived state(table/cache)는 accelerate만 허용, override 금지.
RULE-3: derived와 file이 불일치하면 file을 신뢰하고 경고를 낸다.
RULE-4: derived 없이도 lineage/history/audit가 동작해야 한다.
RULE-5: rebuild는 files → derived 방향만 허용. 역방향 금지.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ACTION_TYPES = {"adoption", "rollback", "validation"}


def scan_adoption_files(adoptions_dir: str) -> list[dict]:
    """ADOPTIONS_DIR 내 모든 adoption/rollback/validation JSON을 스캔한다.

    _latest.json은 제외. 파싱 실패 파일은 _error 항목으로 포함.

    Args:
        adoptions_dir: adoption record 디렉토리

    Returns:
        dict 리스트 (adopted_at/timestamp ASC 정렬)
    """
    adopt_dir = Path(adoptions_dir)
    if not adopt_dir.exists():
        return []

    results: list[dict] = []

    for f in sorted(adopt_dir.glob("*.json")):
        if f.name == "_latest.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_source_filename"] = f.name
            data["_source_path"] = str(f)
            results.append(data)
        except Exception:
            results.append({"_error": True, "_path": str(f)})

    # validations/ 하위 디렉토리도 스캔
    val_dir = adopt_dir / "validations"
    if val_dir.exists():
        for f in sorted(val_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["_source_filename"] = f.name
                data["_source_path"] = str(f)
                results.append(data)
            except Exception:
                results.append({"_error": True, "_path": str(f)})

    # adopted_at 또는 timestamp 기준 ASC 정렬
    def _sort_key(d: dict) -> str:
        if d.get("_error"):
            return ""
        return d.get("adopted_at") or d.get("timestamp") or ""

    results.sort(key=_sort_key)
    return results


def get_latest_adoption(adoptions_dir: str) -> Optional[dict]:
    """현재 latest adoption을 반환한다.

    _latest.json이 있으면 우선 사용. 없으면 scan 기반 최신.

    Args:
        adoptions_dir: adoption record 디렉토리

    Returns:
        latest adoption dict 또는 None
    """
    latest_path = Path(adoptions_dir) / "_latest.json"
    if latest_path.exists():
        try:
            return json.loads(latest_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # fallback: scan에서 action_type=adoption 최신
    records = scan_adoption_files(adoptions_dir)
    adoptions = [
        r for r in records
        if not r.get("_error")
        and r.get("action_type") in ("adoption", None)
        and r.get("skill_name") or r.get("skill_id")
    ]
    if adoptions:
        return adoptions[-1]  # ASC 정렬이므로 마지막이 최신
    return None


def reconstruct_lineage(skill_name: str, adoptions_dir: str) -> list[dict]:
    """files만으로 lineage chain을 재구성한다.

    parent_adoption_ref가 있으면 chain 추적.
    없으면 adopted_at 순서 기반 inference.

    Args:
        skill_name: 대상 스킬 이름
        adoptions_dir: adoption record 디렉토리

    Returns:
        [oldest, ..., latest] 순서 리스트
    """
    records = scan_adoption_files(adoptions_dir)
    # skill_name 필터 + error 제외
    skill_records = [
        r for r in records
        if not r.get("_error")
        and (r.get("skill_name") == skill_name or r.get("skill_id") == skill_name)
        and r.get("action_type") in ("adoption", None)
    ]

    if not skill_records:
        return []

    # parent_adoption_ref 기반 chain 시도
    by_run_id: dict[str, dict] = {}
    for r in skill_records:
        rid = r.get("run_id")
        if rid:
            by_run_id[rid] = r

    # parent_ref가 있는 record가 하나라도 있으면 chain 추적
    has_refs = any(r.get("parent_adoption_ref") for r in skill_records)

    if has_refs and by_run_id:
        # 최신 record에서 역추적
        latest = skill_records[-1]
        chain: list[dict] = []
        visited: set[str] = set()
        current = latest

        while current:
            rid = current.get("run_id")
            if not rid or rid in visited:
                break
            visited.add(rid)
            chain.append(current)

            parent_ref = current.get("parent_adoption_ref")
            if isinstance(parent_ref, dict) and parent_ref.get("run_id"):
                current = by_run_id.get(parent_ref["run_id"])
            else:
                break

        chain.reverse()
        return chain

    # fallback: adopted_at ASC 순서 그대로 (이미 정렬됨)
    return skill_records


def rebuild_derived_index(
    adoptions_dir: str,
    conn: sqlite3.Connection,
) -> dict:
    """adoption files에서 adoption_lineage 테이블을 재구성한다.

    기존 테이블은 TRUNCATE 후 재삽입.

    Args:
        adoptions_dir: adoption record 디렉토리
        conn: SQLite 연결

    Returns:
        {"inserted": int, "skipped": int, "errors": int}
    """
    # TRUNCATE
    conn.execute("DELETE FROM adoption_lineage")
    conn.commit()

    records = scan_adoption_files(adoptions_dir)
    inserted = 0
    skipped = 0
    errors = 0

    for r in records:
        if r.get("_error"):
            errors += 1
            continue

        # adoption 타입만 lineage에 삽입
        action = r.get("action_type")
        if action and action not in ("adoption", "rollback"):
            skipped += 1
            continue

        skill_name = r.get("skill_name") or r.get("skill_id")
        run_id = r.get("run_id")
        if not skill_name or not run_id:
            skipped += 1
            continue

        parent_ref = r.get("parent_adoption_ref")
        parent_skill = None
        parent_run = None
        if isinstance(parent_ref, dict):
            parent_skill = skill_name  # 같은 스킬
            parent_run = parent_ref.get("run_id")

        adopted_at = r.get("adopted_at") or r.get("timestamp") or ""
        scenario_id = r.get("scenario_id") or r.get("scenario_ref")
        policy_hash = r.get("policy_hash")

        try:
            conn.execute(
                """
                INSERT INTO adoption_lineage
                    (child_skill_name, child_run_id, parent_skill_name,
                     parent_run_id, scenario_id, policy_hash, adopted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (skill_name, run_id, parent_skill, parent_run,
                 scenario_id, policy_hash, adopted_at),
            )
            inserted += 1
        except Exception:
            errors += 1

    conn.commit()
    return {"inserted": inserted, "skipped": skipped, "errors": errors}


def check_mismatch(
    adoptions_dir: str,
    conn: sqlite3.Connection,
) -> list[dict]:
    """file과 table의 일치 여부를 확인한다.

    Args:
        adoptions_dir: adoption record 디렉토리
        conn: SQLite 연결

    Returns:
        불일치 항목 리스트 (빈 리스트 = 일치)
    """
    # file 기반 run_id set
    records = scan_adoption_files(adoptions_dir)
    file_run_ids = {
        r.get("run_id")
        for r in records
        if not r.get("_error") and r.get("run_id")
        and r.get("action_type") in ("adoption", "rollback", None)
    }

    # table 기반 run_id set
    rows = conn.execute(
        "SELECT child_run_id FROM adoption_lineage"
    ).fetchall()
    table_run_ids = {row[0] for row in rows}

    mismatches: list[dict] = []
    for rid in file_run_ids - table_run_ids:
        mismatches.append({"type": "missing_in_table", "run_id": rid})
    for rid in table_run_ids - file_run_ids:
        mismatches.append({"type": "missing_in_file", "run_id": rid})

    return mismatches


def find_previous_adoption(
    skill_name: str,
    current_run_id: str,
    adoptions_dir: str,
) -> Optional[dict]:
    """files 기반으로 current_run_id의 직전 adoption record를 반환한다.

    Args:
        skill_name: 스킬 이름
        current_run_id: 현재 run ID
        adoptions_dir: adoption record 디렉토리

    Returns:
        이전 adoption record dict 또는 None
    """
    records = scan_adoption_files(adoptions_dir)
    skill_adoptions = [
        r for r in records
        if not r.get("_error")
        and (r.get("skill_name") == skill_name or r.get("skill_id") == skill_name)
        and r.get("action_type") in ("adoption", None)
        and r.get("run_id")
    ]

    # parent_adoption_ref 기반
    for r in skill_adoptions:
        if r.get("run_id") == current_run_id:
            parent_ref = r.get("parent_adoption_ref")
            if isinstance(parent_ref, dict) and parent_ref.get("run_id"):
                parent_id = parent_ref["run_id"]
                for p in skill_adoptions:
                    if p.get("run_id") == parent_id:
                        return p

    # fallback: adopted_at 역순에서 current 바로 이전
    prev = None
    for r in skill_adoptions:
        if r.get("run_id") == current_run_id:
            return prev
        prev = r

    return None


def load_adoption_record(record_path: str) -> dict:
    """단일 adoption record 파일을 로드한다.

    Args:
        record_path: 파일 경로

    Returns:
        파싱된 dict

    Raises:
        ValueError: 파일 없음 또는 파싱 실패 시
    """
    path = Path(record_path)
    if not path.exists():
        raise ValueError(f"Record file not found: {record_path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Record parse error: {exc}") from exc
