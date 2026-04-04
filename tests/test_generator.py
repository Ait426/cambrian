"""SkillGenerator 스킬 자동 생성 테스트."""

import json
from pathlib import Path

import pytest
import yaml

from engine.fuser import SkillFuser
from engine.generator import SkillGenerator
from engine.loader import SkillLoader
from engine.llm import LLMProvider
from engine.models import GenerateRequest
from engine.registry import SkillRegistry
from engine.search import SkillSearcher
from engine.security import SecurityScanner
from engine.validator import SkillValidator


# ═══════════════════════════════════════════════════════════════════
# Mock LLM
# ═══════════════════════════════════════════════════════════════════


def _make_valid_meta(skill_id: str = "gen_skill") -> str:
    """validator 통과 가능한 meta.yaml 문자열 생성."""
    return yaml.dump({
        "id": skill_id,
        "version": "1.0.0",
        "name": "Generated Skill",
        "description": "An automatically generated skill",
        "domain": "testing",
        "tags": ["gen", "test"],
        "author": "cambrian-generator",
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
    """validator 통과 가능한 interface.yaml 문자열 생성."""
    return yaml.dump({
        "input": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Input data"},
            },
            "required": ["data"],
        },
        "output": {
            "type": "object",
            "properties": {
                "result": {"type": "string", "description": "Output result"},
            },
            "required": ["result"],
        },
    }, allow_unicode=True, sort_keys=False)


def _make_valid_skill_md() -> str:
    """유효한 SKILL.md 내용 생성."""
    return (
        "# Generated Skill\n\n"
        "## Purpose\nThis skill processes input data and returns a result.\n\n"
        "## Instructions\n"
        "1. Read the input data\n"
        "2. Process accordingly\n"
        "3. Return structured output\n\n"
        "## Output Format\n"
        "```json\n"
        '{"result": "processed output"}\n'
        "```\n\n"
        "## Examples\n"
        "Input: {\"data\": \"hello\"}\n"
        "Output: {\"result\": \"processed: hello\"}\n"
    )


class MockGenerateProvider(LLMProvider):
    """generate 테스트용 Mock LLM."""

    def __init__(
        self,
        response: dict | None = None,
        fail: bool = False,
    ) -> None:
        """초기화."""
        self._response = response
        self._fail = fail
        self.call_count = 0

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """Mock 응답 반환."""
        self.call_count += 1
        if self._fail:
            raise RuntimeError("Mock LLM failure")

        response = self._response or {
            "meta_yaml": _make_valid_meta(),
            "interface_yaml": _make_valid_interface(),
            "skill_md": _make_valid_skill_md(),
            "generation_rationale": "Designed as a simple data processor",
        }
        return json.dumps(response, ensure_ascii=False)

    def provider_name(self) -> str:
        """프로바이더 이름."""
        return "mock_gen"


class MockBadJsonProvider(LLMProvider):
    """항상 비 JSON을 반환하는 Mock LLM."""

    def __init__(self) -> None:
        """초기화."""
        self.call_count = 0

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """비 JSON 반환."""
        self.call_count += 1
        return "This is not JSON."

    def provider_name(self) -> str:
        """프로바이더 이름."""
        return "mock_bad"


class MockMissingKeyProvider(LLMProvider):
    """필수 키 누락 JSON 반환 Mock LLM."""

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """skill_md 키 누락."""
        return json.dumps({
            "meta_yaml": _make_valid_meta(),
            "interface_yaml": _make_valid_interface(),
            # skill_md 누락
            "generation_rationale": "test",
        })

    def provider_name(self) -> str:
        """프로바이더 이름."""
        return "mock_missing"


# ═══════════════════════════════════════════════════════════════════
# 헬퍼
# ═══════════════════════════════════════════════════════════════════


