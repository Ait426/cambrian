"""Provenance Source-of-Truth 테스트 (Task 24).

file-first scan, lineage reconstruction, rebuild, mismatch 검출,
file-only 동작을 검증한다.
"""

import json
from pathlib import Path

import pytest

from engine.provenance import (
    check_mismatch,
    find_previous_adoption,
    get_latest_adoption,
    load_adoption_record,
    rebuild_derived_index,
    reconstruct_lineage,
    scan_adoption_files,
)


def _write_record(
    tmp_path: Path,
    name: str,
    skill: str = "summarize",
    run_id: str | None = None,
    action_type: str = "adoption",
    adopted_at: str = "2026-04-06T12:00:00",
    parent_ref: dict | None = None,
) -> Path:
    """테스트용 adoption record 파일 생성."""
    record = {
        "skill_name": skill,
        "skill_id": skill,
        "run_id": run_id or f"run-{name}",
        "action_type": action_type,
        "adopted_at": adopted_at,
        "timestamp": adopted_at,
    }
    if parent_ref is not None:
        record["parent_adoption_ref"] = parent_ref
    path = tmp_path / f"{action_type}_{name}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


# === T1: scan_adoption_files — 3개 파일 → 3개 반환 ===

def test_scan_returns_all_files(tmp_path: Path) -> None:
    """JSON 3개 → dict 3개 반환, _source_filename 포함."""
    _write_record(tmp_path, "a", adopted_at="2026-01-01T00:00:00")
    _write_record(tmp_path, "b", adopted_at="2026-02-01T00:00:00")
    _write_record(tmp_path, "c", adopted_at="2026-03-01T00:00:00")

    results = scan_adoption_files(str(tmp_path))
    valid = [r for r in results if not r.get("_error")]
    assert len(valid) == 3
    assert all("_source_filename" in r for r in valid)


# === T2: scan — 파싱 실패 파일 포함 ===

def test_scan_includes_error_files(tmp_path: Path) -> None:
    """파싱 불가 파일 → _error:True 항목 포함."""
    _write_record(tmp_path, "good")
    bad = tmp_path / "broken.json"
    bad.write_text("{invalid!", encoding="utf-8")

    results = scan_adoption_files(str(tmp_path))
    errors = [r for r in results if r.get("_error")]
    assert len(errors) == 1


# === T3: get_latest — _latest.json 있음 ===

def test_get_latest_with_file(tmp_path: Path) -> None:
    """_latest.json이 있으면 해당 record 반환."""
    latest = {"skill_id": "summarize", "run_id": "run-latest"}
    (tmp_path / "_latest.json").write_text(json.dumps(latest), encoding="utf-8")

    result = get_latest_adoption(str(tmp_path))
    assert result is not None
    assert result["run_id"] == "run-latest"


# === T4: get_latest — _latest.json 없음 → scan 기반 ===

def test_get_latest_without_file(tmp_path: Path) -> None:
    """_latest.json 없으면 scan 기반 최신 adoption 반환."""
    _write_record(tmp_path, "old", adopted_at="2026-01-01T00:00:00")
    _write_record(tmp_path, "new", adopted_at="2026-06-01T00:00:00")

    result = get_latest_adoption(str(tmp_path))
    assert result is not None
    assert result["run_id"] == "run-new"


# === T5: reconstruct_lineage — parent_adoption_ref 있음 ===

def test_lineage_with_parent_ref(tmp_path: Path) -> None:
    """parent_adoption_ref가 있으면 올바른 chain."""
    _write_record(tmp_path, "gen1", run_id="r1", adopted_at="2026-01-01T00:00:00")
    _write_record(
        tmp_path, "gen2", run_id="r2", adopted_at="2026-02-01T00:00:00",
        parent_ref={"run_id": "r1", "record_filename": "adoption_gen1.json"},
    )
    _write_record(
        tmp_path, "gen3", run_id="r3", adopted_at="2026-03-01T00:00:00",
        parent_ref={"run_id": "r2", "record_filename": "adoption_gen2.json"},
    )

    chain = reconstruct_lineage("summarize", str(tmp_path))
    assert len(chain) == 3
    assert chain[0]["run_id"] == "r1"  # oldest
    assert chain[-1]["run_id"] == "r3"  # latest


# === T6: reconstruct_lineage — parent_ref 없음 → adopted_at 순 ===

def test_lineage_without_parent_ref(tmp_path: Path) -> None:
    """parent_ref 없으면 adopted_at 순 inference."""
    _write_record(tmp_path, "a", adopted_at="2026-01-01T00:00:00")
    _write_record(tmp_path, "b", adopted_at="2026-02-01T00:00:00")

    chain = reconstruct_lineage("summarize", str(tmp_path))
    assert len(chain) == 2
    assert chain[0]["run_id"] == "run-a"
    assert chain[1]["run_id"] == "run-b"


# === T7: rebuild_derived_index ===

def test_rebuild_index(tmp_path: Path) -> None:
    """files → table INSERT 성공."""
    from engine.registry import SkillRegistry
    reg = SkillRegistry(":memory:")

    _write_record(tmp_path, "a", adopted_at="2026-01-01T00:00:00")
    _write_record(tmp_path, "b", adopted_at="2026-02-01T00:00:00")

    result = rebuild_derived_index(str(tmp_path), reg._conn)
    assert result["inserted"] == 2
    assert result["errors"] == 0
    reg.close()


# === T8: check_mismatch — 일치 ===

