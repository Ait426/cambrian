"""Cambrian 스킬 로더."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from engine.exceptions import SkillLoadError, SkillValidationError
from engine.models import Skill, SkillLifecycle, SkillRuntime
from engine.validator import SkillValidator

logger = logging.getLogger(__name__)


class SkillLoader:
    """스킬 디렉토리에서 Skill 객체를 로드한다."""

    def __init__(self, schemas_dir: str | Path):
        """스킬 로더를 초기화한다.

        Args:
            schemas_dir: JSON Schema 파일이 있는 디렉토리 경로
        """
        self._validator = SkillValidator(schemas_dir)

    def load(self, skill_dir: str | Path) -> Skill:
        """단일 스킬 디렉토리를 로드한다.

        Args:
            skill_dir: 스킬 루트 디렉토리 (meta.yaml이 있는 곳)

        Returns:
            Skill 도메인 객체

        Raises:
            SkillLoadError: 파일 누락, YAML 파싱 실패
            SkillValidationError: schema 검증 실패
        """
        skill_path = Path(skill_dir)
        if not skill_path.exists():
            raise SkillLoadError(str(skill_path), "Skill directory does not exist")
        if not skill_path.is_dir():
            raise SkillLoadError(str(skill_path), "Skill path is not a directory")

        validation_result = self._validator.validate(skill_path)
        meta_path = skill_path / "meta.yaml"

        if not validation_result.valid:
            meta_for_validation = self._parse_yaml(meta_path)
            filtered_errors = self._filter_validation_errors(
                validation_result.errors,
                meta_for_validation,
            )
            if filtered_errors:
                raise SkillValidationError(str(skill_path), filtered_errors)

        meta = self._parse_yaml(meta_path)
        interface = self._parse_yaml(skill_path / "interface.yaml")

        skill_md_path = skill_path / "SKILL.md"
        skill_md_content = (
            skill_md_path.read_text(encoding="utf-8")
            if skill_md_path.exists()
            else None
        )

        runtime = self._build_runtime(meta)
        lifecycle = self._build_lifecycle(meta)

        return Skill(
            id=meta["id"],
            version=meta["version"],
            name=meta["name"],
            description=meta["description"],
            domain=meta["domain"],
            tags=meta["tags"],
            mode=meta["mode"],
            runtime=runtime,
            lifecycle=lifecycle,
            skill_path=skill_path.resolve(),
            interface_input=interface.get("input", {}),
            interface_output=interface.get("output", {}),
            skill_md_content=skill_md_content,
            author=meta.get("author"),
            license=meta.get("license"),
            created_at=meta.get("created_at"),
            updated_at=meta.get("updated_at"),
        )

    def load_directory(self, base_dir: str | Path) -> list[Skill]:
        """디렉토리 안의 모든 스킬을 로드한다.

        Args:
            base_dir: 스킬들이 들어있는 상위 디렉토리
                (예: skills/ 또는 skill_pool/)

        Returns:
            로드 성공한 Skill 객체 리스트.
            개별 스킬 로드 실패 시 해당 스킬은 건너뛰고 warning 로깅.
        """
        base_path = Path(base_dir)
        skills: list[Skill] = []

        if not base_path.exists() or not base_path.is_dir():
            return skills

        for sub_dir in sorted(path for path in base_path.iterdir() if path.is_dir()):
            if not (sub_dir / "meta.yaml").exists():
                continue

            try:
                skills.append(self.load(sub_dir))
            except (SkillLoadError, SkillValidationError) as exc:
                logger.warning("Failed to load skill from '%s': %s", sub_dir, exc)

        return skills

    def _parse_yaml(self, file_path: Path) -> dict:
        """YAML 파일을 파싱한다.

        Args:
            file_path: 파싱할 YAML 파일 경로

        Returns:
            파싱된 딕셔너리

        Raises:
            SkillLoadError: 파일이 없거나 YAML 파싱 실패
        """
        if not file_path.exists():
            raise SkillLoadError(str(file_path), f"Missing required file: {file_path.name}")

        try:
            with open(file_path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
        except yaml.YAMLError as exc:
            raise SkillLoadError(str(file_path), f"YAML parse error: {exc}") from exc
        except OSError as exc:
            raise SkillLoadError(str(file_path), f"File read error: {exc}") from exc

        if data is None:
            return {}

        if not isinstance(data, dict):
            raise SkillLoadError(
                str(file_path),
                f"Expected YAML object, got {type(data).__name__}",
            )

        return data

    def _build_runtime(self, meta: dict) -> SkillRuntime:
        """meta dict의 runtime 섹션에서 SkillRuntime 객체를 생성한다.

        Args:
            meta: meta.yaml 파싱 결과

        Returns:
            SkillRuntime 객체
        """
        runtime = meta.get("runtime")
        if not isinstance(runtime, dict):
            return SkillRuntime(language="python")

        return SkillRuntime(
            language=runtime.get("language", "python"),
            needs_network=runtime.get("needs_network", False),
            needs_filesystem=runtime.get("needs_filesystem", False),
            timeout_seconds=runtime.get("timeout_seconds", 30),
        )

    def _build_lifecycle(self, meta: dict) -> SkillLifecycle:
        """meta dict의 lifecycle 섹션에서 SkillLifecycle 객체를 생성한다.

        Args:
            meta: meta.yaml 파싱 결과

        Returns:
            SkillLifecycle 객체
        """
        lifecycle = meta.get("lifecycle")
        if not isinstance(lifecycle, dict):
            return SkillLifecycle()

        return SkillLifecycle(
            status=lifecycle.get("status", "newborn"),
            fitness_score=lifecycle.get("fitness_score", 0.0),
            total_executions=lifecycle.get("total_executions", 0),
            successful_executions=lifecycle.get("successful_executions", 0),
            last_used=lifecycle.get("last_used"),
            crystallized_at=lifecycle.get("crystallized_at"),
        )

    def _filter_validation_errors(self, errors: list[str], meta: dict) -> list[str]:
        """로더 레벨에서 허용 가능한 검증 에러를 필터링한다.

        Args:
            errors: validator가 반환한 에러 목록
            meta: meta.yaml 파싱 결과

        Returns:
            필터링 후 남은 에러 목록
        """
        filtered_errors: list[str] = []
        mode = meta.get("mode")

        for error in errors:
            if error == "[meta.yaml] 필수 필드 누락: 'lifecycle'":
                continue
            if mode == "a" and error == "[SKILL.md] 필수 파일이 존재하지 않음":
                continue
            filtered_errors.append(error)

        return filtered_errors
