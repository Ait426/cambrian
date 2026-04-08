"""loop input contract gate 테스트."""
from pathlib import Path
from unittest.mock import patch
import yaml
from engine.loop import CambrianEngine


def _write_skill(base: Path, skill_id: str, required_field: str) -> Path:
    """input에 required_field를 요구하는 테스트 스킬을 생성한다."""
    d = base / skill_id
    (d / "execute").mkdir(parents=True)
    (d / "meta.yaml").write_text(yaml.dump({
        "id": skill_id, "version": "1.0.0", "name": "T", "description": "t",
        "domain": "testing", "tags": ["test"], "mode": "b",
        "created_at": "2026-04-08", "updated_at": "2026-04-08",
        "runtime": {"language": "python", "needs_network": False,
                    "needs_filesystem": False, "timeout_seconds": 10},
        "lifecycle": {"status": "active", "fitness_score": 0.0,
                      "total_executions": 0, "successful_executions": 0,
                      "last_used": None, "crystallized_at": None},
    }), encoding="utf-8")
    (d / "interface.yaml").write_text(yaml.dump({
        "input": {
            "type": "object",
            "properties": {required_field: {"type": "string", "description": "d"}},
            "required": [required_field],
        },
        "output": {"type": "object", "properties": {
            "result": {"type": "string", "description": "r"},
        }, "required": []},
    }), encoding="utf-8")
    (d / "SKILL.md").write_text("# T\n", encoding="utf-8")
    (d / "execute" / "main.py").write_text(
        'import json,sys\ndef run(input_data: dict) -> dict:\n    return {"result":"ok"}\nif __name__ == "__main__":\n    d=json.load(sys.stdin)\n    print(json.dumps(run(d)))',
        encoding="utf-8",
    )
    return d


def test_loop_validates_input_before_execution(tmp_path: Path, schemas_dir: Path) -> None:
    """입력 스키마 불일치 시 executor.execute()가 호출되지 않는다."""
    skill_dir = _write_skill(tmp_path, "contract_skill", "required_field")

    with CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=skill_dir.parent,
        skill_pool_dir=tmp_path / "pool",
        db_path=":memory:",
    ) as engine:
        with patch.object(engine._executor, "execute", wraps=engine._executor.execute) as mock_exec:
            result = engine.run_task("testing", ["test"], {}, max_retries=0)
            assert result.success is False
            mock_exec.assert_not_called()


def test_loop_proceeds_when_input_valid(tmp_path: Path, schemas_dir: Path) -> None:
    """정상 입력이면 executor.execute()가 호출된다."""
    skill_dir = _write_skill(tmp_path, "contract_skill", "required_field")

    with CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=skill_dir.parent,
        skill_pool_dir=tmp_path / "pool",
        db_path=":memory:",
    ) as engine:
        with patch.object(engine._executor, "execute", wraps=engine._executor.execute) as mock_exec:
            engine.run_task("testing", ["test"], {"required_field": "hello"}, max_retries=0)
            mock_exec.assert_called_once()
