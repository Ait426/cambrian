"""SkillFuser 스킬 융합 테스트."""

import json
from pathlib import Path

import pytest
import yaml

from conftest import create_valid_skill
from engine.fuser import SkillFuser
from engine.loader import SkillLoader
from engine.llm import LLMProvider
from engine.models import FuseRequest
from engine.registry import SkillRegistry
from engine.security import SecurityScanner
from engine.validator import SkillValidator


# ═══════════════════════════════════════════════════════════════════
# Mock LLM
# ═══════════════════════════════════════════════════════════════════


def _make_valid_meta(skill_id: str = "fused_skill") -> str:
    """validator 통과 가능한 meta.yaml 문자열 생성."""
    return yaml.dump({
        "id": skill_id,
        "version": "1.0.0",
        "name": "Fused Skill",
        "description": "A fused skill for testing",
        "domain": "testing",
        "tags": ["fuse", "test"],
        "author": "cambrian-fuser",
        "created_at": "2026-04-04",
        "updated_at": "2026-04-04",
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
        "# Fused Skill\n\n"
        "## Purpose\nThis skill combines data cleaning and chart generation.\n\n"
        "## Instructions\n"
        "1. Parse the input data\n"
        "2. Clean and process the data\n"
        "3. Generate the output\n\n"
        "## Output Format\n"
        "```json\n"
        '{"result": "processed output"}\n'
        "```\n"
    )


class MockFuseProvider(LLMProvider):
    """fuse 테스트용 Mock LLM."""

    def __init__(self, response: dict | None = None, fail: bool = False) -> None:
        """초기화.

        Args:
            response: 반환할 JSON dict. None이면 기본값.
            fail: True면 예외 발생.
        """
        self._response = response
        self._fail = fail
        self.call_count = 0

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """Mock LLM 응답 반환."""
        self.call_count += 1
        if self._fail:
            raise RuntimeError("Mock LLM failure")

        response = self._response or {
            "meta_yaml": _make_valid_meta(),
            "interface_yaml": _make_valid_interface(),
            "skill_md": _make_valid_skill_md(),
            "fusion_rationale": "CHAIN pattern: A의 출력을 B의 입력으로 연결",
        }
        return json.dumps(response, ensure_ascii=False)

    def provider_name(self) -> str:
        """프로바이더 이름 반환."""
        return "mock_fuse"


class MockBadJsonProvider(LLMProvider):
    """항상 비 JSON을 반환하는 Mock LLM."""

    def __init__(self) -> None:
        """초기화."""
        self.call_count = 0

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """비 JSON 응답 반환."""
        self.call_count += 1
        return "This is not JSON at all."

    def provider_name(self) -> str:
        """프로바이더 이름 반환."""
        return "mock_bad"


class MockMissingKeyProvider(LLMProvider):
    """필수 키가 누락된 JSON을 반환하는 Mock LLM."""

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """skill_md 키가 누락된 응답 반환."""
        return json.dumps({
            "meta_yaml": _make_valid_meta(),
            "interface_yaml": _make_valid_interface(),
            # skill_md 누락
            "fusion_rationale": "test",
        })

    def provider_name(self) -> str:
        """프로바이더 이름 반환."""
        return "mock_missing"


# ═══════════════════════════════════════════════════════════════════
# 헬퍼
# ═══════════════════════════════════════════════════════════════════


def create_mode_a_skill(
    base_dir: Path,
    skill_id: str,
    schemas_dir: Path,
    domain: str = "testing",
    tags: list[str] | None = None,
) -> Path:
    """Mode A 테스트 스킬을 생성한다.

    Args:
        base_dir: 상위 디렉토리
        skill_id: 스킬 ID
        schemas_dir: 스키마 디렉토리
        domain: 도메인
        tags: 태그 리스트

    Returns:
        생성된 스킬 디렉토리 경로
    """
    if tags is None:
        tags = ["test"]
    skill_dir = base_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": skill_id,
        "version": "1.0.0",
        "name": f"Test Skill {skill_id}",
        "description": f"A test mode-a skill: {skill_id}",
        "domain": domain,
        "tags": tags,
        "created_at": "2026-04-04",
        "updated_at": "2026-04-04",
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
                "value": {"type": "string", "description": "Input value"},
            },
            "required": ["value"],
        },
        "output": {
            "type": "object",
            "properties": {
                "result": {"type": "string", "description": "Output result"},
            },
            "required": ["result"],
        },
    }
    with open(skill_dir / "interface.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(interface, f, allow_unicode=True)

    (skill_dir / "SKILL.md").write_text(
        f"# {skill_id}\n\n## Purpose\nTest skill for fusion.\n\n"
        f"## Instructions\nProcess the input and return result.\n\n"
        f"## Output Format\n```json\n{{\"result\": \"...\"}}\n```\n",
        encoding="utf-8",
    )

    return skill_dir


def _make_fuser(
    tmp_path: Path,
    schemas_dir: Path,
    provider: LLMProvider | None = None,
) -> tuple[SkillFuser, SkillRegistry, SkillLoader]:
    """테스트용 fuser 환경을 구성한다.

    Args:
        tmp_path: pytest tmp_path
        schemas_dir: 스키마 디렉토리
        provider: LLM 프로바이더

    Returns:
        (fuser, registry, loader) 튜플
    """
    pool_dir = tmp_path / "skill_pool"
    pool_dir.mkdir()
    registry = SkillRegistry(":memory:")
    loader = SkillLoader(schemas_dir)
    validator = SkillValidator(schemas_dir)
    scanner = SecurityScanner()

    # 소스 스킬 2개 생성 + 등록
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    skill_a_dir = create_mode_a_skill(
        skills_dir, "skill_alpha", schemas_dir, "data", ["csv", "clean"],
    )
    skill_a = loader.load(skill_a_dir)
    registry.register(skill_a)

    skill_b_dir = create_mode_a_skill(
        skills_dir, "skill_beta", schemas_dir, "data", ["chart", "viz"],
    )
    skill_b = loader.load(skill_b_dir)
    registry.register(skill_b)

    if provider is None:
        provider = MockFuseProvider()

    fuser = SkillFuser(loader, validator, scanner, registry, pool_dir, provider)
    return fuser, registry, loader


# ═══════════════════════════════════════════════════════════════════
# 테스트 케이스
# ═══════════════════════════════════════════════════════════════════


def test_fuse_happy_path(tmp_path: Path, schemas_dir: Path) -> None:
    """기본 Mode A 2개 → 새 스킬 생성 + 검증 통과 + 등록."""
    fuser, registry, _ = _make_fuser(tmp_path, schemas_dir)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="데이터 정리 후 차트 생성",
    )
    result = fuser.fuse(request)

    assert result.success is True
    assert result.validation_passed is True
    assert result.registered is True
    assert result.skill_id == "skill_alpha_skill_beta"
    assert result.source_ids == ["skill_alpha", "skill_beta"]
    assert result.fusion_rationale != ""
    assert result.output_mode == "a"
    # registry에 등록되었는지 확인
    skill_data = registry.get(result.skill_id)
    assert skill_data["id"] == result.skill_id


