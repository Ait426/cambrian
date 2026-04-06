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
from engine.models import (
    AcquireRequest, AcquireResult,
    BenchmarkReport, EvolutionRecord, ExecutionResult, FailureType,
    FuseRequest, FuseResult,
    GenerateRequest, GenerateResult,
    ProjectScanReport, SearchQuery, SearchReport,
)
from engine.registry import SkillRegistry
from engine.scanner import ProjectScanner
from engine.search import SkillSearcher

logger = logging.getLogger(__name__)


class CambrianEngine:
    """자가 진화 스킬 엔진. 전체 루프를 오케스트레이션한다."""

    MAX_CANDIDATES_PER_RUN: int = 5   # 경쟁 실행 최대 후보 수
    MAX_MODE_A_PER_RUN: int = 2       # Mode A LLM 호출 상한
    MAX_EVAL_CASES: int = 20          # 단일 eval 최대 케이스 수

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
        self._searcher = SkillSearcher(self._registry, self._loader)
        self._scanner = ProjectScanner(searcher=self._searcher)
        self._external_dirs = [Path(path) for path in (external_skill_dirs or [])]

        # fuser 초기화 (지연 import 방지를 위해 여기서 생성)
        from engine.fuser import SkillFuser
        from engine.security import SecurityScanner as _SecurityScanner
        from engine.validator import SkillValidator as _SkillValidator
        self._fuser = SkillFuser(
            loader=self._loader,
            validator=_SkillValidator(schemas_dir),
            scanner=_SecurityScanner(),
            registry=self._registry,
            skill_pool_dir=skill_pool_dir,
            provider=self._provider,
        )

        from engine.generator import SkillGenerator
        self._generator = SkillGenerator(
            fuser=self._fuser,
            registry=self._registry,
            loader=self._loader,
            searcher=self._searcher,
            provider=self._provider,
        )

        self._register_seed_skills(skills_dir)
        self._register_pool_skills(skill_pool_dir)
        self._evolution_suggested: str | None = None

        # acquirer는 seed/pool 등록 후 초기화 (search가 등록된 스킬을 참조하므로)
        from engine.acquirer import SkillAcquirer
        self._acquirer = SkillAcquirer(engine=self)

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
        domain: str = "",
        tags: list[str] | None = None,
    ) -> ExecutionResult | None:
        """후보 스킬을 경쟁 실행하고 최고 결과를 반환한다.

        Mode B 후보는 전원, Mode A 후보는 fitness 상위 2개만 실행.
        승자 선택 기준:
        - 1차: execution_time_ms 오름차순 (Mode A는 999999 고정)
        - 2차 (tiebreaker): fitness_score 내림차순

        Args:
            candidates: registry.search() 결과 리스트
            input_data: 실행 입력 데이터
            domain: trace 기록용 도메인
            tags: trace 기록용 태그

        Returns:
            성공한 결과 중 최적 ExecutionResult. 전원 실패 시 None.
        """
        mode_b = [c for c in candidates if c["mode"] == "b"]
        mode_a = sorted(
            [c for c in candidates if c["mode"] == "a"],
            key=lambda c: c["fitness_score"],
            reverse=True,
        )[:self.MAX_MODE_A_PER_RUN]

        run_targets = mode_b + mode_a

        # release_state 기반 정렬: production > candidate > experimental
        _state_priority = {"production": 0, "candidate": 1, "experimental": 2}
        run_targets.sort(
            key=lambda c: _state_priority.get(
                c.get("release_state", "experimental"), 99
            )
        )

        original_candidate_count = len(run_targets)
        truncated = False

        if len(run_targets) > self.MAX_CANDIDATES_PER_RUN:
            truncated = True
            run_targets = sorted(
                run_targets,
                key=lambda c: (
                    _state_priority.get(
                        c.get("release_state", "experimental"), 99
                    ),
                    -c["fitness_score"],
                ),
            )[:self.MAX_CANDIDATES_PER_RUN]
            logger.warning(
                "Budget cap: %d candidates truncated to %d",
                original_candidate_count,
                self.MAX_CANDIDATES_PER_RUN,
            )

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

                # fitness 하락 시 자동 강등 체크
                self._check_auto_demote(skill.id)
                # 진화 채택 후 성능 악화 시 자동 롤백 체크
                self._check_auto_rollback(skill.id)

        successful = [
            (candidate, result) for candidate, result in results if result.success
        ]

        # trace용 후보 데이터 조립
        candidates_data = []
        for candidate, result in results:
            candidates_data.append({
                "skill_id": result.skill_id,
                "mode": result.mode,
                "success": result.success,
                "execution_time_ms": result.execution_time_ms,
                "fitness_before": candidate["fitness_score"],
                "error": (result.error[:200] if result.error else ""),
            })
        total_ms = sum(r.execution_time_ms for _, r in results)
        input_summary = json.dumps(input_data, ensure_ascii=False)[:200]

        budget_note = (
            f"[BUDGET {original_candidate_count}→{self.MAX_CANDIDATES_PER_RUN}] "
            if truncated else ""
        )

        if not successful:
            # 전부 실패 시에도 trace 저장
            try:
                self._registry.add_run_trace(
                    trace_type="competitive_run",
                    domain=domain,
                    tags=tags or [],
                    input_summary=input_summary,
                    candidate_count=len(results),
                    success_count=0,
                    winner_id=None,
                    winner_reason=f"{budget_note}all_failed",
                    candidates_json=json.dumps(
                        candidates_data, ensure_ascii=False
                    ),
                    total_ms=total_ms,
                )
            except Exception:
                pass
            return None

        # Mode B: execution_time_ms가 짧은 쪽 우선
        # Mode A: 999999 고정 (실행 시간이 의미 없으므로 최하위)
        # 동점 처리: fitness_score를 tiebreaker로만 사용
        best_candidate, best_result = min(
            successful,
            key=lambda pair: (
                pair[1].execution_time_ms
                if pair[1].mode == "b"
                else 999999,
                -pair[0]["fitness_score"],
            ),
        )
        logger.info(
            "Competitive run: %d/%d succeeded, best='%s' (fitness=%.4f)",
            len(successful),
            len(results),
            best_result.skill_id,
            best_candidate["fitness_score"],
        )

        # 성공 시 trace 저장
        winner_reason = budget_note + (
            f"execution_time={best_result.execution_time_ms}ms"
            if best_result.mode == "b"
            else f"fitness_tiebreaker={best_candidate['fitness_score']:.4f}"
        )
        try:
            self._registry.add_run_trace(
                trace_type="competitive_run",
                domain=domain,
                tags=tags or [],
                input_summary=input_summary,
                candidate_count=len(results),
                success_count=len(successful),
                winner_id=best_result.skill_id,
                winner_reason=winner_reason,
                candidates_json=json.dumps(
                    candidates_data, ensure_ascii=False
                ),
                total_ms=total_ms,
            )
        except Exception:
            pass

        self._check_auto_promote(best_result.skill_id)
        return best_result

    def _check_auto_promote(self, skill_id: str) -> None:
        """experimental 스킬이 candidate 조건을 충족하면 자동 승격한다.

        조건: total_executions >= 10, fitness_score >= 0.5, quarantine 이력 < 2회.

        Args:
            skill_id: 체크할 스킬 ID
        """
        try:
            skill_data = self._registry.get(skill_id)
            if skill_data.get("release_state") != "experimental":
                return

            if (
                skill_data["total_executions"] >= 10
                and skill_data["fitness_score"] >= 0.5
            ):
                q_count = self._registry.get_quarantine_count(skill_id)
                if q_count >= 2:
                    logger.info(
                        "승격 차단: '%s' quarantine %d회 이력",
                        skill_id, q_count,
                    )
                    return

                self._registry.update_release_state(
                    skill_id,
                    new_state="candidate",
                    reason=(
                        f"auto: executions={skill_data['total_executions']}, "
                        f"fitness={skill_data['fitness_score']:.4f}"
                    ),
                    triggered_by="auto",
                )
                logger.info("자동 승격: '%s' → candidate", skill_id)
        except Exception:
            pass  # 승격 실패가 실행을 중단하지 않음

    def _check_auto_demote(self, skill_id: str) -> None:
        """fitness가 크게 떨어진 candidate/production 스킬을 experimental로 강등한다.

        조건: release_state가 candidate 또는 production이고 fitness < 0.3.

        Args:
            skill_id: 체크할 스킬 ID
        """
        try:
            skill_data = self._registry.get(skill_id)
            state = skill_data.get("release_state", "experimental")
            if state in ("candidate", "production") and skill_data["fitness_score"] < 0.3:
                self._registry.update_release_state(
                    skill_id,
                    new_state="experimental",
                    reason=f"auto: fitness dropped to {skill_data['fitness_score']:.4f}",
                    triggered_by="auto",
                )
                logger.warning("자동 강등: '%s' → experimental", skill_id)
        except Exception:
            pass

    def _check_auto_rollback(self, skill_id: str) -> None:
        """진화 채택 후 성능이 악화되면 자동으로 이전 버전으로 복원한다.

        조건: fitness < 0.2 + 총 실행 5회 이상 + 최근 adopted 이력 존재.
        복원 시 해당 record에 auto_rolled_back=1을 마킹한다.

        Args:
            skill_id: 체크할 스킬 ID
        """
        try:
            skill_data = self._registry.get(skill_id)
            if skill_data["fitness_score"] >= 0.2:
                return
            if skill_data["total_executions"] < 5:
                return

            history = self._registry.get_evolution_history(skill_id, limit=1)
            if not history or not history[0]["adopted"]:
                return

            record = history[0]
            # 이미 롤백된 record면 스킵
            if record.get("auto_rolled_back"):
                return

            # 자동 롤백 실행: parent_skill_md로 SKILL.md 복원
            skill_path = Path(skill_data["skill_path"])
            skill_md_path = skill_path / "SKILL.md"
            skill_md_path.write_text(
                record["parent_skill_md"], encoding="utf-8"
            )

            # auto_rolled_back 마킹
            self._registry._conn.execute(
                "UPDATE evolution_history SET auto_rolled_back = 1 WHERE id = ?",
                (record["id"],),
            )
            self._registry._conn.commit()
            logger.warning(
                "Auto-rollback executed for skill '%s' (record #%d)",
                skill_id,
                record["id"],
            )

            # 롤백된 스킬을 quarantine 상태로 격리
            self._registry.update_release_state(
                skill_id,
                new_state="quarantined",
                reason=f"auto_rollback: fitness={skill_data['fitness_score']:.4f}",
                triggered_by="auto",
            )
        except Exception:
            pass  # 롤백 실패는 조용히 무시

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

            result = self._run_competitive(
                candidates, input_data, domain=domain, tags=tags
            )

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

    def get_run_traces(
        self,
        trace_type: str | None = None,
        skill_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """실행 trace를 조회한다.

        Args:
            trace_type: trace 유형 필터
            skill_id: 스킬 ID 필터
            limit: 최대 반환 개수

        Returns:
            최신순 trace 목록
        """
        return self._registry.get_run_traces(trace_type, skill_id, limit)

    def get_run_trace_by_id(self, trace_id: int) -> dict | None:
        """특정 run trace를 ID로 조회한다.

        Args:
            trace_id: 조회할 trace ID

        Returns:
            trace dict 또는 None
        """
        return self._registry.get_run_trace_by_id(trace_id)

    def get_skill_stats(self, skill_id: str) -> dict:
        """스킬의 운영 통계를 집계한다.

        Args:
            skill_id: 대상 스킬 ID

        Returns:
            skill, trace, evolution, rollback, feedback 집계 dict

        Raises:
            SkillNotFoundError: 해당 ID가 DB에 없을 때
        """
        skill_data = self._registry.get(skill_id)
        trace_stats = self._registry.get_skill_trace_stats(skill_id)
        evo_stats = self._registry.get_skill_evolution_stats(skill_id)
        rollback_count = self._registry.get_skill_rollback_count(skill_id)
        feedback_list = self._registry.get_feedback(skill_id, limit=20)

        avg_feedback = 0.0
        if feedback_list:
            avg_feedback = sum(f["rating"] for f in feedback_list) / len(
                feedback_list
            )

        return {
            "skill": skill_data,
            "trace": trace_stats,
            "evolution": evo_stats,
            "rollback_count": rollback_count,
            "avg_feedback_rating": round(avg_feedback, 1),
            "feedback_count": len(feedback_list),
        }

    def evaluate(self, skill_id: str) -> dict:
        """스킬을 replay set으로 평가하고 스냅샷을 저장한다.

        Args:
            skill_id: 평가할 스킬 ID

        Returns:
            snapshot_id, pass_rate, verdict, delta 등 평가 결과 dict

        Raises:
            SkillNotFoundError: 해당 ID가 DB에 없을 때
            RuntimeError: evaluation_inputs가 없을 때
        """
        skill_data = self._registry.get(skill_id)
        eval_inputs = self._registry.get_evaluation_inputs(skill_id)
        if not eval_inputs:
            raise RuntimeError(
                f"No evaluation inputs for skill '{skill_id}'. "
                f"Add with: cambrian eval-input add {skill_id} --input '...'"
            )

        if len(eval_inputs) > self.MAX_EVAL_CASES:
            logger.warning(
                "Budget cap: %d eval cases truncated to %d",
                len(eval_inputs),
                self.MAX_EVAL_CASES,
            )
            eval_inputs = eval_inputs[:self.MAX_EVAL_CASES]

        skill = self._loader.load(skill_data["skill_path"])
        results: list[dict] = []
        pass_count = 0
        success_times: list[int] = []

        for ei in eval_inputs:
            input_data = json.loads(ei["input_data"])
            try:
                result = self._executor.execute(skill, input_data)
                success = result.success
                time_ms = result.execution_time_ms
                output_preview = (
                    json.dumps(result.output, ensure_ascii=False)[:200]
                    if result.output else ""
                )
                error = result.error[:200] if result.error else ""
            except Exception as exc:
                success = False
                time_ms = 0
                output_preview = ""
                error = str(exc)[:200]

            if success:
                pass_count += 1
                if time_ms > 0:
                    success_times.append(time_ms)

            results.append({
                "eval_input_id": ei["id"],
                "description": ei.get("description", ""),
                "success": success,
                "execution_time_ms": time_ms,
                "output_preview": output_preview,
                "error": error,
            })

        input_count = len(eval_inputs)
        fail_count = input_count - pass_count
        pass_rate = round(pass_count / input_count, 4) if input_count > 0 else 0.0
        avg_time_ms = (
            round(sum(success_times) / len(success_times))
            if success_times else 0
        )
        fitness_at_time = float(skill_data["fitness_score"])

        snapshot_id = self._registry.add_evaluation_snapshot(
            skill_id=skill_id,
            input_count=input_count,
            pass_count=pass_count,
            fail_count=fail_count,
            pass_rate=pass_rate,
            avg_time_ms=avg_time_ms,
            fitness_at_time=fitness_at_time,
            results_json=json.dumps(results, ensure_ascii=False),
        )

        # delta/verdict 계산
        snapshots = self._registry.get_evaluation_snapshots(skill_id, limit=2)
        delta: dict | None = None
        verdict = "baseline"

        if len(snapshots) >= 2:
            prev = snapshots[1]  # 직전 스냅샷
            d_pass = round(pass_rate - prev["pass_rate"], 4)
            d_time = avg_time_ms - prev["avg_time_ms"]
            d_fitness = round(fitness_at_time - prev["fitness_at_time"], 4)
            delta = {
                "pass_rate": d_pass,
                "avg_time_ms": d_time,
                "fitness": d_fitness,
                "prev_pass_rate": prev["pass_rate"],
                "prev_avg_time_ms": prev["avg_time_ms"],
                "prev_fitness": prev["fitness_at_time"],
            }

            if d_pass < 0:
                verdict = "regression"
            else:
                improvements = 0
                if d_pass >= 0:
                    improvements += 1
                if d_time <= 0:
                    improvements += 1
                if d_fitness >= 0:
                    improvements += 1

                has_positive = d_pass > 0 or d_time < 0 or d_fitness > 0
                if improvements >= 2 and has_positive:
                    verdict = "improving"
                elif improvements >= 2:
                    verdict = "stable"
                else:
                    verdict = "regression"

        return {
            "snapshot_id": snapshot_id,
            "skill_id": skill_id,
            "input_count": input_count,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "pass_rate": pass_rate,
            "avg_time_ms": avg_time_ms,
            "fitness_at_time": fitness_at_time,
            "results": results,
            "verdict": verdict,
            "delta": delta,
        }

    def get_eval_report(self, skill_id: str, limit: int = 5) -> dict:
        """스킬의 최근 evaluation 스냅샷 추이를 반환한다.

        Args:
            skill_id: 대상 스킬 ID
            limit: 최대 스냅샷 수

        Returns:
            snapshots 리스트 + trend + latest_verdict
        """
        snapshots = self._registry.get_evaluation_snapshots(skill_id, limit)
        if not snapshots:
            return {
                "skill_id": skill_id,
                "snapshots": [],
                "trend": "no_data",
                "latest_verdict": None,
                "total_snapshots": 0,
            }

        # 시간순 (오래된 것 먼저)
        snapshots = list(reversed(snapshots))

        # 각 스냅샷에 delta 추가
        for i, snap in enumerate(snapshots):
            if i == 0:
                snap["delta_verdict"] = "-"
            else:
                prev = snapshots[i - 1]
                d_pass = snap["pass_rate"] - prev["pass_rate"]
                d_time = snap["avg_time_ms"] - prev["avg_time_ms"]
                d_fitness = snap["fitness_at_time"] - prev["fitness_at_time"]

                if d_pass < 0:
                    snap["delta_verdict"] = "regression"
                else:
                    imps = 0
                    if d_pass >= 0:
                        imps += 1
                    if d_time <= 0:
                        imps += 1
                    if d_fitness >= 0:
                        imps += 1
                    has_pos = d_pass > 0 or d_time < 0 or d_fitness > 0
                    if imps >= 2 and has_pos:
                        snap["delta_verdict"] = "improving"
                    elif imps >= 2:
                        snap["delta_verdict"] = "stable"
                    else:
                        snap["delta_verdict"] = "regression"

        # 전체 trend
        first_rate = snapshots[0]["pass_rate"]
        last_rate = snapshots[-1]["pass_rate"]
        if len(snapshots) == 1:
            trend = "insufficient_data"
        elif last_rate > first_rate:
            trend = "improving"
        elif last_rate < first_rate:
            trend = "declining"
        else:
            trend = "stable"

        return {
            "skill_id": skill_id,
            "snapshots": snapshots,
            "trend": trend,
            "latest_verdict": snapshots[-1].get("delta_verdict", "-"),
            "total_snapshots": len(snapshots),
        }

    def search(self, query: SearchQuery) -> SearchReport:
        """통합 스킬 검색을 실행한다.

        Args:
            query: SearchQuery 검색 쿼리

        Returns:
            SearchReport 검색 결과 보고서
        """
        external = self._external_dirs if self._external_dirs else None
        return self._searcher.search(query, external_dirs=external)

    def scan(
        self,
        project_path: str,
        max_depth: int = 4,
        max_queries: int = 10,
        top_k: int = 3,
        run_search: bool = True,
    ) -> ProjectScanReport:
        """프로젝트를 분석하여 capability gap과 추천 스킬을 반환한다.

        Args:
            project_path: 분석할 프로젝트 디렉토리 경로
            max_depth: 파일트리 스캔 최대 깊이
            max_queries: 최대 search 호출 횟수
            top_k: gap당 최대 추천 스킬 수
            run_search: False면 search 미실행 (gap 분석까지만)

        Returns:
            ProjectScanReport
        """
        external = self._external_dirs if self._external_dirs else None
        return self._scanner.scan(
            project_path=project_path,
            max_depth=max_depth,
            max_queries=max_queries,
            top_k=top_k,
            run_search=run_search,
            external_dirs=external,
        )

    def fuse(self, request: FuseRequest) -> FuseResult:
        """스킬 2개를 융합하여 새 스킬을 생성한다.

        Args:
            request: FuseRequest 융합 요청

        Returns:
            FuseResult 융합 결과
        """
        return self._fuser.fuse(request)

    def generate(self, request: GenerateRequest) -> GenerateResult:
        """스킬을 0에서 자동 생성한다.

        Args:
            request: GenerateRequest 생성 요청

        Returns:
            GenerateResult 생성 결과
        """
        return self._generator.generate(request)

    def acquire(self, request: AcquireRequest) -> AcquireResult:
        """프로젝트 capability를 자동 분석·확보한다.

        Args:
            request: AcquireRequest 확보 요청

        Returns:
            AcquireResult 확보 결과
        """
        return self._acquirer.acquire(request)

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
