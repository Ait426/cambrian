"""Cambrian 엔진 커스텀 예외."""


class CambrianError(Exception):
    """모든 Cambrian 예외의 베이스."""


class SkillLoadError(CambrianError):
    """스킬 로드 실패. 파일 누락, 파싱 에러 등."""

    def __init__(self, skill_path: str, reason: str):
        self.skill_path = skill_path
        self.reason = reason
        super().__init__(f"Failed to load skill at '{skill_path}': {reason}")


class SkillValidationError(CambrianError):
    """스킬 검증 실패. schema 위반 등."""

    def __init__(self, skill_path: str, errors: list[str]):
        self.skill_path = skill_path
        self.errors = errors
        super().__init__(
            f"Skill validation failed at '{skill_path}': {'; '.join(errors)}"
        )


class SkillExecutionError(CambrianError):
    """스킬 실행 실패."""

    def __init__(self, skill_id: str, reason: str, stderr: str = ""):
        self.skill_id = skill_id
        self.reason = reason
        self.stderr = stderr
        super().__init__(f"Skill '{skill_id}' execution failed: {reason}")


class SkillNotFoundError(CambrianError):
    """Registry에서 스킬을 찾지 못함."""

    def __init__(self, query: str):
        self.query = query
        super().__init__(f"No skill found matching: {query}")


class SecurityViolationError(CambrianError):
    """보안 검사 위반."""

    def __init__(self, skill_path: str, violations: list[str]):
        self.skill_path = skill_path
        self.violations = violations
        super().__init__(
            f"Security violations in '{skill_path}': {'; '.join(violations)}"
        )
