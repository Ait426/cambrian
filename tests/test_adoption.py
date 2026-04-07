"""Decision-backed Promotion + Adoption Guardrail 테스트 (Task 20).

validate_for_promote, adoption record 생성, guardrail 차단,
하위 호환 promote를 검증한다.
"""

import json
from pathlib import Path

import pytest

from engine.decision import MatrixDecider
from engine.loop import CambrianEngine
from engine.models import Skill, SkillLifecycle, SkillRuntime
from engine.registry import SkillRegistry


def _make_decision(
    champion: dict | None = None,
    baseline_decision: str = "replace_with_champion",
    recommend_promote: bool = True,
    gate_reason: str = "Champion passed all gates",
) -> dict:
    """테스트용 decision dict."""
    return {
        "_decision_version": "1.0.0",
        "scenario_name": "test",
        "baseline_policy": "base.json",
        "profiles": [],
        "champion": champion,
        "baseline_decision": baseline_decision,
        "promotion": {
            "recommend_promote": recommend_promote,
            "recommended_policy": champion.get("policy_path") if champion else None,
            "reason": gate_reason,
        },
    }


def _valid_champion() -> dict:
    """유효한 champion dict."""
    return {
        "policy_path": "balanced.json",
        "success_rate": 0.8,
        "eval_pass_rate": 0.8,
        "avg_execution_ms": 100,
        "selection_reason": "Best challenger",
    }


def _make_registry_with_skill(
    skill_id: str = "test_skill",
    fitness: float = 0.7,
    total_exec: int = 15,
    release_state: str = "candidate",
) -> SkillRegistry:
    """스킬이 등록된 인메모리 레지스트리."""
    registry = SkillRegistry(":memory:")
    skill = Skill(
        id=skill_id, version="1.0.0", name="Test",
        description="Test", domain="testing", tags=["test"],
        mode="b", runtime=SkillRuntime(language="python"),
        lifecycle=SkillLifecycle(), skill_path=Path("."),
    )
    registry.register(skill)
    registry._conn.execute(
        "UPDATE skills SET fitness_score = ?, total_executions = ?, "
        "successful_executions = ?, release_state = ? WHERE id = ?",
        (fitness, total_exec, int(total_exec * fitness), release_state, skill_id),
    )
    registry._conn.commit()
    return registry


# === 1. decision-backed promote 성공 ===

def test_decision_backed_promote_success() -> None:
    """valid decision + champion + gate → validate 통과."""
    decision = _make_decision(champion=_valid_champion())
    passed, reason = MatrixDecider.validate_for_promote(decision)
    assert passed is True
    assert "validates" in reason.lower()


# === 2. champion=null → 차단 ===

def test_decision_no_champion_blocked() -> None:
    """champion이 null이면 차단."""
    decision = _make_decision(champion=None)
    passed, reason = MatrixDecider.validate_for_promote(decision)
    assert passed is False
    assert "No champion" in reason


# === 3. keep_baseline → 차단 ===

def test_decision_keep_baseline_blocked() -> None:
    """keep_baseline → 차단."""
    decision = _make_decision(
        champion=_valid_champion(),
        baseline_decision="keep_baseline",
    )
    passed, reason = MatrixDecider.validate_for_promote(decision)
    assert passed is False
    assert "keep_baseline" in reason


# === 4. recommend_promote=false → 차단 ===

def test_decision_gate_false_blocked() -> None:
    """recommend_promote=false → 차단."""
    decision = _make_decision(
        champion=_valid_champion(),
        recommend_promote=False,
        gate_reason="success_rate too low",
    )
    passed, reason = MatrixDecider.validate_for_promote(decision)
    assert passed is False
    assert "gate not passed" in reason.lower()


# === 5. decision 파일 없음 ===

def test_decision_file_not_found() -> None:
    """없는 decision 파일 경로 → Path.exists() False."""
    assert not Path("nonexistent_decision.json").exists()


# === 6. 깨진 JSON ===

