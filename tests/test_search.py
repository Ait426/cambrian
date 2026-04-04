"""SkillSearcher 통합 검색 테스트."""

from pathlib import Path

import yaml

from conftest import create_valid_skill
from engine.loader import SkillLoader
from engine.models import SearchQuery
from engine.registry import SkillRegistry
from engine.search import SkillSearcher


def _create_skill_with_meta(
    base_dir: Path,
    skill_id: str,
    name: str,
    description: str,
    domain: str,
    tags: list[str],
    mode: str = "b",
) -> Path:
    """커스텀 메타데이터로 테스트 스킬을 생성한다.

    Args:
        base_dir: 상위 디렉토리
        skill_id: 스킬 ID
        name: 스킬 이름
        description: 설명
        domain: 도메인
        tags: 태그 리스트
        mode: 실행 모드

    Returns:
        생성된 스킬 디렉토리 경로
    """
    skill_dir = create_valid_skill(base_dir, skill_id)
    meta_path = skill_dir / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["id"] = skill_id
    meta["name"] = name
    meta["description"] = description
    meta["domain"] = domain
    meta["tags"] = tags
    meta["mode"] = mode
    meta_path.write_text(yaml.dump(meta, allow_unicode=True), encoding="utf-8")
    return skill_dir


def _setup_searcher(
    tmp_path: Path,
    schemas_dir: Path,
    skills: list[dict],
) -> tuple[SkillSearcher, SkillRegistry]:
    """스킬 목록으로 searcher를 구성한다.

    Args:
        tmp_path: pytest tmp_path
        schemas_dir: 스키마 디렉토리
        skills: 스킬 메타데이터 dict 리스트

    Returns:
        (SkillSearcher, SkillRegistry) 튜플
    """
    loader = SkillLoader(schemas_dir)
    registry = SkillRegistry(":memory:")
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    for skill_meta in skills:
        skill_dir = _create_skill_with_meta(
            skills_dir,
            skill_id=skill_meta["id"],
            name=skill_meta["name"],
            description=skill_meta["description"],
            domain=skill_meta["domain"],
            tags=skill_meta["tags"],
            mode=skill_meta.get("mode", "b"),
        )
        skill = loader.load(skill_dir)
        registry.register(skill)

    searcher = SkillSearcher(registry, loader)
    return searcher, registry


def test_search_by_keyword_match(tmp_path: Path, schemas_dir: Path) -> None:
    """description 키워드 매칭으로 결과를 반환한다."""
    searcher, _ = _setup_searcher(tmp_path, schemas_dir, [
        {"id": "csv_parser", "name": "CSV Parser", "description": "Parse CSV files into structured data", "domain": "data", "tags": ["csv", "parsing"]},
        {"id": "email_draft", "name": "Email Draft", "description": "Draft professional emails", "domain": "writing", "tags": ["email"]},
    ])

    query = SearchQuery(text="CSV data", include_external=False)
    report = searcher.search(query)

    assert len(report.results) > 0
    assert report.results[0].skill_id == "csv_parser"


def test_search_by_tags(tmp_path: Path, schemas_dir: Path) -> None:
    """태그 매칭 시 점수가 높아진다."""
    searcher, _ = _setup_searcher(tmp_path, schemas_dir, [
        {"id": "chart_maker", "name": "Chart Maker", "description": "Generate charts", "domain": "data", "tags": ["chart", "visualization"]},
        {"id": "data_cleaner", "name": "Data Cleaner", "description": "Clean messy data", "domain": "data", "tags": ["cleaning"]},
    ])

    query = SearchQuery(text="chart", include_external=False)
    report = searcher.search(query)

    assert len(report.results) > 0
    # chart는 description과 tags 양쪽에 매칭되므로 chart_maker가 1순위
    assert report.results[0].skill_id == "chart_maker"


def test_search_by_domain(tmp_path: Path, schemas_dir: Path) -> None:
    """domain 일치 시 점수가 부스트된다."""
    searcher, _ = _setup_searcher(tmp_path, schemas_dir, [
        {"id": "skill_a", "name": "Skill A", "description": "Does something with data processing", "domain": "data", "tags": ["test"]},
        {"id": "skill_b", "name": "Skill B", "description": "Does something with data processing", "domain": "writing", "tags": ["test"]},
    ])

    query = SearchQuery(text="data", include_external=False)
    report = searcher.search(query)

    assert len(report.results) >= 2
    # domain="data"인 skill_a가 더 높은 점수
    assert report.results[0].skill_id == "skill_a"


