"""Cambrian 프로젝트 문맥 스캐너 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_context import ProjectContextScanner
from engine.project_mode import ProjectInitializer, ProjectRunPreparer, ProjectStatusReader


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def _prepare_login_fixture(project_root: Path) -> None:
    _prepare_python_project(project_root)
    (project_root / "src" / "auth").mkdir(parents=True, exist_ok=True)
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "auth" / "login.py").write_text(
        "def login(username: str, password: str) -> bool:\n"
        "    return username == 'admin' and password == 'secret'\n",
        encoding="utf-8",
    )
    (project_root / "tests" / "test_login.py").write_text(
        "from src.auth.login import login\n\n"
        "def test_login() -> None:\n"
        "    assert login('admin', 'secret') is True\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_scanner_finds_path_match(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)

    result = ProjectContextScanner().scan(
        user_request="로그인 에러 수정해",
        project_root=tmp_path,
        request_id="req-001",
    )

    assert result.status == "success"
    assert result.top_source == "src/auth/login.py"
    assert result.top_test == "tests/test_login.py"
    assert any("related test file found" in reason for reason in result.suggested_sources[0].reasons)


def test_scanner_finds_content_match(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text(
        "def handler() -> str:\n"
        "    token = 'auth-login-flow'\n"
        "    return token\n",
        encoding="utf-8",
    )

    result = ProjectContextScanner().scan(
        user_request="login issue 확인",
        project_root=tmp_path,
        request_id="req-002",
    )

    assert result.suggested_sources
    assert result.suggested_sources[0].path == "src/service.py"
    assert any("content matched term" in reason for reason in result.suggested_sources[0].reasons)


def test_scanner_no_match_path(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "alpha.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = ProjectContextScanner().scan(
        user_request="결제 승인 실패 수정해",
        project_root=tmp_path,
        request_id="req-003",
    )

    assert result.status == "no_match"
    assert any("Try a more specific request" in action for action in result.next_actions)


def test_protected_paths_ignored(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    (tmp_path / ".cambrian").mkdir(exist_ok=True)
    (tmp_path / ".cambrian" / "login.py").write_text("auth = 1\n", encoding="utf-8")
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / ".git" / "config").write_text("login=true\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir(exist_ok=True)
    (tmp_path / "node_modules" / "login.js").write_text("export const login = true;\n", encoding="utf-8")

    result = ProjectContextScanner().scan(
        user_request="로그인 에러 수정해",
        project_root=tmp_path,
        request_id="req-004",
    )

    paths = {candidate.path for candidate in result.suggested_sources}
    assert ".cambrian/login.py" not in paths
    assert ".git/config" not in paths
    assert "node_modules/login.js" not in paths


def test_large_file_skipped(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    (tmp_path / "src").mkdir()
    big_file = tmp_path / "src" / "login_large.py"
    big_file.write_text("login\n" * 300000, encoding="utf-8")

    result = ProjectContextScanner().scan(
        user_request="로그인 수정해",
        project_root=tmp_path,
        request_id="req-005",
    )

    assert any("큰 파일" in warning for warning in result.warnings)
    assert result.status in {"success", "no_match"}


def test_classification_and_related_test_suggestion(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    (tmp_path / "README.md").write_text("# login docs\n", encoding="utf-8")

    result = ProjectContextScanner().scan(
        user_request="login test 문제 확인",
        project_root=tmp_path,
        request_id="req-006",
    )

    source = next(item for item in result.suggested_sources if item.path == "src/auth/login.py")
    test = next(item for item in result.suggested_tests if item.path == "tests/test_login.py")
    assert source.kind == "source"
    assert test.kind == "test"
    assert any("related test file found" in reason for reason in source.reasons)


def test_context_artifact_created(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    scanner = ProjectContextScanner()
    result = scanner.scan(
        user_request="로그인 에러 수정해",
        project_root=tmp_path,
        request_id="req-007",
    )
    out_path = tmp_path / ".cambrian" / "context" / "context_req-007.yaml"

    scanner.save(result, out_path)

    payload = _read_yaml(out_path)
    assert payload["schema_version"] == "1.0.0"
    assert payload["user_request"] == "로그인 에러 수정해"
    assert payload["query_terms"]
    assert payload["suggested_sources"]
    assert payload["suggested_tests"]


def test_cli_context_scan_smoke(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)

    result = _run_cli(["context", "scan", "로그인 에러 수정해"], tmp_path)

    assert result.returncode == 0
    assert "Cambrian scanned project context." in result.stdout
    assert "src/auth/login.py" in result.stdout
    assert list((tmp_path / ".cambrian" / "context").glob("context_*.yaml"))


def test_run_auto_scan_when_needs_context(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")

    request_payload = _read_yaml(tmp_path / result.request_path)
    assert request_payload["context_scan"]["enabled"] is True
    assert request_payload["context_scan_ref"]
    assert request_payload["context_scan"]["top_sources"] == ["src/auth/login.py"]
    assert request_payload["context_scan"]["top_tests"] == ["tests/test_login.py"]
    task_payload = _read_yaml(tmp_path / result.task_spec_path)
    assert not task_payload.get("actions")


def test_run_no_scan(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해", no_scan=True)

    request_payload = _read_yaml(tmp_path / result.request_path)
    assert request_payload["context_scan"]["enabled"] is False
    assert request_payload["context_scan_ref"] is None
    assert not (tmp_path / ".cambrian" / "context").exists()


def test_status_shows_recent_context_scan(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")

    status = ProjectStatusReader().read(tmp_path)

    assert status.recent_context_scan
    assert status.recent_context_scan["top_file"] == "src/auth/login.py"


def test_context_scan_json_output(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)

    result = _run_cli(["context", "scan", "로그인 에러 수정해", "--json"], tmp_path)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["suggested_sources"]
    assert payload["suggested_tests"]
    assert payload["artifact_path"]


def test_source_immutability(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    source_path = tmp_path / "src" / "auth" / "login.py"
    before_hash = _sha256(source_path)

    ProjectContextScanner().scan(
        user_request="로그인 에러 수정해",
        project_root=tmp_path,
        request_id="req-008",
    )

    assert _sha256(source_path) == before_hash