def test_fuse_nonexistent_source(tmp_path: Path, schemas_dir: Path) -> None:
    """없는 skill_id → success=False."""
    fuser, _, _ = _make_fuser(tmp_path, schemas_dir)

    request = FuseRequest(
        skill_id_a="nonexistent",
        skill_id_b="skill_beta",
        goal="테스트 융합",
    )
    result = fuser.fuse(request)

    assert result.success is False


def test_fuse_same_skill(tmp_path: Path, schemas_dir: Path) -> None:
    """skill_a == skill_b → success=False."""
    fuser, _, _ = _make_fuser(tmp_path, schemas_dir)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_alpha",
        goal="자기 자신 융합 시도",
    )
    result = fuser.fuse(request)

    assert result.success is False
    assert any("같은 스킬" in w for w in result.warnings)


def test_fuse_fossil_skill(tmp_path: Path, schemas_dir: Path) -> None:
    """fossil 상태 스킬 → success=False."""
    fuser, registry, _ = _make_fuser(tmp_path, schemas_dir)
    registry.update_status("skill_alpha", "fossil")

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="화석 스킬 융합 시도",
    )
    result = fuser.fuse(request)

    assert result.success is False
    assert any("fossil" in w or "화석화된" in w for w in result.warnings)


def test_fuse_no_skill_md(tmp_path: Path, schemas_dir: Path) -> None:
    """SKILL.md가 없는 스킬 → 호환성 검사 실패."""
    pool_dir = tmp_path / "skill_pool"
    pool_dir.mkdir()
    registry = SkillRegistry(":memory:")
    loader = SkillLoader(schemas_dir)
    validator = SkillValidator(schemas_dir)
    scanner = SecurityScanner()

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Mode A 스킬 (SKILL.md 존재하지만 로드 후 None으로 패치)
    skill_a_dir = create_mode_a_skill(
        skills_dir, "skill_with_md", schemas_dir,
    )
    skill_a = loader.load(skill_a_dir)
    registry.register(skill_a)

    # Mode A 스킬 (SKILL.md 삭제 → loader에서 SkillValidationError)
    skill_b_dir = create_mode_a_skill(
        skills_dir, "skill_no_md", schemas_dir,
    )
    # SKILL.md 있는 상태로 로드·등록 후 파일 삭제하여
    # fuser가 re-load 시 SkillValidationError 발생하게 함
    skill_b = loader.load(skill_b_dir)
    registry.register(skill_b)
    (skill_b_dir / "SKILL.md").unlink()

    fuser = SkillFuser(
        loader, validator, scanner, registry, pool_dir, MockFuseProvider(),
    )
    request = FuseRequest(
        skill_id_a="skill_with_md",
        skill_id_b="skill_no_md",
        goal="SKILL.md 없는 스킬 융합",
    )

    # loader.load()에서 SkillValidationError 발생
    from engine.exceptions import SkillValidationError
    with pytest.raises(SkillValidationError):
        fuser.fuse(request)


