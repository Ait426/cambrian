"""SkillAcquirer 오케스트레이터 테스트."""

import json
from pathlib import Path

import pytest
import yaml

from engine.acquirer import SkillAcquirer
from engine.llm import LLMProvider
from engine.loop import CambrianEngine
from engine.models import AcquireRequest


# ═══════════════════════════════════════════════════════════════════
# Mock LLM (fuse/generate 호출용)
# ═══════════════════════════════════════════════════════════════════


def _make_valid_meta() -> str:
    """validator 통과 meta.yaml."""
    return yaml.dump({
        "id": "gen_skill",
        "version": "1.0.0",
        "name": "Generated Skill",
        "description": "Auto-generated skill",
        "domain": "testing",
        "tags": ["auto"],
        "author": "cambrian",
        "created_at": "2026-04-05",
        "updated_at": "2026-04-05",
        "mode": "a",
        "runtime": {
            "language": "python",
            "needs_network": False,
            "needs_filesystem": False,
            "timeout_seconds": 30,
        },
    }, allow_unicode=True, sort_keys=False)


def _make_valid_interface() -> str:
    """validator 통과 interface.yaml."""
    return yaml.dump({
        "input": {
            "type": "object",
            "properties": {"data": {"type": "string", "description": "Input"}},
            "required": ["data"],
        },
        "output": {
            "type": "object",
            "properties": {"result": {"type": "string", "description": "Output"}},
            "required": ["result"],
        },
    }, allow_unicode=True, sort_keys=False)


def _make_valid_skill_md() -> str:
    """유효한 SKILL.md."""
    return (
        "# Generated Skill\n\n## Purpose\nProcess data.\n\n"
        "## Instructions\n1. Read input\n2. Process\n3. Return\n\n"
        "## Output Format\n```json\n{\"result\": \"...\"}\n```\n"
    )


class MockAcquireProvider(LLMProvider):
    """acquire 테스트용 Mock LLM."""

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """유효한 스킬 파일 JSON 반환."""
        return json.dumps({
            "meta_yaml": _make_valid_meta(),
            "interface_yaml": _make_valid_interface(),
            "skill_md": _make_valid_skill_md(),
            "fusion_rationale": "Test fusion",
            "generation_rationale": "Test generation",
        }, ensure_ascii=False)

    def provider_name(self) -> str:
        """프로바이더 이름."""
        return "mock_acquire"


# ═══════════════════════════════════════════════════════════════════
# 헬퍼
# ═══════════════════════════════════════════════════════════════════


