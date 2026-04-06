"""Adoption Rollback 테스트 (Task 22).

validate_rollback_target, execute_rollback, resolve_previous_adoption,
CLI adoption rollback 동작을 검증한다.
"""

import json
from pathlib import Path

import pytest

from engine.rollback import (
    RollbackError,
    execute_rollback,
    resolve_previous_adoption,
    validate_rollback_target,
)


def _write_adoption(tmp_path: Path, name: str, **fields: object) -> Path:
    """테스트용 adoption record JSON 파일을 생성한다."""
    record: dict = {
        "skill_name": "summarize",
        "skill_id": "summarize",
        "run_id": f"run-{name}",
        "promoted_to": "production",
        "timestamp": "2026-04-06T12:00:00",
        "adopted_at": "2026-04-06T12:00:00",
    }
    record.update(fields)
    path = tmp_path / f"adoption_{name}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _write_latest(tmp_path: Path, **fields: object) -> Path:
    """테스트용 _latest.json을 생성한다."""
    data: dict = {
        "skill_id": "summarize",
        "skill_name": "summarize",
        "run_id": "run-current",
        "promoted_to": "production",
        "timestamp": "2026-04-06T14:00:00",
    }
    data.update(fields)
    path = tmp_path / "_latest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# === T1: valid target → rollback 성공 ===

def test_valid_rollback_success(tmp_path: Path) -> None:
    """유효한 target → execute_rollback 성공."""
    target = _write_adoption(tmp_path, "old", run_id="run-old")
    latest = _write_latest(tmp_path, run_id="run-current")

    record = execute_rollback(
        target_path=str(target),
        current_latest_path=str(latest),
        human_reason="테스트 롤백",
        adoptions_dir=str(tmp_path),
    )

    assert record["action_type"] == "rollback"
    assert record["execution_result"] == "success"
    assert record["skill_name"] == "summarize"


# === T2: 존재하지 않는 파일 → RollbackError ===

def test_file_not_found(tmp_path: Path) -> None:
    """파일이 없으면 RollbackError (V1)."""
    latest = {"run_id": "run-x", "skill_name": "s"}
    with pytest.raises(RollbackError, match="V1"):
        validate_rollback_target("/nonexistent.json", latest)


# === T3: JSON 파싱 불가 → RollbackError ===

def test_json_parse_error(tmp_path: Path) -> None:
    """깨진 JSON → RollbackError (V2)."""
    bad = tmp_path / "bad.json"
    bad.write_text("{broken!", encoding="utf-8")
    latest = {"run_id": "run-x", "skill_name": "s"}

    with pytest.raises(RollbackError, match="V2"):
        validate_rollback_target(str(bad), latest)


# === T4: skill_name 없음 → RollbackError ===

def test_no_skill_name(tmp_path: Path) -> None:
    """skill_name 없는 record → RollbackError (V3)."""
    no_skill = tmp_path / "no_skill.json"
    no_skill.write_text(json.dumps({"run_id": "r1"}), encoding="utf-8")
    latest = {"run_id": "run-x", "skill_name": "s"}

    with pytest.raises(RollbackError, match="V3"):
        validate_rollback_target(str(no_skill), latest)


# === T5: target == current → RollbackError ===

def test_same_run_id(tmp_path: Path) -> None:
    """target run_id == current run_id → RollbackError (V4)."""
    target = _write_adoption(tmp_path, "same", run_id="run-same")
    latest = {"run_id": "run-same", "skill_name": "summarize"}

    with pytest.raises(RollbackError, match="V4.*already current"):
        validate_rollback_target(str(target), latest)


# === T6: skill_name mismatch → RollbackError ===

def test_skill_mismatch(tmp_path: Path) -> None:
    """skill_name 불일치 → RollbackError (V5)."""
    target = _write_adoption(tmp_path, "other", skill_name="translate", skill_id="translate")
    latest = {"run_id": "run-x", "skill_name": "summarize"}

    with pytest.raises(RollbackError, match="V5.*skill mismatch"):
        validate_rollback_target(str(target), latest)


# === T7: scenario metadata 없음 → warnings + 성공 ===

def test_missing_metadata_warning(tmp_path: Path) -> None:
    """scenario/policy metadata 없으면 경고만, rollback 진행."""
    target = _write_adoption(tmp_path, "no_meta", run_id="run-old")
    latest = {"run_id": "run-current", "skill_name": "summarize"}

    result = validate_rollback_target(str(target), latest)
    assert len(result["warnings"]) > 0
    assert "V6" in result["warnings"][0]
    assert result["target"]["run_id"] == "run-old"


# === T8: rollback record 파일 생성 ===

def test_rollback_record_created(tmp_path: Path) -> None:
    """rollback 성공 시 record 파일이 생성된다."""
    target = _write_adoption(tmp_path, "old", run_id="run-old")
    _write_latest(tmp_path, run_id="run-current")

    execute_rollback(
        target_path=str(target),
        current_latest_path=str(tmp_path / "_latest.json"),
        adoptions_dir=str(tmp_path),
    )

    rollback_files = list(tmp_path.glob("rollback_*.json"))
    assert len(rollback_files) == 1

    record = json.loads(rollback_files[0].read_text(encoding="utf-8"))
    assert record["action_type"] == "rollback"


# === T9: _latest.json이 target으로 갱신 ===

