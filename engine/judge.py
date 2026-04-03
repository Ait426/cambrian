"""Cambrian 스킬 출력 품질 심사기."""

from __future__ import annotations

import json
import logging
import random
import re

from engine.llm import LLMProvider, create_provider
from engine.models import JudgeVerdict

logger = logging.getLogger(__name__)


class SkillJudge:
    """두 스킬 출력을 익명화(A/B)하여 LLM에게 비교 채점시킨다."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        """초기화.

        Args:
            provider: LLM 프로바이더. None이면 judge 호출 시 자동 생성.
        """
        self._provider = provider

    def judge(
        self,
        original_output: dict | None,
        variant_output: dict | None,
        skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        """두 출력을 비교 채점한다.

        Args:
            original_output: 원본 스킬의 출력 결과.
            variant_output: 변이 스킬의 출력 결과.
            skill_description: 스킬 목적 설명.
            feedback_list: 사용자 피드백 목록.

        Returns:
            JudgeVerdict: 비교 채점 결과.

        Raises:
            RuntimeError: anthropic 패키지가 없거나 API 키가 없을 때.
        """
        if original_output is None and variant_output is None:
            return JudgeVerdict(0.0, 0.0, "Both outputs are empty", "tie")

        if original_output is None:
            return JudgeVerdict(0.0, 5.0, "Original output is empty", "variant")

        if variant_output is None:
            return JudgeVerdict(5.0, 0.0, "Variant output is empty", "original")

        try:
            system_prompt, user_message, swapped = self._build_judge_prompt(
                original_output=original_output,
                variant_output=variant_output,
                skill_description=skill_description,
                feedback_list=feedback_list,
            )

            provider = self._provider or create_provider()
            response_text = provider.complete(
                system=system_prompt,
                user=user_message,
                max_tokens=1024,
            )
            return self._parse_verdict(response_text, swapped)
        except Exception as exc:
            logger.warning("Judge failed: %s", exc)
            return JudgeVerdict(5.0, 5.0, f"Judge failed: {exc}", "tie")

    def _build_judge_prompt(
        self,
        original_output: dict | None,
        variant_output: dict | None,
        skill_description: str,
        feedback_list: list[dict],
    ) -> tuple[str, str, bool]:
        """Judge용 프롬프트를 생성한다. A/B 순서를 랜덤화한다.

        Args:
            original_output: 원본 스킬의 출력 결과.
            variant_output: 변이 스킬의 출력 결과.
            skill_description: 스킬 목적 설명.
            feedback_list: 사용자 피드백 목록.

        Returns:
            tuple[str, str, bool]: 시스템 프롬프트, 유저 메시지, 스왑 여부.
        """
        swapped = random.choice([True, False])

        if swapped:
            output_a = variant_output
            output_b = original_output
        else:
            output_a = original_output
            output_b = variant_output

        system_prompt = (
            "You are a skill output quality judge for the Cambrian engine.\n"
            "You receive two outputs (A and B) from the same skill, along with the skill's purpose and user feedback.\n"
            "Your job: score each output on a 0-10 scale and pick a winner.\n\n"
            "Scoring criteria:\n"
            "1. Correctness: Does the output fulfill the skill's purpose? (0-3 points)\n"
            "2. Feedback adherence: Does the output address the user feedback? (0-4 points)\n"
            "3. Quality: Is the output well-structured, detailed, and professional? (0-3 points)\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"score_a": N, "score_b": N, "reasoning": "...", "winner": "a"|"b"|"tie"}'
        )

        formatted_feedback = "\n".join(
            f"Rating: {feedback['rating']}/5 | Comment: {feedback['comment']}"
            for feedback in feedback_list
        )
        output_a_text = (
            json.dumps(output_a, ensure_ascii=False, indent=2)
            if output_a is not None
            else "null"
        )
        output_b_text = (
            json.dumps(output_b, ensure_ascii=False, indent=2)
            if output_b is not None
            else "null"
        )

        user_message = (
            f"## Skill Purpose\n{skill_description}\n\n"
            f"## User Feedback\n{formatted_feedback}\n\n"
            f"## Output A\n{output_a_text}\n\n"
            f"## Output B\n{output_b_text}"
        )

        return system_prompt, user_message, swapped

    def _parse_verdict(self, response_text: str, swapped: bool) -> JudgeVerdict:
        """LLM 응답에서 JudgeVerdict를 파싱한다.

        Args:
            response_text: LLM 원문 응답.
            swapped: A/B 출력이 스왑되었는지 여부.

        Returns:
            JudgeVerdict: 파싱된 채점 결과. 파싱 실패 시 tie 기본값.
        """
        stripped = response_text.strip()
        parsed: dict | None = None

        try:
            loaded = json.loads(stripped)
            if isinstance(loaded, dict):
                parsed = loaded
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed = None

        if parsed is None:
            match = re.search(r"```json\s*(\{.*?\})\s*```", stripped, re.DOTALL)
            if match is not None:
                try:
                    loaded = json.loads(match.group(1))
                    if isinstance(loaded, dict):
                        parsed = loaded
                except (json.JSONDecodeError, TypeError, ValueError):
                    parsed = None

        if parsed is None:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start != -1 and end != -1 and start < end:
                try:
                    loaded = json.loads(stripped[start : end + 1])
                    if isinstance(loaded, dict):
                        parsed = loaded
                except (json.JSONDecodeError, TypeError, ValueError):
                    parsed = None

        if parsed is None:
            return JudgeVerdict(5.0, 5.0, "Judge parse failed", "tie")

        try:
            score_a = float(parsed.get("score_a", 5.0))
        except (TypeError, ValueError):
            score_a = 5.0

        try:
            score_b = float(parsed.get("score_b", 5.0))
        except (TypeError, ValueError):
            score_b = 5.0

        score_a = max(0.0, min(10.0, score_a))
        score_b = max(0.0, min(10.0, score_b))

        reasoning = str(parsed.get("reasoning", ""))
        raw_winner = str(parsed.get("winner", "tie")).lower().strip()

        if swapped:
            original_score = score_b
            variant_score = score_a
        else:
            original_score = score_a
            variant_score = score_b

        if raw_winner == "a":
            winner = "variant" if swapped else "original"
        elif raw_winner == "b":
            winner = "original" if swapped else "variant"
        else:
            winner = "tie"

        return JudgeVerdict(
            original_score=original_score,
            variant_score=variant_score,
            reasoning=reasoning,
            winner=winner,
        )
