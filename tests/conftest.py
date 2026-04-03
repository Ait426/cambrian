from pathlib import Path

import pytest
import yaml


@pytest.fixture
def schemas_dir():
    """프로젝트 루트의 schemas/ 디렉토리 경로."""
    return Path(__file__).parent.parent / "schemas"


def create_valid_skill(base_dir: Path, skill_id: str = "test_skill") -> Path:
    """테스트용 정상 스킬 디렉토리를 생성한다.

    Args:
        base_dir: 스킬 디렉토리를 생성할 상위 경로
        skill_id: 스킬 ID (기본값: "test_skill")

    Returns:
        생성된 스킬 디렉토리 경로
    """
    skill_dir = base_dir / skill_id
    skill_dir.mkdir(parents=True)
    (skill_dir / "execute").mkdir()

    meta = {
        "id": skill_id,
        "version": "1.0.0",
        "name": "Test Skill",
        "description": "A test skill for unit testing",
        "domain": "testing",
        "tags": ["test"],
        "created_at": "2026-03-31",
        "updated_at": "2026-03-31",
        "mode": "b",
        "runtime": {
            "language": "python",
            "needs_network": False,
            "needs_filesystem": False,
            "timeout_seconds": 10,
        },
        "lifecycle": {
            "status": "active",
            "fitness_score": 0.0,
            "total_executions": 0,
            "successful_executions": 0,
            "last_used": None,
            "crystallized_at": None,
        },
    }
    with open(skill_dir / "meta.yaml", "w", encoding="utf-8") as f:
        yaml.dump(meta, f)

    interface = {
        "input": {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "description": "Test input value",
                }
            },
            "required": ["value"],
        },
        "output": {
            "type": "object",
            "properties": {
                "result": {
                    "type": "string",
                    "description": "Test output result",
                }
            },
            "required": ["result"],
        },
    }
    with open(skill_dir / "interface.yaml", "w", encoding="utf-8") as f:
        yaml.dump(interface, f)

    (skill_dir / "SKILL.md").write_text("# Test Skill\nA test skill.", encoding="utf-8")

    main_py = '''
import json
import sys

def run(input_data: dict) -> dict:
    return {"result": f"processed: {input_data.get('value', '')}"}

if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    print(json.dumps(run(input_data)))
'''
    (skill_dir / "execute" / "main.py").write_text(main_py, encoding="utf-8")

    return skill_dir
