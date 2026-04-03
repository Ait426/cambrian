"""Benchmark 테스트."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from engine.loop import CambrianEngine


def _create_skill(
    root_dir: Path,
    skill_id: str,
    *,
    domain: str = "utility",
    tags: list[str] | None = None,
    status: str = "active",
    fitness_score: float = 0.0,
    execute_body: str | None = None,
) -> Path:
    """테스트용 mode-b 스킬 디렉토리를 생성한다.

    Args:
        root_dir: 스킬 디렉토리를 생성할 상위 경로
        skill_id: 스킬 ID
        domain: 스킬 도메인
        tags: 스킬 태그
        status: lifecycle 상태
        fitness_score: lifecycle 피트니스 점수
        execute_body: execute/main.py 소스 오버라이드

    Returns:
        생성된 스킬 디렉토리 경로
    """
    skill_dir = root_dir / skill_id
    (skill_dir / "execute").mkdir(parents=True, exist_ok=True)

    meta = {
        "id": skill_id,
        "version": "1.0.0",
        "name": skill_id.replace("_", " ").title(),
        "description": f"Benchmark test skill {skill_id}",
        "domain": domain,
        "tags": list(tags or ["test"]),
        "created_at": "2026-04-02",
        "updated_at": "2026-04-02",
        "mode": "b",
        "runtime": {
            "language": "python",
            "needs_network": False,
            "needs_filesystem": False,
            "timeout_seconds": 10,
        },
        "lifecycle": {
            "status": status,
            "fitness_score": fitness_score,
            "total_executions": 0,
            "successful_executions": 0,
            "last_used": None,
            "crystallized_at": None,
        },
    }

    interface = {
        "input": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "입력 텍스트"},
            },
            "required": ["text"],
        },
        "output": {
            "type": "object",
            "properties": {
                "greeting": {"type": "string", "description": "결과 텍스트"},
            },
            "required": ["greeting"],
        },
    }

    (skill_dir / "meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (skill_dir / "interface.yaml").write_text(
        yaml.safe_dump(interface, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(f"# {skill_id}\n", encoding="utf-8")

    # subprocess 실행 방식이므로 stdin/stdout 핸들러 포함
    default_body = (
        "from __future__ import annotations\n"
        "import json\n"
        "import sys\n\n"
        "def run(input_data: dict) -> dict:\n"
        "    _ = input_data\n"
        f"    return {{'greeting': '{skill_id}'}}\n\n"
        "if __name__ == '__main__':\n"
        "    _raw = sys.stdin.read()\n"
        "    _data = json.loads(_raw) if _raw.strip() else {}\n"
        "    print(json.dumps(run(_data)))\n"
    )
    (skill_dir / "execute" / "main.py").write_text(
        execute_body or default_body,
        encoding="utf-8",
    )
    return skill_dir


def _make_project_root(tmp_path: Path) -> Path:
    """테스트용 프로젝트 루트를 생성한다."""
    project_root = tmp_path / "project"
    (project_root / "skills").mkdir(parents=True, exist_ok=True)
    (project_root / "skill_pool").mkdir(parents=True, exist_ok=True)
    return project_root


def _make_engine(project_root: Path, schemas_dir: Path) -> CambrianEngine:
    """테스트용 CambrianEngine을 생성한다."""
    return CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=project_root / "skills",
        skill_pool_dir=project_root / "skill_pool",
    )


def test_benchmark_empty_candidates(tmp_path: Path, schemas_dir: Path) -> None:
    """매칭 스킬 없으면 빈 보고서를 반환한다."""
    project_root = _make_project_root(tmp_path)
    engine = _make_engine(project_root, schemas_dir)

    report = engine.benchmark(domain="nonexistent", tags=["missing"], input_data={"text": "hi"})

    assert report.entries == []
    assert report.best_skill_id is None


def test_benchmark_single_skill(tmp_path: Path, schemas_dir: Path) -> None:
    """단일 매칭 스킬을 최선으로 반환한다."""
    project_root = _make_project_root(tmp_path)
    _create_skill(
        project_root / "skills",
        "hello_world",
        domain="utility",
        tags=["test", "greeting"],
        fitness_score=0.3,
    )
    engine = _make_engine(project_root, schemas_dir)

    report = engine.benchmark(domain="utility", tags=["test", "greeting"], input_data={"text": "hi"})

    assert len(report.entries) == 1
    assert report.best_skill_id == "hello_world"


def test_benchmark_ranking_success_first(tmp_path: Path, schemas_dir: Path) -> None:
    """성공 스킬이 실패 스킬보다 앞에 순위된다."""
    project_root = _make_project_root(tmp_path)
    _create_skill(
        project_root / "skills",
        "csv_to_chart",
        domain="chart",
        tags=["csv"],
        fitness_score=0.3,
    )
    _create_skill(
        project_root / "skills",
        "broken_chart",
        domain="chart",
        tags=["csv"],
        fitness_score=0.9,
        execute_body=(
            "from __future__ import annotations\n\n"
            "def run(input_data: dict) -> dict:\n"
            "    _ = input_data\n"
            "    raise ValueError('broken')\n"
        ),
    )
    engine = _make_engine(project_root, schemas_dir)

    report = engine.benchmark(domain="chart", tags=["csv"], input_data={"text": "hi"})

    assert report.entries[0].success is True


def test_benchmark_ranking_by_fitness(tmp_path: Path, schemas_dir: Path) -> None:
    """성공 스킬 중 피트니스 높은 것이 먼저 순위된다."""
    project_root = _make_project_root(tmp_path)
    _create_skill(
        project_root / "skills",
        "low_fit",
        domain="utility",
        tags=["test"],
        fitness_score=0.1,
    )
    _create_skill(
        project_root / "skills",
        "high_fit",
        domain="utility",
        tags=["test"],
        fitness_score=0.9,
    )
    engine = _make_engine(project_root, schemas_dir)

    report = engine.benchmark(domain="utility", tags=["test"], input_data={"text": "hi"})

    assert report.entries[0].skill_id == "high_fit"


def test_benchmark_ranking_by_time(tmp_path: Path, schemas_dir: Path) -> None:
    """피트니스가 같으면 빠른 스킬이 먼저 순위된다."""
    project_root = _make_project_root(tmp_path)
    _create_skill(
        project_root / "skills",
        "hello_world",
        domain="utility",
        tags=["test"],
        fitness_score=0.5,
    )
    _create_skill(
        project_root / "skills",
        "slow_skill",
        domain="utility",
        tags=["test"],
        fitness_score=0.5,
        execute_body=(
            "from __future__ import annotations\n\n"
            "import time\n\n"
            "def run(input_data: dict) -> dict:\n"
            "    _ = input_data\n"
            "    time.sleep(0.02)\n"
            "    return {'greeting': 'slow'}\n"
        ),
    )
    engine = _make_engine(project_root, schemas_dir)

    report = engine.benchmark(domain="utility", tags=["test"], input_data={"text": "hi"})

    assert report.entries[0].skill_id == "hello_world"
    assert report.entries[1].skill_id == "slow_skill"


def test_benchmark_report_fields(tmp_path: Path, schemas_dir: Path) -> None:
    """벤치마크 요약 필드가 정확히 채워진다."""
    project_root = _make_project_root(tmp_path)
    _create_skill(
        project_root / "skills",
        "hello_world",
        domain="utility",
        tags=["test"],
        status="active",
        fitness_score=0.3,
    )
    _create_skill(
        project_root / "skill_pool",
        "newborn_skill",
        domain="utility",
        tags=["test"],
        status="newborn",
        fitness_score=0.1,
    )
    engine = _make_engine(project_root, schemas_dir)

    report = engine.benchmark(domain="utility", tags=["test"], input_data={"text": "hi"})

    assert report.total_candidates == 2
    assert report.successful_count == 2
    assert report.domain == "utility"
    assert report.tags == ["test"]
    assert datetime.fromisoformat(report.timestamp)


def test_benchmark_updates_registry(tmp_path: Path, schemas_dir: Path) -> None:
    """벤치마크 후 실행 카운터가 레지스트리에 갱신된다."""
    project_root = _make_project_root(tmp_path)
    _create_skill(
        project_root / "skills",
        "hello_world",
        domain="utility",
        tags=["test"],
        fitness_score=0.3,
    )
    engine = _make_engine(project_root, schemas_dir)

    report = engine.benchmark(domain="utility", tags=["test"], input_data={"text": "hi"})
    assert len(report.entries) == 1

    skill_info = engine.get_registry().get("hello_world")
    assert skill_info["total_executions"] == 1


def test_benchmark_entry_rank_assigned(tmp_path: Path, schemas_dir: Path) -> None:
    """1부터 순차적인 rank 값이 할당된다."""
    project_root = _make_project_root(tmp_path)
    _create_skill(
        project_root / "skills",
        "a_skill",
        domain="utility",
        tags=["test"],
        fitness_score=0.3,
    )
    _create_skill(
        project_root / "skills",
        "b_skill",
        domain="utility",
        tags=["test"],
        fitness_score=0.9,
    )
    _create_skill(
        project_root / "skills",
        "c_skill",
        domain="utility",
        tags=["test"],
        fitness_score=0.1,
        execute_body=(
            "from __future__ import annotations\n\n"
            "def run(input_data: dict) -> dict:\n"
            "    _ = input_data\n"
            "    raise RuntimeError('fail')\n"
        ),
    )
    engine = _make_engine(project_root, schemas_dir)

    report = engine.benchmark(domain="utility", tags=["test"], input_data={"text": "hi"})

    assert [entry.rank for entry in report.entries] == [1, 2, 3]