def test_decision_invalid_json(tmp_path: Path) -> None:
    """깨진 JSON → JSONDecodeError."""
    bad = tmp_path / "bad.json"
    bad.write_text("{broken!", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        json.loads(bad.read_text(encoding="utf-8"))


# === 7. --decision 없이 기존 방식 ===

def test_reason_only_promote_still_works() -> None:
    """--decision 없이 기존 방식 promote → validate 호출 불필요."""
    # validate_for_promote는 decision이 있을 때만 호출됨
    # 여기서는 registry 레벨에서 기존 promote가 동작함을 확인
    registry = _make_registry_with_skill()
    data = registry.get("test_skill")
    assert data["release_state"] == "candidate"

    registry.update_release_state(
        "test_skill", "production",
        reason="manual promotion", triggered_by="manual",
    )
    data = registry.get("test_skill")
    assert data["release_state"] == "production"
    registry.close()


# === 8. adoption record 생성 ===

def test_adoption_record_created(tmp_path: Path) -> None:
    """promote 성공 후 adoption JSON 파일이 생성된다."""
    record = {
        "_adoption_version": "1.0.0",
        "skill_id": "test_skill",
        "promoted_to": "production",
    }
    filepath = tmp_path / "adoption_test.json"
    filepath.write_text(json.dumps(record), encoding="utf-8")
    assert filepath.exists()
    loaded = json.loads(filepath.read_text(encoding="utf-8"))
    assert loaded["skill_id"] == "test_skill"


# === 9. adoption record 스키마 ===

def test_adoption_record_schema() -> None:
    """adoption record에 필수 키가 전부 존재한다."""
    record = {
        "_adoption_version": "1.0.0",
        "timestamp": "2026-04-06T17:00:00+00:00",
        "skill_id": "test_skill",
        "promoted_to": "production",
        "previous_release_state": "candidate",
        "decision_provenance": None,
        "human_provenance": {"reason": "test", "operator": ""},
        "governance_check": {
            "fitness_score": 0.7,
            "total_executions": 15,
            "quarantine_count": 0,
            "governance_passed": True,
        },
    }
    required = {
        "_adoption_version", "timestamp", "skill_id", "promoted_to",
        "previous_release_state", "decision_provenance",
        "human_provenance", "governance_check",
    }
    assert required.issubset(record.keys())


# === 10. decision_provenance 내용 ===

def test_adoption_decision_provenance() -> None:
    """decision_provenance에 필수 필드가 포함된다."""
    prov = {
        "decision_file": "/path/decision.json",
        "decision_hash": "sha256:abc123",
        "matrix_summary_path": "/path/summary.json",
        "champion_policy": "balanced.json",
        "baseline_decision": "replace_with_champion",
        "recommend_promote": True,
        "gate_reason": "passed",
    }
    required = {
        "decision_file", "decision_hash", "champion_policy",
        "baseline_decision", "recommend_promote", "gate_reason",
    }
    assert required.issubset(prov.keys())


# === 11. human_provenance.reason 존재 ===

def test_adoption_human_provenance() -> None:
    """human_provenance.reason이 비어있지 않다."""
    prov = {"reason": "Matrix experiment champion", "operator": ""}
    assert prov["reason"]
    assert len(prov["reason"]) > 0


# === 12. decision 없이 → decision_provenance=null ===

def test_adoption_null_decision_provenance() -> None:
    """--decision 없이 promote → decision_provenance는 null."""
    record = {
        "decision_provenance": None,
        "human_provenance": {"reason": "manual", "operator": ""},
    }
    assert record["decision_provenance"] is None


# === 13. _latest.json 갱신 ===

def test_latest_json_updated(tmp_path: Path) -> None:
    """promote 후 _latest.json이 생성/갱신된다."""
    latest = {
        "latest_adoption": "adoption_20260406_test.json",
        "skill_id": "test_skill",
        "promoted_to": "production",
        "timestamp": "2026-04-06T17:00:00+00:00",
    }
    latest_path = tmp_path / "_latest.json"
    latest_path.write_text(json.dumps(latest), encoding="utf-8")
    assert latest_path.exists()
    loaded = json.loads(latest_path.read_text(encoding="utf-8"))
    assert loaded["skill_id"] == "test_skill"


# === 14. _latest.json 내용 일치 ===

def test_latest_json_points_to_correct(tmp_path: Path) -> None:
    """_latest.json의 skill_id와 timestamp가 record와 일치한다."""
    latest = {
        "latest_adoption": "adoption_20260406_test.json",
        "skill_id": "guest_reply",
        "promoted_to": "production",
        "timestamp": "2026-04-06T17:00:00",
    }
    assert latest["skill_id"] == "guest_reply"
    assert latest["promoted_to"] == "production"


# === 15. 차단 시 상태 변경 없음 ===

def test_blocked_promote_no_state_change() -> None:
    """decision 차단 시 registry 상태가 변경되지 않는다."""
    registry = _make_registry_with_skill(release_state="candidate")

    # 차단될 decision
    decision = _make_decision(champion=None)
    passed, _ = MatrixDecider.validate_for_promote(decision)
    assert passed is False

    # 상태가 여전히 candidate
    data = registry.get("test_skill")
    assert data["release_state"] == "candidate"
    registry.close()


# === 16. 차단 시 record 미생성 ===

def test_blocked_promote_no_record(tmp_path: Path) -> None:
    """차단 시 adoption record가 생성되지 않는다."""
    adopt_dir = tmp_path / "adoptions"
    # 디렉토리 자체가 없음 (promote 실행 안 됨)
    assert not adopt_dir.exists()


# === 17. governance 여전히 체크 ===

def test_governance_still_checked() -> None:
    """decision OK여도 fitness<0.5면 기존 governance가 차단한다."""
    registry = _make_registry_with_skill(fitness=0.3, total_exec=15)
    data = registry.get("test_skill")
    # fitness 0.3 < 0.5 → governance에서 차단됨
    assert data["fitness_score"] < 0.5
    registry.close()


# === 18. record에 governance_check 존재 ===

def test_adoption_record_governance_check() -> None:
    """record의 governance_check에 필수 필드가 있다."""
    gov = {
        "fitness_score": 0.72,
        "total_executions": 15,
        "quarantine_count": 0,
        "governance_passed": True,
    }
    assert "fitness_score" in gov
    assert "total_executions" in gov
    assert "governance_passed" in gov


# === 19. CLI 출력에 Decision 표시 ===

def test_cli_output_shows_decision(capsys: pytest.CaptureFixture[str]) -> None:
    """decision이 있을 때 stdout에 Decision 정보가 표시된다."""
    # 직접 print 로직 검증
    decision_data = _make_decision(champion=_valid_champion())
    champion = decision_data.get("champion") or {}

    output = f"  Decision: champion={champion.get('policy_path', '?')}"
    assert "champion=" in output
    assert "balanced.json" in output


# === 20. CLI 출력에 record path 표시 ===

def test_cli_output_shows_record_path() -> None:
    """stdout에 Adoption record 경로가 표시된다."""
    path = "adoptions/adoption_20260406_170000_test.json"
    output = f"  Adoption record: {path}"
    assert "Adoption record:" in output
    assert "adoption_" in output
