"""HarnessBootstrapper 유닛 테스트."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from engine.harness import HarnessBootstrapper
from engine.models import (
    CapabilityGap,
    ProjectFingerprint,
    ProjectScanReport,
    SkillSuggestion,
)


def _make_fingerprint(name: str = "test_project") -> ProjectFingerprint:
    """테스트용 최소 fingerprint."""
    return ProjectFingerprint(
        project_path=f"/tmp/{name}",
        project_name=name,
        total_files=3,
        total_dirs=1,
        languages={"python": 3},
        primary_language="python",
        frameworks=[],
        package_managers=[],
        project_types=["cli"],
        has_tests=False,
        has_docs=False,
        has_ci=False,
        has_docker=False,
        has_api=False,
        has_config=False,
        key_files=["main.py", "utils.py"],
    )


def _make_gaps() -> list[CapabilityGap]:
    """테스트용 gap 목록."""
    return [
        CapabilityGap(
            category="testing",
            description="테스트 코드가 없음",
            priority="medium",
            evidence=["tests/ 없음"],
            suggested_domain="testing",
            suggested_tags=["test", "pytest"],
            search_query="testing unit test",
        ),
        CapabilityGap(
            category="documentation",
            description="문서화 부족",
            priority="medium",
            evidence=["README 없음"],
            suggested_domain="documentation",
            suggested_tags=["readme", "docs"],
            search_query="documentation readme",
        ),
    ]


def _make_report(
    fingerprint: ProjectFingerprint | None = None,
    gaps: list[CapabilityGap] | None = None,
) -> ProjectScanReport:
    """테스트용 scan report."""
    fp = fingerprint or _make_fingerprint()
    g = gaps if gaps is not None else _make_gaps()
    return ProjectScanReport(
        fingerprint=fp,
        gaps=g,
        suggestions=[],
        total_gaps=len(g),
        covered_gaps=0,
        uncovered_gaps=len(g),
        search_executed=False,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _make_registry_skills() -> list[dict]:
    """테스트용 registry 스킬 목록."""
    return [
        {
            "id": "pytest_scaffold",
            "name": "Pytest Scaffold",
            "domain": "testing",
            "tags": ["test", "pytest", "scaffold"],
            "mode": "b",
        },
        {
            "id": "readme_generator",
            "name": "README Generator",
            "domain": "documentation",
            "tags": ["readme", "docs", "documentation"],
            "mode": "b",
        },
        {
            "id": "hello_world",
            "name": "Hello World",
            "domain": "utility",
            "tags": ["test", "greeting"],
            "mode": "b",
        },
    ]


def test_bootstrap_harness_creates_required_files(tmp_path: Path) -> None:
    """5개 하네스 파일 + 1개 리포트가 생성된다."""
    report = _make_report()
    bootstrapper = HarnessBootstrapper()
    result = bootstrapper.bootstrap(report, tmp_path)

    harness_dir = tmp_path / ".cambrian" / "harness"
    assert (harness_dir / "harness.yaml").is_file()
    assert (harness_dir / "eval_cases.jsonl").is_file()
    assert (harness_dir / "judge_rubric.md").is_file()
    assert (harness_dir / "promotion_policy.json").is_file()
    assert (harness_dir / "rollback_policy.json").is_file()

    reports_dir = tmp_path / ".cambrian" / "reports"
    assert (reports_dir / "latest_harness_bootstrap.json").is_file()


def test_bootstrap_harness_populates_focus_areas_from_scan(
    tmp_path: Path,
) -> None:
    """harness.yaml의 focus_areas가 scan gaps에서 채워진다."""
    report = _make_report()
    bootstrapper = HarnessBootstrapper()
    bootstrapper.bootstrap(report, tmp_path)

    harness_path = tmp_path / ".cambrian" / "harness" / "harness.yaml"
    harness = yaml.safe_load(harness_path.read_text(encoding="utf-8"))

    focus_areas = harness["focus_areas"]
    categories = [fa["category"] for fa in focus_areas]
    assert "testing" in categories
    assert "documentation" in categories

    # priority도 반영됨
    for fa in focus_areas:
        assert "priority" in fa
        assert fa["priority"] in ("high", "medium", "low")


def test_bootstrap_harness_generates_minimal_eval_cases(
    tmp_path: Path,
) -> None:
    """eval_cases.jsonl에 최소 2개 케이스가 있다."""
    report = _make_report()
    bootstrapper = HarnessBootstrapper()
    bootstrapper.bootstrap(report, tmp_path)

    cases_path = tmp_path / ".cambrian" / "harness" / "eval_cases.jsonl"
    lines = [
        line.strip()
        for line in cases_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) >= 2, f"eval_cases가 {len(lines)}개 — 최소 2개 필요"

    for line in lines:
        case = json.loads(line)
        assert "id" in case
        assert "category" in case
        assert "task_domain" in case
        assert "input" in case


def test_bootstrap_harness_generates_candidate_mapping_report(
    tmp_path: Path,
) -> None:
    """candidate mapping이 gap별로 생성된다."""
    report = _make_report()
    bootstrapper = HarnessBootstrapper(
        registry_skills=_make_registry_skills(),
    )
    result = bootstrapper.bootstrap(report, tmp_path)

    mapping = result["gap_candidate_mapping"]

    # testing gap → pytest_scaffold 매칭
    assert "testing" in mapping
    testing = mapping["testing"]
    assert testing["status"] == "candidates_available"
    skill_ids = [c["skill_id"] for c in testing["candidates"]]
    assert "pytest_scaffold" in skill_ids

    # documentation gap → readme_generator 매칭
    assert "documentation" in mapping
    doc = mapping["documentation"]
    assert doc["status"] == "candidates_available"
    skill_ids = [c["skill_id"] for c in doc["candidates"]]
    assert "readme_generator" in skill_ids


def test_bootstrap_harness_no_candidates_status(tmp_path: Path) -> None:
    """매칭 스킬이 없으면 no_viable_candidate 상태."""
    report = _make_report()
    # 빈 registry
    bootstrapper = HarnessBootstrapper(registry_skills=[])
    result = bootstrapper.bootstrap(report, tmp_path)

    for gap_cat, info in result["gap_candidate_mapping"].items():
        if not info["candidates"]:
            assert info["status"] == "no_viable_candidate_currently_available"


def test_bootstrap_harness_next_actions_not_empty(tmp_path: Path) -> None:
    """next_actions가 최소 1개 이상."""
    report = _make_report()
    bootstrapper = HarnessBootstrapper(
        registry_skills=_make_registry_skills(),
    )
    result = bootstrapper.bootstrap(report, tmp_path)

    assert len(result["next_actions"]) >= 1
    # "cambrian" 명령이 포함되어야 함
    assert any("cambrian" in a for a in result["next_actions"])


def test_bootstrap_harness_empty_gaps(tmp_path: Path) -> None:
    """gap이 없어도 정상 동작한다."""
    report = _make_report(gaps=[])
    bootstrapper = HarnessBootstrapper()
    result = bootstrapper.bootstrap(report, tmp_path)

    # 파일은 생성됨
    harness_dir = tmp_path / ".cambrian" / "harness"
    assert (harness_dir / "harness.yaml").is_file()
    assert (harness_dir / "eval_cases.jsonl").is_file()

    # 최소 1개 eval case
    cases_path = harness_dir / "eval_cases.jsonl"
    lines = [
        line for line in cases_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) >= 1
