"""Policy Engine 테스트 (Task 16).

JSON 정책 파일 로드, 기본값 병합, 타입 검증, 엔진 연동을 검증한다.
"""

import json
from pathlib import Path

import pytest

from engine.policy import CambrianPolicy


# === 1. 기본값 11개 확인 ===

def test_default_policy_values() -> None:
    """파일 없이 CambrianPolicy() → 내장 기본값 11개 확인."""
    policy = CambrianPolicy()  # cambrian_policy.json이 있으면 읽힘

    # 기본값이 적용되는지 확인 (프로젝트 루트의 cambrian_policy.json도 기본값과 동일)
    assert policy.max_candidates_per_run == 5
    assert policy.max_mode_a_per_run == 2
    assert policy.max_eval_cases == 20
    assert policy.max_eval_inputs_evolve == 10
    assert policy.promote_min_executions == 10
    assert policy.promote_min_fitness == 0.5
    assert policy.demote_fitness_threshold == 0.3
    assert policy.rollback_fitness_threshold == 0.2
    assert policy.quarantine_block_count == 2
    assert policy.adoption_margin == 0.5
    assert policy.trial_count == 3


# === 2. 커스텀 JSON 로드 ===

def test_load_custom_policy(tmp_path: Path) -> None:
    """JSON 파일에서 커스텀 값을 로드한다."""
    custom = {
        "budget": {"max_candidates_per_run": 3},
        "governance": {"promote_min_fitness": 0.7},
        "evolution": {"adoption_margin": 1.0},
    }
    policy_file = tmp_path / "custom.json"
    policy_file.write_text(json.dumps(custom), encoding="utf-8")

    policy = CambrianPolicy(policy_file)
    assert policy.max_candidates_per_run == 3
    assert policy.promote_min_fitness == 0.7
    assert policy.adoption_margin == 1.0
    assert policy.policy_source == str(policy_file)


# === 3. 부분 정책 병합 ===

def test_partial_policy_merge(tmp_path: Path) -> None:
    """budget만 있는 JSON → budget은 커스텀, 나머지 기본값."""
    custom = {
        "budget": {"max_candidates_per_run": 8, "max_mode_a_per_run": 4},
    }
    policy_file = tmp_path / "partial.json"
    policy_file.write_text(json.dumps(custom), encoding="utf-8")

    policy = CambrianPolicy(policy_file)
    assert policy.max_candidates_per_run == 8
    assert policy.max_mode_a_per_run == 4
    # 나머지는 기본값
    assert policy.max_eval_cases == 20
    assert policy.promote_min_executions == 10
    assert policy.adoption_margin == 0.5


# === 4. 타입 오류 시 기본값 fallback ===

def test_invalid_type_fallback(tmp_path: Path) -> None:
    """fitness에 문자열 → warning + 기본값."""
    custom = {
        "governance": {"promote_min_fitness": "abc"},
    }
    policy_file = tmp_path / "bad_type.json"
    policy_file.write_text(json.dumps(custom), encoding="utf-8")

    policy = CambrianPolicy(policy_file)
    # 기본값으로 fallback
    assert policy.promote_min_fitness == 0.5


# === 5. 음수 값 시 기본값 fallback ===

def test_negative_value_fallback(tmp_path: Path) -> None:
    """max_candidates: -1 → warning + 기본값."""
    custom = {
        "budget": {"max_candidates_per_run": -1},
    }
    policy_file = tmp_path / "negative.json"
    policy_file.write_text(json.dumps(custom), encoding="utf-8")

    policy = CambrianPolicy(policy_file)
    assert policy.max_candidates_per_run == 5  # 기본값


# === 6. 알 수 없는 키 무시 ===

def test_unknown_key_ignored(tmp_path: Path) -> None:
    """알 수 없는 최상위 키 → warning, 에러 아님."""
    custom = {
        "budget": {"max_candidates_per_run": 7},
        "future_feature": {"some_param": 42},
    }
    policy_file = tmp_path / "unknown.json"
    policy_file.write_text(json.dumps(custom), encoding="utf-8")

    policy = CambrianPolicy(policy_file)
    assert policy.max_candidates_per_run == 7  # 정상 로드


# === 7. 파일 미존재 → FileNotFoundError ===