def test_latest_updated_to_target(tmp_path: Path) -> None:
    """rollback 후 _latest.json이 target adoption을 가리킨다."""
    target = _write_adoption(tmp_path, "old", run_id="run-old")
    _write_latest(tmp_path, run_id="run-current")

    execute_rollback(
        target_path=str(target),
        current_latest_path=str(tmp_path / "_latest.json"),
        adoptions_dir=str(tmp_path),
    )

    latest = json.loads((tmp_path / "_latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "run-old"
    assert latest["action"] == "rollback"


# === T10: 검증 실패 시 _latest.json 불변 ===

def test_failed_rollback_preserves_latest(tmp_path: Path) -> None:
    """검증 실패 시 _latest.json이 변경되지 않는다."""
    _write_latest(tmp_path, run_id="run-current")

    original = (tmp_path / "_latest.json").read_text(encoding="utf-8")

    with pytest.raises(RollbackError):
        execute_rollback(
            target_path="/nonexistent.json",
            current_latest_path=str(tmp_path / "_latest.json"),
            adoptions_dir=str(tmp_path),
        )

    after = (tmp_path / "_latest.json").read_text(encoding="utf-8")
    assert original == after


# === T11: CLI smoke — 성공 (구조 검증) ===

def test_cli_rollback_structure(tmp_path: Path) -> None:
    """execute_rollback이 올바른 구조의 record를 반환한다."""
    target = _write_adoption(tmp_path, "old", run_id="run-old")
    _write_latest(tmp_path, run_id="run-current")

    record = execute_rollback(
        target_path=str(target),
        current_latest_path=str(tmp_path / "_latest.json"),
        human_reason="CLI 테스트",
        adoptions_dir=str(tmp_path),
    )

    required_keys = {
        "schema_version", "action_type", "skill_name", "timestamp",
        "previous_latest", "target_adoption", "validation_summary",
        "human_reason", "execution_result", "operator",
    }
    assert required_keys.issubset(record.keys())
    assert record["human_reason"] == "CLI 테스트"


# === T12: CLI invalid path → 실패, latest 불변 ===

def test_cli_invalid_path_preserves_latest(tmp_path: Path) -> None:
    """없는 경로 → RollbackError, latest 불변."""
    _write_latest(tmp_path, run_id="run-current")

    with pytest.raises(RollbackError):
        execute_rollback(
            target_path=str(tmp_path / "nonexistent.json"),
            current_latest_path=str(tmp_path / "_latest.json"),
            adoptions_dir=str(tmp_path),
        )

    latest = json.loads((tmp_path / "_latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "run-current"


# === T13: 기존 테스트 regression 없음 (전체 pytest에서 확인) ===

def test_rollback_error_is_exception() -> None:
    """RollbackError가 Exception 하위 클래스다."""
    assert issubclass(RollbackError, Exception)


# === T14: --previous (lineage 기반) ===

def test_resolve_previous_with_lineage(tmp_path: Path) -> None:
    """lineage에 parent가 있으면 경로를 반환한다."""
    from engine.registry import SkillRegistry

    registry = SkillRegistry(":memory:")
    # parent adoption record 파일 생성
    parent = _write_adoption(tmp_path, "parent", run_id="run-parent")

    # lineage 기록
    registry.add_lineage(
        child_skill_name="summarize",
        child_run_id="run-current",
        parent_skill_name="summarize",
        parent_run_id="run-parent",
    )

    result = resolve_previous_adoption(
        "summarize", "run-current", registry._conn, str(tmp_path),
    )
    assert result is not None
    assert "parent" in result
    registry.close()


# === T15: --previous, lineage 없음 → None ===

def test_resolve_previous_no_lineage() -> None:
    """lineage에 parent가 없으면 None을 반환한다."""
    from engine.registry import SkillRegistry

    registry = SkillRegistry(":memory:")
    result = resolve_previous_adoption(
        "summarize", "run-001", registry._conn,
    )
    assert result is None
    registry.close()


# === T16: 연속 rollback (A→B→A) ===

def test_consecutive_rollback(tmp_path: Path) -> None:
    """연속 rollback이 정상 동작한다."""
    target_a = _write_adoption(tmp_path, "a", run_id="run-a")
    target_b = _write_adoption(tmp_path, "b", run_id="run-b")
    _write_latest(tmp_path, run_id="run-c")

    # C → A
    execute_rollback(
        str(target_a), str(tmp_path / "_latest.json"),
        adoptions_dir=str(tmp_path),
    )
    latest = json.loads((tmp_path / "_latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "run-a"

    # A → B
    execute_rollback(
        str(target_b), str(tmp_path / "_latest.json"),
        adoptions_dir=str(tmp_path),
    )
    latest = json.loads((tmp_path / "_latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "run-b"

    # B → A (다시)
    execute_rollback(
        str(target_a), str(tmp_path / "_latest.json"),
        adoptions_dir=str(tmp_path),
    )
    latest = json.loads((tmp_path / "_latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "run-a"


# === T17: human_reason 기록 ===

def test_human_reason_recorded(tmp_path: Path) -> None:
    """human_reason이 rollback record에 기록된다."""
    target = _write_adoption(tmp_path, "old", run_id="run-old")
    _write_latest(tmp_path, run_id="run-current")

    record = execute_rollback(
        target_path=str(target),
        current_latest_path=str(tmp_path / "_latest.json"),
        human_reason="eval set B에서 성능 저하",
        adoptions_dir=str(tmp_path),
    )

    assert record["human_reason"] == "eval set B에서 성능 저하"
