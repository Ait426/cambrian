"""Cambrian 하네스 부트스트래퍼.

프로젝트 scan 결과를 바탕으로 검증 하네스 초안을 생성한다.
산출물: harness.yaml, eval_cases.jsonl, judge_rubric.md,
       promotion_policy.json, rollback_policy.json,
       candidate mapping report.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.models import (
    CapabilityGap,
    ProjectFingerprint,
    ProjectScanReport,
    SkillSuggestion,
)

logger = logging.getLogger(__name__)

CAMBRIAN_VERSION = "0.3.0"


class HarnessBootstrapper:
    """프로젝트 scan 결과로 하네스 아티팩트를 생성한다."""

    def __init__(
        self,
        registry_skills: list[dict] | None = None,
    ) -> None:
        """초기화.

        Args:
            registry_skills: 현재 등록된 스킬 목록 (registry.list_all() 결과).
                             candidate mapping에 사용. None이면 매핑 스킵.
        """
        self._registry_skills = registry_skills or []

    def bootstrap(
        self,
        report: ProjectScanReport,
        output_dir: str | Path,
    ) -> dict:
        """하네스 아티팩트를 생성하고 디스크에 저장한다.

        Args:
            report: 프로젝트 scan 결과
            output_dir: 프로젝트 루트 경로. .cambrian/ 하위에 생성.

        Returns:
            bootstrap 결과 dict:
            - files_created: list[str]
            - focus_areas: list[dict]
            - gap_candidate_mapping: dict
            - next_actions: list[str]
            - generated_at: str
        """
        project_root = Path(output_dir)
        harness_dir = project_root / ".cambrian" / "harness"
        reports_dir = project_root / ".cambrian" / "reports"
        harness_dir.mkdir(parents=True, exist_ok=True)
        reports_dir.mkdir(parents=True, exist_ok=True)

        fp = report.fingerprint
        gaps = report.gaps
        suggestions = report.suggestions
        timestamp = datetime.now(timezone.utc).isoformat()

        files_created: list[str] = []

        # 1. harness.yaml
        harness_yaml = self._generate_harness_yaml(fp, gaps, timestamp)
        path = harness_dir / "harness.yaml"
        path.write_text(
            yaml.safe_dump(harness_yaml, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        files_created.append(str(path.relative_to(project_root)))

        # 2. eval_cases.jsonl
        eval_cases = self._generate_eval_cases(fp, gaps)
        path = harness_dir / "eval_cases.jsonl"
        lines = [json.dumps(c, ensure_ascii=False) for c in eval_cases]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        files_created.append(str(path.relative_to(project_root)))

        # 3. judge_rubric.md
        rubric = self._generate_judge_rubric(fp, gaps)
        path = harness_dir / "judge_rubric.md"
        path.write_text(rubric, encoding="utf-8")
        files_created.append(str(path.relative_to(project_root)))

        # 4. promotion_policy.json
        promo = self._generate_promotion_policy()
        path = harness_dir / "promotion_policy.json"
        path.write_text(
            json.dumps(promo, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        files_created.append(str(path.relative_to(project_root)))

        # 5. rollback_policy.json
        rollback = self._generate_rollback_policy()
        path = harness_dir / "rollback_policy.json"
        path.write_text(
            json.dumps(rollback, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        files_created.append(str(path.relative_to(project_root)))

        # 6. candidate mapping
        candidate_mapping = self._generate_candidate_mapping(
            gaps, suggestions,
        )

        # 7. next actions
        next_actions = self._generate_next_actions(fp, gaps, candidate_mapping)

        # 8. bootstrap report 저장
        bootstrap_report = {
            "project_name": fp.project_name,
            "project_path": fp.project_path,
            "generated_at": timestamp,
            "cambrian_version": CAMBRIAN_VERSION,
            "focus_areas": [
                {"category": g.category, "priority": g.priority}
                for g in gaps
            ],
            "gap_candidate_mapping": candidate_mapping,
            "next_actions": next_actions,
            "files_created": files_created,
            "scan_summary": {
                "total_gaps": report.total_gaps,
                "covered_gaps": report.covered_gaps,
                "uncovered_gaps": report.uncovered_gaps,
            },
        }
        report_path = reports_dir / "latest_harness_bootstrap.json"
        report_path.write_text(
            json.dumps(bootstrap_report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        files_created.append(str(report_path.relative_to(project_root)))

        logger.info(
            "하네스 부트스트랩 완료: %s (%d 아티팩트, %d eval cases)",
            fp.project_name,
            len(files_created),
            len(eval_cases),
        )

        return bootstrap_report

    # ───────────────────────────────────────────────────────────
    # 아티팩트 생성 메서드
    # ───────────────────────────────────────────────────────────

    def _generate_harness_yaml(
        self,
        fp: ProjectFingerprint,
        gaps: list[CapabilityGap],
        timestamp: str,
    ) -> dict:
        """harness.yaml 내용을 생성한다."""
        focus_descriptions: dict[str, str] = {
            "testing": "테스트 자동화 역량 검증 및 개선",
            "documentation": "문서화 역량 검증 및 개선",
            "ci_cd": "CI/CD 파이프라인 역량 검증",
            "containerization": "컨테이너화 역량 검증",
            "linting": "코드 품질 도구 역량 검증",
            "type_checking": "타입 검사 역량 검증",
            "api_documentation": "API 문서 역량 검증",
        }

        focus_areas: list[dict] = []
        for gap in gaps:
            focus_areas.append({
                "category": gap.category,
                "priority": gap.priority,
                "description": focus_descriptions.get(
                    gap.category, gap.description,
                ),
            })

        # 목표 문장
        if focus_areas:
            area_names = ", ".join(fa["category"] for fa in focus_areas[:3])
            objective = f"프로젝트의 {area_names} 역량을 검증하고 개선한다."
        else:
            objective = "프로젝트의 전반적 엔지니어링 역량을 검증한다."

        return {
            "project": {
                "name": fp.project_name,
                "path": fp.project_path,
                "language": fp.primary_language,
                "frameworks": fp.frameworks,
            },
            "objective": objective,
            "focus_areas": focus_areas,
            "artifacts": {
                "eval_cases": "eval_cases.jsonl",
                "judge_rubric": "judge_rubric.md",
                "promotion_policy": "promotion_policy.json",
                "rollback_policy": "rollback_policy.json",
                "replay_cases": None,
            },
            "generated_at": timestamp,
            "cambrian_version": CAMBRIAN_VERSION,
        }

    def _generate_eval_cases(
        self,
        fp: ProjectFingerprint,
        gaps: list[CapabilityGap],
    ) -> list[dict]:
        """eval_cases.jsonl 행 목록을 생성한다."""
        cases: list[dict] = []
        case_id = 1

        for gap in gaps:
            case = self._create_eval_case_for_gap(fp, gap, case_id)
            if case:
                cases.append(case)
                case_id += 1

            # gap당 최대 2개
            second = self._create_secondary_eval_case(fp, gap, case_id)
            if second:
                cases.append(second)
                case_id += 1

        # 최소 1개 보장
        if not cases:
            cases.append({
                "id": "eval_001",
                "category": "general",
                "task_domain": "utility",
                "task_tags": ["test", "utility"],
                "input": {"text": fp.project_name},
                "description": "기본 프로젝트 검증",
                "expected_behavior": "정상 실행 및 결과 반환",
            })

        return cases

    def _create_eval_case_for_gap(
        self,
        fp: ProjectFingerprint,
        gap: CapabilityGap,
        case_id: int,
    ) -> dict | None:
        """gap 유형에 맞는 1차 eval case를 생성한다."""
        templates: dict[str, dict] = {
            "testing": {
                "task_domain": "testing",
                "task_tags": ["test", "pytest", "scaffold", "unit_test"],
                "input": {
                    "source_code": "def main():\n    pass\n",
                    "module_name": "main",
                },
                "description": "기본 함수에 대한 테스트 스캔폴드 생성",
                "expected_behavior": "test_code 필드에 유효한 pytest 코드 포함",
            },
            "documentation": {
                "task_domain": "documentation",
                "task_tags": ["readme", "docs", "documentation", "markdown"],
                "input": {
                    "project_name": fp.project_name,
                    "file_tree": fp.key_files[:10] if fp.key_files else [],
                    "language": fp.primary_language,
                },
                "description": "프로젝트 README 초안 생성",
                "expected_behavior": "readme_content에 프로젝트 구조와 사용법 포함",
            },
            "ci_cd": {
                "task_domain": "deployment",
                "task_tags": ["ci", "cd", "github_actions"],
                "input": {
                    "project_name": fp.project_name,
                    "language": fp.primary_language,
                },
                "description": "CI/CD 파이프라인 설정 초안 생성",
                "expected_behavior": "유효한 CI 설정 파일 내용 포함",
            },
        }

        template = templates.get(gap.category)
        if not template:
            # 범용 케이스
            template = {
                "task_domain": gap.suggested_domain,
                "task_tags": gap.suggested_tags,
                "input": {"project_name": fp.project_name},
                "description": gap.description,
                "expected_behavior": "관련 산출물이 정상 생성됨",
            }

        return {
            "id": f"eval_{case_id:03d}",
            "category": gap.category,
            **template,
        }

    def _create_secondary_eval_case(
        self,
        fp: ProjectFingerprint,
        gap: CapabilityGap,
        case_id: int,
    ) -> dict | None:
        """gap에 대한 2차 eval case (선택적)."""
        secondary: dict[str, dict] = {
            "testing": {
                "task_domain": "testing",
                "task_tags": ["test", "pytest", "unit_test"],
                "input": {
                    "source_code": (
                        "class Calculator:\n"
                        "    def add(self, a: int, b: int) -> int:\n"
                        "        return a + b\n"
                    ),
                    "module_name": "calculator",
                },
                "description": "클래스 메서드에 대한 테스트 스캔폴드 생성",
                "expected_behavior": "클래스 fixture와 메서드별 테스트 포함",
            },
            "documentation": {
                "task_domain": "documentation",
                "task_tags": ["summary", "analysis", "documentation"],
                "input": {
                    "project_name": fp.project_name,
                    "file_tree": fp.key_files[:10] if fp.key_files else [],
                },
                "description": "프로젝트 구조 요약 생성",
                "expected_behavior": "summary에 핵심 구성요소와 통계 포함",
            },
        }

        template = secondary.get(gap.category)
        if not template:
            return None

        return {
            "id": f"eval_{case_id:03d}",
            "category": gap.category,
            **template,
        }

    def _generate_judge_rubric(
        self,
        fp: ProjectFingerprint,
        gaps: list[CapabilityGap],
    ) -> str:
        """judge_rubric.md 내용을 생성한다."""
        lines = [
            f"# Judge Rubric — {fp.project_name}",
            "",
            f"프로젝트 유형: {fp.primary_language} | "
            f"파일 수: {fp.total_files}",
            "",
        ]

        rubric_templates: dict[str, list[str]] = {
            "testing": [
                "## testing 과제 판정 기준",
                "",
                "- 생성된 테스트 코드가 Python 문법적으로 유효한가",
                "- 원본 함수/클래스명이 import 구문에 포함되어 있는가",
                "- 최소 1개 이상의 test_ 함수가 있는가",
                "- assertion이 포함되어 있는가",
                "",
            ],
            "documentation": [
                "## documentation 과제 판정 기준",
                "",
                "- 프로젝트 이름이 문서에 포함되어 있는가",
                "- 설치 또는 사용법 섹션이 있는가",
                "- 프로젝트 구조가 반영되어 있는가",
                "- 마크다운 형식이 유효한가",
                "",
            ],
            "ci_cd": [
                "## ci_cd 과제 판정 기준",
                "",
                "- CI 설정 파일 형식이 유효한가",
                "- 빌드/테스트 단계가 포함되어 있는가",
                "- 프로젝트 언어에 맞는 도구가 사용되었는가",
                "",
            ],
        }

        for gap in gaps:
            template = rubric_templates.get(gap.category)
            if template:
                lines.extend(template)
            else:
                lines.extend([
                    f"## {gap.category} 과제 판정 기준",
                    "",
                    f"- {gap.description}에 대한 결과가 유효한가",
                    "- 산출물이 프로젝트 컨텍스트에 맞는가",
                    "",
                ])

        if not gaps:
            lines.extend([
                "## 일반 판정 기준",
                "",
                "- 실행이 정상 완료되었는가",
                "- 출력 형식이 유효한가",
                "",
            ])

        return "\n".join(lines)

    def _generate_promotion_policy(self) -> dict:
        """promotion_policy.json 기본값."""
        return {
            "_comment": "하네스 승격 정책 — 프로젝트별 조정 가능",
            "min_success_rate": 0.70,
            "min_eval_pass_rate": 0.60,
            "min_executions_for_promote": 10,
            "auto_promote": False,
        }

    def _generate_rollback_policy(self) -> dict:
        """rollback_policy.json 기본값."""
        return {
            "_comment": "하네스 롤백 정책 — 프로젝트별 조정 가능",
            "rollback_fitness_threshold": 0.2,
            "max_consecutive_failures": 3,
            "auto_rollback": True,
        }

    def _generate_candidate_mapping(
        self,
        gaps: list[CapabilityGap],
        suggestions: list[SkillSuggestion],
    ) -> dict:
        """gap별 후보 스킬 매핑을 생성한다."""
        mapping: dict[str, dict] = {}

        for gap in gaps:
            # scan suggestions에서 매칭
            gap_suggestions = [
                s for s in suggestions
                if s.gap_category == gap.category
            ]

            # registry에서 추가 매칭 (domain/tags 기반)
            registry_matches = self._search_registry_for_gap(gap)

            # 중복 제거 후 병합
            seen_ids: set[str] = set()
            candidates: list[dict] = []

            for s in gap_suggestions:
                if s.skill_id not in seen_ids:
                    seen_ids.add(s.skill_id)
                    candidates.append({
                        "skill_id": s.skill_id,
                        "skill_name": s.skill_name,
                        "mode": "unknown",
                        "relevance": round(s.relevance_score, 2),
                        "source": s.source,
                    })

            for skill in registry_matches:
                sid = skill.get("id", "")
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    candidates.append({
                        "skill_id": sid,
                        "skill_name": skill.get("name", ""),
                        "mode": skill.get("mode", "unknown"),
                        "relevance": 0.5,
                        "source": "registry",
                    })

            if candidates:
                status = "candidates_available"
            else:
                status = "no_viable_candidate_currently_available"

            mapping[gap.category] = {
                "candidates": candidates,
                "status": status,
                "suggested_domain": gap.suggested_domain,
                "suggested_tags": gap.suggested_tags,
            }

        return mapping

    def _search_registry_for_gap(self, gap: CapabilityGap) -> list[dict]:
        """registry 스킬 중 gap에 매칭되는 것을 찾는다."""
        matches: list[dict] = []
        gap_tags = set(gap.suggested_tags)
        gap_domain = gap.suggested_domain

        for skill in self._registry_skills:
            skill_domain = skill.get("domain", "")
            raw_tags = skill.get("tags", [])
            skill_tags = set(raw_tags if isinstance(raw_tags, list) else [])

            # 도메인 일치 또는 태그 교집합
            if skill_domain == gap_domain or gap_tags & skill_tags:
                matches.append(skill)

        return matches

    def _generate_next_actions(
        self,
        fp: ProjectFingerprint,
        gaps: list[CapabilityGap],
        candidate_mapping: dict,
    ) -> list[str]:
        """bootstrap 후 사용자에게 보여줄 추천 액션을 생성한다."""
        actions: list[str] = []

        for gap in gaps[:3]:
            mapping = candidate_mapping.get(gap.category, {})
            candidates = mapping.get("candidates", [])

            if candidates:
                best = candidates[0]
                sid = best["skill_id"]
                domain = gap.suggested_domain
                tags = " ".join(gap.suggested_tags[:3])
                actions.append(
                    f"cambrian run --domain {domain} --tags {tags} "
                    f"-i '{{...}}'"
                    f"  # {gap.category} gap → {sid}"
                )
            else:
                actions.append(
                    f"cambrian search \"{gap.search_query}\""
                    f"  # {gap.category} gap 후보 탐색"
                )

        # benchmark 추천
        if gaps:
            top_gap = gaps[0]
            top_mapping = candidate_mapping.get(top_gap.category, {})
            if len(top_mapping.get("candidates", [])) >= 2:
                domain = top_gap.suggested_domain
                tags = " ".join(top_gap.suggested_tags[:3])
                actions.append(
                    f"cambrian benchmark --domain {domain} "
                    f"--tags {tags} -i '{{...}}'"
                    f"  # {top_gap.category} 후보 비교"
                )

        # 일반 안내
        actions.append(
            "cambrian skills  # 전체 스킬 목록 확인"
        )

        return actions
