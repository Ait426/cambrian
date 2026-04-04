"""ProjectScanner 프로젝트 스캔 테스트."""

from pathlib import Path

import pytest
import yaml

from conftest import create_valid_skill
from engine.loader import SkillLoader
from engine.registry import SkillRegistry
from engine.scanner import ProjectScanner
from engine.search import SkillSearcher


# ═══════════════════════════════════════════════════════════════════
# 테스트 헬퍼
# ═══════════════════════════════════════════════════════════════════


def create_python_project(base_dir: Path) -> Path:
    """테스트용 Python CLI 프로젝트 생성.

    Args:
        base_dir: 상위 디렉토리

    Returns:
        프로젝트 디렉토리 경로
    """
    proj = base_dir / "my_python_project"
    proj.mkdir()
    (proj / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (proj / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "test"\n', encoding="utf-8",
    )
    return proj


def create_node_web_project(base_dir: Path) -> Path:
    """테스트용 Node.js 웹 프로젝트 생성.

    Args:
        base_dir: 상위 디렉토리

    Returns:
        프로젝트 디렉토리 경로
    """
    proj = base_dir / "my_node_project"
    proj.mkdir()
    (proj / "package.json").write_text(
        '{"dependencies": {"react": "^18.0.0"}}\n', encoding="utf-8",
    )
    (proj / "src").mkdir()
    (proj / "src" / "App.tsx").write_text(
        "export default function App() {}\n", encoding="utf-8",
    )
    (proj / "src" / "index.ts").write_text(
        "import App from './App'\n", encoding="utf-8",
    )
    return proj


def create_full_project(base_dir: Path) -> Path:
    """모든 capability를 갖춘 프로젝트 생성.

    Args:
        base_dir: 상위 디렉토리

    Returns:
        프로젝트 디렉토리 경로
    """
    proj = base_dir / "full_project"
    proj.mkdir()
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "full"\n[tool.pytest]\n[tool.ruff]\n[tool.mypy]\n',
        encoding="utf-8",
    )
    (proj / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (proj / "tests").mkdir()
    (proj / "tests" / "test_main.py").write_text(
        "def test_a(): pass\n", encoding="utf-8",
    )
    (proj / "docs").mkdir()
    (proj / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (proj / "README.md").write_text(
        "# Full Project\n" + "description line\n" * 60, encoding="utf-8",
    )
    (proj / ".github").mkdir()
    (proj / ".github" / "workflows").mkdir()
    (proj / ".github" / "workflows" / "ci.yml").write_text(
        "on: push\n", encoding="utf-8",
    )
    (proj / "Dockerfile").write_text("FROM python:3.11\n", encoding="utf-8")
    return proj


def create_fastapi_project(base_dir: Path) -> Path:
    """테스트용 FastAPI 프로젝트 생성.

    Args:
        base_dir: 상위 디렉토리

    Returns:
        프로젝트 디렉토리 경로
    """
    proj = base_dir / "fastapi_project"
    proj.mkdir()
    (proj / "requirements.txt").write_text(
        "fastapi==0.100.0\nuvicorn\n", encoding="utf-8",
    )
    (proj / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8",
    )
    (proj / "api").mkdir()
    (proj / "api" / "routes.py").write_text("pass\n", encoding="utf-8")
    return proj


def create_data_project(base_dir: Path) -> Path:
    """테스트용 데이터 파이프라인 프로젝트 생성.

    Args:
        base_dir: 상위 디렉토리

    Returns:
        프로젝트 디렉토리 경로
    """
    proj = base_dir / "data_project"
    proj.mkdir()
    (proj / "requirements.txt").write_text(
        "pandas==2.0.0\nnumpy\n", encoding="utf-8",
    )
    (proj / "pipeline.py").write_text("import pandas as pd\n", encoding="utf-8")
    (proj / "data").mkdir()
    (proj / "data" / "input.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    return proj


# ═══════════════════════════════════════════════════════════════════
# 테스트 케이스
# ═══════════════════════════════════════════════════════════════════


def test_scan_python_project_language(tmp_path: Path) -> None:
    """Python 프로젝트 → primary_language='python'."""
    proj = create_python_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    assert report.fingerprint.primary_language == "python"
    assert "python" in report.fingerprint.languages
    assert report.fingerprint.languages["python"] >= 2


def test_scan_node_project_language(tmp_path: Path) -> None:
    """Node 프로젝트 → primary_language='typescript'."""
    proj = create_node_web_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    assert report.fingerprint.primary_language == "typescript"


def test_scan_framework_detection(tmp_path: Path) -> None:
    """package.json에 react → frameworks에 'react' 포함."""
    proj = create_node_web_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    assert "react" in report.fingerprint.frameworks


def test_scan_package_manager_detection(tmp_path: Path) -> None:
    """pyproject.toml 존재 → package_managers에 'pip'."""
    proj = create_python_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    assert "pip" in report.fingerprint.package_managers


def test_scan_project_type_web_api(tmp_path: Path) -> None:
    """fastapi 의존성 → project_types에 'web_api'."""
    proj = create_fastapi_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    assert "web_api" in report.fingerprint.project_types


def test_scan_project_type_data(tmp_path: Path) -> None:
    """pandas 의존성 → project_types에 'data_pipeline'."""
    proj = create_data_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    assert "data_pipeline" in report.fingerprint.project_types


def test_scan_testing_gap(tmp_path: Path) -> None:
    """tests/ 없는 프로젝트 → gaps에 'testing' 포함."""
    proj = create_python_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    gap_categories = [g.category for g in report.gaps]
    assert "testing" in gap_categories


def test_scan_no_testing_gap_when_tests_exist(tmp_path: Path) -> None:
    """tests/ 있는 프로젝트 → gaps에 'testing' 미포함."""
    proj = create_full_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    gap_categories = [g.category for g in report.gaps]
    assert "testing" not in gap_categories


def test_scan_documentation_gap(tmp_path: Path) -> None:
    """docs/README 없는 프로젝트 → gaps에 'documentation'."""
    proj = create_python_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    gap_categories = [g.category for g in report.gaps]
    assert "documentation" in gap_categories


def test_scan_full_project_minimal_gaps(tmp_path: Path) -> None:
    """모든 capability 갖춘 프로젝트 → gaps 최소화."""
    proj = create_full_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    # testing, documentation, ci_cd, containerization 모두 갖춤
    gap_categories = [g.category for g in report.gaps]
    assert "testing" not in gap_categories
    assert "documentation" not in gap_categories
    assert "ci_cd" not in gap_categories
    assert "containerization" not in gap_categories


def test_scan_search_integration(tmp_path: Path, schemas_dir: Path) -> None:
    """search 연동 시 gaps에 맞는 suggestions 반환."""
    # 스킬 등록
    loader = SkillLoader(schemas_dir)
    registry = SkillRegistry(":memory:")
    skills_dir = tmp_path / "reg_skills"
    skills_dir.mkdir()

    skill_dir = create_valid_skill(skills_dir, "test_tool")
    meta_path = skill_dir / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["domain"] = "testing"
    meta["tags"] = ["unit_test", "pytest", "testing"]
    meta["name"] = "Testing Tool"
    meta["description"] = "Automated testing and unit test generation"
    meta_path.write_text(yaml.dump(meta, allow_unicode=True), encoding="utf-8")
    skill = loader.load(skill_dir)
    registry.register(skill)

    searcher = SkillSearcher(registry, loader)
    scanner = ProjectScanner(searcher=searcher)

    # tests가 없는 프로젝트 스캔
    proj = create_python_project(tmp_path)
    report = scanner.scan(proj, run_search=True)

    assert report.search_executed is True
    # testing gap에 대한 suggestion이 있어야 함
    testing_suggestions = [s for s in report.suggestions if s.gap_category == "testing"]
    assert len(testing_suggestions) > 0
    assert testing_suggestions[0].skill_id == "test_tool"


def test_scan_no_search_flag(tmp_path: Path) -> None:
    """run_search=False → suggestions 빈 리스트, search_executed=False."""
    proj = create_python_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    assert report.search_executed is False
    assert report.suggestions == []


def test_scan_empty_directory(tmp_path: Path) -> None:
    """빈 디렉토리 → fingerprint 정상, gaps 있을 수 있음."""
    proj = tmp_path / "empty_project"
    proj.mkdir()

    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    assert report.fingerprint.total_files == 0
    assert report.fingerprint.primary_language == "unknown"
    assert report.fingerprint.project_types == ["unknown"]


def test_scan_nonexistent_path(tmp_path: Path) -> None:
    """존재하지 않는 경로 → FileNotFoundError."""
    scanner = ProjectScanner()
    with pytest.raises(FileNotFoundError):
        scanner.scan(tmp_path / "nonexistent")


def test_scan_file_not_dir(tmp_path: Path) -> None:
    """파일 경로 → ValueError."""
    some_file = tmp_path / "not_a_dir.txt"
    some_file.write_text("hello", encoding="utf-8")

    scanner = ProjectScanner()
    with pytest.raises(ValueError):
        scanner.scan(some_file)


def test_scan_depth_limit(tmp_path: Path) -> None:
    """max_depth=1 → 하위 디렉토리 미스캔."""
    proj = tmp_path / "deep_project"
    proj.mkdir()
    (proj / "top.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "level1").mkdir()
    (proj / "level1" / "mid.py").write_text("y = 2\n", encoding="utf-8")
    (proj / "level1" / "level2").mkdir()
    (proj / "level1" / "level2" / "deep.py").write_text("z = 3\n", encoding="utf-8")

    scanner = ProjectScanner()
    report = scanner.scan(proj, max_depth=1, run_search=False)

    # depth=1이면 level1까지만 스캔 (level2 미포함)
    assert report.fingerprint.total_files <= 2


def test_scan_ignore_patterns(tmp_path: Path) -> None:
    """node_modules, __pycache__ 등이 무시된다."""
    proj = tmp_path / "ignore_project"
    proj.mkdir()
    (proj / "main.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "node_modules").mkdir()
    (proj / "node_modules" / "pkg.js").write_text("//\n", encoding="utf-8")
    (proj / "__pycache__").mkdir()
    (proj / "__pycache__" / "cached.pyc").write_text("", encoding="utf-8")

    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    # node_modules, __pycache__의 파일은 카운트에 포함되면 안 됨
    assert report.fingerprint.total_files == 1


def test_scan_max_queries_limit(tmp_path: Path, schemas_dir: Path) -> None:
    """max_queries=1 → search 1회만 호출."""
    loader = SkillLoader(schemas_dir)
    registry = SkillRegistry(":memory:")
    searcher = SkillSearcher(registry, loader)
    scanner = ProjectScanner(searcher=searcher)

    # gaps가 여러 개 나올 프로젝트
    proj = create_python_project(tmp_path)
    report = scanner.scan(proj, max_queries=1, run_search=True)

    # max_queries=1이므로 첫 번째 gap만 search됨
    # suggestions에 포함된 gap_category 종류가 1개 이하여야 함
    categories = {s.gap_category for s in report.suggestions}
    assert len(categories) <= 1


def test_scan_gap_priority_order(tmp_path: Path) -> None:
    """gaps가 high > medium > low 순 정렬."""
    proj = create_python_project(tmp_path)
    # 파일 추가로 파일 수 > 30 만들기 (code_review gap 유발)
    for i in range(35):
        (proj / f"module_{i}.py").write_text(f"x = {i}\n", encoding="utf-8")

    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    priorities = [g.priority for g in report.gaps]
    priority_order = {"high": 0, "medium": 1, "low": 2}
    ordered = [priority_order.get(p, 99) for p in priorities]
    assert ordered == sorted(ordered)


def test_scan_api_documentation_gap_for_web_api(tmp_path: Path) -> None:
    """web_api 프로젝트에서 API 문서가 없으면 api_documentation gap 발생."""
    proj = create_fastapi_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    gap_categories = [g.category for g in report.gaps]
    assert "api_documentation" in gap_categories


def test_scan_report_structure(tmp_path: Path) -> None:
    """ProjectScanReport에 올바른 구조가 포함된다."""
    proj = create_python_project(tmp_path)
    scanner = ProjectScanner()
    report = scanner.scan(proj, run_search=False)

    assert report.fingerprint is not None
    assert report.timestamp is not None
    assert report.total_gaps == len(report.gaps)
    assert report.uncovered_gaps == report.total_gaps - report.covered_gaps
    assert report.fingerprint.project_name == "my_python_project"
    assert report.fingerprint.project_path is not None
