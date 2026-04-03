"""Cambrian CLI 진화 명령어 테스트."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from engine.cli import main
from engine.models import EvolutionRecord


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """CLI를 subprocess로 실행한다."""
    cmd = [sys.executable, "-m", "engine.cli", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(cwd or Path(__file__).parent.parent),
        timeout=30,
    )


def _prepare_history_db(
    db_path: Path,
    *,
    with_record: bool = True,
    judge_reasoning: str = "test reasoning here",
    parent_skill_md: str = "# Original\nLine 1",
    child_skill_md: str = "# Evolved\nLine 1\nLine 2",
    record_id: int = 1,
) -> None:
    """history CLI 테스트용 SQLite DB를 준비한다."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS skills (
            id TEXT PRIMARY KEY,
            version TEXT,
            name TEXT,
            description TEXT,
            domain TEXT,
            tags TEXT,
            mode TEXT,
            language TEXT,
            needs_network INTEGER DEFAULT 0,
            needs_filesystem INTEGER DEFAULT 0,
            timeout_seconds INTEGER DEFAULT 30,
            skill_path TEXT,
            status TEXT DEFAULT 'newborn',
            fitness_score REAL DEFAULT 0.0,
            total_executions INTEGER DEFAULT 0,
            successful_executions INTEGER DEFAULT 0,
            last_used TEXT,
            crystallized_at TEXT,
            avg_judge_score REAL,
            registered_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id TEXT,
            rating INTEGER,
            comment TEXT DEFAULT '',
            input_data TEXT DEFAULT '{}',
            output_data TEXT DEFAULT '{}',
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS evolution_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id TEXT,
            parent_skill_md TEXT,
            child_skill_md TEXT,
            parent_fitness REAL DEFAULT 0.0,
            child_fitness REAL DEFAULT 0.0,
            adopted INTEGER DEFAULT 0,
            mutation_summary TEXT DEFAULT '',
            feedback_ids TEXT DEFAULT '[]',
            judge_reasoning TEXT DEFAULT '',
            created_at TEXT
        )
        """
    )

    conn.execute(
        """
        INSERT INTO skills (
            id, version, name, description, domain, tags, mode, language,
            needs_network, needs_filesystem, timeout_seconds, skill_path,
            status, fitness_score, total_executions, successful_executions,
            last_used, crystallized_at, avg_judge_score, registered_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test_skill",
            "1.0.0",
            "Test Skill",
            "desc",
            "testing",
            '["test"]',
            "a",
            "python",
            0,
            0,
            30,
            "/tmp/test_skill",
            "active",
            0.5,
            0,
            0,
            None,
            None,
            None,
            "2026-04-03T00:00:00+00:00",
        ),
    )

    if with_record:
        conn.execute(
            """
            INSERT INTO evolution_history (
                id, skill_id, parent_skill_md, child_skill_md,
                parent_fitness, child_fitness, adopted, mutation_summary,
                feedback_ids, judge_reasoning, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                "test_skill",
                parent_skill_md,
                child_skill_md,
                0.4,
                0.8,
                1,
                "summary",
                "[]",
                judge_reasoning,
                "2026-04-03T12:00:00+00:00",
            ),
        )

    conn.commit()
    conn.close()


@pytest.fixture
def cli_engine(schemas_dir: Path, tmp_path: Path):
    """CLI 테스트용 임시 스킬 디렉토리를 준비한다."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    db_path = tmp_path / "registry.db"
    skill_dir = skills_dir / "cli_test"
    skill_dir.mkdir(parents=True)

    meta = {
        "id": "cli_test",
        "version": "1.0.0",
        "name": "CLI Test",
        "description": "CLI evolution test skill",
        "domain": "testing",
        "tags": ["test", "cli"],
        "created_at": "2026-04-02",
        "updated_at": "2026-04-02",
        "mode": "a",
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
    interface = {
        "input": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "query"}},
            "required": ["query"],
        },
        "output": {
            "type": "object",
            "properties": {"html": {"type": "string", "description": "html"}},
            "required": ["html"],
        },
    }

    with open(skill_dir / "meta.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
    with open(skill_dir / "interface.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(interface, f, allow_unicode=True, sort_keys=False)
    (skill_dir / "SKILL.md").write_text(
        '# Test\nRespond with JSON: {"html": "<p>answer</p>"}',
        encoding="utf-8",
    )

    return {
        "schemas_dir": str(schemas_dir),
        "skills_dir": str(skills_dir),
        "pool_dir": str(pool_dir),
        "db_path": str(db_path),
    }


def _base_args(cli_engine: dict) -> list[str]:
    """공통 CLI 인자 목록을 반환한다."""
    return [
        "--schemas", cli_engine["schemas_dir"],
        "--skills", cli_engine["skills_dir"],
        "--pool", cli_engine["pool_dir"],
        "--db", cli_engine["db_path"],
    ]


def test_feedback_command(cli_engine: dict, capsys) -> None:
    """feedback 명령어가 [OK] 메시지를 출력한다."""
    args = _base_args(cli_engine) + ["feedback", "cli_test", "4", "great output"]

    with patch("sys.argv", ["cambrian"] + args):
        main()

    captured = capsys.readouterr()
    assert "[OK] Feedback #" in captured.out
    assert "cli_test" in captured.out
    assert "rating: 4/5" in captured.out


def test_feedback_invalid_rating(cli_engine: dict) -> None:
    """유효하지 않은 rating은 SystemExit을 발생시킨다."""
    args = _base_args(cli_engine) + ["feedback", "cli_test", "6", "bad"]

    with patch("sys.argv", ["cambrian"] + args):
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code != 0


def test_evolve_command(cli_engine: dict, capsys) -> None:
    """evolve 명령어가 진화 결과를 출력한다."""
    fake_record = EvolutionRecord(
        id=1,
        skill_id="cli_test",
        parent_skill_md="# Old",
        child_skill_md="# New",
        parent_fitness=0.0,
        child_fitness=0.5,
        adopted=True,
        mutation_summary="improved",
        feedback_ids="[1]",
        created_at=datetime.now().astimezone().isoformat(),
    )

    base = _base_args(cli_engine)
    # feedback을 먼저 저장해야 evolve가 동작
    feedback_args = base + ["feedback", "cli_test", "3", "ok"]
    with patch("sys.argv", ["cambrian"] + feedback_args):
        main()

    evolve_args = base + ["evolve", "cli_test", "--input", '{"query": "hello"}']
    with patch("sys.argv", ["cambrian"] + evolve_args):
        with patch("engine.loop.CambrianEngine.evolve", return_value=fake_record):
            main()

    captured = capsys.readouterr()
    assert "[OK] Evolution complete" in captured.out
    assert "adopted" in captured.out


def test_evolve_no_feedback(cli_engine: dict) -> None:
    """피드백 없이 evolve하면 SystemExit."""
    args = _base_args(cli_engine) + ["evolve", "cli_test", "--input", '{"query": "hi"}']

    with patch("sys.argv", ["cambrian"] + args):
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code != 0


def test_history_no_records(cli_engine: dict, capsys) -> None:
    """진화 이력이 없으면 안내 메시지를 출력한다."""
    args = _base_args(cli_engine) + ["history", "cli_test"]

    with patch("sys.argv", ["cambrian"] + args):
        main()

    captured = capsys.readouterr()
    assert "No evolution history" in captured.out


def test_history_with_records(cli_engine: dict, capsys) -> None:
    """진화 이력이 있으면 테이블을 출력한다."""
    from engine.loop import CambrianEngine
    from engine.models import EvolutionRecord

    engine = CambrianEngine(
        schemas_dir=cli_engine["schemas_dir"],
        skills_dir=cli_engine["skills_dir"],
        skill_pool_dir=cli_engine["pool_dir"],
        db_path=cli_engine["db_path"],
    )
    record = EvolutionRecord(
        id=0,
        skill_id="cli_test",
        parent_skill_md="# Old",
        child_skill_md="# New",
        parent_fitness=0.1,
        child_fitness=0.9,
        adopted=True,
        mutation_summary="better",
        feedback_ids="[1]",
        created_at=datetime.now().astimezone().isoformat(),
    )
    engine.get_registry().add_evolution_record(record)

    args = _base_args(cli_engine) + ["history", "cli_test"]
    with patch("sys.argv", ["cambrian"] + args):
        with patch("engine.cli._create_engine", return_value=engine):
            main()

    captured = capsys.readouterr()
    assert "YES" in captured.out
    assert "cli_test" in captured.out


def test_rollback_command(cli_engine: dict, capsys) -> None:
    """rollback 명령어가 SKILL.md를 이전 버전으로 복원한다."""
    from engine.loop import CambrianEngine

    engine = CambrianEngine(
        schemas_dir=cli_engine["schemas_dir"],
        skills_dir=cli_engine["skills_dir"],
        skill_pool_dir=cli_engine["pool_dir"],
        db_path=cli_engine["db_path"],
    )
    original_md = "# Original SKILL.md\nOriginal instructions."
    record = EvolutionRecord(
        id=0,
        skill_id="cli_test",
        parent_skill_md=original_md,
        child_skill_md="# Mutated",
        parent_fitness=0.3,
        child_fitness=0.7,
        adopted=True,
        mutation_summary="mutated",
        feedback_ids="[1]",
        created_at=datetime.now().astimezone().isoformat(),
    )
    record_id = engine.get_registry().add_evolution_record(record)
    skill_path = Path(engine.get_registry().get("cli_test")["skill_path"])

    args = _base_args(cli_engine) + ["rollback", "cli_test", str(record_id)]
    with patch("sys.argv", ["cambrian"] + args):
        with patch("engine.cli._create_engine", return_value=engine):
            main()

    captured = capsys.readouterr()
    assert "[OK] Rolled back" in captured.out
    assert (skill_path / "SKILL.md").read_text(encoding="utf-8") == original_md


# === Phase 2: history 상세 테스트 ===


def test_history_shows_reasoning_column(
    schemas_dir: Path,
    tmp_path: Path,
) -> None:
    """history 목록 출력은 REASONING 컬럼과 reasoning 내용을 포함한다."""
    db_path = tmp_path / "test.db"
    empty_skills = tmp_path / "empty_skills"
    pool_dir = tmp_path / "pool"
    empty_skills.mkdir()
    pool_dir.mkdir()

    _prepare_history_db(db_path, with_record=True, judge_reasoning="test reasoning here")

    result = run_cli(
        "history",
        "test_skill",
        "--db",
        str(db_path),
        "--skills",
        str(empty_skills),
        "--pool",
        str(pool_dir),
        "--schemas",
        str(schemas_dir),
    )

    assert result.returncode == 0
    assert "REASONING" in result.stdout
    assert "test reasoning" in result.stdout


def test_history_detail_shows_diff(
    schemas_dir: Path,
    tmp_path: Path,
) -> None:
    """history --detail은 SKILL.md diff와 변경 내용을 출력한다."""
    db_path = tmp_path / "test.db"
    empty_skills = tmp_path / "empty_skills"
    pool_dir = tmp_path / "pool"
    empty_skills.mkdir()
    pool_dir.mkdir()

    _prepare_history_db(
        db_path,
        with_record=True,
        judge_reasoning="detail reasoning",
        parent_skill_md="# Original\nLine 1",
        child_skill_md="# Evolved\nLine 1\nLine 2",
        record_id=1,
    )

    result = run_cli(
        "history",
        "test_skill",
        "--detail",
        "1",
        "--db",
        str(db_path),
        "--skills",
        str(empty_skills),
        "--pool",
        str(pool_dir),
        "--schemas",
        str(schemas_dir),
    )

    assert result.returncode == 0
    assert "--- SKILL.md Diff ---" in result.stdout or "--- parent" in result.stdout
    assert "+Line 2" in result.stdout or "Evolved" in result.stdout


def test_history_detail_not_found(
    schemas_dir: Path,
    tmp_path: Path,
) -> None:
    """없는 record_id를 조회하면 오류 코드와 not found 메시지를 반환한다."""
    db_path = tmp_path / "test.db"
    empty_skills = tmp_path / "empty_skills"
    pool_dir = tmp_path / "pool"
    empty_skills.mkdir()
    pool_dir.mkdir()

    _prepare_history_db(db_path, with_record=False)

    result = run_cli(
        "history",
        "test_skill",
        "--detail",
        "999",
        "--db",
        str(db_path),
        "--skills",
        str(empty_skills),
        "--pool",
        str(pool_dir),
        "--schemas",
        str(schemas_dir),
    )

    assert result.returncode != 0
    assert "not found" in result.stderr.lower()


# === Phase 3: init 테스트 ===


def test_init_creates_directory(tmp_path: Path) -> None:
    """init 후 프로젝트 디렉토리가 생성된다."""
    target = tmp_path / "new_project"
    result = run_cli(
        "init",
        "--dir", str(target),
        "--skills", "skills",
        "--schemas", "schemas",
    )

    assert result.returncode == 0
    assert target.exists()
    assert (target / "skills").exists()
    assert (target / "schemas").exists()
    assert (target / "skill_pool").exists()
    assert (target / "cambrian.yaml").exists()


def test_init_copies_skills(tmp_path: Path) -> None:
    """init 후 시드 스킬이 복사된다."""
    target = tmp_path / "new_project2"
    result = run_cli(
        "init",
        "--dir", str(target),
        "--skills", "skills",
        "--schemas", "schemas",
    )

    assert result.returncode == 0
    skills_dir = target / "skills"
    skill_names = [d.name for d in skills_dir.iterdir() if d.is_dir()]
    assert "hello_world" in skill_names
    assert len(skill_names) >= 7  # 최소 원래 7개 이상
