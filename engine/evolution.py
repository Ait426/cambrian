"""Cambrian 진화 코어."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.executor import SkillExecutor
from engine.judge import SkillJudge
from engine.llm import LLMProvider, create_provider
from engine.loader import SkillLoader
from engine.models import EvolutionRecord, ExecutionResult, JudgeVerdict, Skill
from engine.registry import SkillRegistry

logger = logging.getLogger(__name__)


class SkillEvolver:
    """스킬의 SKILL.md를 LLM으로 변이시키고 벤치마크로 비교한다."""

    TRIAL_COUNT: int = 3  # 진화 비교 시행 횟수

    def __init__(
        self,
        loader: SkillLoader,
        executor: SkillExecutor,
        registry: SkillRegistry,
        provider: LLMProvider | None = None,
    ) -> None:
        """초기화.

        Args:
            loader: SkillLoader 인스턴스
            executor: SkillExecutor 인스턴스
            registry: SkillRegistry 인스턴스
            provider: LLM 프로바이더. None이면 mutate 시 자동 생성.
        """
        self._loader = loader
        self._executor = executor
        self._registry = registry
        self._provider = provider

    def mutate(self, skill: Skill, feedback_list: list[dict]) -> str:
        """LLM에게 기존 SKILL.md + 피드백을 보내고 개선된 SKILL.md를 받는다.

        Args:
            skill: 원본 Skill 객체
            feedback_list: registry.get_feedback()가 반환한 dict 리스트

        Returns:
            개선된 SKILL.md 내용

        Raises:
            RuntimeError: anthropic 패키지 미설치 또는 API 키 미설정 시
            RuntimeError: LLM 호출 실패 시
        """
        if skill.skill_md_content is None:
            raise RuntimeError("SKILL.md content is empty")

        feedback_lines: list[str] = []
        for feedback in feedback_list:
            line = f"Rating: {feedback['rating']}/5 | Comment: {feedback['comment']}"
            input_data = feedback.get("input_data")
            if input_data and input_data != "{}":
                line += f"\nInput: {input_data}"
            output_data = feedback.get("output_data")
            if output_data and output_data != "{}":
                truncated = output_data[:200] + ("..." if len(output_data) > 200 else "")
                line += f"\nOutput: {truncated}"
            feedback_lines.append(line)
        formatted_feedback = "\n\n".join(feedback_lines)

        system_prompt = (
            "You are a skill instruction optimizer for the Cambrian engine.\n"
            "You receive a SKILL.md (the current instruction for an LLM) and user feedback on its outputs.\n"
            "Your job: rewrite the SKILL.md to address the feedback and improve output quality.\n\n"
            "CRITICAL RULES:\n"
            "1. COPY the '## Output Format' section EXACTLY as-is. Do NOT modify it at all.\n"
            "2. COPY the '## Input Format' section EXACTLY as-is. Do NOT modify it at all.\n"
            "3. Only improve OTHER sections: design guidance, analysis logic, quality criteria, examples.\n"
            "4. Keep the same JSON keys in the output format (do not rename or remove required keys).\n"
            "5. Add a '## Changelog' section at the very end listing what you changed and why.\n"
            "6. Output ONLY the new SKILL.md content. No explanation, no markdown fences around the whole output."
        )
        user_message = (
            "## Current SKILL.md\n"
            f"{skill.skill_md_content}\n\n"
            "## User Feedback (most recent first)\n"
            f"{formatted_feedback}"
        )

        try:
            provider = self._provider or create_provider()
            mutated_raw = provider.complete(
                system=system_prompt,
                user=user_message,
                max_tokens=8192,
            )
        except Exception as exc:
            raise RuntimeError(f"LLM mutation failed: {exc}") from exc

        mutated = mutated_raw.strip()
        if not mutated:
            raise RuntimeError("LLM mutation returned empty content")

        # Output Format 섹션이 원본과 동일한지 검증, 다르면 강제 복원
        mutated = self._ensure_output_format(mutated, skill.skill_md_content or "")

        return mutated

    @staticmethod
    def _extract_section(md: str, header: str) -> str | None:
        """마크다운에서 특정 ## 섹션을 추출한다.

        Args:
            md: 마크다운 전문
            header: 섹션 헤더 (예: "## Output Format")

        Returns:
            섹션 텍스트 (헤더 포함) 또는 None
        """
        idx = md.find(header)
        if idx == -1:
            return None
        rest = md[idx:]
        next_section = rest.find("\n## ", len(header))
        if next_section != -1:
            return rest[:next_section].rstrip()
        return rest.rstrip()

    def _ensure_output_format(self, mutated: str, original: str) -> str:
        """변이된 SKILL.md의 Output Format 섹션을 원본과 동일하게 보장한다.

        Args:
            mutated: 변이된 SKILL.md
            original: 원본 SKILL.md

        Returns:
            Output Format이 보장된 SKILL.md
        """
        original_section = self._extract_section(original, "## Output Format")
        if original_section is None:
            # 원본에 Output Format 없으면 검증 스킵
            return mutated

        mutated_section = self._extract_section(mutated, "## Output Format")

        if mutated_section == original_section:
            return mutated

        # Output Format이 변경됐거나 누락됨 → 강제 복원
        logger.warning("Output Format section modified by LLM — restoring original.")

        if mutated_section is not None:
            # 변경된 섹션을 원본으로 교체
            mutated = mutated.replace(mutated_section, original_section)
        else:
            # 누락됨 → 끝에 추가
            mutated = mutated.rstrip() + "\n\n" + original_section

        return mutated

    def evolve(
        self,
        skill_id: str,
        test_input: dict,
        feedback_list: list[dict],
    ) -> EvolutionRecord:
        """진화 1회를 실행한다: 변이 → 벤치마크 비교 → 채택/폐기.

        Args:
            skill_id: 진화시킬 스킬 ID
            test_input: 벤치마크에 사용할 테스트 입력
            feedback_list: 이번 진화에 사용할 피드백 리스트

        Returns:
            EvolutionRecord
        """
        variant_dir: Path | None = None
        variant_id = f"{skill_id}_variant"

        skill_data = self._registry.get(skill_id)
        original_skill = self._loader.load(skill_data["skill_path"])
        if original_skill.mode != "a":
            raise RuntimeError("Only mode 'a' skills can evolve")

        parent_skill_md = original_skill.skill_md_content or ""
        parent_fitness = float(skill_data["fitness_score"])
        child_skill_md = self.mutate(original_skill, feedback_list)

        try:
            variant_dir = original_skill.skill_path.parent / variant_id
            if variant_dir.exists():
                shutil.rmtree(variant_dir)
            shutil.copytree(original_skill.skill_path, variant_dir)
            (variant_dir / "SKILL.md").write_text(child_skill_md, encoding="utf-8")

            meta_path = variant_dir / "meta.yaml"
            with open(meta_path, "r", encoding="utf-8") as file:
                meta = yaml.safe_load(file) or {}
            if not isinstance(meta, dict):
                raise RuntimeError(f"Invalid meta.yaml for skill '{skill_id}'")
            meta["id"] = variant_id
            with open(meta_path, "w", encoding="utf-8") as file:
                yaml.safe_dump(meta, file, allow_unicode=True, sort_keys=False)

            # TRIAL_COUNT 횟수만큼 원본/variant 실행 후 Judge로 비교
            variant_skill = self._loader.load(variant_dir)
            judge = SkillJudge(provider=self._provider)
            verdicts: list[JudgeVerdict] = []
            last_original_result: ExecutionResult | None = None

            for _ in range(self.TRIAL_COUNT):
                original_result = self._executor.execute(original_skill, test_input)
                variant_result = self._executor.execute(variant_skill, test_input)
                verdict = judge.judge(
                    original_result.output,
                    variant_result.output,
                    original_skill.description,
                    feedback_list,
                )
                verdicts.append(verdict)
                last_original_result = original_result

            avg_original = sum(v.original_score for v in verdicts) / len(verdicts)
            avg_variant = sum(v.variant_score for v in verdicts) / len(verdicts)
            adopted = avg_variant > avg_original

            # 원본 lifecycle 갱신 (Judge 평균 점수 반영)
            if last_original_result is not None:
                self._registry.update_after_execution(
                    skill_id, last_original_result, judge_score=avg_original
                )

            if adopted:
                (original_skill.skill_path / "SKILL.md").write_text(
                    child_skill_md, encoding="utf-8"
                )
                logger.info("Evolution adopted for skill '%s'", skill_id)
            else:
                logger.info(
                    "Evolution discarded for skill '%s': avg_variant=%.2f <= avg_original=%.2f",
                    skill_id,
                    avg_variant,
                    avg_original,
                )

            child_fitness = round(avg_variant / 10.0, 4)
            judge_reasoning = " | ".join(
                v.reasoning for v in verdicts if v.reasoning
            )
            mutation_summary = (
                child_skill_md[:200] + ("..." if len(child_skill_md) > 200 else "")
            )
            record = EvolutionRecord(
                id=0,
                skill_id=skill_id,
                parent_skill_md=parent_skill_md,
                child_skill_md=child_skill_md,
                parent_fitness=parent_fitness,
                child_fitness=child_fitness,
                adopted=adopted,
                mutation_summary=mutation_summary,
                feedback_ids=json.dumps(
                    [feedback["id"] for feedback in feedback_list]
                ),
                created_at=datetime.now(timezone.utc).isoformat(),
                judge_reasoning=judge_reasoning,
            )
            record.id = self._registry.add_evolution_record(record)
            return record
        finally:
            if variant_dir is not None and variant_dir.exists():
                shutil.rmtree(variant_dir)