def test_fuse_auto_output_id(tmp_path: Path, schemas_dir: Path) -> None:
    """output_id=None → 자동 생성 ID."""
    fuser, _, _ = _make_fuser(tmp_path, schemas_dir)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="자동 ID 테스트",
    )
    result = fuser.fuse(request)

    assert result.success is True
    assert result.skill_id == "skill_alpha_skill_beta"


def test_fuse_custom_output_id(tmp_path: Path, schemas_dir: Path) -> None:
    """output_id 지정 → 해당 ID 사용."""
    fuser, _, _ = _make_fuser(tmp_path, schemas_dir)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="커스텀 ID 테스트",
        output_id="custom_fused",
    )
    result = fuser.fuse(request)

    assert result.success is True
    assert result.skill_id == "custom_fused"


def test_fuse_duplicate_output_id(tmp_path: Path, schemas_dir: Path) -> None:
    """이미 존재하는 ID → 접미사 _2 추가."""
    fuser, registry, loader = _make_fuser(tmp_path, schemas_dir)

    # 첫 번째 fuse
    request1 = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="첫 번째 융합",
    )
    result1 = fuser.fuse(request1)
    assert result1.success is True
    assert result1.skill_id == "skill_alpha_skill_beta"

    # 두 번째 fuse (동일 ID 충돌)
    request2 = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="두 번째 융합",
    )
    result2 = fuser.fuse(request2)
    assert result2.success is True
    assert result2.skill_id == "skill_alpha_skill_beta_2"


def test_fuse_dry_run(tmp_path: Path, schemas_dir: Path) -> None:
    """dry_run=True → 등록 안 됨."""
    fuser, registry, _ = _make_fuser(tmp_path, schemas_dir)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="드라이런 테스트",
        dry_run=True,
    )
    result = fuser.fuse(request)

    assert result.success is True
    assert result.registered is False
    assert result.dry_run is True
    assert result.validation_passed is True
    # temp_dir이 유지되어야 함
    assert Path(result.skill_path).exists()


def test_fuse_validation_fail(tmp_path: Path, schemas_dir: Path) -> None:
    """LLM이 잘못된 interface 생성 → validator 실패."""
    # meta는 guardrail이 복구하므로, interface를 깨뜨려서 검증 실패 유발
    bad_response = {
        "meta_yaml": _make_valid_meta(),
        "interface_yaml": "not_valid_yaml: [broken: {",
        "skill_md": _make_valid_skill_md(),
        "fusion_rationale": "test",
    }
    provider = MockFuseProvider(response=bad_response)
    fuser, _, _ = _make_fuser(tmp_path, schemas_dir, provider)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="검증 실패 테스트",
    )
    result = fuser.fuse(request)

    assert result.success is False
    assert result.validation_passed is False