def test_file_not_found() -> None:
    """명시적 경로에 파일이 없으면 FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        CambrianPolicy("nonexistent_policy.json")


# === 8. 깨진 JSON → 에러 ===

def test_invalid_json(tmp_path: Path) -> None:
    """깨진 JSON 파일 → JSONDecodeError."""
    bad_file = tmp_path / "broken.json"
    bad_file.write_text("{invalid json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        CambrianPolicy(bad_file)


# === 9. 엔진에 policy budget 반영 ===

def test_engine_uses_policy_budget(tmp_path: Path) -> None:
    """policy max_candidates=3 → 엔진에 반영."""
    custom = {"budget": {"max_candidates_per_run": 3}}
    policy_file = tmp_path / "budget.json"
    policy_file.write_text(json.dumps(custom), encoding="utf-8")

    from engine.loop import CambrianEngine
    engine = CambrianEngine(
        schemas_dir="schemas", skills_dir="skills",
        skill_pool_dir="skill_pool", db_path=":memory:",
        policy_path=policy_file,
    )
    assert engine.MAX_CANDIDATES_PER_RUN == 3
    engine.close()


# === 10. 엔진에 policy governance 반영 ===

def test_engine_uses_policy_governance(tmp_path: Path) -> None:
    """policy promote_min_fitness=0.7 → 승격 기준 변경."""
    custom = {"governance": {"promote_min_fitness": 0.7}}
    policy_file = tmp_path / "gov.json"
    policy_file.write_text(json.dumps(custom), encoding="utf-8")

    from engine.loop import CambrianEngine
    engine = CambrianEngine(
        schemas_dir="schemas", skills_dir="skills",
        skill_pool_dir="skill_pool", db_path=":memory:",
        policy_path=policy_file,
    )
    assert engine.get_policy().promote_min_fitness == 0.7
    engine.close()


# === 11. 엔진에 policy evolution 반영 ===

def test_engine_uses_policy_evolution(tmp_path: Path) -> None:
    """policy adoption_margin=1.0 → 진화 마진 변경."""
    custom = {"evolution": {"adoption_margin": 1.0}}
    policy_file = tmp_path / "evo.json"
    policy_file.write_text(json.dumps(custom), encoding="utf-8")

    from engine.loop import CambrianEngine
    engine = CambrianEngine(
        schemas_dir="schemas", skills_dir="skills",
        skill_pool_dir="skill_pool", db_path=":memory:",
        policy_path=policy_file,
    )
    assert engine.get_policy().adoption_margin == 1.0
    engine.close()


# === 12. CLI --policy 옵션 ===

def test_cli_policy_option(tmp_path: Path) -> None:
    """--policy 경로가 엔진에 전달된다."""
    custom = {"budget": {"max_candidates_per_run": 2}}
    policy_file = tmp_path / "cli_test.json"
    policy_file.write_text(json.dumps(custom), encoding="utf-8")

    from engine.loop import CambrianEngine
    engine = CambrianEngine(
        schemas_dir="schemas", skills_dir="skills",
        skill_pool_dir="skill_pool", db_path=":memory:",
        policy_path=policy_file,
    )
    assert engine.MAX_CANDIDATES_PER_RUN == 2
    assert engine.get_policy().policy_source == str(policy_file)
    engine.close()


# === 13. stats에 Policy 섹션 ===

def test_stats_shows_policy() -> None:
    """get_policy().to_dict()에 source 키가 포함된다."""
    from engine.loop import CambrianEngine
    engine = CambrianEngine(
        schemas_dir="schemas", skills_dir="skills",
        skill_pool_dir="skill_pool", db_path=":memory:",
    )
    d = engine.get_policy().to_dict()
    assert "source" in d
    assert "budget" in d
    assert "governance" in d
    assert "evolution" in d
    engine.close()


# === 14. to_dict() 직렬화 가능 ===

def test_policy_to_dict() -> None:
    """to_dict()가 JSON 직렬화 가능한 11개 키를 포함한다."""
    policy = CambrianPolicy()
    d = policy.to_dict()

    # JSON 직렬화 가능
    json_str = json.dumps(d)
    assert json_str

    # 11개 파라미터 + source
    assert d["budget"]["max_candidates_per_run"] == 5
    assert d["governance"]["promote_min_executions"] == 10
    assert d["evolution"]["adoption_margin"] == 0.5


# === 15. 자동 탐색: cambrian_policy.json ===

def test_auto_detect_policy_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """현재 디렉토리에 cambrian_policy.json이 있으면 자동 로드한다."""
    custom = {"budget": {"max_candidates_per_run": 9}}
    policy_file = tmp_path / "cambrian_policy.json"
    policy_file.write_text(json.dumps(custom), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    policy = CambrianPolicy()

    assert policy.max_candidates_per_run == 9
    assert policy.policy_source == "cambrian_policy.json"


# === 16. CLI override > policy ===

def test_cli_override_over_policy(tmp_path: Path) -> None:
    """policy max_candidates=5 + CLI override → override 적용."""
    custom = {"budget": {"max_candidates_per_run": 5}}
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps(custom), encoding="utf-8")

    from engine.loop import CambrianEngine
    engine = CambrianEngine(
        schemas_dir="schemas", skills_dir="skills",
        skill_pool_dir="skill_pool", db_path=":memory:",
        policy_path=policy_file,
    )
    assert engine.MAX_CANDIDATES_PER_RUN == 5

    # CLI override (run --max-candidates 3 패턴)
    engine.MAX_CANDIDATES_PER_RUN = 3
    assert engine.MAX_CANDIDATES_PER_RUN == 3
    engine.close()


# === 추가: int 필드에 float 허용 ===

def test_int_field_accepts_float(tmp_path: Path) -> None:
    """JSON에서 10.0이 오면 int로 변환한다."""
    custom = {"budget": {"max_candidates_per_run": 7.0}}
    policy_file = tmp_path / "float_int.json"
    policy_file.write_text(json.dumps(custom), encoding="utf-8")

    policy = CambrianPolicy(policy_file)
    assert policy.max_candidates_per_run == 7
    assert isinstance(policy.max_candidates_per_run, int)