def _create_mode_a_skill(
    base_dir: Path,
    skill_id: str,
    domain: str = "testing",
    tags: list[str] | None = None,
) -> Path:
    """Mode A 테스트 스킬 생성.

    Args:
        base_dir: 상위 디렉토리
        skill_id: 스킬 ID
        domain: 도메인
        tags: 태그

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
        "name": f"Test Skill {skill_id}",
        "description": f"A reference skill: {skill_id}",
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
            "properties": {
                "value": {"type": "string", "description": "Input"},
            },
            "required": ["value"],
        },
        "output": {
            "type": "object",
            "properties": {
                "result": {"type": "string", "description": "Output"},
            },
            "required": ["result"],
        },
    }
    with open(skill_dir / "interface.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(interface, f, allow_unicode=True)

    (skill_dir / "SKILL.md").write_text(
        f"# {skill_id}\n\n## Purpose\nReference skill.\n\n"
        "## Output Format\n```json\n{\"result\": \"...\"}\n```\n",
        encoding="utf-8",
    )
    return skill_dir


def _make_generator(
    tmp_path: Path,
    schemas_dir: Path,
    provider: LLMProvider | None = None,
    register_ref: bool = False,
) -> tuple[SkillGenerator, SkillRegistry, SkillLoader, SkillSearcher]:
    """테스트용 generator 환경 구성.

    Args:
        tmp_path: pytest tmp_path
        schemas_dir: 스키마 디렉토리
        provider: LLM 프로바이더
        register_ref: True면 참고용 스킬 등록

    Returns:
        (generator, registry, loader, searcher) 튜플
    """
    pool_dir = tmp_path / "skill_pool"
    pool_dir.mkdir()
    registry = SkillRegistry(":memory:")
    loader = SkillLoader(schemas_dir)
    validator = SkillValidator(schemas_dir)
    scanner = SecurityScanner()
    searcher = SkillSearcher(registry, loader)

    if register_ref:
        skills_dir = tmp_path / "ref_skills"
        skills_dir.mkdir()
        ref_dir = _create_mode_a_skill(
            skills_dir, "ref_data_tool", "data", ["csv", "chart"],
        )
        ref_skill = loader.load(ref_dir)
        registry.register(ref_skill)

    if provider is None:
        provider = MockGenerateProvider()

    fuser = SkillFuser(loader, validator, scanner, registry, pool_dir, provider)
    generator = SkillGenerator(fuser, registry, loader, searcher, provider)

    return generator, registry, loader, searcher


# ═══════════════════════════════════════════════════════════════════
# 테스트 케이스
# ═══════════════════════════════════════════════════════════════════


def test_generate_mode_a_happy_path(tmp_path: Path, schemas_dir: Path) -> None:
    """기본 Mode A 생성 + 검증 통과 + 등록."""
    gen, registry, _, _ = _make_generator(tmp_path, schemas_dir)

    request = GenerateRequest(
        goal="CSV 파일을 읽어 차트를 생성하는 스킬",
        domain="data",
        tags=["csv", "chart"],
    )
    result = gen.generate(request)

    assert result.success is True
    assert result.validation_passed is True
    assert result.registered is True
    assert result.domain == "data"
    assert result.tags == ["csv", "chart"]
    assert result.output_mode == "a"
    assert result.generation_rationale != ""
    # registry 확인
    skill_data = registry.get(result.skill_id)
    assert skill_data["id"] == result.skill_id


def test_generate_auto_output_id(tmp_path: Path, schemas_dir: Path) -> None:
    """output_id=None → 자동 생성."""
    gen, _, _, _ = _make_generator(tmp_path, schemas_dir)

    request = GenerateRequest(
        goal="데이터 파이프라인 자동화 스킬을 생성합니다",
        domain="data",
        tags=["pipeline"],
    )
    result = gen.generate(request)

    assert result.success is True
    assert result.skill_id == "data_pipeline"


def test_generate_custom_output_id(tmp_path: Path, schemas_dir: Path) -> None:
    """output_id 지정 → 해당 ID 사용."""
    gen, _, _, _ = _make_generator(tmp_path, schemas_dir)

    request = GenerateRequest(
        goal="커스텀 ID로 스킬을 생성하는 테스트입니다",
        domain="testing",
        tags=["custom"],
        output_id="my_custom_skill",
    )
    result = gen.generate(request)

    assert result.success is True
    assert result.skill_id == "my_custom_skill"


def test_generate_duplicate_id(tmp_path: Path, schemas_dir: Path) -> None:
    """중복 ID → 접미사 _2 추가."""
    gen, _, _, _ = _make_generator(tmp_path, schemas_dir)

    request1 = GenerateRequest(
        goal="첫 번째 스킬을 생성하는 테스트입니다",
        domain="data",
        tags=["csv"],
    )
    result1 = gen.generate(request1)
    assert result1.success is True
    assert result1.skill_id == "data_csv"

    request2 = GenerateRequest(
        goal="두 번째 동일 도메인 스킬을 생성합니다",
        domain="data",
        tags=["csv"],
    )
    result2 = gen.generate(request2)
    assert result2.success is True
    assert result2.skill_id == "data_csv_2"


def test_generate_dry_run(tmp_path: Path, schemas_dir: Path) -> None:
    """dry_run=True → 등록 안 됨, temp_dir 유지."""
    gen, _, _, _ = _make_generator(tmp_path, schemas_dir)

    request = GenerateRequest(
        goal="드라이런 테스트용 스킬을 생성합니다",
        domain="testing",
        tags=["dry"],
        dry_run=True,
    )
    result = gen.generate(request)

    assert result.success is True
    assert result.registered is False
    assert result.dry_run is True
    assert result.validation_passed is True
    assert Path(result.skill_path).exists()


def test_generate_validation_fail(tmp_path: Path, schemas_dir: Path) -> None:
    """LLM이 잘못된 interface → validator 실패."""
    bad_response = {
        "meta_yaml": _make_valid_meta(),
        "interface_yaml": "broken: yaml: [invalid",
        "skill_md": _make_valid_skill_md(),
        "generation_rationale": "test",
    }
    provider = MockGenerateProvider(response=bad_response)
    gen, _, _, _ = _make_generator(tmp_path, schemas_dir, provider)

    request = GenerateRequest(
        goal="검증 실패 테스트용 스킬을 생성합니다",
        domain="testing",
        tags=["fail"],
    )
    result = gen.generate(request)

    assert result.success is False
    assert result.validation_passed is False


def test_generate_llm_malformed(tmp_path: Path, schemas_dir: Path) -> None:
    """LLM 비JSON 응답 → retry → 2회 실패."""
    provider = MockBadJsonProvider()
    gen, _, _, _ = _make_generator(tmp_path, schemas_dir, provider)

    request = GenerateRequest(
        goal="비정상 LLM 응답 테스트용 스킬입니다",
        domain="testing",
        tags=["bad"],
    )
    result = gen.generate(request)

    assert result.success is False
    assert provider.call_count == 2


def test_generate_llm_missing_key(tmp_path: Path, schemas_dir: Path) -> None:
    """skill_md 키 누락 → 실패."""
    provider = MockMissingKeyProvider()
    gen, _, _, _ = _make_generator(tmp_path, schemas_dir, provider)

    request = GenerateRequest(
        goal="키 누락 테스트용 스킬을 생성합니다",
        domain="testing",
        tags=["missing"],
    )
    result = gen.generate(request)

    assert result.success is False


def test_generate_meta_guardrail(tmp_path: Path, schemas_dir: Path) -> None:
    """id/mode/runtime 강제 교정 검증."""
    bad_meta = yaml.dump({
        "id": "wrong_id",
        "version": "9.9.9",
        "name": "Wrong",
        "description": "Wrong",
        "domain": "wrong",
        "tags": ["wrong"],
        "mode": "b",
        "runtime": {
            "language": "python",
            "needs_network": True,
            "needs_filesystem": False,
            "timeout_seconds": 30,
        },
    }, allow_unicode=True)

    response = {
        "meta_yaml": bad_meta,
        "interface_yaml": _make_valid_interface(),
        "skill_md": _make_valid_skill_md(),
        "generation_rationale": "guardrail test",
    }
    provider = MockGenerateProvider(response=response)
    gen, _, _, _ = _make_generator(tmp_path, schemas_dir, provider)

    request = GenerateRequest(
        goal="guardrail 교정 테스트용 스킬을 생성합니다",
        domain="data",
        tags=["csv"],
        output_id="guard_test",
    )
    result = gen.generate(request)

    assert result.success is True
    meta = yaml.safe_load(
        Path(result.skill_path, "meta.yaml").read_text(encoding="utf-8")
    )
    assert meta["id"] == "guard_test"
    assert meta["mode"] == "a"
    assert meta["version"] == "1.0.0"
    assert meta["runtime"]["needs_network"] is False
    assert meta["domain"] == "data"
    assert meta["tags"] == ["csv"]


def test_generate_provenance_file(tmp_path: Path, schemas_dir: Path) -> None:
    """_cambrian_generate.json 생성 + 내용 검증."""
    gen, _, _, _ = _make_generator(tmp_path, schemas_dir)

    request = GenerateRequest(
        goal="provenance 추적 테스트용 스킬을 생성합니다",
        domain="testing",
        tags=["provenance"],
    )
    result = gen.generate(request)

    assert result.success is True
    prov_path = Path(result.skill_path) / "_cambrian_generate.json"
    assert prov_path.exists()

    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    assert prov["generated_by"] == "cambrian-generator"
    assert prov["goal"] == request.goal
    assert prov["domain"] == "testing"
    assert "generated_at" in prov


def test_generate_unnecessary(tmp_path: Path, schemas_dir: Path) -> None:
    """relevance >= 0.7 스킬 존재 → generate 불필요 판정."""
    # 높은 relevance 매칭이 되도록 참고 스킬 등록
    pool_dir = tmp_path / "skill_pool"
    pool_dir.mkdir()
    registry = SkillRegistry(":memory:")
    loader = SkillLoader(schemas_dir)
    validator = SkillValidator(schemas_dir)
    scanner = SecurityScanner()
    searcher = SkillSearcher(registry, loader)

    # 높은 매칭을 유발하는 스킬 등록
    skills_dir = tmp_path / "ref_skills"
    skills_dir.mkdir()
    ref_dir = _create_mode_a_skill(
        skills_dir, "csv_chart_gen", "data", ["csv", "chart", "data"],
    )
    # description을 goal과 매우 유사하게 설정
    meta_path = ref_dir / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["name"] = "CSV Chart Generator"
    meta["description"] = "CSV data chart generation tool"
    meta_path.write_text(yaml.dump(meta, allow_unicode=True), encoding="utf-8")

    ref_skill = loader.load(ref_dir)
    registry.register(ref_skill)

    # fitness를 높여서 최종 점수 부스트
    from engine.models import ExecutionResult
    for _ in range(10):
        registry.update_after_execution(
            "csv_chart_gen",
            ExecutionResult(skill_id="csv_chart_gen", success=True, mode="a"),
        )

    provider = MockGenerateProvider()
    fuser = SkillFuser(loader, validator, scanner, registry, pool_dir, provider)
    gen = SkillGenerator(fuser, registry, loader, searcher, provider)

    request = GenerateRequest(
        goal="csv data chart generation tool",
        domain="data",
        tags=["csv", "chart", "data"],
    )
    result = gen.generate(request)

    # strong 매칭 존재 → generate 불필요
    assert result.success is False
    assert len(result.existing_alternatives) > 0
    assert any("기존 스킬" in w for w in result.warnings)


def test_generate_skip_search(tmp_path: Path, schemas_dir: Path) -> None:
    """skip_search=True → 판정 스킵, 강제 생성."""
    gen, _, _, _ = _make_generator(
        tmp_path, schemas_dir, register_ref=True,
    )

    request = GenerateRequest(
        goal="reference data tool for csv chart data processing",
        domain="data",
        tags=["csv", "chart"],
        skip_search=True,
    )
    result = gen.generate(request)

    # skip_search이므로 판정 없이 생성 진행
    assert result.success is True
    assert result.existing_alternatives == []


def test_generate_with_references(tmp_path: Path, schemas_dir: Path) -> None:
    """reference_skills 지정 → few-shot 컨텍스트 포함."""
    gen, _, _, _ = _make_generator(
        tmp_path, schemas_dir, register_ref=True,
    )

    request = GenerateRequest(
        goal="참고 스킬 기반으로 새 스킬을 생성합니다",
        domain="testing",
        tags=["ref_test"],
        reference_skills=["ref_data_tool"],
        skip_search=True,
    )
    result = gen.generate(request)

    assert result.success is True
    assert "ref_data_tool" in result.reference_skill_ids


def test_generate_goal_too_short(tmp_path: Path, schemas_dir: Path) -> None:
    """goal < 10자 → 실패."""
    gen, _, _, _ = _make_generator(tmp_path, schemas_dir)

    request = GenerateRequest(
        goal="짧은 목적",
        domain="testing",
        tags=["short"],
    )
    result = gen.generate(request)

    assert result.success is False
    assert any("10자" in w for w in result.warnings)


def test_generate_registered_in_registry(tmp_path: Path, schemas_dir: Path) -> None:
    """등록 후 registry.get(output_id) 성공."""
    gen, registry, _, _ = _make_generator(tmp_path, schemas_dir)

    request = GenerateRequest(
        goal="레지스트리 등록 검증용 스킬을 생성합니다",
        domain="testing",
        tags=["registry"],
        output_id="reg_verify",
    )
    result = gen.generate(request)

    assert result.success is True
    assert result.registered is True
    skill_data = registry.get("reg_verify")
    assert skill_data["id"] == "reg_verify"
    assert skill_data["mode"] == "a"


def test_generate_deploy_reuses_fuser(tmp_path: Path, schemas_dir: Path) -> None:
    """validate_and_deploy가 fuser 인스턴스 메서드인지 검증."""
    gen, _, _, _ = _make_generator(tmp_path, schemas_dir)

    # generator가 fuser를 갖고 있는지 확인
    assert hasattr(gen, "_fuser")
    assert hasattr(gen._fuser, "validate_and_deploy")
    assert callable(gen._fuser.validate_and_deploy)


def test_generate_llm_failure(tmp_path: Path, schemas_dir: Path) -> None:
    """LLM 호출 자체가 실패 → success=False."""
    provider = MockGenerateProvider(fail=True)
    gen, _, _, _ = _make_generator(tmp_path, schemas_dir, provider)

    request = GenerateRequest(
        goal="LLM 호출 실패 테스트용 스킬을 생성합니다",
        domain="testing",
        tags=["fail"],
    )
    result = gen.generate(request)

    assert result.success is False
