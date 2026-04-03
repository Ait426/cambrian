"""Cambrian 실패 분석기."""

import logging

from engine.models import (
    AutopsyReport,
    ExecutionResult,
    FailureType,
    Skill,
    SkillNeed,
)

logger = logging.getLogger(__name__)


class Autopsy:
    """규칙 기반 실패 분석기. 실행 실패의 원인을 분류하고 대응을 추천한다."""

    def analyze(
        self,
        result: ExecutionResult,
        skill: Skill | None = None,
        task_description: str = "",
    ) -> AutopsyReport:
        """실행 결과를 분석하여 AutopsyReport를 생성한다.

        Args:
            result: 실패한 ExecutionResult (success=False)
            skill: 실패한 스킬의 Skill 객체 (없으면 skill_missing 판단)
            task_description: 원래 태스크 설명

        Returns:
            AutopsyReport
        """
        del task_description
        failure_type = self._classify(result, skill)
        return self._build_report(result, skill, failure_type)

    def _classify(self, result: ExecutionResult, skill: Skill | None) -> FailureType:
        """실패 유형을 분류한다.

        Args:
            result: 실패한 실행 결과
            skill: 실패한 스킬 객체 또는 None

        Returns:
            분류된 FailureType
        """
        if skill is None:
            return FailureType.SKILL_MISSING

        if result.exit_code == -1:
            return FailureType.TIMEOUT

        stderr_failure = self._check_stderr(result.stderr)
        if stderr_failure is not None:
            return stderr_failure

        if "Invalid JSON output" in result.error:
            return FailureType.OUTPUT_INVALID

        return FailureType.UNKNOWN

    def _check_stderr(self, stderr: str) -> FailureType | None:
        """stderr 내용에서 키워드를 찾아 실패 유형을 반환한다.

        Args:
            stderr: stderr 문자열

        Returns:
            매칭된 FailureType 또는 None
        """
        input_mismatch_keywords = (
            "TypeError",
            "KeyError",
            "ValidationError",
            "missing",
            "required",
            "schema",
        )
        execution_error_keywords = (
            "ValueError",
            "AttributeError",
            "IndexError",
            "ModuleNotFoundError",
            "ImportError",
            "PermissionError",
            "FileNotFoundError",
            "RuntimeError",
            "ZeroDivisionError",
        )

        for keyword in input_mismatch_keywords:
            if keyword in stderr:
                return FailureType.INPUT_MISMATCH

        for keyword in execution_error_keywords:
            if keyword in stderr:
                return FailureType.EXECUTION_ERROR

        return None

    def _build_report(
        self,
        result: ExecutionResult,
        skill: Skill | None,
        failure_type: FailureType,
    ) -> AutopsyReport:
        """분류된 실패 유형으로 AutopsyReport를 구성한다.

        Args:
            result: 실패한 실행 결과
            skill: 실패한 스킬 객체 또는 None
            failure_type: 분류된 실패 유형

        Returns:
            구성된 AutopsyReport
        """
        del skill
        stderr_summary = result.stderr[:500]

        if failure_type == FailureType.SKILL_MISSING:
            return AutopsyReport(
                skill_id=result.skill_id,
                failure_type=failure_type,
                root_cause="No skill available to handle this task",
                stderr_summary=stderr_summary,
                recommendation="Search registry for matching skill or absorb from external source",
                needed_skill=SkillNeed(
                    domain="unknown",
                    tags=[],
                    description="Skill needed for task execution",
                ),
                retry_suggested=False,
                fitness_penalty=0.0,
            )

        if failure_type == FailureType.TIMEOUT:
            return AutopsyReport(
                skill_id=result.skill_id,
                failure_type=failure_type,
                root_cause="Skill execution exceeded timeout limit",
                stderr_summary=stderr_summary,
                recommendation="Consider increasing timeout or optimizing skill code",
                needed_skill=None,
                retry_suggested=True,
                fitness_penalty=0.3,
            )

        if failure_type == FailureType.INPUT_MISMATCH:
            return AutopsyReport(
                skill_id=result.skill_id,
                failure_type=failure_type,
                root_cause="Input data does not match skill's expected interface",
                stderr_summary=stderr_summary,
                recommendation="Validate input against interface schema before execution",
                needed_skill=None,
                retry_suggested=False,
                fitness_penalty=0.1,
            )

        if failure_type == FailureType.EXECUTION_ERROR:
            return AutopsyReport(
                skill_id=result.skill_id,
                failure_type=failure_type,
                root_cause="Runtime error during skill execution",
                stderr_summary=stderr_summary,
                recommendation="Check skill code for bugs or missing dependencies",
                needed_skill=None,
                retry_suggested=False,
                fitness_penalty=0.5,
            )

        if failure_type == FailureType.OUTPUT_INVALID:
            return AutopsyReport(
                skill_id=result.skill_id,
                failure_type=failure_type,
                root_cause="Skill produced output that is not valid JSON",
                stderr_summary=stderr_summary,
                recommendation="Fix skill's output formatting",
                needed_skill=None,
                retry_suggested=False,
                fitness_penalty=0.4,
            )

        return AutopsyReport(
            skill_id=result.skill_id,
            failure_type=FailureType.UNKNOWN,
            root_cause="Could not determine failure cause",
            stderr_summary=stderr_summary,
            recommendation="Manual inspection required",
            needed_skill=None,
            retry_suggested=True,
            fitness_penalty=0.2,
        )