def test_mismatch_none(tmp_path: Path) -> None:
    """file/table 일치 → 빈 list."""
    from engine.registry import SkillRegistry
    reg = SkillRegistry(":memory:")

    _write_record(tmp_path, "a")
    rebuild_derived_index(str(tmp_path), reg._conn)

    mismatches = check_mismatch(str(tmp_path), reg._conn)
    assert mismatches == []
    reg.close()


# === T9: check_mismatch — table 누락 ===

def test_mismatch_missing_in_table(tmp_path: Path) -> None:
    """file에 있지만 table에 없는 항목 감지."""
    from engine.registry import SkillRegistry
    reg = SkillRegistry(":memory:")

    _write_record(tmp_path, "a")
    # table은 비어있음 (rebuild 안 함)

    mismatches = check_mismatch(str(tmp_path), reg._conn)
    missing = [m for m in mismatches if m["type"] == "missing_in_table"]
    assert len(missing) >= 1
    reg.close()


# === T10: find_previous — parent_ref 기반 ===

def test_find_previous_with_ref(tmp_path: Path) -> None:
    """parent_adoption_ref 기반 직전 record 반환."""
    _write_record(tmp_path, "parent", run_id="r1", adopted_at="2026-01-01T00:00:00")
    _write_record(
        tmp_path, "child", run_id="r2", adopted_at="2026-02-01T00:00:00",
        parent_ref={"run_id": "r1"},
    )

    result = find_previous_adoption("summarize", "r2", str(tmp_path))
    assert result is not None
    assert result["run_id"] == "r1"


# === T11: find_previous — adopted_at 역순 ===

def test_find_previous_by_time(tmp_path: Path) -> None:
    """parent_ref 없으면 adopted_at 역순 탐색."""
    _write_record(tmp_path, "a", run_id="r1", adopted_at="2026-01-01T00:00:00")
    _write_record(tmp_path, "b", run_id="r2", adopted_at="2026-02-01T00:00:00")

    result = find_previous_adoption("summarize", "r2", str(tmp_path))
    assert result is not None
    assert result["run_id"] == "r1"


# === T12: rollback resolve — db_conn=None, file-only ===

def test_rollback_resolve_file_only(tmp_path: Path) -> None:
    """db_conn 없이 file 기반 resolve."""
    from engine.rollback import resolve_previous_adoption

    _write_record(tmp_path, "parent", run_id="r1", adopted_at="2026-01-01T00:00:00")
    _write_record(
        tmp_path, "child", run_id="r2", adopted_at="2026-02-01T00:00:00",
        parent_ref={"run_id": "r1"},
    )

    result = resolve_previous_adoption(
        "summarize", "r2", db_conn=None, adoptions_dir=str(tmp_path),
    )
    assert result is not None


# === T13: validation basis — inline_metrics (table 불필요) ===

def test_validation_basis_inline() -> None:
    """inline_metrics 기반 basis 로드 — table 불필요."""
    from engine.validation import load_comparison_basis

    adoption = {"metrics": {"score": 0.8, "latency_ms": 100}}
    result = load_comparison_basis(adoption)
    assert result["source"] == "inline_metrics"
    assert result["basis_metrics"]["score"] == 0.8


# === T14: CLI rebuild-index (구조 검증) ===

def test_rebuild_index_result_structure(tmp_path: Path) -> None:
    """rebuild_derived_index가 올바른 구조를 반환한다."""
    from engine.registry import SkillRegistry
    reg = SkillRegistry(":memory:")

    _write_record(tmp_path, "x", action_type="validation")
    _write_record(tmp_path, "y", action_type="adoption")

    result = rebuild_derived_index(str(tmp_path), reg._conn)
    assert "inserted" in result
    assert "skipped" in result
    assert "errors" in result
    assert result["inserted"] == 1  # adoption만
    assert result["skipped"] == 1   # validation 스킵
    reg.close()


# === T15: CLI adoption list (구조 검증) ===

def test_scan_filters_latest_json(tmp_path: Path) -> None:
    """scan_adoption_files가 _latest.json을 제외한다."""
    _write_record(tmp_path, "a")
    (tmp_path / "_latest.json").write_text('{"skip": true}', encoding="utf-8")

    results = scan_adoption_files(str(tmp_path))
    filenames = [r.get("_source_filename") for r in results if not r.get("_error")]
    assert "_latest.json" not in filenames


# === T16: load_adoption_record ===

def test_load_adoption_record(tmp_path: Path) -> None:
    """단일 record 로드."""
    path = _write_record(tmp_path, "test")
    data = load_adoption_record(str(path))
    assert data["skill_name"] == "summarize"


def test_load_adoption_record_not_found() -> None:
    """파일 없으면 ValueError."""
    with pytest.raises(ValueError, match="not found"):
        load_adoption_record("/nonexistent.json")


# === T17: 구형 record (parent_ref 없음) → None fallback ===

def test_old_record_no_parent_ref(tmp_path: Path) -> None:
    """parent_adoption_ref가 없는 구형 record 읽기 → None."""
    _write_record(tmp_path, "old", run_id="r1")
    results = scan_adoption_files(str(tmp_path))
    assert results[0].get("parent_adoption_ref") is None


# === T18: empty dir → empty results ===

def test_empty_dir(tmp_path: Path) -> None:
    """빈 디렉토리 → 빈 리스트."""
    empty = tmp_path / "empty"
    empty.mkdir()
    assert scan_adoption_files(str(empty)) == []
    assert get_latest_adoption(str(empty)) is None
