"""Cambrian 자가 진화 스킬 엔진."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.absorber import SkillAbsorber
from engine.autopsy import Autopsy
from engine.benchmark import SkillBenchmark
from engine.critic import SkillCritic
from engine.evolution import SkillEvolver
from engine.executor import SkillExecutor
from engine.llm import LLMProvider
from engine.loader import SkillLoader
from engine.models import BenchmarkReport, EvolutionRecord, ExecutionResult, FailureType
from engine.registry import SkillRegistry

logger = logging.getLogger(__name__)


class CambrianEngine:
    """자가 진화 스킬 엔진. 전체 루프를 오케스트레이션한다."""

    def __init__(
        self,
        schemas_dir: str | Path = "schemas",
        skills_dir: str | Path = "skills",
        skill_pool_dir: str | Path = "skill_pool",
        db_path: str | Path = ":memory:",
        external_skill_dirs: list[str | Path] | None = None,
        provider: LLMProvider | None = None,
    ):
        """Cambrian 엔진을 초기화한다.

        Args:
            schemas_dir: JSON Schema 디렉토리
            skills_dir: 시드 스킬 디렉토리
            skill_pool_dir: 흡수된 스킬 저장 디렉토리
            db_path: SQLite DB 경로
            external_skill_dirs: 외부 스킬 검색 경로 리스트
            provider: LLM 프로바이더. None이면 필요 시 자동 생성.
        """
        self._provider = provider
        self._loader = SkillLoader(schemas_dir)
        self._executor = SkillExecutor(provider=self._provider)
        self._registry = SkillRegistry(db_path)
        self._autopsy = Autopsy()
        self._absorber = SkillAbsorber(schemas_dir, skill_pool_dir, self._registry)
        self._external_dirs = [Path(path) for path in (external_skill_dirs or [])]

        self._register_seed_skills(skills_dir)
        self._register_pool_skills(skill_pool_dir)
        self._evolution_suggested: str | None = None

        # 장기 미사용 스킬 자동 퇴화
        self._registry.decay()

    def __enter__(self) -> "CambrianEngine":
        """context manager 진입."""
        return self

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: object) -> None:
        """context manager 종료 시 DB 연결을 닫는다."""
        self.close()

    def close(self) -> None:
        """엔진 리소스를 정리한다. DB 연결을 닫는다."""
        self._registry.close()

    def _register_seed_skills(self, skills_dir: str | Path) -> None:
        """시드 스킬 디렉토리의 모든 스킬을 Registry에 등록한다.

        Args:
            skills_dir: 시드 스킬 디렉토리 경로
        """
        skills = self._loader.load_directory(skills_dir)
        for skill in skills:
            self._registry.register(skill)
            logger.info("Registered seed skill: %s", skill.id)

    def _register_pool_skills(self, pool_dir: str | Path) -> None:
        """skill_pool/ 디렉토리의 기존 흡수 스킬을 Registry에 등록한다.

        Args:
            pool_dir: skill_pool 디렉토리 경로
        """
        pool_path = Path(pool_dir)
        if not pool_path.exists():
            pool_path.mkdir(parents=True, exist_ok=True)
            return

        skills = self._loader.load_directory(pool_path)
        for skill in skills:
            self._registry.register(skill)
            logger.info("Registered pool skill: %s", skill.id)

    def _run_competitive(
        self,
        candidates: list[dict],
        input_data: dict,
    ) -> ExecutionResult | None:
        """후보 스킬을 경쟁 실행하고 최고 결과를 반환한다.

        Mode B 후보는 전원, Mode A 후보는 fitness 상위 2개만 실행.

        Args:
            candidates: registry.search() 결과 리스트
            input_data: 실행 입력 데이터

        Returns:
            성공한 결과 중 fitness 최고인 ExecutionResult. 전원 실패 시 None.
        """
        MODE_A_LIMIT = 2

        mode_b = [c for c in candidates if c["mode"] == "b"]
        mode_a = sorted(
            [c for c in candidates if c["mode"] == "a"],
            key=lambda c: c["fitness_score"],
            reverse=True,
        )[:MODE_A_LIMIT]

        run_targets = mode_b + mode_a
        results: list[tuple[dict, ExecutionResult]] = []

        for candidate in run_targets:
            skill = self._loader.load(candidate["skill_path"])
            result = self._executor.execute(skill, input_data)

            # H-3: 성공 결과의 출력 스키마 검증
            if result.success and result.output is not None:
                output_errors = self._executor.validate_output(skill, result.output)
                if output_errors:
                    logger.warning(
                        "Output schema validation failed for '%s': %s",
                        skill.id,
                        output_errors,
                    )
                    result = ExecutionResult(
                        skill_id=result.skill_id,
                        success=False,
                        output=result.output,
                        error=f"Output schema mismatch: {'; '.join(output_errors)}",
                        stderr=result.stderr,
                        exit_code=result.exit_code,
                        execution_time_ms=result.execution_time_ms,
                        mode=result.mode,
                    )

            self._registry.update_after_execution(skill.id, result)
            results.append((candidate, result))

            # 실패 시 autopsy 분석 → 자동 피드백 저장
            if not result.success:
                report = self._autopsy.analyze(result, skill)
                if report.failure_type != FailureType.SKILL_MISSING:
                    auto_comment = (
                        f"[AUTO] {report.failure_type.value}: {report.root_cause}. "
                        f"Recommendation: {report.recommendation}"
                    )
                    try:
                        self._registry.add_feedback(
                            skill_id=skill.id,
                            rating=1,
                            comment=auto_comment,
                            input_data=json.dumps(input_data, ensure_ascii=False)[:500],
                            output_data=json.dumps(result.output or {}, ensure_ascii=False)[:500],
                        )
                        logger.info(
                            "Auto-feedback saved for skill '%s': %s",
                            skill.id,
                            report.failure_type.value,
                        )
                    except Exception as exc:
                        logger.warning("Failed to save auto-feedback: %s", exc)

        successful = [
            (candidate, result) for candidate, result in results if result.success
        ]
        if not successful:
            return None

        best_candidate, best_result = max(
            successful,
            key=lambda pair: pair[0]["fitness_score"],
        )
        logger.info(
            "Competitive run: %d/%d succeeded, best='%s' (fitness=%.4f)",
            len(successful),
            len(results),
            best_result.skill_id,
            best_candidate["fitness_score"],
        )
        return best_result

    def run_task(
        self,
        domain: str,
        tags: list[str],
        input_data: dict,
        max_retries: int = 3,
    ) -> ExecutionResult:
        """태스크를 실행한다. 실패 시 자가 진화 루프를 돌린다.

        Args:
            domain: 태스크에 필요한 스킬 도메인
            tags: 태스크에 필요한 스킬 태그
            input_data: 스킬에 전달할 입력 데이터
            max_retries: 최대 재시도 횟수

        Returns:
            최종 ExecutionResult
        """
        attempt = 0
        last_result: ExecutionResult | None = None

        while attempt <= max_retries:
            candidates = self._registry.search(
                domain=domain,
                tags=tags,
                status="active",
            ) + self._registry.search(
                domain=domain,
                tags=tags,
                status="newborn",
            )

            if not candidates:
                absorbed = self._try_absorb_from_external(domain, tags)
                if absorbed:
                    attempt += 1
                    continue

                last_result = ExecutionResult(
                    skill_id="",
                    success=False,
                    output=None,
                    error="No matching skill found",
                    stderr="",
                    exit_code=1,
                    execution_time_ms=0,
                    mode="b",
                )
                logger.error("Task failed after %s attempts", max_retries + 1)
                return last_result

            result = self._run_competitive(candidates, input_data)

            if result is not None:
                logger.info("Task completed with skill '%s'", result.skill_id)
                self._check_evolution_suggestion(result.skill_id)
                return result

            last_result = ExecutionResult(
                skill_id="",
                success=False,
                output=None,
                error="All candidates failed",
                stderr="",
                exit_code=1,
                execution_time_ms=0,
                mode="b",
            )
            attempt += 1

        if last_result is None:
            last_result = ExecutionResult(
                skill_id="",
                success=False,
                output=None,
                error="Task execution failed",
                stderr="",
                exit_code=1,
                execution_time_ms=0,
                mode="b",
            )

        logger.error("Task failed after %s attempts", max_retries + 1)
        return last_result

    def _try_absorb_from_external(self, domain: str, tags: list[str]) -> bool:
        """외부 디렉토리에서 매칭되는 스킬을 흡수 시도한다.

        Args:
            domain: 필요한 도메인
            tags: 필요한 태그

        Returns:
            True면 흡수 성공, False면 실패
        """
        for external_dir in self._external_dirs:
            if not external_dir.exists() or not external_dir.is_dir():
                continue

            for sub_dir in external_dir.iterdir():
                if not sub_dir.is_dir():
                    continue

                meta_path = sub_dir / "meta.yaml"
                if not meta_path.exists():
                    continue

                try:
                    with open(meta_path, "r", encoding="utf-8") as file:
                        meta = yaml.safe_load(file) or {}
                except (OSError, yaml.YAMLError) as exc:
                    logger.warning("Failed to read meta.yaml at '%s': %s", meta_path, exc)
                    continue

                if not isinstance(meta, dict):
                    continue

                meta_domain = meta.get("domain")
                meta_tags = meta.get("tags", [])

                if meta_domain != domain:
                    continue

                if not isinstance(meta_tags, list):
                    continue

                if not any(tag in meta_tags for tag in tags):
                    continue

                try:
                    self._absorber.absorb(sub_dir)
                    return True
                except Exception as exc:
                    logger.warning("Failed to absorb external skill from '%s': %s", sub_dir, exc)
                    continue

        return False

    def _check_evolution_suggestion(self, skill_id: str) -> None:
        """실행된 스킬의 fitness가 낮으면 진화를 제안한다.

        Args:
            skill_id: 검사할 스킬 ID
        """
        try:
            skill_data = self._registry.get(skill_id)
            feedback_list = self._registry.get_feedback(skill_id)
            if (
                skill_data["fitness_score"] < 0.3
                and skill_data["mode"] == "a"
                and skill_data["total_executions"] >= 5
                and len(feedback_list) >= 3
            ):
                logger.info(
                    "Evolution suggested for skill '%s' "
                    "(fitness=%.4f, executions=%d, feedback=%d)",
                    skill_id,
                    skill_data["fitness_score"],
                    skill_data["total_executions"],
                    len(feedback_list),
                )
                self._evolution_suggested = skill_id
        except Exception:
            pass

    def get_evolution_suggestion(self) -> str | None:
        """run_task 후 진화가 제안된 스킬 ID를 반환한다. 1회 소비.

        Returns:
            스킬 ID 또는 None
        """
        suggestion = self._evolution_suggested
        self._evolution_suggested = None
        return suggestion

    def get_registry(self) -> SkillRegistry:
        """Registry 인스턴스를 반환한다. 테스트·디버깅용."""
        return self._registry

    def get_loader(self) -> SkillLoader:
        """Loader 인스턴스를 반환한다."""
        return self._loader

    def absorb_skill(self, path: str | Path) -> "Skill":
        """외부 스킬을 흡수한다.

        Args:
            path: 흡수할 스킬 디렉토리 경로

        Returns:
            흡수된 Skill 객체
        """
        return self._absorber.absorb(path)

    def remove_skill(self, skill_id: str) -> None:
        """흡수된 스킬을 제거한다.

        Args:
            skill_id: 제거할 스킬 ID
        """
        self._absorber.remove(skill_id)

    def get_skill_count(self) -> int:
        """등록된 스킬 수를 반환한다."""
        return self._registry.count()

    def list_skills(self) -> list[dict]:
        """등록된 모든 스킬을 반환한다."""
        return self._registry.list_all()

    def feedback(
        self,
        skill_id: str,
        rating: int,
        comment: str,
        input_data: dict | None = None,
        output_data: dict | None = None,
    ) -> int:
        """스킬 실행 결과에 피드백을 저장한다.

        Args:
            skill_id: 대상 스킬 ID
            rating: 1~5 평점
            comment: 피드백 코멘트
            input_data: 실행에 사용한 입력
            output_data: 실행 결과 출력

        Returns:
            생성된 피드백 ID
        """
        # 사용자 입력에서 시스템 접두사 제거 (injection 방지)
        for prefix in ("[AUTO] ", "[AUTO]", "[CRITIC] ", "[CRITIC]"):
            if comment.startswith(prefix):
                comment = comment[len(prefix):].strip() or "(sanitized)"
                break

        input_json = json.dumps(input_data or {}, ensure_ascii=False)
        output_json = json.dumps(output_data or {}, ensure_ascii=False)
        return self._registry.add_feedback(
            skill_id, rating, comment, input_json, output_json
        )

    def critique(self, skill_id: str) -> list[dict]:
        """스킬을 비판적으로 분석한다.

        Args:
            skill_id: 분석할 스킬 ID

        Returns:
            발견된 약점 목록
        """
        skill_data = self._registry.get(skill_id)
        skill = self._loader.load(skill_data["skill_path"])
        critic = SkillCritic(provider=self._provider)
        findings = critic.critique(skill)

        # HIGH severity 발견을 자동 피드백으로 저장
        for finding in findings:
            if finding["severity"] == "high":
                comment = (
                    f"[CRITIC] {finding['category']}: {finding['finding']}. "
                    f"Suggestion: {finding['suggestion']}"
                )
                try:
                    self._registry.add_feedback(
                        skill_id=skill_id,
                        rating=2,
                        comment=comment,
                        input_data="{}",
                        output_data="{}",
                    )
                except Exception as exc:
                    logger.warning("Failed to save critic feedback: %s", exc)

        return findings

    def evolve(self, skill_id: str, test_input: dict) -> EvolutionRecord:
        """스킬을 1회 진화시킨다.

        Args:
            skill_id: 진화시킬 스킬 ID
            test_input: 벤치마크용 테스트 입력

        Returns:
            EvolutionRecord

        Raises:
            RuntimeError: 피드백이 없는 경우
        """
        feedback_list = self._registry.get_feedback(skill_id)
        if not feedback_list:
            raise RuntimeError(f"No feedback available for skill '{skill_id}'")

        evolver = SkillEvolver(
            self._loader, self._executor, self._registry,
            provider=self._provider,
        )
        return evolver.evolve(skill_id, test_input, feedback_list)

    def benchmark(
        self,
        domain: str,
        tags: list[str],
        input_data: dict,
    ) -> BenchmarkReport:
        """스킬들을 동일 입력으로 벤치마크하고 순위를 매긴다.

        Args:
            domain: 대상 도메인
            tags: 필요 태그
            input_data: 벤치마크 입력 데이터

        Returns:
            BenchmarkReport
        """
        active_candidates = self._registry.search(
            domain=domain,
            tags=tags,
            status="active",
        )
        newborn_candidates = self._registry.search(
            domain=domain,
            tags=tags,
            status="newborn",
        )
        candidates = active_candidates + newborn_candidates

        if not candidates:
            return BenchmarkReport(
                entries=[],
                best_skill_id=None,
                total_candidates=0,
                successful_count=0,
                domain=domain,
                tags=tags,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        report = SkillBenchmark(self._loader, self._executor).run(
            candidates=candidates,
            input_data=input_data,
            domain=domain,
            tags=tags,
        )

        for entry in report.entries:
            execution_result = ExecutionResult(
                skill_id=entry.skill_id,
                success=entry.success,
                output=entry.output,
                error=entry.error,
                execution_time_ms=entry.execution_time_ms,
                mode=entry.mode,
            )
            self._registry.update_after_execution(entry.skill_id, execution_result)

        return report
