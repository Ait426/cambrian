"""Cambrian 스킬 비판적 분석기."""

from __future__ import annotations

import json
import logging
import re

from engine.llm import LLMProvider, create_provider
from engine.models import Skill

logger = logging.getLogger(__name__)


class SkillCritic:
    """스킬의 SKILL.md를 비판적으로 분석하여 잠재적 약점을 찾는다."""

    VALID_CATEGORIES = {"clarity", "robustness", "format", "edge_case", "consistency"}
    VALID_SEVERITIES = {"high", "medium", "low"}

    def __init__(self, provider: LLMProvider | None = None) -> None:
        """초기화.

        Args:
            provider: LLM 프로바이더. None이면 critique 호출 시 자동 생성.
        """
        self._provider = provider

    def critique(self, skill: Skill) -> list[dict]:
        """SKILL.md를 비판적으로 분석한다.

        Args:
            skill: 분석할 Skill 객체

        Returns:
            발견된 약점 목록. 각 dict:
            {
                "category": str,    # "clarity" | "robustness" | "format" | "edge_case" | "consistency"
                "severity": str,    # "high" | "medium" | "low"
                "finding": str,     # 발견 내용
                "suggestion": str,  # 개선 제안
            }

        Raises:
            RuntimeError: SKILL.md가 없는 경우
        """
        if not skill.skill_md_content:
            raise RuntimeError(f"SKILL.md content is empty for skill '{skill.id}'")

        system_prompt = (
            "You are a critical skill reviewer for the Cambrian engine.\n"
            "You analyze SKILL.md files (LLM instruction documents) for potential weaknesses.\n"
            "Review categories:\n\n"
            "CLARITY: Are instructions ambiguous? Could the LLM misinterpret them?\n"
            "ROBUSTNESS: What happens with edge cases? Empty input? Huge input? Unexpected types?\n"
            "FORMAT: Is the output format specification precise enough? Will JSON parsing succeed?\n"
            "EDGE_CASE: Are there scenarios not covered by the instructions?\n"
            "CONSISTENCY: Do different sections contradict each other?\n\n"
            "For each finding, rate severity:\n"
            "HIGH: Will likely cause execution failure\n"
            "MEDIUM: May cause suboptimal output\n"
            "LOW: Minor improvement opportunity\n\n"
            "Respond with ONLY a JSON array:\n"
            '[{"category": "format", "severity": "high", "finding": "...", "suggestion": "..."}]\n'
            "If the skill is well-written and has no issues, return an empty array: []"
        )
        user_message = (
            f"## Skill: {skill.id}\n"
            f"## Description: {skill.description}\n\n"
            f"## SKILL.md\n{skill.skill_md_content}"
        )

        try:
            provider = self._provider or create_provider()
            response = provider.complete(
                system=system_prompt,
                user=user_message,
                max_tokens=2048,
            )
            return self._parse_findings(response)
        except Exception as exc:
            logger.warning("Critique failed for skill '%s': %s", skill.id, exc)
            return []

    def _parse_findings(self, response: str) -> list[dict]:
        """LLM 응답에서 findings 배열을 파싱한다.

        Args:
            response: LLM 원문 응답

        Returns:
            검증된 finding dict 리스트. 파싱 실패 시 빈 리스트.
        """
        stripped = response.strip()
        parsed: list | None = None

        # JSON 배열 직접 파싱 시도
        try:
            loaded = json.loads(stripped)
            if isinstance(loaded, list):
                parsed = loaded
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed = None

        # 코드 블록 내 JSON 추출
        if parsed is None:
            match = re.search(r"```json\s*(\[.*?\])\s*```", stripped, re.DOTALL)
            if match:
                try:
                    loaded = json.loads(match.group(1))
                    if isinstance(loaded, list):
                        parsed = loaded
                except (json.JSONDecodeError, TypeError, ValueError):
                    parsed = None

        # 첫 번째 [...] 추출
        if parsed is None:
            start = stripped.find("[")
            end = stripped.rfind("]")
            if start != -1 and end != -1 and start < end:
                try:
                    loaded = json.loads(stripped[start : end + 1])
                    if isinstance(loaded, list):
                        parsed = loaded
                except (json.JSONDecodeError, TypeError, ValueError):
                    parsed = None

        if parsed is None:
            logger.warning("Failed to parse critique response")
            return []

        # 각 항목 검증
        validated: list[dict] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category", "")).lower()
            severity = str(item.get("severity", "")).lower()
            finding = str(item.get("finding", ""))
            suggestion = str(item.get("suggestion", ""))

            if category not in self.VALID_CATEGORIES:
                continue
            if severity not in self.VALID_SEVERITIES:
                continue
            if not finding:
                continue

            validated.append({
                "category": category,
                "severity": severity,
                "finding": finding,
                "suggestion": suggestion,
            })

        return validated
