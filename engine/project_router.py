"""Cambrian 프로젝트 모드 라우터와 실행 가능한 TaskSpec 빌더."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from engine.brain.models import TaskSpec
from engine.project_memory import default_memory_path
from engine.project_memory_router import MemoryAwareSkillTuner

logger = logging.getLogger(__name__)


INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "bug_fix": (
        "fix",
        "bug",
        "error",
        "failing",
        "broken",
        "로그인 에러",
        "오류",
        "버그",
        "실패",
        "수정",
    ),
    "test_generation": (
        "test",
        "pytest",
        "regression",
        "coverage",
        "테스트",
        "회귀 테스트",
    ),
    "small_refactor": (
        "refactor",
        "cleanup",
        "simplify",
        "정리",
        "리팩터링",
        "개선",
    ),
    "docs_update": (
        "docs",
        "readme",
        "문서",
        "설명",
        "changelog",
    ),
    "review_candidate": (
        "review",
        "compare",
        "choose",
        "pr",
        "후보",
        "비교",
        "골라",
        "더 안전한",
    ),
}

INTENT_DEFAULT_SKILLS: dict[str, list[str]] = {
    "bug_fix": ["bug_fix", "regression_test", "review_candidate"],
    "test_generation": ["regression_test", "test_generation", "review_candidate"],
    "small_refactor": ["small_refactor", "regression_test", "review_candidate"],
    "docs_update": ["docs_update", "review_candidate"],
    "review_candidate": ["review_candidate"],
    "unknown": [],
}


@dataclass
class SkillRoute:
    """선택된 스킬 후보."""

    skill_id: str
    score: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunIntent:
    """자연어 요청 해석 결과."""

    intent_type: str
    confidence: float
    routes: list[SkillRoute]
    required_context: list[str]
    safety_warnings: list[str]
    execution_readiness: str
    memory_context: dict = field(default_factory=dict)

    def selected_skills(self) -> list[str]:
        return [route.skill_id for route in self.routes]

    def to_dict(self) -> dict:
        return {
            "intent_type": self.intent_type,
            "confidence": self.confidence,
            "selected_skills": self.selected_skills(),
            "required_context": list(self.required_context),
            "safety_warnings": list(self.safety_warnings),
            "execution_readiness": self.execution_readiness,
            "routes": [route.to_dict() for route in self.routes],
            "memory_context": dict(self.memory_context),
        }


@dataclass
class TaskSpecBuildResult:
    """TaskSpec 빌드 결과."""

    task_spec: TaskSpec
    routing: dict
    action_payloads: list[dict] = field(default_factory=list)


class ProjectSkillRouter:
    """프로젝트 문맥 기반 rule-based 스킬 라우터."""

    def route(
        self,
        user_request: str,
        project_config: dict,
        rules: dict,
        skills: dict,
        profile: dict,
        explicit_options: dict | None = None,
    ) -> RunIntent:
        """자연어 요청을 분류하고 실행 준비도를 판단한다."""
        del project_config, profile
        options = explicit_options or {}
        request_text = user_request.lower()
        intent_type, hit_count = self._classify_intent(request_text)
        confidence = 0.25 if intent_type == "unknown" else min(0.98, 0.55 + hit_count * 0.12)

        available_skill_ids = self._available_skill_ids(skills)
        explicit_skills = [str(item) for item in options.get("skill_ids", []) if item]
        selected_skills: list[str] = []
        route_reason: dict[str, str] = {}
        warnings: list[str] = []

        for skill_id in explicit_skills:
            if skill_id in available_skill_ids:
                selected_skills.append(skill_id)
                route_reason[skill_id] = "사용자가 명시적으로 요청한 스킬"
            else:
                warnings.append(f"알 수 없는 스킬을 건너뜁니다: {skill_id}")

        default_skills = list(skills.get("selection", {}).get("default", []))
        intent_skills = INTENT_DEFAULT_SKILLS.get(intent_type, [])
        if not intent_skills:
            intent_skills = default_skills or ["bug_fix", "review_candidate"]

        for skill_id in intent_skills:
            if skill_id in available_skill_ids:
                selected_skills.append(skill_id)
                route_reason.setdefault(skill_id, f"{intent_type} 작업에 기본 추천되는 스킬")
            elif skill_id == "docs_update" and "review_candidate" in available_skill_ids:
                selected_skills.append("review_candidate")
                route_reason.setdefault(
                    "review_candidate",
                    "문서 업데이트 전용 스킬이 없어 review_candidate로 대체",
                )

        if not selected_skills:
            selected_skills = default_skills or ["bug_fix", "review_candidate"]
            for skill_id in selected_skills:
                route_reason.setdefault(skill_id, "기본 스킬 선택")

        selected_skills = _dedupe(selected_skills)

        readiness, required_context, safety_messages = self._determine_readiness(
            intent_type=intent_type,
            rules=rules,
            options=options,
        )
        warnings.extend(safety_messages)

        routes: list[SkillRoute] = []
        base_score = 0.95
        for index, skill_id in enumerate(selected_skills):
            routes.append(
                SkillRoute(
                    skill_id=skill_id,
                    score=max(0.1, round(base_score - index * 0.08, 2)),
                    reason=route_reason.get(skill_id, "요청과 프로젝트 문맥을 기준으로 선택"),
                )
            )

        project_root_value = options.get("project_root")
        lessons_path = (
            default_memory_path(Path(project_root_value).resolve())
            if project_root_value else None
        )
        memory_context = MemoryAwareSkillTuner().build_context(
            user_request=user_request,
            lessons_path=lessons_path,
            available_skills=available_skill_ids,
            intent_type=intent_type,
        )
        routes = MemoryAwareSkillTuner().apply_adjustments(
            routes,
            memory_context,
            route_factory=SkillRoute,
        )
        warnings.extend(memory_context.warnings)

        return RunIntent(
            intent_type=intent_type,
            confidence=round(confidence, 2),
            routes=routes,
            required_context=required_context,
            safety_warnings=_dedupe(warnings),
            execution_readiness=readiness,
            memory_context=memory_context.to_dict(),
        )

    @staticmethod
    def _classify_intent(request_text: str) -> tuple[str, int]:
        hits_by_intent: dict[str, int] = {}
        for intent_type, keywords in INTENT_KEYWORDS.items():
            hits = sum(1 for keyword in keywords if keyword in request_text)
            if hits > 0:
                hits_by_intent[intent_type] = hits

        if not hits_by_intent:
            return "unknown", 0

        best_intent = max(
            hits_by_intent.items(),
            key=lambda item: (item[1], item[0] == "review_candidate"),
        )
        return best_intent[0], best_intent[1]

    @staticmethod
    def _available_skill_ids(skills_payload: dict) -> set[str]:
        available: set[str] = set()
        for item in skills_payload.get("recommended_skills", []):
            if isinstance(item, dict) and item.get("id"):
                available.add(str(item["id"]))
        available.update(
            str(item)
            for item in skills_payload.get("selection", {}).get("default", [])
            if item
        )
        return available

    def _determine_readiness(
        self,
        *,
        intent_type: str,
        rules: dict,
        options: dict,
    ) -> tuple[str, list[str], list[str]]:
        action = str(options.get("action") or "none")
        target = str(options.get("target") or "")
        content = options.get("content")
        content_file = options.get("content_file")
        old_text = options.get("old_text")
        new_text = options.get("new_text")
        warnings: list[str] = []
        required_context: list[str] = []

        if content and content_file:
            return "blocked", [], ["--content와 --content-file을 동시에 사용할 수 없습니다."]

        if action not in {"none", "write_file", "patch_file"}:
            return "blocked", [], [f"지원하지 않는 action 입니다: {action}"]

        if action == "none":
            if intent_type == "review_candidate":
                return "review_only", [], warnings
            if intent_type == "unknown":
                return "needs_context", ["target_file", "expected_behavior"], warnings
            if intent_type == "docs_update":
                return "needs_context", ["target_file", "expected_behavior"], warnings
            if intent_type in {"bug_fix", "small_refactor"}:
                return "needs_context", ["target_file", "related_tests"], warnings
            return "needs_context", ["target_file", "patch_content"], warnings

        if not target:
            return "needs_context", ["target_file"], warnings

        safety_issue = self._validate_target_path(target, rules, options)
        if safety_issue is not None:
            return "blocked", [], [safety_issue]

        for test_path in options.get("tests", []) or []:
            test_issue = self._validate_target_path(
                str(test_path),
                rules,
                options,
                allow_protected=False,
            )
            if test_issue is not None:
                return "blocked", [], [f"안전하지 않은 테스트 경로: {test_issue}"]

        for output_path in options.get("outputs", []) or []:
            output_issue = self._validate_target_path(str(output_path), rules, options)
            if output_issue is not None:
                return "blocked", [], [f"안전하지 않은 출력 경로: {output_issue}"]

        if action == "write_file":
            if content is None and content_file is None:
                return "needs_context", ["patch_content"], warnings
            if content_file and not Path(content_file).exists():
                return "blocked", [], [f"content file을 찾을 수 없습니다: {content_file}"]
            return "executable", [], warnings

        if old_text is None or new_text is None:
            return "needs_context", ["patch_content"], warnings
        return "executable", [], warnings

    @staticmethod
    def _validate_target_path(
        target: str,
        rules: dict,
        options: dict,
        *,
        allow_protected: bool = True,
    ) -> str | None:
        if not target:
            return "빈 target path는 허용되지 않습니다."
        path = Path(target)
        if path.is_absolute():
            return f"절대 경로는 허용되지 않습니다: {target}"
        if ".." in path.parts:
            return f"상위 경로 참조는 허용되지 않습니다: {target}"

        protect_paths = list(rules.get("workspace", {}).get("protect_paths", []))
        if allow_protected:
            for protected in protect_paths:
                if protected and (
                    target == protected or target.startswith(f"{protected}/") or target.startswith(f"{protected}\\")
                ):
                    return f"보호 경로는 수정할 수 없습니다: {target}"

        project_root = Path(options.get("project_root") or Path.cwd()).resolve()
        candidate = (project_root / path).resolve()
        try:
            candidate.relative_to(project_root)
        except ValueError:
            return f"프로젝트 밖 경로는 허용되지 않습니다: {target}"
        return None


class ExecutableTaskSpecBuilder:
    """RunIntent를 실행 가능한 TaskSpec 초안으로 변환한다."""

    def build(
        self,
        user_request: str,
        run_intent: RunIntent,
        project_config: dict,
        options: dict,
        request_id: str,
    ) -> TaskSpecBuildResult:
        """TaskSpec과 routing 메타데이터를 생성한다."""
        related_tests = [str(item) for item in options.get("tests", []) if item]
        output_paths = [str(item) for item in options.get("outputs", []) if item]
        target = str(options.get("target") or "")
        action = str(options.get("action") or "none")

        action_payloads: list[dict] = []
        if run_intent.execution_readiness == "executable":
            action_payload = self._build_action_payload(action, target, options)
            if action_payload is not None:
                action_payloads.append(action_payload)
            if target and target not in output_paths:
                output_paths.append(target)

        if run_intent.execution_readiness == "needs_context":
            scope = [
                "Prepare a safe run for the request",
                "Collect missing context before execution",
            ]
        elif run_intent.execution_readiness == "review_only":
            scope = [
                "Review and compare provided approaches safely",
                "Avoid direct execution until inputs are clarified",
            ]
        else:
            scope = [
                "Execute the explicit action safely",
                "Run related tests if provided",
            ]

        acceptance_criteria = [
            "Relevant tests pass if provided",
            "Change is small and reviewable",
            "No automatic adoption occurs",
        ]
        if run_intent.intent_type == "review_candidate":
            acceptance_criteria = [
                "Safer approach is identified",
                "No automatic adoption occurs",
            ]

        hypothesis = self._build_hypothesis(
            request_id=request_id,
            user_request=user_request,
            run_intent=run_intent,
            related_tests=related_tests,
        )

        task_spec = TaskSpec(
            task_id=f"task-{request_id}",
            goal=user_request,
            scope=scope,
            acceptance_criteria=acceptance_criteria,
            related_tests=related_tests,
            output_paths=output_paths,
            hypothesis=hypothesis,
            competitive={"enabled": False},
            generation_seed=None,
            selection_pressure=None,
            actions=action_payloads or None,
        )

        routing = {
            "intent_type": run_intent.intent_type,
            "confidence": run_intent.confidence,
            "selected_skills": run_intent.selected_skills(),
            "execution_readiness": run_intent.execution_readiness,
            "required_context": list(run_intent.required_context),
            "safety_warnings": list(run_intent.safety_warnings),
            "routes": [route.to_dict() for route in run_intent.routes],
            "memory_context": dict(run_intent.memory_context),
        }
        if project_config.get("test", {}).get("command"):
            routing["test_command"] = project_config["test"]["command"]

        return TaskSpecBuildResult(
            task_spec=task_spec,
            routing=routing,
            action_payloads=action_payloads,
        )

    @staticmethod
    def _build_action_payload(action: str, target: str, options: dict) -> dict | None:
        if action == "write_file":
            content = options.get("content")
            if content is None and options.get("content_file"):
                content = Path(options["content_file"]).read_text(encoding="utf-8")
            return {
                "type": "write_file",
                "target_path": target,
                "content": content or "",
            }
        if action == "patch_file":
            return {
                "type": "patch_file",
                "target_path": target,
                "old_text": str(options.get("old_text") or ""),
                "new_text": str(options.get("new_text") or ""),
            }
        return None

    @staticmethod
    def _build_hypothesis(
        *,
        request_id: str,
        user_request: str,
        run_intent: RunIntent,
        related_tests: list[str],
    ) -> dict | None:
        if run_intent.intent_type == "review_candidate":
            return None

        statement = (
            "A small, related change should address the request "
            "without failing related tests."
        )
        if run_intent.intent_type == "test_generation":
            statement = (
                "Creating the requested test artifact should keep related tests passing."
            )
        elif run_intent.intent_type == "docs_update":
            statement = (
                "The documentation change should stay reviewable and avoid unsafe side effects."
            )
        elif run_intent.intent_type == "small_refactor":
            statement = (
                "A small refactor should improve the target area without breaking related tests."
            )
        elif run_intent.intent_type == "unknown":
            statement = (
                "The request should be clarified before execution to avoid unsafe changes."
            )

        predicts: dict = {"tests": {"failed_max": 0}}
        if related_tests:
            predicts["tests"]["passed_min"] = 1

        return {
            "id": f"hyp-{request_id}",
            "statement": statement,
            "predicts": predicts,
            "source_request": user_request,
        }


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
