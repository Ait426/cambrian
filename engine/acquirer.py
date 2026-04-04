"""Cambrian capability 자동 확보 오케스트레이터."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from engine.models import (
    AcquireAction,
    AcquireActionResult,
    AcquirePlan,
    AcquireRequest,
    AcquireResult,
    CapabilityGap,
    FuseRequest,
    GenerateRequest,
    ProjectScanReport,
    SearchQuery,
)

if TYPE_CHECKING:
    from engine.loop import CambrianEngine

logger = logging.getLogger(__name__)

_VALID_MODES = {"advisory", "execute"}
_VALID_STRATEGIES = {"conservative", "balanced", "aggressive"}

# relevance 임계값
_REUSE_THRESHOLD = 0.6
_FUSE_THRESHOLD_LOW = 0.3
_FUSE_THRESHOLD_HIGH = 0.6


class SkillAcquirer:
    """scan → search → fuse/generate 워크플로우를 오케스트레이션한다."""

    def __init__(self, engine: "CambrianEngine") -> None:
        """초기화.

        Args:
            engine: CambrianEngine 인스턴스
        """
        self._engine = engine

    # ═══════════════════════════════════════════════════════════════
    # 메인 진입점
    # ═══════════════════════════════════════════════════════════════

    def acquire(self, request: AcquireRequest) -> AcquireResult:
        """capability 확보 워크플로우를 실행한다.

        Args:
            request: AcquireRequest

        Returns:
            AcquireResult
        """
        # 1. 입력 검증
        errors = self._validate_request(request)
        if errors:
            return AcquireResult(
                success=False, mode=request.mode, strategy=request.strategy,
                warnings=errors,
            )

        # 2. gap 수집
        scan_report: ProjectScanReport | None = None
        gaps: list[CapabilityGap] = []

        if request.project_path:
            scan_report = self._scan_project(request)
            if scan_report is None:
                return AcquireResult(
                    success=False, mode=request.mode, strategy=request.strategy,
                    warnings=["프로젝트 스캔 실패"],
                )
            gaps = scan_report.gaps[:request.max_actions]
        elif request.goal:
            gaps = self._build_goal_gaps(request)

        # 3. 계획 수립
        plan = self._build_plan(gaps, request)

        # 4. 모드 분기
        executed: list[AcquireActionResult] = []
        if request.mode == "execute":
            executed = self._execute_plan(plan, request)

        # 5. 요약 생성
        summary = self._build_summary(plan, executed, request)

        # 6. 전체 성공 판정
        if request.mode == "advisory":
            overall_success = True
        else:
            executed_real = [e for e in executed if e.executed]
            overall_success = all(e.success for e in executed_real) if executed_real else True

        return AcquireResult(
            success=overall_success,
            mode=request.mode,
            strategy=request.strategy,
            scan_report=scan_report,
            plan=plan,
            executed_actions=executed,
            summary=summary,
        )

    # ═══════════════════════════════════════════════════════════════
    # Step 1: 입력 처리
    # ═══════════════════════════════════════════════════════════════

    def _validate_request(self, request: AcquireRequest) -> list[str]:
        """요청 유효성을 검증한다.

        Args:
            request: 확보 요청

        Returns:
            에러 메시지 리스트
        """
        errors: list[str] = []

        if request.project_path is None and request.goal is None:
            errors.append("project_path 또는 goal 중 최소 하나는 필수입니다")

        if request.mode not in _VALID_MODES:
            errors.append(f"유효하지 않은 mode: '{request.mode}'")

        if request.strategy not in _VALID_STRATEGIES:
            errors.append(f"유효하지 않은 strategy: '{request.strategy}'")

        if request.project_path is not None and not Path(request.project_path).exists():
            errors.append(f"project_path가 존재하지 않음: {request.project_path}")

        return errors

    def _scan_project(self, request: AcquireRequest) -> ProjectScanReport | None:
        """프로젝트를 스캔한다.

        Args:
            request: 확보 요청

        Returns:
            ProjectScanReport 또는 None (실패 시)
        """
        try:
            return self._engine.scan(
                project_path=request.project_path,
                run_search=True,
            )
        except Exception as exc:
            logger.error("프로젝트 스캔 실패: %s", exc)
            return None

    def _build_goal_gaps(self, request: AcquireRequest) -> list[CapabilityGap]:
        """goal에서 수동 gap을 생성한다.

        Args:
            request: 확보 요청

        Returns:
            CapabilityGap 1개 리스트
        """
        return [CapabilityGap(
            category="user_goal",
            description=request.goal or "",
            priority="high",
            evidence=["사용자 직접 지정"],
            suggested_domain=request.domain or "general",
            suggested_tags=request.tags or [],
            search_query=request.goal or "",
        )]

    # ═══════════════════════════════════════════════════════════════
    # Step 2: 계획 수립
    # ═══════════════════════════════════════════════════════════════

    def _build_plan(
        self, gaps: list[CapabilityGap], request: AcquireRequest,
    ) -> AcquirePlan:
        """gap별 액션을 결정하고 계획을 수립한다.

        Args:
            gaps: gap 리스트
            request: 확보 요청

        Returns:
            AcquirePlan
        """
        actions: list[AcquireAction] = []
        deferred = 0

        for gap in gaps:
            action = self._decide_action_for_gap(gap, request)
            actions.append(action)
            if action.action_type == "defer":
                deferred += 1

        # confidence 내림차순, 동점이면 risk 오름차순
        risk_order = {"low": 0, "medium": 1, "high": 2}
        actions.sort(key=lambda a: (-a.confidence, risk_order.get(a.risk, 99)))

        return AcquirePlan(
            actions=actions,
            total_gaps=len(gaps),
            addressable_gaps=len(gaps) - deferred,
            deferred_gaps=deferred,
            strategy_applied=request.strategy,
        )

    def _decide_action_for_gap(
        self, gap: CapabilityGap, request: AcquireRequest,
    ) -> AcquireAction:
        """단일 gap에 대한 최적 액션을 결정한다.

        Args:
            gap: 대상 gap
            request: 확보 요청

        Returns:
            AcquireAction
        """
        # search 실행
        query = SearchQuery(
            text=gap.search_query,
            domain=gap.suggested_domain,
            tags=gap.suggested_tags if gap.suggested_tags else None,
            include_external=False,
            limit=5,
        )
        report = self._engine.search(query)
        results = report.results

        # Step B: REUSE 판정 (relevance >= 0.6)
        strong = [r for r in results if r.relevance_score >= _REUSE_THRESHOLD]
        if strong:
            best = strong[0]
            return AcquireAction(
                action_type="reuse",
                gap_category=gap.category,
                description=f"기존 스킬 '{best.skill_id}' 사용 권장",
                confidence=best.relevance_score,
                risk="low",
                reuse_skill_id=best.skill_id,
                reuse_relevance=best.relevance_score,
            )

        # Step C: FUSE 판정 (0.3 <= relevance < 0.6, 2개 이상)
        partial = [
            r for r in results
            if _FUSE_THRESHOLD_LOW <= r.relevance_score < _FUSE_THRESHOLD_HIGH
        ]
        if len(partial) >= 2:
            if not request.allow_fuse:
                return self._make_defer(gap, "fuse 비허용")
            top = partial[:2]
            confidence = min(top[0].relevance_score, top[1].relevance_score) + 0.1
            return AcquireAction(
                action_type="fuse",
                gap_category=gap.category,
                description=f"'{top[0].skill_id}' + '{top[1].skill_id}' 융합",
                confidence=min(confidence, 0.6),
                risk="medium",
                fuse_skill_a=top[0].skill_id,
                fuse_skill_b=top[1].skill_id,
                fuse_goal=gap.description,
            )

        # Step D: GENERATE 판정
        if not request.allow_generate:
            return self._make_defer(gap, "generate 비허용")

        # generate 최소 조건 확인
        gen_domain = gap.suggested_domain or request.domain or "general"
        gen_tags = gap.suggested_tags or request.tags or []
        if len(gap.description) < 10 or not gen_tags:
            return self._make_defer(gap, "generate 최소 조건 미충족 (goal 10자+ 또는 tags 필요)")

        return AcquireAction(
            action_type="generate",
            gap_category=gap.category,
            description=f"새 스킬 생성: {gap.description[:50]}",
            confidence=0.4,
            risk="high",
            generate_goal=gap.description,
            generate_domain=gen_domain,
            generate_tags=gen_tags,
        )

    @staticmethod
    def _make_defer(gap: CapabilityGap, reason: str) -> AcquireAction:
        """DEFER 액션을 생성한다.

        Args:
            gap: 대상 gap
            reason: 보류 사유

        Returns:
            AcquireAction (defer)
        """
        return AcquireAction(
            action_type="defer",
            gap_category=gap.category,
            description=f"보류: {reason}",
            confidence=0.0,
            risk="low",
        )

    # ═══════════════════════════════════════════════════════════════
    # Step 3: 실행
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _get_allowed_types(strategy: str) -> set[str]:
        """전략에 따른 허용 액션 타입을 반환한다.

        Args:
            strategy: 실행 전략

        Returns:
            허용된 action_type 세트
        """
        if strategy == "conservative":
            return {"reuse"}
        elif strategy == "balanced":
            return {"reuse", "fuse"}
        elif strategy == "aggressive":
            return {"reuse", "fuse", "generate"}
        return {"reuse"}

    def _execute_plan(
        self, plan: AcquirePlan, request: AcquireRequest,
    ) -> list[AcquireActionResult]:
        """계획을 전략에 따라 실행한다.

        Args:
            plan: 실행 계획
            request: 확보 요청

        Returns:
            AcquireActionResult 리스트
        """
        allowed = self._get_allowed_types(request.strategy)
        results: list[AcquireActionResult] = []

        for action in plan.actions:
            if action.action_type not in allowed:
                results.append(AcquireActionResult(
                    action=action,
                    executed=False,
                    success=False,
                    skipped_reason=(
                        f"strategy '{request.strategy}'에서 "
                        f"'{action.action_type}' 비허용"
                    ),
                ))
                continue
            results.append(self._execute_action(action, request))

        return results

    def _execute_action(
        self, action: AcquireAction, request: AcquireRequest,
    ) -> AcquireActionResult:
        """단일 액션을 실행한다.

        Args:
            action: 실행할 액션
            request: 확보 요청

        Returns:
            AcquireActionResult
        """
        if action.action_type == "reuse":
            return AcquireActionResult(
                action=action,
                executed=True,
                success=True,
                skill_id=action.reuse_skill_id,
            )

        if action.action_type == "fuse":
            try:
                fuse_result = self._engine.fuse(FuseRequest(
                    skill_id_a=action.fuse_skill_a or "",
                    skill_id_b=action.fuse_skill_b or "",
                    goal=action.fuse_goal or action.description,
                    dry_run=request.dry_run,
                ))
                return AcquireActionResult(
                    action=action,
                    executed=True,
                    success=fuse_result.success,
                    skill_id=fuse_result.skill_id if fuse_result.success else None,
                    skill_path=fuse_result.skill_path if fuse_result.success else None,
                    error="" if fuse_result.success else "; ".join(
                        fuse_result.validation_errors or fuse_result.warnings
                    ),
                )
            except Exception as exc:
                logger.error("fuse 실행 실패: %s", exc)
                return AcquireActionResult(
                    action=action, executed=True, success=False,
                    error=str(exc),
                )

        if action.action_type == "generate":
            try:
                gen_result = self._engine.generate(GenerateRequest(
                    goal=action.generate_goal or action.description,
                    domain=action.generate_domain or "general",
                    tags=action.generate_tags or ["auto"],
                    dry_run=request.dry_run,
                    skip_search=True,
                ))
                return AcquireActionResult(
                    action=action,
                    executed=True,
                    success=gen_result.success,
                    skill_id=gen_result.skill_id if gen_result.success else None,
                    skill_path=gen_result.skill_path if gen_result.success else None,
                    error="" if gen_result.success else "; ".join(
                        gen_result.validation_errors or gen_result.warnings
                    ),
                )
            except Exception as exc:
                logger.error("generate 실행 실패: %s", exc)
                return AcquireActionResult(
                    action=action, executed=True, success=False,
                    error=str(exc),
                )

        # defer
        return AcquireActionResult(
            action=action, executed=False, success=False,
            skipped_reason="defer 액션은 실행 대상이 아님",
        )

    # ═══════════════════════════════════════════════════════════════
    # 보조
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _build_summary(
        plan: AcquirePlan,
        executed: list[AcquireActionResult],
        request: AcquireRequest,
    ) -> str:
        """사람이 읽을 수 있는 요약을 생성한다.

        Args:
            plan: 실행 계획
            executed: 실행 결과
            request: 확보 요청

        Returns:
            요약 문자열
        """
        lines: list[str] = []
        lines.append(
            f"총 {plan.total_gaps}개 gap 중 "
            f"{plan.addressable_gaps}개 대응 가능, "
            f"{plan.deferred_gaps}개 보류"
        )

        if request.mode == "advisory":
            reuse = sum(1 for a in plan.actions if a.action_type == "reuse")
            fuse = sum(1 for a in plan.actions if a.action_type == "fuse")
            gen = sum(1 for a in plan.actions if a.action_type == "generate")
            lines.append(f"추천: reuse {reuse}건, fuse {fuse}건, generate {gen}건")
        elif executed:
            ok = sum(1 for e in executed if e.executed and e.success)
            fail = sum(1 for e in executed if e.executed and not e.success)
            skip = sum(1 for e in executed if not e.executed)
            lines.append(f"실행: {ok}건 성공, {fail}건 실패, {skip}건 스킵")

        return " | ".join(lines)