def test_search_empty_query(tmp_path: Path, schemas_dir: Path) -> None:
    """빈 쿼리는 전체 결과를 반환한다 (fitness순)."""
    searcher, _ = _setup_searcher(tmp_path, schemas_dir, [
        {"id": "skill_x", "name": "Skill X", "description": "Something", "domain": "test", "tags": ["alpha"]},
        {"id": "skill_y", "name": "Skill Y", "description": "Another", "domain": "test", "tags": ["beta"]},
    ])

    query = SearchQuery(text="", include_external=False)
    report = searcher.search(query)

    # 빈 키워드 → 모든 스킬 반환 (relevance = 0.5 + fitness 보정)
    assert len(report.results) == 2


def test_search_no_results(tmp_path: Path, schemas_dir: Path) -> None:
    """매칭되는 스킬이 없으면 빈 리스트를 반환한다."""
    searcher, _ = _setup_searcher(tmp_path, schemas_dir, [
        {"id": "hello", "name": "Hello", "description": "Greeting skill", "domain": "utility", "tags": ["greeting"]},
    ])

    query = SearchQuery(text="quantum physics simulation", include_external=False)
    report = searcher.search(query)

    assert len(report.results) == 0


def test_search_with_external(tmp_path: Path, schemas_dir: Path) -> None:
    """외부 디렉토리의 스킬도 검색 결과에 포함된다."""
    loader = SkillLoader(schemas_dir)
    registry = SkillRegistry(":memory:")

    # 내부 스킬 등록
    internal_dir = tmp_path / "internal"
    internal_dir.mkdir()
    skill_dir = _create_skill_with_meta(
        internal_dir, "internal_csv", "Internal CSV", "Parse CSV internally",
        "data", ["csv"],
    )
    skill = loader.load(skill_dir)
    registry.register(skill)

    # 외부 스킬 디렉토리 생성
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    _create_skill_with_meta(
        external_dir, "external_chart", "External Chart", "Generate charts from data",
        "data", ["chart"],
    )

    searcher = SkillSearcher(registry, loader)
    query = SearchQuery(text="data chart", include_external=True)
    report = searcher.search(query, external_dirs=[external_dir])

    assert report.external_hits > 0
    external_results = [r for r in report.results if r.source.startswith("external:")]
    assert len(external_results) > 0
    assert external_results[0].skill_id == "external_chart"
    assert external_results[0].status == "unregistered"


def test_search_external_dedup(tmp_path: Path, schemas_dir: Path) -> None:
    """이미 레지스트리에 등록된 스킬은 외부 결과에서 제외된다."""
    loader = SkillLoader(schemas_dir)
    registry = SkillRegistry(":memory:")

    # 동일 ID로 내부/외부 모두 생성
    internal_dir = tmp_path / "internal"
    internal_dir.mkdir()
    skill_dir = _create_skill_with_meta(
        internal_dir, "shared_skill", "Shared", "A shared skill",
        "data", ["shared"],
    )
    skill = loader.load(skill_dir)
    registry.register(skill)

    external_dir = tmp_path / "external"
    external_dir.mkdir()
    _create_skill_with_meta(
        external_dir, "shared_skill", "Shared External", "Same skill externally",
        "data", ["shared"],
    )

    searcher = SkillSearcher(registry, loader)
    query = SearchQuery(text="shared", include_external=True)
    report = searcher.search(query, external_dirs=[external_dir])

    # 중복 제거: 외부 결과 0건
    assert report.external_hits == 0
    shared_results = [r for r in report.results if r.skill_id == "shared_skill"]
    assert len(shared_results) == 1
    assert shared_results[0].source == "registry"


def test_search_limit(tmp_path: Path, schemas_dir: Path) -> None:
    """limit 파라미터가 결과 수를 제한한다."""
    skills = [
        {"id": f"skill_{i}", "name": f"Skill {i}", "description": f"Test skill number {i}", "domain": "test", "tags": ["test"]}
        for i in range(5)
    ]
    searcher, _ = _setup_searcher(tmp_path, schemas_dir, skills)

    query = SearchQuery(text="test skill", include_external=False, limit=3)
    report = searcher.search(query)

    assert len(report.results) <= 3


