"""Cambrian 스킬 흡수기."""

import logging
import shutil
from pathlib import Path

from engine.exceptions import (
    SecurityViolationError,
    SkillLoadError,
    SkillNotFoundError,
    SkillValidationError,
    SymlinkSecurityError,
)
from engine.loader import SkillLoader
from engine.models import Skill
from engine.registry import SkillRegistry
from engine.security import SecurityScanner
from engine.validator import SkillValidator

logger = logging.getLogger(__name__)


class SkillAbsorber:
    """외부 스킬을 검증·보안 검사 후 skill_pool/에 흡수하고 Registry에 등록한다."""

    def __init__(
        self,
        schemas_dir: str | Path,
        skill_pool_dir: str | Path,
        registry: SkillRegistry,
    ):
        """흡수기를 초기화한다.

        Args:
            schemas_dir: JSON Schema 디렉토리 경로
            skill_pool_dir: 흡수된 스킬을 저장할 디렉토리 경로
            registry: 스킬 등록용 SkillRegistry 인스턴스
        """
        self._validator = SkillValidator(schemas_dir)
        self._loader = SkillLoader(schemas_dir)
        self._scanner = SecurityScanner()
        self._pool_dir = Path(skill_pool_dir)
        self._pool_dir.mkdir(parents=True, exist_ok=True)
        self._registry = registry

    def absorb(self, source_path: str | Path) -> Skill:
        """외부 스킬을 검증·흡수한다.

        Args:
            source_path: 외부 스킬 디렉토리 경로

        Returns:
            흡수되어 skill_pool/에 복사되고 Registry에 등록된 Skill 객체

        Raises:
            SkillLoadError: 소스 경로가 존재하지 않을 때
            SkillValidationError: 스킬 포맷 검증 실패 시
            SecurityViolationError: 보안 검사 위반 시
        """
        source = Path(source_path)
        if not source.exists():
            raise SkillLoadError(str(source), "Source path does not exist")

        validation_result = self._validator.validate(source)
        if not validation_result.valid:
            raise SkillValidationError(str(source), validation_result.errors)

        loaded_skill = self._loader.load(source)
        violations = self._scanner.scan_skill(
            source,
            needs_network=loaded_skill.runtime.needs_network,
        )
        if violations:
            raise SecurityViolationError(str(source), violations)

        self._verify_no_symlinks(source)

        destination = self._pool_dir / loaded_skill.id
        if destination.exists():
            shutil.rmtree(destination)

        shutil.copytree(source, destination)

        absorbed_skill = self._loader.load(destination)
        self._registry.register(absorbed_skill)
        logger.info("Absorbed skill '%s' into %s", absorbed_skill.id, destination)

        return absorbed_skill

    def is_absorbed(self, skill_id: str) -> bool:
        """해당 skill_id가 이미 흡수되었는지 확인한다.

        Args:
            skill_id: 확인할 스킬 ID

        Returns:
            True면 이미 흡수됨
        """
        return (self._pool_dir / skill_id).exists()

    @staticmethod
    def _verify_no_symlinks(source_root: Path) -> None:
        """소스 디렉토리 내 symlink를 전수 검사한다.

        Args:
            source_root: 검사할 스킬 디렉토리 루트

        Raises:
            SymlinkSecurityError: symlink가 소스 루트 바깥을 가리킬 때
        """
        resolved_root = source_root.resolve()
        for p in source_root.rglob("*"):
            if p.is_symlink():
                raise SymlinkSecurityError(p, p.resolve())
            try:
                p.resolve().relative_to(resolved_root)
            except ValueError:
                raise SymlinkSecurityError(p, p.resolve())

    def remove(self, skill_id: str) -> None:
        """흡수된 스킬을 삭제하고 Registry에서도 제거한다.

        Args:
            skill_id: 삭제할 스킬 ID

        Raises:
            SkillNotFoundError: 해당 ID가 없을 때
        """
        destination = self._pool_dir / skill_id
        if not destination.exists():
            raise SkillNotFoundError(skill_id)

        shutil.rmtree(destination)
        self._registry.unregister(skill_id)
