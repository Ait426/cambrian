"""Cambrian 스킬 패키지 내보내기/가져오기."""

from __future__ import annotations

import json
import logging
import shutil
import zipfile
from pathlib import Path

from engine.loader import SkillLoader
from engine.registry import SkillRegistry
from engine.security import SecurityScanner

logger = logging.getLogger(__name__)


class SkillPorter:
    """스킬을 .cambrian 패키지로 내보내거나 가져온다."""

    def __init__(
        self,
        loader: SkillLoader,
        registry: SkillRegistry,
        skill_pool_dir: str | Path = "skill_pool",
    ) -> None:
        """초기화.

        Args:
            loader: SkillLoader 인스턴스
            registry: SkillRegistry 인스턴스
            skill_pool_dir: 스킬 풀 디렉토리
        """
        self._loader = loader
        self._registry = registry
        self._pool_dir = Path(skill_pool_dir)
        self._scanner = SecurityScanner()

    def export_skill(self, skill_id: str, output_path: Path) -> Path:
        """스킬을 .cambrian 패키지(zip)로 내보낸다.

        Args:
            skill_id: 내보낼 스킬 ID
            output_path: 출력 디렉토리 경로

        Returns:
            생성된 zip 파일 경로

        Raises:
            FileNotFoundError: 스킬 경로가 존재하지 않을 때
        """
        skill_data = self._registry.get(skill_id)
        skill_path = Path(skill_data["skill_path"])

        if not skill_path.exists():
            raise FileNotFoundError(f"Skill directory not found: {skill_path}")

        output_path = Path(output_path)
        output_path.mkdir(parents=True, exist_ok=True)
        zip_path = output_path / f"{skill_id}.cambrian"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 스킬 파일들
            for file_path in skill_path.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(skill_path)
                    zf.write(file_path, arcname)

            # 메타데이터 (fitness, 실행 통계)
            metadata = {
                "skill_id": skill_id,
                "fitness_score": skill_data["fitness_score"],
                "total_executions": skill_data["total_executions"],
                "successful_executions": skill_data["successful_executions"],
                "avg_judge_score": skill_data.get("avg_judge_score"),
            }

            # 피드백
            feedback_list = self._registry.get_feedback(skill_id, limit=100)
            metadata["feedback"] = feedback_list

            # 진화 이력
            history = self._registry.get_evolution_history(skill_id, limit=100)
            metadata["evolution_history"] = history

            zf.writestr(
                "_cambrian_metadata.json",
                json.dumps(metadata, ensure_ascii=False, indent=2),
            )

        logger.info("Exported skill '%s' to %s", skill_id, zip_path)
        return zip_path

    def import_skill(self, package_path: Path) -> str:
        """패키지에서 스킬을 가져와 등록한다.

        Args:
            package_path: .cambrian 패키지 경로

        Returns:
            등록된 skill_id

        Raises:
            FileNotFoundError: 패키지 파일 없음
            ValueError: 유효하지 않은 패키지
        """
        package_path = Path(package_path)
        if not package_path.exists():
            raise FileNotFoundError(f"Package not found: {package_path}")

        with zipfile.ZipFile(package_path, "r") as zf:
            names = zf.namelist()
            if "meta.yaml" not in names:
                raise ValueError("Invalid package: meta.yaml not found")

            # 임시 디렉토리에 추출
            import tempfile
            with tempfile.TemporaryDirectory() as tmp_dir:
                zf.extractall(tmp_dir)
                tmp_path = Path(tmp_dir)

                # 스킬 로드하여 ID 확인
                skill = self._loader.load(tmp_path)
                skill_id = skill.id

                # 보안 스캔
                if skill.mode == "b":
                    violations = self._scanner.scan_skill(
                        tmp_path, needs_network=skill.runtime.needs_network
                    )
                    if violations:
                        raise ValueError(
                            f"Security violations: {'; '.join(violations)}"
                        )

                # skill_pool에 복사
                dest = self._pool_dir / skill_id
                if dest.exists():
                    shutil.rmtree(dest)
                self._pool_dir.mkdir(parents=True, exist_ok=True)

                # _cambrian_metadata.json은 제외하고 복사
                dest.mkdir(parents=True)
                for item in tmp_path.iterdir():
                    if item.name == "_cambrian_metadata.json":
                        continue
                    target = dest / item.name
                    if item.is_dir():
                        shutil.copytree(item, target)
                    else:
                        shutil.copy2(item, target)

                # 다시 로드하여 등록
                imported_skill = self._loader.load(dest)
                self._registry.register(imported_skill)

        logger.info("Imported skill '%s' from %s", skill_id, package_path)
        return skill_id