def test_search_dormant_excluded(tmp_path: Path, schemas_dir: Path) -> None:
    """include_dormant=False면 dormant 스킬이 제외된다."""
    searcher, registry = _setup_searcher(tmp_path, schemas_dir, [
        {"id": "active_skill", "name": "Active", "description": "An active skill for testing", "domain": "test", "tags": ["test"]},
        {"id": "dormant_skill", "name": "Dormant", "description": "A dormant skill for testing", "domain": "test", "tags": ["test"]},
    ])

    # dormant_skill을 dormant로 변경
    registry.update_status("dormant_skill", "dormant")

    query = SearchQuery(text="skill testing", include_external=False, include_dormant=False)
    report = searcher.search(query)

    result_ids = [r.skill_id for r in report.results]
    assert "active_skill" in result_ids
    assert "dormant_skill" not in result_ids


def test_search_dormant_included(tmp_path: Path, schemas_dir: Path) -> None:
    """include_dormant=True면 dormant 스킬도 포함된다."""
    searcher, registry = _setup_searcher(tmp_path, schemas_dir, [
        {"id": "active_skill", "name": "Active", "description": "An active skill for testing", "domain": "test", "tags": ["test"]},
        {"id": "dormant_skill", "name": "Dormant", "description": "A dormant skill for testing", "domain": "test", "tags": ["test"]},
    ])

    registry.update_status("dormant_skill", "dormant")

    query = SearchQuery(text="skill testing", include_external=False, include_dormant=True)
    report = searcher.search(query)

    result_ids = [r.skill_id for r in report.results]
    assert "active_skill" in result_ids
    assert "dormant_skill" in result_ids


def test_search_relevance_ranking(tmp_path: Path, schemas_dir: Path) -> None:
    """관련도 점수가 높은 순서로 정렬된다."""
    searcher, _ = _setup_searcher(tmp_path, schemas_dir, [
        {"id": "low_match", "name": "Low", "description": "Does something unrelated", "domain": "utility", "tags": ["misc"]},
        {"id": "high_match", "name": "Email Writer", "description": "Write professional emails", "domain": "email", "tags": ["email", "writing"]},
        {"id": "mid_match", "name": "Messenger", "description": "Send messages via email", "domain": "communication", "tags": ["messaging"]},
    ])

    query = SearchQuery(text="email writing", include_external=False)
    report = searcher.search(query)

    assert len(report.results) >= 2
    # high_match가 description + tags + domain 매칭으로 최고 점수
    assert report.results[0].skill_id == "high_match"
    # relevance 내림차순 정렬 검증
    for i in range(len(report.results) - 1):
        assert report.results[i].relevance_score >= report.results[i + 1].relevance_score


def test_search_domain_filter(tmp_path: Path, schemas_dir: Path) -> None:
    """domain 필터가 적용되면 해당 도메인만 반환된다."""
    searcher, _ = _setup_searcher(tmp_path, schemas_dir, [
        {"id": "data_skill", "name": "Data Skill", "description": "Process data", "domain": "data", "tags": ["processing"]},
        {"id": "writing_skill", "name": "Writing Skill", "description": "Write content", "domain": "writing", "tags": ["content"]},
    ])

    query = SearchQuery(text="skill", domain="data", include_external=False)
    report = searcher.search(query)

    assert all(r.domain == "data" for r in report.results)


def test_search_report_metadata(tmp_path: Path, schemas_dir: Path) -> None:
    """SearchReport에 올바른 메타데이터가 포함된다."""
    searcher, _ = _setup_searcher(tmp_path, schemas_dir, [
        {"id": "test_skill", "name": "Test", "description": "A test skill", "domain": "test", "tags": ["test"]},
    ])

    query = SearchQuery(text="test", include_external=False)
    report = searcher.search(query)

    assert report.query is query
    assert report.registry_hits >= 0
    assert report.external_hits == 0
    assert report.timestamp is not None
    assert report.total_scanned >= 0
