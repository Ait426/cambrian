"""Cambrian E2E 통합 테스트.

핵심 시나리오: "스킬이 없는 태스크 → 외부에서 흡수 → 재시도 성공"
이것이 Cambrian의 존재 이유를 증명하는 테스트다.
"""

from pathlib import Path

import yaml
from conftest import create_valid_skill

from engine.loop import CambrianEngine


def create_external_skill(base_dir: Path) -> Path:
    """E2E 테스트용 외부 스킬을 생성한다.

    Args:
        base_dir: 외부 스킬을 생성할 상위 경로

    Returns:
        생성된 외부 스킬 디렉토리 경로
    """
    skill_dir = create_valid_skill(base_dir, "uppercase_skill")

    meta_path = skill_dir / "meta.yaml"
    with open(meta_path, "r", encoding="utf-8") as file:
        meta = yaml.safe_load(file)
    meta["id"] = "uppercase_skill"
    meta["domain"] = "data"
    meta["tags"] = ["uppercase", "transform"]
    with open(meta_path, "w", encoding="utf-8") as file:
        yaml.dump(meta, file)

    main_py = """
import json
import sys

def run(input_data: dict) -> dict:
    value = input_data.get("value", "")
    return {"result": value.upper()}

if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    print(json.dumps(run(input_data)))
"""
    (skill_dir / "execute" / "main.py").write_text(main_py, encoding="utf-8")
    return skill_dir


def create_malicious_external_skill(base_dir: Path) -> Path:
    """E2E 테스트용 악성 외부 스킬을 생성한다.

    Args:
        base_dir: 외부 스킬을 생성할 상위 경로

    Returns:
        생성된 외부 스킬 디렉토리 경로
    """
    skill_dir = create_valid_skill(base_dir, "malicious_process_skill")

    meta_path = skill_dir / "meta.yaml"
    with open(meta_path, "r", encoding="utf-8") as file:
        meta = yaml.safe_load(file)
    meta["id"] = "malicious_process_skill"
    meta["domain"] = "data"
    meta["tags"] = ["process", "unsafe"]
    with open(meta_path, "w", encoding="utf-8") as file:
        yaml.dump(meta, file)

    main_py = """
import json
import sys

def run(input_data: dict) -> dict:
    expr = input_data.get("value", "1+1")
    return {"result": str(eval(expr))}

if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    print(json.dumps(run(input_data)))
"""
    (skill_dir / "execute" / "main.py").write_text(main_py, encoding="utf-8")
    return skill_dir


def test_evolve_absorb_and_succeed(schemas_dir: Path, tmp_path: Path) -> None:
    """Registry에 없는 스킬이 필요한 태스크 → 외부 디렉토리에서 흡수 → 재시도 → 성공."""
    pool_dir = tmp_path / "pool"
    external_dir = tmp_path / "external"
    external_dir.mkdir(parents=True, exist_ok=True)
    create_external_skill(external_dir)

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir="skills",
        skill_pool_dir=pool_dir,
        external_skill_dirs=[external_dir],
    )
    initial_count = engine.get_skill_count()

    result = engine.run_task(
        domain="data",
        tags=["uppercase"],
        input_data={"value": "hello cambrian"},
    )

    assert result.success is True
    assert result.output is not None
    assert result.output["result"] == "HELLO CAMBRIAN"
    assert engine.get_skill_count() > initial_count
    assert (pool_dir / "uppercase_skill").exists()


def test_evolve_reject_malicious(schemas_dir: Path, tmp_path: Path) -> None:
    """외부에 매칭되는 스킬이 있지만 보안 위반이면 흡수 거부."""
    pool_dir = tmp_path / "pool"
    external_dir = tmp_path / "external"
    external_dir.mkdir(parents=True, exist_ok=True)
    create_malicious_external_skill(external_dir)

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir="skills",
        skill_pool_dir=pool_dir,
        external_skill_dirs=[external_dir],
    )

    result = engine.run_task(
        domain="data",
        tags=["process"],
        input_data={"value": "2+2"},
    )

    assert result.success is False


def test_direct_success_no_evolution(schemas_dir: Path, tmp_path: Path) -> None:
    """Registry에 이미 매칭 스킬이 있으면 흡수 없이 즉시 성공."""
    pool_dir = tmp_path / "pool"

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir="skills",
        skill_pool_dir=pool_dir,
        external_skill_dirs=[],
    )

    result = engine.run_task(
        domain="utility",
        tags=["greeting"],
        input_data={"text": "direct"},
    )

    assert result.success is True
    assert result.output is not None
    assert result.output["greeting"] == "Hello, direct!"


def test_fitness_accumulates(schemas_dir: Path, tmp_path: Path) -> None:
    """같은 스킬을 5회 성공 실행하면 fitness가 0보다 커진다."""
    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir="skills",
        skill_pool_dir=tmp_path / "pool",
    )

    for _ in range(5):
        engine.run_task(
            domain="utility",
            tags=["greeting"],
            input_data={"text": "test"},
        )

    skill = engine.get_registry().get("hello_world")

    assert skill["total_executions"] == 5
    assert skill["successful_executions"] == 5
    assert skill["fitness_score"] > 0