def test_fuse_llm_malformed_response(tmp_path: Path, schemas_dir: Path) -> None:
    """LLM이 비 JSON 응답 → retry → 2회 실패 → success=False."""
    provider = MockBadJsonProvider()
    fuser, _, _ = _make_fuser(tmp_path, schemas_dir, provider)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="비정상 LLM 응답 테스트",
    )
    result = fuser.fuse(request)

    assert result.success is False
    assert provider.call_count == 2  # 1차 + 1회 retry


def test_fuse_llm_missing_key(tmp_path: Path, schemas_dir: Path) -> None:
    """LLM 응답에 skill_md 키 누락 → success=False."""
    provider = MockMissingKeyProvider()
    fuser, _, _ = _make_fuser(tmp_path, schemas_dir, provider)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="키 누락 테스트",
    )
    result = fuser.fuse(request)

    assert result.success is False


def test_fuse_meta_guardrail(tmp_path: Path, schemas_dir: Path) -> None:
    """LLM이 잘못된 id/mode 생성 → guardrail이 교정."""
    bad_meta = yaml.dump({
        "id": "wrong_id",
        "version": "9.9.9",
        "name": "Wrong Name",
        "description": "Wrong",
        "domain": "wrong",
        "tags": ["wrong"],
        "mode": "b",  # 잘못된 모드
        "runtime": {
            "language": "python",
            "needs_network": True,  # 잘못 — guardrail이 False로 교정
            "needs_filesystem": False,
            "timeout_seconds": 30,
        },
    }, allow_unicode=True)

    response = {
        "meta_yaml": bad_meta,
        "interface_yaml": _make_valid_interface(),
        "skill_md": _make_valid_skill_md(),
        "fusion_rationale": "test guardrail",
    }
    provider = MockFuseProvider(response=response)
    fuser, _, _ = _make_fuser(tmp_path, schemas_dir, provider)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="guardrail 교정 테스트",
        output_id="guardrail_test",
    )
    result = fuser.fuse(request)

    assert result.success is True
    assert result.skill_id == "guardrail_test"
    # guardrail이 교정했는지 확인
    skill_path = Path(result.skill_path)
    meta = yaml.safe_load((skill_path / "meta.yaml").read_text(encoding="utf-8"))
    assert meta["id"] == "guardrail_test"
    assert meta["mode"] == "a"
    assert meta["version"] == "1.0.0"
    assert meta["runtime"]["needs_network"] is False


def test_fuse_provenance_file(tmp_path: Path, schemas_dir: Path) -> None:
    """_cambrian_fuse.json 파일 생성 + 내용 검증."""
    fuser, _, _ = _make_fuser(tmp_path, schemas_dir)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="provenance 테스트",
    )
    result = fuser.fuse(request)

    assert result.success is True
    provenance_path = Path(result.skill_path) / "_cambrian_fuse.json"
    assert provenance_path.exists()

    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["parent_ids"] == ["skill_alpha", "skill_beta"]
    assert provenance["fusion_goal"] == "provenance 테스트"
    assert "fused_at" in provenance


def test_fuse_goal_too_short(tmp_path: Path, schemas_dir: Path) -> None:
    """goal < 5자 → ValueError."""
    fuser, _, _ = _make_fuser(tmp_path, schemas_dir)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="짧",
    )
    with pytest.raises(ValueError, match="5자"):
        fuser.fuse(request)


def test_fuse_registered_in_registry(tmp_path: Path, schemas_dir: Path) -> None:
    """등록 후 registry.get(output_id) 성공."""
    fuser, registry, _ = _make_fuser(tmp_path, schemas_dir)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="레지스트리 등록 검증",
        output_id="reg_check",
    )
    result = fuser.fuse(request)

    assert result.success is True
    assert result.registered is True
    skill_data = registry.get("reg_check")
    assert skill_data["id"] == "reg_check"
    assert skill_data["mode"] == "a"


def test_fuse_llm_failure(tmp_path: Path, schemas_dir: Path) -> None:
    """LLM 호출 자체가 실패 → success=False."""
    provider = MockFuseProvider(fail=True)
    fuser, _, _ = _make_fuser(tmp_path, schemas_dir, provider)

    request = FuseRequest(
        skill_id_a="skill_alpha",
        skill_id_b="skill_beta",
        goal="LLM 실패 테스트",
    )
    result = fuser.fuse(request)

    assert result.success is False
