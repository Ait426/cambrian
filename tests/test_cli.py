"""CLI 테스트.

subprocess로 실제 CLI 명령어를 실행하여 테스트한다.
엔진 초기화에 실제 파일 시스템이 필요하므로 프로젝트 루트에서 실행.
"""

import subprocess
import sys
from pathlib import Path


def run_cli(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """cambrian CLI를 subprocess로 실행한다.

    Args:
        *args: CLI 인자들
        cwd: 실행 작업 디렉토리

    Returns:
        subprocess 실행 결과
    """
    cmd = [sys.executable, "-m", "engine.cli"] + list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd or str(Path(__file__).parent.parent),
        timeout=30,
    )


def test_help() -> None:
    """cambrian --help가 정상 출력된다."""
    result = run_cli("--help")

    assert result.returncode == 0
    assert "cambrian" in result.stdout.lower() or "Cambrian" in result.stdout


def test_no_command() -> None:
    """명령어 없이 실행하면 도움말이 출력된다."""
    result = run_cli()

    assert result.returncode == 0


def test_skills_list() -> None:
    """cambrian skills가 hello_world를 표시한다."""
    result = run_cli("skills", "--db", ":memory:")

    assert result.returncode == 0
    assert "hello_world" in result.stdout


def test_skill_detail() -> None:
    """cambrian skill hello_world가 상세 정보를 표시한다."""
    result = run_cli("skill", "hello_world", "--db", ":memory:")

    assert result.returncode == 0
    assert "hello_world" in result.stdout
    assert "utility" in result.stdout


def test_run_success() -> None:
    """cambrian run으로 hello_world 태스크를 실행한다."""
    result = run_cli(
        "run",
        "--domain",
        "utility",
        "--tags",
        "greeting",
        "--input",
        '{"text": "CLI Test"}',
        "--db",
        ":memory:",
    )

    assert result.returncode == 0
    assert "Hello, CLI Test!" in result.stdout


def test_run_invalid_json() -> None:
    """잘못된 JSON을 입력하면 에러 메시지가 출력된다."""
    result = run_cli(
        "run",
        "--domain",
        "utility",
        "--tags",
        "greeting",
        "--input",
        "not a json",
        "--db",
        ":memory:",
    )

    assert result.returncode != 0


def test_stats() -> None:
    """cambrian stats가 통계를 표시한다."""
    result = run_cli("stats", "--db", ":memory:")

    assert result.returncode == 0
    assert "Total" in result.stdout or "total" in result.stdout


def test_skill_not_found() -> None:
    """없는 스킬 ID를 조회하면 에러."""
    result = run_cli("skill", "nonexistent_abc", "--db", ":memory:")

    assert (
        result.returncode != 0
        or "not found" in result.stdout.lower()
        or "not found" in result.stderr.lower()
    )