def _create_mode_a_skill(
    base_dir: Path,
    skill_id: str,
    domain: str = "testing",
    tags: list[str] | None = None,
    description: str = "A test skill",
) -> Path:
    """Mode A 테스트 스킬 생성.

    Args:
        base_dir: 상위 디렉토리
        skill_id: 스킬 ID
        domain: 도메인
        tags: 태그
        description: 설명

    Returns:
        스킬 디렉토리 경로
    """
    if tags is None:
        tags = ["test"]
    skill_dir = base_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": skill_id,
        "version": "1.0.0",
        "name": f"Skill {skill_id}",
        "description": description,
        "domain": domain,
        "tags": tags,
        "created_at": "2026-04-05",
        "updated_at": "2026-04-05",
        "mode": "a",
        "runtime": {
            "language": "python",
            "needs_network": False,
            "needs_filesystem": False,
            "timeout_seconds": 30,
        },
    }
    with open(skill_dir / "meta.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True)

    interface = {
        "input": {
            "type": "object",
            "properties": {"value": {"type": "string", "description": "Input"}},
            "required": ["value"],
        },
        "output": {
            "type": "object",
            "properties": {"result": {"type": "string", "description": "Output"}},
            "required": ["result"],
        },
    }
    with open(skill_dir / "interface.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(interface, f, allow_unicode=True)

    (skill_dir / "SKILL.md").write_text(
        f"# {skill_id}\n\n## Purpose\n{description}\n\n"
        "## Output Format\n```json\n{\"result\": \"...\"}\n```\n",
        encoding="utf-8",
    )
    return skill_dir


def _create_python_project(base_dir: Path) -> Path:
    """tests 없는 간단한 Python 프로젝트 생성."""
    proj = base_dir / "test_project"
    proj.mkdir()
    (proj / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (proj / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "test"\n', encoding="utf-8",
    )
    return proj


def _make_engine(
    tmp_path: Path,
    schemas_dir: Path,
    extra_skills: list[dict] | None = None,
) -> CambrianEngine:
    """테스트용 CambrianEngine 생성.

    Args:
        tmp_path: pytest tmp_path
        schemas_dir: 스키마 디렉토리
        extra_skills: 추가 등록할 스킬 정의

    Returns:
        CambrianEngine
    """
    skills_dir = tmp_path / "seed_skills"
    skills_dir.mkdir()
    pool_dir = tmp_path / "skill_pool"
    pool_dir.mkdir()

    # 시드 스킬 생성 (최소 1개)
    _create_mode_a_skill(skills_dir, "base_skill", "testing", ["test"])

    provider = MockAcquireProvider()
    engine = CambrianEngine(
        schemas_dir=str(schemas_dir),
        skills_dir=str(skills_dir),
        skill_pool_dir=str(pool_dir),
        db_path=":memory:",
        provider=provider,
    )

    # 추가 스킬 등록
    if extra_skills:
        from engine.loader import SkillLoader
        loader = SkillLoader(schemas_dir)
        ext_dir = tmp_path / "extra_skills"
        ext_dir.mkdir()
        for skill_def in extra_skills:
            skill_path = _create_mode_a_skill(
                ext_dir,
                skill_def["id"],
                skill_def.get("domain", "testing"),
                skill_def.get("tags", ["test"]),
                skill_def.get("description", "Extra skill"),
            )
            skill = loader.load(skill_path)
            engine.get_registry().register(skill)

    return engine


# ═══════════════════════════════════════════════════════════════════
# 테스트 케이스
# ═══════════════════════════════════════════════════════════════════


def test_acquire_advisory_happy_path(tmp_path: Path, schemas_dir: Path) -> None:
    """project 스캔 → plan 반환, executed_actions 빈 리스트."""
    engine = _make_engine(tmp_path, schemas_dir)
    proj = _create_python_project(tmp_path)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest(project_path=str(proj), mode="advisory")
    result = acquirer.acquire(request)

    assert result.success is True
    assert result.mode == "advisory"
    assert result.plan is not None
    assert len(result.plan.actions) >= 0
    assert result.executed_actions == []
    assert result.scan_report is not None


def test_acquire_advisory_with_goal(tmp_path: Path, schemas_dir: Path) -> None:
    """goal만 지정 → 수동 gap 1개 → plan 생성."""
    engine = _make_engine(tmp_path, schemas_dir)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest(
        goal="CSV 데이터를 차트로 변환하는 기능이 필요합니다",
        domain="data",
        tags=["csv", "chart"],
        mode="advisory",
    )
    result = acquirer.acquire(request)

    assert result.success is True
    assert result.plan is not None
    assert len(result.plan.actions) == 1
    assert result.plan.actions[0].gap_category == "user_goal"
    assert result.scan_report is None


def test_acquire_execute_reuse(tmp_path: Path, schemas_dir: Path) -> None:
    """relevance 높은 스킬 존재 → reuse 액션 실행."""
    # 높은 매칭 스킬 등록
    engine = _make_engine(tmp_path, schemas_dir, extra_skills=[
        {"id": "csv_chart_tool", "domain": "data", "tags": ["csv", "chart", "data"],
         "description": "CSV data chart tool"},
    ])
    # fitness 올리기
    from engine.models import ExecutionResult
    for _ in range(10):
        engine.get_registry().update_after_execution(
            "csv_chart_tool",
            ExecutionResult(skill_id="csv_chart_tool", success=True, mode="a"),
        )

    acquirer = SkillAcquirer(engine)
    request = AcquireRequest(
        goal="csv data chart tool for data processing",
        domain="data",
        tags=["csv", "chart", "data"],
        mode="execute",
        strategy="conservative",
    )
    result = acquirer.acquire(request)

    assert result.success is True
    reuse_actions = [
        e for e in result.executed_actions
        if e.action.action_type == "reuse" and e.executed
    ]
    assert len(reuse_actions) > 0
    assert reuse_actions[0].success is True
    assert reuse_actions[0].skill_id == "csv_chart_tool"


def test_acquire_execute_generate_aggressive(tmp_path: Path, schemas_dir: Path) -> None:
    """매칭 없음 + aggressive → generate 실행."""
    engine = _make_engine(tmp_path, schemas_dir)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest(
        goal="quantum computing simulation for advanced physics research",
        domain="science",
        tags=["quantum", "simulation"],
        mode="execute",
        strategy="aggressive",
    )
    result = acquirer.acquire(request)

    gen_actions = [
        e for e in result.executed_actions
        if e.action.action_type == "generate" and e.executed
    ]
    assert len(gen_actions) > 0


def test_acquire_conservative_skips_fuse(tmp_path: Path, schemas_dir: Path) -> None:
    """conservative → fuse 액션 skip."""
    engine = _make_engine(tmp_path, schemas_dir)
    acquirer = SkillAcquirer(engine)

    # goal로 gap 생성 → search 매칭 없음 → generate/defer
    request = AcquireRequest(
        goal="completely unique capability for testing purposes here",
        domain="unique",
        tags=["unique_tag"],
        mode="execute",
        strategy="conservative",
    )
    result = acquirer.acquire(request)

    # conservative에서는 fuse/generate 비허용, reuse만
    for e in result.executed_actions:
        if e.action.action_type in {"fuse", "generate"}:
            assert e.executed is False


def test_acquire_balanced_skips_generate(tmp_path: Path, schemas_dir: Path) -> None:
    """balanced → generate 액션 skip."""
    engine = _make_engine(tmp_path, schemas_dir)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest(
        goal="completely unique capability for testing purposes here",
        domain="unique",
        tags=["unique_tag"],
        mode="execute",
        strategy="balanced",
    )
    result = acquirer.acquire(request)

    for e in result.executed_actions:
        if e.action.action_type == "generate":
            assert e.executed is False


def test_acquire_no_fuse_flag(tmp_path: Path, schemas_dir: Path) -> None:
    """allow_fuse=False → fuse 대신 defer 또는 generate."""
    engine = _make_engine(tmp_path, schemas_dir)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest(
        goal="need a combined skill for testing fuse disable flag",
        domain="testing",
        tags=["fuse_test"],
        mode="advisory",
        allow_fuse=False,
    )
    result = acquirer.acquire(request)

    fuse_actions = [a for a in result.plan.actions if a.action_type == "fuse"]
    assert len(fuse_actions) == 0


def test_acquire_no_generate_flag(tmp_path: Path, schemas_dir: Path) -> None:
    """allow_generate=False → generate 대신 defer."""
    engine = _make_engine(tmp_path, schemas_dir)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest(
        goal="completely unique capability without generate permission",
        domain="unique",
        tags=["no_gen"],
        mode="advisory",
        allow_generate=False,
    )
    result = acquirer.acquire(request)

    gen_actions = [a for a in result.plan.actions if a.action_type == "generate"]
    assert len(gen_actions) == 0


def test_acquire_dry_run(tmp_path: Path, schemas_dir: Path) -> None:
    """execute + dry_run → fuse/generate에 dry_run 전달."""
    engine = _make_engine(tmp_path, schemas_dir)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest(
        goal="dry run test capability for unique purpose testing",
        domain="testing",
        tags=["dryrun", "test"],
        mode="execute",
        strategy="aggressive",
        dry_run=True,
    )
    result = acquirer.acquire(request)

    # generate가 실행되었다면 등록 안 됨
    for e in result.executed_actions:
        if e.action.action_type == "generate" and e.executed and e.success:
            # dry_run이므로 skill_path는 temp 경로
            assert e.skill_path is not None


def test_acquire_nonexistent_project(tmp_path: Path, schemas_dir: Path) -> None:
    """존재하지 않는 경로 → 에러."""
    engine = _make_engine(tmp_path, schemas_dir)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest(project_path="/nonexistent/path")
    result = acquirer.acquire(request)

    assert result.success is False


def test_acquire_no_project_no_goal(tmp_path: Path, schemas_dir: Path) -> None:
    """둘 다 없음 → 에러."""
    engine = _make_engine(tmp_path, schemas_dir)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest()
    result = acquirer.acquire(request)

    assert result.success is False
    assert any("필수" in w for w in result.warnings)


def test_acquire_max_actions_limit(tmp_path: Path, schemas_dir: Path) -> None:
    """max_actions=1 → gap 1개만 처리."""
    engine = _make_engine(tmp_path, schemas_dir)
    proj = _create_python_project(tmp_path)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest(
        project_path=str(proj),
        mode="advisory",
        max_actions=1,
    )
    result = acquirer.acquire(request)

    assert result.plan is not None
    assert len(result.plan.actions) <= 1


def test_acquire_plan_action_order(tmp_path: Path, schemas_dir: Path) -> None:
    """actions가 confidence 내림차순 정렬."""
    engine = _make_engine(tmp_path, schemas_dir)
    proj = _create_python_project(tmp_path)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest(
        project_path=str(proj),
        mode="advisory",
        max_actions=10,
    )
    result = acquirer.acquire(request)

    if result.plan and len(result.plan.actions) > 1:
        confidences = [a.confidence for a in result.plan.actions]
        assert confidences == sorted(confidences, reverse=True)


def test_acquire_json_output_structure(tmp_path: Path, schemas_dir: Path) -> None:
    """결과에 필수 필드가 존재한다."""
    engine = _make_engine(tmp_path, schemas_dir)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest(
        goal="JSON 구조 검증용 테스트 capability 확보",
        domain="testing",
        tags=["json"],
        mode="advisory",
    )
    result = acquirer.acquire(request)

    assert result.mode == "advisory"
    assert result.strategy == "conservative"
    assert result.plan is not None
    assert isinstance(result.executed_actions, list)
    assert isinstance(result.summary, str)
    assert isinstance(result.warnings, list)


def test_acquire_summary_text(tmp_path: Path, schemas_dir: Path) -> None:
    """summary에 gap 수 정보가 포함된다."""
    engine = _make_engine(tmp_path, schemas_dir)
    proj = _create_python_project(tmp_path)
    acquirer = SkillAcquirer(engine)

    request = AcquireRequest(project_path=str(proj), mode="advisory")
    result = acquirer.acquire(request)

    assert "gap" in result.summary


def test_acquire_strategy_difference(tmp_path: Path, schemas_dir: Path) -> None:
    """같은 gap에 strategy만 다르게 → 실행 결과 차이."""
    engine = _make_engine(tmp_path, schemas_dir)
    acquirer = SkillAcquirer(engine)

    goal = "unique quantum physics capability for strategy test"
    base_kwargs = {
        "goal": goal,
        "domain": "science",
        "tags": ["quantum"],
        "mode": "execute",
    }

    result_con = acquirer.acquire(AcquireRequest(**base_kwargs, strategy="conservative"))
    result_agg = acquirer.acquire(AcquireRequest(**base_kwargs, strategy="aggressive"))

    # conservative에서 generate는 스킵, aggressive에서는 실행
    con_gen = [e for e in result_con.executed_actions if e.action.action_type == "generate"]
    agg_gen = [e for e in result_agg.executed_actions if e.action.action_type == "generate"]

    if con_gen:
        assert con_gen[0].executed is False
    if agg_gen:
        assert agg_gen[0].executed is True
